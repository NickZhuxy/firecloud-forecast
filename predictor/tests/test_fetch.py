from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
import xarray as xr

from predictor.fetch import FakeSource, HRRRSource, WeatherSnapshot, _nearest_grid_index


def _fake_hrrr_clouds_dataset(lat_target=42.36, lon_target=-71.06):
    """Build a tiny 3x3 xarray Dataset shaped like a HRRR cloud-cover slice.

    cfgrib uses shortnames: hcc (high), mcc (middle), lcc (low).
    """
    # Build a 3x3 grid centered on target with ~0.05 deg spacing
    lats = np.array([[lat_target + dy for _ in range(3)] for dy in [-0.05, 0.0, 0.05]])
    lons = np.array([[lon_target + dx for dx in [-0.05, 0.0, 0.05]] for _ in range(3)])
    hcc = np.array([[10, 20, 30], [40, 55, 60], [50, 50, 50]], dtype=float)
    mcc = np.array([[20, 30, 40], [50, 65, 70], [60, 60, 60]], dtype=float)
    lcc = np.array([[5, 8, 10], [12, 15, 20], [18, 22, 25]], dtype=float)
    return xr.Dataset(
        data_vars={
            "hcc": (("y", "x"), hcc),
            "mcc": (("y", "x"), mcc),
            "lcc": (("y", "x"), lcc),
        },
        coords={
            "latitude": (("y", "x"), lats),
            "longitude": (("y", "x"), lons),
        },
    )


def _fake_hrrr_rh_dataset(lat_target=42.36, lon_target=-71.06):
    lats = np.array([[lat_target + dy for _ in range(3)] for dy in [-0.05, 0.0, 0.05]])
    lons = np.array([[lon_target + dx for dx in [-0.05, 0.0, 0.05]] for _ in range(3)])
    rh = np.array([[50, 55, 60], [55, 62, 65], [60, 65, 70]], dtype=float)
    return xr.Dataset(
        data_vars={"r2": (("y", "x"), rh)},  # cfgrib often names 2m RH 'r2'
        coords={
            "latitude": (("y", "x"), lats),
            "longitude": (("y", "x"), lons),
        },
    )


def test_snapshot_from_datasets_picks_nearest_grid_point():
    clouds = _fake_hrrr_clouds_dataset()
    rh = _fake_hrrr_rh_dataset()
    snap = HRRRSource._snapshot_from_datasets(
        ds_clouds=clouds,
        ds_rh=rh,
        lat=42.36, lon=-71.06,
        run_label="hrrr@2026-05-20T18:00Z+f06",
        retrieved_at=datetime(2026, 5, 20, 18, 30, tzinfo=timezone.utc),
    )
    # Center grid point is the nearest; values should match the [1,1] cells.
    assert snap.cloud_high_pct == 55.0
    assert snap.cloud_mid_pct == 65.0
    assert snap.cloud_low_pct == 15.0
    assert snap.humidity_pct == 62.0
    assert snap.source_label == "hrrr@2026-05-20T18:00Z+f06"


def test_weather_snapshot_fields():
    s = WeatherSnapshot(
        cloud_low_pct=20.0, cloud_mid_pct=40.0, cloud_high_pct=30.0,
        humidity_pct=55.0, source_label="fake", retrieved_at=datetime(2026, 5, 20, tzinfo=timezone.utc),
    )
    assert s.cloud_low_pct == 20.0
    d = s.to_dict()
    assert d["cloud_mid_pct"] == 40.0
    assert d["source_label"] == "fake"


def test_fake_source_returns_canned_snapshot():
    canned = WeatherSnapshot(
        cloud_low_pct=10, cloud_mid_pct=50, cloud_high_pct=40,
        humidity_pct=60, source_label="fake",
        retrieved_at=datetime(2026, 5, 20, tzinfo=timezone.utc),
    )
    src = FakeSource(canned)
    got = src.fetch(lat=42.36, lon=-71.06, time=datetime(2026, 5, 20, 23, 0, tzinfo=timezone.utc))
    assert got is canned


