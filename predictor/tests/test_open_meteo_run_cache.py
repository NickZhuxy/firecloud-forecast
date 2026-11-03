"""One Open-Meteo request per coordinate batch must serve every product of a run."""
import dataclasses
from datetime import date, datetime, timedelta, timezone

from predictor.fetch import OpenMeteoRunCache, OpenMeteoSource
from predictor.solar_event import SolarEvent


class _Response:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


class _ForecastServer:
    """Answer each request from its own parameters, like the real API.

    Values depend on the location and the hour, so a wrong hour or a wrong
    location gives a different snapshot.
    """

    def __init__(self):
        self.calls: list[dict] = []

    def get(self, url, params=None, timeout=None):
        self.calls.append(dict(params))
        start = date.fromisoformat(params["start_date"])
        end = date.fromisoformat(params["end_date"])
        days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
        lats = [float(v) for v in params["latitude"].split(",")]
        lons = [float(v) for v in params["longitude"].split(",")]
        results = [self._location(lat, lon, days, params["daily"]) for lat, lon in zip(lats, lons)]
        return _Response(results if len(results) > 1 else results[0])

    @staticmethod
    def _location(lat, lon, days, daily_fields):
        hours = [datetime(d.year, d.month, d.day, h) for d in days for h in range(24)]
        # Clock hours, not positions in the range: the same hour has the same value.
        clock = [int(h.timestamp() // 3600) for h in hours]
        seed = int(lat * 100) + int(lon * 10)
        daily = {"time": [d.isoformat() for d in days]}
        minute = seed % 60
        for field in daily_fields.split(","):
            hour = 22 if field == "sunrise" else 9
            daily[field] = [f"{d.isoformat()}T{hour:02d}:{minute:02d}" for d in days]
        return {
            "hourly": {
                "time": [h.strftime("%Y-%m-%dT%H:%M") for h in hours],
                "cloud_cover_low": [float((seed + 3 * c) % 100) for c in clock],
                "cloud_cover_mid": [float((seed + 7 * c) % 100) for c in clock],
                "cloud_cover_high": [float((seed + 11 * c) % 100) for c in clock],
                "relative_humidity_2m": [float(30 + (seed + c) % 60) for c in clock],
                "visibility": [float(10000 + 50 * ((seed + c) % 200)) for c in clock],
            },
            "daily": daily,
        }


# Shanghai-like grid larger than one request batch (280 coordinates).
COORDS = [(30.0 + 0.1 * (i // 20), 120.0 + 0.1 * (i % 20)) for i in range(300)]

# Sunrise is the previous UTC evening; sunset is the same UTC day.
PRODUCTS = [
    (SolarEvent.SUNRISE, datetime(2026, 11, 3, 22, 20, tzinfo=timezone.utc)),
    (SolarEvent.SUNSET, datetime(2026, 11, 4, 9, 0, tzinfo=timezone.utc)),
    (SolarEvent.SUNRISE, datetime(2026, 11, 4, 22, 21, tzinfo=timezone.utc)),
    (SolarEvent.SUNSET, datetime(2026, 11, 5, 8, 59, tzinfo=timezone.utc)),
]


def _without_retrieval_time(snapshots):
    return [dataclasses.replace(s, retrieved_at=None) for s in snapshots]


def test_run_cache_serves_four_products_with_one_request_per_batch():
    plain_server, cached_server = _ForecastServer(), _ForecastServer()
    cache = OpenMeteoRunCache.for_dates(date(2026, 11, 4), date(2026, 11, 5))
    for event, query in PRODUCTS:
        plain = OpenMeteoSource(session=plain_server, solar_event=event).fetch_many(COORDS, query)
        cached = OpenMeteoSource(
            session=cached_server, solar_event=event, run_cache=cache,
        ).fetch_many(COORDS, query)
        assert _without_retrieval_time(cached) == _without_retrieval_time(plain)
        assert all(s.sunset_time is not None for s in cached)
    assert len(plain_server.calls) == 4 * 2
    assert len(cached_server.calls) == 2
    assert cache.requests == 2
    assert cached_server.calls[0]["daily"] == "sunrise,sunset"


def test_run_cache_falls_back_outside_its_window():
    server = _ForecastServer()
    cache = OpenMeteoRunCache.for_dates(date(2026, 11, 4), date(2026, 11, 4))
    late = datetime(2026, 11, 9, 9, 0, tzinfo=timezone.utc)
    cached = OpenMeteoSource(session=server, run_cache=cache).fetch_many(COORDS[:5], late)
    plain = OpenMeteoSource(session=_ForecastServer()).fetch_many(COORDS[:5], late)
    assert _without_retrieval_time(cached) == _without_retrieval_time(plain)
    assert server.calls[0]["start_date"] == "2026-11-08"
    assert cache.requests == 0