def test_nearest_grid_index_applies_cos_lat_correction():
    """At mid-to-high latitudes, longitudinal distance shrinks by cos(lat).

    Without the correction, naive Euclidean-in-degrees picks the
    latitudinally-closer point; with it, the longitudinally-closer point wins
    because 0.7 deg of longitude at 60 deg N is geographically shorter than
    0.5 deg of latitude.
    """
    # Two candidate grid points relative to query (60.0, 0.0):
    #   A = (60.5, 0.0)  -> Δlat=0.5,  Δlon=0   (d² = 0.25 either way)
    #   B = (60.0, 0.7)  -> Δlat=0,    Δlon=0.7 (d² = 0.49 plain; 0.1225 with cos(60°)=0.5)
    lat_arr = np.array([[60.5, 60.0]])
    lon_arr = np.array([[0.0, 0.7]])

    yi, xi = _nearest_grid_index(lat_arr, lon_arr, lat=60.0, lon=0.0)
    assert (yi, xi) == (0, 1)


def test_nearest_grid_index_at_equator_unchanged():
    """At the equator, cos(0°)=1, so behavior matches the original Euclidean rule."""
    lat_arr = np.array([[0.5, 0.0]])
    lon_arr = np.array([[0.0, 0.7]])

    yi, xi = _nearest_grid_index(lat_arr, lon_arr, lat=0.0, lon=0.0)
    # A=(0.5, 0): d²=0.25 (winner); B=(0, 0.7): d²=0.49
    assert (yi, xi) == (0, 0)


def test_hrrr_source_caches_parsed_datasets_per_run(monkeypatch, tmp_path):
    """Repeated fetches with the same (run_dt, fxx) reuse the parsed datasets.

    Without caching, every fetch() recomputes Herbie.xarray(...), which is the
    slow path the map notebook hammers. The cache key is (run_dt, fxx); query
    lat/lon vary freely between calls.
    """
    cloud_ds = _fake_hrrr_clouds_dataset()
    rh_ds = _fake_hrrr_rh_dataset()
    counts = {"init": 0, "xarray": 0}

    class FakeHerbie:
        def __init__(self, *args, **kwargs):
            counts["init"] += 1

        def xarray(self, search):
            counts["xarray"] += 1
            if "CDC" in search:
                return [cloud_ds]
            return rh_ds

    import herbie
    monkeypatch.setattr(herbie, "Herbie", FakeHerbie)

    src = HRRRSource(cache_dir=tmp_path)
    t = datetime(2026, 5, 20, 18, 0, tzinfo=timezone.utc)

    snap1 = src.fetch(lat=42.36, lon=-71.06, time=t)
    snap2 = src.fetch(lat=44.0, lon=-72.0, time=t)  # different point, same run_dt

    # First call parses (1 cloud search + 1 RH search). Second is a pure cache hit.
    assert counts["init"] == 1
    assert counts["xarray"] == 2
    # Sanity: both calls returned a real snapshot.
    assert isinstance(snap1, WeatherSnapshot)
    assert isinstance(snap2, WeatherSnapshot)


def test_hrrr_source_cache_misses_on_different_run(monkeypatch, tmp_path):
    """A fetch landing on a different run cycle parses afresh."""
    cloud_ds = _fake_hrrr_clouds_dataset()
    rh_ds = _fake_hrrr_rh_dataset()
    counts = {"init": 0, "xarray": 0}

    class FakeHerbie:
        def __init__(self, *args, **kwargs):
            counts["init"] += 1

        def xarray(self, search):
            counts["xarray"] += 1
            if "CDC" in search:
                return [cloud_ds]
            return rh_ds

    import herbie
    monkeypatch.setattr(herbie, "Herbie", FakeHerbie)

    src = HRRRSource(cache_dir=tmp_path)
    t1 = datetime(2026, 5, 20, 18, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 5, 20, 19, 0, tzinfo=timezone.utc)  # different hour -> different run_dt

    src.fetch(lat=42.36, lon=-71.06, time=t1)
    src.fetch(lat=42.36, lon=-71.06, time=t2)

    assert counts["init"] == 2
    assert counts["xarray"] == 4  # 2 clouds + 2 RH


# ---------------------------------------------------------------------------
# OpenMeteoSource — offline tests (no real HTTP)
# ---------------------------------------------------------------------------

from predictor.fetch import OpenMeteoSource


def _open_meteo_payload(
    *,
    query_time_str="2026-05-20T23:00",
    times=("2026-05-20T22:00", "2026-05-20T23:00", "2026-05-21T00:00"),
    cloud_low=(5.0, 10.0, 15.0),
    cloud_mid=(40.0, 50.0, 60.0),
    cloud_high=(30.0, 35.0, 40.0),
    visibility=(20_000.0, 25_000.0, 30_000.0),
    humidity=(55.0, 60.0, 65.0),
    sunsets=("2026-05-20T23:30", "2026-05-21T23:31"),
):
    """Factory: build a canned Open-Meteo-shaped dict for parser tests."""
    return {
        "hourly": {
            "time": list(times),
            "cloud_cover_low": list(cloud_low),
            "cloud_cover_mid": list(cloud_mid),
            "cloud_cover_high": list(cloud_high),
            "visibility": list(visibility),
            "relative_humidity_2m": list(humidity),
        },
        "daily": {
            "sunset": list(sunsets),
        },
    }


class _FakeResponse:
    """Minimal fake HTTP response."""
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass  # no-op

    def json(self):
        return self._data


class _FakeSession:
    """Minimal fake requests Session — records calls, never touches the network."""
    def __init__(self, payload):
        self._payload = payload
        self.calls: list[dict] = []

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        return _FakeResponse(self._payload)


# --- _snapshot_from_payload (pure parser) ---

def test_snapshot_from_payload_picks_nearest_hour():
    payload = _open_meteo_payload()
    query_utc = datetime(2026, 5, 20, 23, 0, tzinfo=timezone.utc)
    snap = OpenMeteoSource._snapshot_from_payload(payload, query_utc)
    # Hour index 1 ("2026-05-20T23:00") is the exact match
    assert snap.cloud_low_pct == 10.0
    assert snap.cloud_mid_pct == 50.0
    assert snap.cloud_high_pct == 35.0
    assert snap.humidity_pct == 60.0


def test_snapshot_from_payload_sets_visibility_m():
    payload = _open_meteo_payload()
    query_utc = datetime(2026, 5, 20, 23, 0, tzinfo=timezone.utc)
    snap = OpenMeteoSource._snapshot_from_payload(payload, query_utc)
    assert snap.visibility_m == 25_000.0


def test_snapshot_from_payload_cloud_base_is_none():
    """OpenMeteoSource never sets cloud_base_m — it must be None."""
    payload = _open_meteo_payload()
    query_utc = datetime(2026, 5, 20, 23, 0, tzinfo=timezone.utc)
    snap = OpenMeteoSource._snapshot_from_payload(payload, query_utc)
    assert snap.cloud_base_m is None


def test_snapshot_from_payload_picks_nearest_sunset():
    payload = _open_meteo_payload(sunsets=["2026-05-20T23:30", "2026-05-21T23:31"])
    query_utc = datetime(2026, 5, 20, 23, 0, tzinfo=timezone.utc)
    snap = OpenMeteoSource._snapshot_from_payload(payload, query_utc)
    # The closer sunset is 2026-05-20T23:30 (30 min away vs ~24 h away)
    assert snap.sunset_time is not None
    assert snap.sunset_time.year == 2026 and snap.sunset_time.month == 5 and snap.sunset_time.day == 20


def test_snapshot_from_payload_source_label_format():
    payload = _open_meteo_payload()
    query_utc = datetime(2026, 5, 20, 23, 0, tzinfo=timezone.utc)
    snap = OpenMeteoSource._snapshot_from_payload(payload, query_utc)
    assert snap.source_label == "open-meteo@2026-05-20T23Z"


def test_snapshot_from_payload_no_sunsets_sunset_time_none():
    payload = _open_meteo_payload(sunsets=[])
    query_utc = datetime(2026, 5, 20, 23, 0, tzinfo=timezone.utc)
    snap = OpenMeteoSource._snapshot_from_payload(payload, query_utc)
    assert snap.sunset_time is None


# --- #60: sunrise-bound source reads the sunrise daily field ---

def test_params_daily_field_follows_solar_event():
    from predictor.solar_event import SolarEvent
    q = datetime(2026, 5, 20, tzinfo=timezone.utc)
    assert OpenMeteoSource._params([(30.0, 120.0)], q, window_days=1)["daily"] == "sunset"
    assert OpenMeteoSource._params(
        [(30.0, 120.0)], q, window_days=1, solar_event=SolarEvent.SUNRISE
    )["daily"] == "sunrise"


def test_snapshot_from_payload_sunrise_event_uses_sunrise_time():
    from predictor.solar_event import SolarEvent
    payload = _open_meteo_payload()
    payload["daily"]["sunrise"] = ["2026-05-20T09:30", "2026-05-21T09:29"]
    query_utc = datetime(2026, 5, 20, 9, 0, tzinfo=timezone.utc)
    snap = OpenMeteoSource._snapshot_from_payload(
        payload, query_utc, solar_event=SolarEvent.SUNRISE
    )
    # The event-time slot now holds the SUNRISE instant, not the sunset one.
    assert snap.sunset_time is not None
    assert snap.sunset_time.hour == 9 and snap.sunset_time.day == 20


def test_sunrise_bound_source_requests_sunrise_and_sets_event_time():
    from predictor.solar_event import SolarEvent
    payload = _open_meteo_payload()
    payload["daily"]["sunrise"] = ["2026-05-20T09:30", "2026-05-21T09:29"]
    session = _FakeSession(payload)
    src = OpenMeteoSource(session=session, solar_event=SolarEvent.SUNRISE)
    snap = src.fetch(30.0, 120.0, datetime(2026, 5, 20, 9, 0, tzinfo=timezone.utc))
    assert session.calls[0]["params"]["daily"] == "sunrise"
    assert snap.sunset_time.hour == 9 and snap.sunset_time.day == 20


def test_snapshot_from_payload_off_hour_query_picks_closest():
    # Query at 22:45 — closer to 23:00 (15 min) than to 22:00 (45 min)
    payload = _open_meteo_payload()
    query_utc = datetime(2026, 5, 20, 22, 45, tzinfo=timezone.utc)
    snap = OpenMeteoSource._snapshot_from_payload(payload, query_utc)
    # Index 1 (23:00) is closer → cloud_mid=50, not 40
    assert snap.cloud_mid_pct == 50.0


# --- fetch via injected session ---

def test_open_meteo_fetch_returns_weather_snapshot():
    payload = _open_meteo_payload()
    session = _FakeSession(payload)
    src = OpenMeteoSource(session=session)
    snap = src.fetch(lat=42.36, lon=-71.06, time=datetime(2026, 5, 20, 23, 0, tzinfo=timezone.utc))
    assert isinstance(snap, WeatherSnapshot)
    assert snap.cloud_mid_pct == 50.0


def test_open_meteo_fetch_makes_no_real_http():
    """The session mock captures all calls; confirm exactly one call was made."""
    payload = _open_meteo_payload()
    session = _FakeSession(payload)
    src = OpenMeteoSource(session=session)
    src.fetch(lat=42.36, lon=-71.06, time=datetime(2026, 5, 20, 23, 0, tzinfo=timezone.utc))
    assert len(session.calls) == 1
    assert session.calls[0]["url"] == OpenMeteoSource.ENDPOINT


def test_open_meteo_fetch_passes_lat_lon_params():
    payload = _open_meteo_payload()
    session = _FakeSession(payload)
    src = OpenMeteoSource(session=session)
    src.fetch(lat=42.36, lon=-71.06, time=datetime(2026, 5, 20, 23, 0, tzinfo=timezone.utc))
    params = session.calls[0]["params"]
    assert "42.3600" in params["latitude"]
    assert "-71.0600" in params["longitude"]


# --- fetch_many via injected session ---

def test_open_meteo_fetch_many_returns_one_snapshot_per_coord():
    single_payload = _open_meteo_payload()
    multi_payload = [single_payload, single_payload]
    session = _FakeSession(multi_payload)
    src = OpenMeteoSource(session=session)
    coords = [(42.36, -71.06), (40.71, -74.01)]
    snaps = src.fetch_many(coords=coords, time=datetime(2026, 5, 20, 23, 0, tzinfo=timezone.utc))
    assert len(snaps) == 2
    assert all(isinstance(s, WeatherSnapshot) for s in snaps)


def test_open_meteo_fetch_many_empty_coords_returns_empty_list():
    session = _FakeSession([])
    src = OpenMeteoSource(session=session)
    result = src.fetch_many(coords=[], time=datetime(2026, 5, 20, 23, 0, tzinfo=timezone.utc))
    assert result == []
    # No HTTP call should be made for empty coord list
    assert len(session.calls) == 0


def test_open_meteo_fetch_many_makes_single_http_call():
    single_payload = _open_meteo_payload()
    multi_payload = [single_payload, single_payload, single_payload]
    session = _FakeSession(multi_payload)
    src = OpenMeteoSource(session=session)
    coords = [(42.36, -71.06), (40.71, -74.01), (37.77, -122.42)]
    src.fetch_many(coords=coords, time=datetime(2026, 5, 20, 23, 0, tzinfo=timezone.utc))
    # Multi-location API uses a single request
    assert len(session.calls) == 1


def test_open_meteo_fetch_many_single_coord_wrapped_in_list():
    # Single-coord multi-location: payload is a dict (not list), should still return 1 snapshot
    single_payload = _open_meteo_payload()
    session = _FakeSession(single_payload)  # not a list — mimics the "object not array" edge case
    src = OpenMeteoSource(session=session)
    snaps = src.fetch_many(coords=[(42.36, -71.06)], time=datetime(2026, 5, 20, 23, 0, tzinfo=timezone.utc))
    assert len(snaps) == 1
    assert isinstance(snaps[0], WeatherSnapshot)


def test_fetch_for_sunset_selects_weather_nearest_score_window():
    """The rough evening hint must not become the weather observation time."""
    payload = _open_meteo_payload(
        times=("2026-05-20T22:00", "2026-05-20T23:00", "2026-05-21T00:00"),
        cloud_mid=(10.0, 70.0, 20.0),
        sunsets=("2026-05-20T23:30",),
    )
    session = _FakeSession(payload)
    src = OpenMeteoSource(session=session)

    snap = src.fetch_for_sunset(
        lat=42.36,
        lon=-71.06,
        evening_hint=datetime(2026, 5, 20, 22, 0, tzinfo=timezone.utc),
        score_offset=timedelta(minutes=10),
    )

    # Sunset - 10 min = 23:20, so 23:00 is closer than the 22:00 hint.
    assert snap.cloud_mid_pct == 70.0
    assert snap.source_label == "open-meteo@2026-05-20T23Z"
    assert snap.sunset_time == datetime(2026, 5, 20, 23, 30, tzinfo=timezone.utc)


def test_fetch_many_for_sunset_uses_each_locations_own_sunset():
    east = _open_meteo_payload(
        cloud_mid=(11.0, 12.0, 13.0),
        sunsets=("2026-05-20T22:10",),
    )
    west = _open_meteo_payload(
        cloud_mid=(21.0, 22.0, 23.0),
        sunsets=("2026-05-20T23:10",),
    )
    session = _FakeSession([east, west])
    src = OpenMeteoSource(session=session)

    snaps = src.fetch_many_for_sunset(
        coords=[(31.0, 121.0), (31.0, 91.0)],
        evening_hint=datetime(2026, 5, 20, 22, 0, tzinfo=timezone.utc),
        score_offset=timedelta(minutes=10),
        window_days=0,
    )

    # East targets 22:00; west targets 23:00 from the same batched response.
    assert [s.cloud_mid_pct for s in snaps] == [11.0, 22.0]
    params = session.calls[0]["params"]
    assert params["start_date"] == params["end_date"] == "2026-05-20"


def test_open_meteo_retries_http_429(monkeypatch):
    import json
    from urllib.error import HTTPError
    import time as time_module
    import urllib.request

    payload = _open_meteo_payload()
    calls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(payload).encode()

    def fake_urlopen(url, timeout):
        calls.append(url)
        if len(calls) == 1:
            raise HTTPError(url, 429, "rate limited", {"Retry-After": "0"}, None)
        return Response()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(time_module, "sleep", lambda _: None)

    result = OpenMeteoSource()._get_json("https://example.test", {"x": "1"})

    assert result == payload
    assert len(calls) == 2


def _detail_weather_payload(mid_cover: float) -> dict:
    payload = _open_meteo_payload(
        times=("2026-06-22T10:00",),
        cloud_low=(10.0,),
        cloud_mid=(mid_cover,),
        cloud_high=(30.0,),
        visibility=(25_000.0,),
        humidity=(60.0,),
        sunsets=("2026-06-22T11:00",),
    )
    payload["hourly"].update(
        {
            "wind_speed_850hPa": [5.0],
            "wind_direction_850hPa": [90.0],
            "wind_speed_700hPa": [20.0],
            "wind_direction_700hPa": [90.0],
            "wind_speed_400hPa": [30.0],
            "wind_direction_400hPa": [90.0],
        }
    )
    return payload


def test_fetch_sunward_profile_batches_weather_and_aod_at_one_time():
    import threading

    weather = [_detail_weather_payload(70.0 - i * 10.0) for i in range(8)]
    air = [
        {
            "hourly": {
                "time": ["2026-06-22T10:00"],
                "aerosol_optical_depth": [0.10 + i * 0.01],
            }
        }
        for i in range(8)
    ]

    class RoutedSession:
        def __init__(self):
            self.calls = []
            # A sequential implementation deadlocks the first request here and
            # fails the test. Both worker requests must enter before either can
            # return, proving actual overlap rather than merely flexible order.
            self.both_started = threading.Barrier(2, timeout=2.0)

        def get(self, url, params=None, timeout=None):
            self.calls.append({"url": url, "params": params, "timeout": timeout})
            self.both_started.wait()
            return _FakeResponse(air if "air-quality" in url else weather)

    session = RoutedSession()
    src = OpenMeteoSource(session=session)
    snapshot = src.fetch_sunward_profile(
        31.23,
        121.47,
        datetime(2026, 6, 22, 10, 50, tzinfo=timezone.utc),
        270.0,
    )

    # Weather and air-quality are fetched concurrently, so identify each call by
    # its URL rather than by ordering.
    assert len(session.calls) == 2
    weather_call = next(c for c in session.calls if c["url"] == OpenMeteoSource.ENDPOINT)
    air_calls = [c for c in session.calls if c["url"] == OpenMeteoSource.AIR_QUALITY_ENDPOINT]
    assert weather_call["params"]["start_date"] == "2026-06-22"
    assert weather_call["params"]["end_date"] == "2026-06-22"
    assert weather_call["params"]["wind_speed_unit"] == "ms"
    assert len(air_calls) == 1
    assert snapshot.aerosol_optical_depth == 0.10
    assert snapshot.sunward_profile is not None
    assert len(snapshot.sunward_profile.distances_km) == 8
    assert snapshot.sunward_profile.cloud_mid_pct[-1] == 0.0
    assert snapshot.sunward_profile.aerosol_optical_depth[-1] == 0.17


def test_fetch_sunward_profile_survives_aod_service_failure():
    weather = [_detail_weather_payload(50.0) for _ in range(8)]

    class WeatherOnlySession:
        def get(self, url, params=None, timeout=None):
            if "air-quality" in url:
                raise RuntimeError("air quality unavailable")
            return _FakeResponse(weather)

    snapshot = OpenMeteoSource(session=WeatherOnlySession()).fetch_sunward_profile(
        31.23,
        121.47,
        datetime(2026, 6, 22, 10, 50, tzinfo=timezone.utc),
        270.0,
    )

    assert snapshot.sunward_profile is not None
    assert snapshot.aerosol_optical_depth is None
    assert all(v is None for v in snapshot.sunward_profile.aerosol_optical_depth)


@pytest.mark.integration
def test_hrrr_source_real_fetch_for_boston(tmp_path):
    """Hits the network (AWS S3). Run manually with: pytest -m integration."""
    src = HRRRSource(cache_dir=tmp_path)
    # Pick a recent past time (HRRR keeps several days online).
    t = datetime.now(timezone.utc) - timedelta(hours=3)
    snap = src.fetch(lat=42.36, lon=-71.06, time=t)
    assert 0 <= snap.cloud_low_pct <= 100
    assert 0 <= snap.cloud_mid_pct <= 100
    assert 0 <= snap.cloud_high_pct <= 100
    assert 0 <= snap.humidity_pct <= 100
    assert snap.source_label.startswith("hrrr@")
