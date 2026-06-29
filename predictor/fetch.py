"""Weather data acquisition.

Defines a WeatherSource protocol so callers can swap HRRR / GFS / OpenMeteo.
Real implementations live alongside FakeSource (used by tests).
"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol

import numpy as np
import xarray as xr

from predictor.solar_event import SolarEvent, spec_for
from predictor.spatial import (
    DEFAULT_SUNWARD_DISTANCES_KM,
    SunwardProfile,
    sunward_coordinates,
)

# Note: herbie is heavy; import lazily inside fetch() so unit tests don't pay the cost.


@dataclass
class WeatherSnapshot:
    cloud_low_pct: float
    cloud_mid_pct: float
    cloud_high_pct: float
    humidity_pct: float
    source_label: str          # e.g. "hrrr@2026-05-20T18Z+f01"
    retrieved_at: datetime
    # Optional fields — older sources (HRRR cloud/RH only) may not supply them.
    visibility_m: float | None = None   # surface horizontal visibility, metres
    cloud_base_m: float | None = None   # illuminated canvas base height, metres
    sunset_time: datetime | None = None  # source-reported local sunset (if any)
    # AOD at 550 nm is a column aerosol measurement. It is a much closer match
    # to the manual method than surface visibility, which is also degraded by
    # fog and near-surface humidity.
    aerosol_optical_depth: float | None = None
    # Pressure-level winds used to estimate cloud-boundary motion. Open-Meteo
    # returns meteorological direction (where the wind comes from).
    wind_speed_850_m_s: float | None = None
    wind_direction_850_deg: float | None = None
    wind_speed_700_m_s: float | None = None
    wind_direction_700_deg: float | None = None
    wind_speed_400_m_s: float | None = None
    wind_direction_400_deg: float | None = None
    # Present only for detailed point forecasts. National overview snapshots
    # remain small and continue to use the cheap local-only request.
    sunward_profile: SunwardProfile | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["retrieved_at"] = self.retrieved_at.isoformat()
        if self.sunset_time is not None:
            d["sunset_time"] = self.sunset_time.isoformat()
        return d


class WeatherSource(Protocol):
    def fetch(self, lat: float, lon: float, time: datetime) -> WeatherSnapshot: ...


@dataclass
class FakeSource:
    """Test fixture — returns a pre-built WeatherSnapshot for any query."""
    snapshot: WeatherSnapshot

    def fetch(self, lat: float, lon: float, time: datetime) -> WeatherSnapshot:
        return self.snapshot


class OpenMeteoSource:
    """Fetch point weather from the free, key-less, global Open-Meteo API.

    Unlike HRRRSource (CONUS-only, slow GRIB downloads), Open-Meteo returns a
    JSON point forecast in well under a second worldwide, which makes it the
    right backend for an interactive map application. It supplies layered cloud
    cover, 2 m relative humidity, surface visibility, and the daily sunset time.

    It does not report a cloud-base height; ``cloud_base_m`` is left None and
    estimated downstream in ``features.derive`` from the present cloud layers.
    """

    ENDPOINT = "https://api.open-meteo.com/v1/forecast"
    AIR_QUALITY_ENDPOINT = "https://air-quality-api.open-meteo.com/v1/air-quality"
    HOURLY = "cloud_cover_low,cloud_cover_mid,cloud_cover_high,visibility,relative_humidity_2m"
    DETAIL_HOURLY = HOURLY + (
        ",wind_speed_850hPa,wind_direction_850hPa"
        ",wind_speed_700hPa,wind_direction_700hPa"
        ",wind_speed_400hPa,wind_direction_400hPa"
    )

    def __init__(self, session=None, timeout: float = 15.0, solar_event: SolarEvent | str = SolarEvent.SUNSET):
        self._session = session
        self._timeout = timeout
        # #60: bind this source to a solar event (sunset/sunrise). It chooses the
        # Open-Meteo daily field and the event time; the scoring azimuth/GFS step
        # follow from the event time supplied to the scorer. Defaults to sunset.
        self._solar_event = SolarEvent(solar_event)

    def fetch(self, lat: float, lon: float, time: datetime) -> WeatherSnapshot:
        query_utc = self._as_utc(time)

        # Request a ±1 day window: near the event the UTC date rolls over relative
        # to the local evening/morning (e.g. 20:24 EDT = 00:24Z next day), so a
        # single UTC date would return the wrong event. We pick the event and hour
        # nearest the query time across the window.
        params = self._params([(lat, lon)], query_utc, window_days=1, solar_event=self._solar_event)
        data = self._get_json(self.ENDPOINT, params)
        return self._snapshot_from_payload(data, query_utc, solar_event=self._solar_event)

    def fetch_for_sunset(
        self,
        lat: float,
        lon: float,
        evening_hint: datetime,
        score_offset: timedelta = timedelta(minutes=10),
    ) -> WeatherSnapshot:
        """Fetch one point and select weather at its sunset minus ``score_offset``.

        The response already contains the complete hourly series and daily
        sunset values. Selecting the target hour from that same payload avoids
        the old two-request probe/refetch sequence without accidentally scoring
        the rough 18:00 hint instead of the real fire-cloud window.
        """
        query_utc = self._as_utc(evening_hint)
        params = self._params([(lat, lon)], query_utc, window_days=1, solar_event=self._solar_event)
        data = self._get_json(self.ENDPOINT, params)
        return self._snapshot_for_sunset(data, query_utc, score_offset, solar_event=self._solar_event)

    # Max coordinates per request: the multi-coordinate API is a GET, so too
    # many coords overflow the URL length limit (HTTP 414). ~289 worked, ~484
    # failed; 280 leaves headroom. Larger grids are split across requests.
    MAX_COORDS_PER_REQUEST = 280

    def fetch_many(
        self, coords: list[tuple[float, float]], time: datetime
    ) -> list[WeatherSnapshot]:
        """Fetch many points via the Open-Meteo multi-coordinate API.

        Open-Meteo accepts comma-separated latitude/longitude lists and returns
        one result object per location, turning a map grid into one HTTP
        round-trip (or a few, when the grid exceeds the URL-length limit).
        Returns snapshots in the same order as ``coords``.
        """
        return self._fetch_many(coords, time)

    def fetch_many_for_sunset(
        self,
        coords: list[tuple[float, float]],
        evening_hint: datetime,
        score_offset: timedelta = timedelta(minutes=10),
        *,
        window_days: int = 1,
    ) -> list[WeatherSnapshot]:
        """Batch variant of :meth:`fetch_for_sunset`.

        Every result is evaluated against its own reported sunset. This matters
        for a country-wide grid: western and eastern China differ by several
        hours of solar time even though they share one batched HTTP request.
        """
        return self._fetch_many(
            coords,
            evening_hint,
            sunset_offset=score_offset,
            window_days=window_days,
        )

    def fetch_sunward_profile(
        self,
        lat: float,
        lon: float,
        time: datetime,
        azimuth_deg: float,
        distances_km: tuple[float, ...] | list[float] = DEFAULT_SUNWARD_DISTANCES_KM,
    ) -> WeatherSnapshot:
        """Fetch the detailed observer-to-sun cross-section at one instant.

        All samples use the observer's scoring time; using each sample's own
        sunset would shear an 800 km cross-section across different instants.
        Weather and pressure-level winds come from one multi-coordinate
        forecast request. AOD comes from one auxiliary Air Quality request and
        degrades gracefully to ``None`` if that service is unavailable.
        """
        if not distances_km or distances_km[0] != 0:
            raise ValueError("sunward profile distances must start at 0 km")

        target_utc = self._as_utc(time)
        distances = [float(d) for d in distances_km]
        coords = sunward_coordinates(lat, lon, azimuth_deg, distances)

        # Weather and air-quality are independent upstream endpoints; fetch them
        # concurrently so a point forecast pays one round-trip of latency, not two.
        def _fetch_weather():
            return self._get_json(
                self.ENDPOINT,
                self._params(
                    coords,
                    target_utc,
                    window_days=0,
                    hourly=self.DETAIL_HOURLY,
                    extra={"wind_speed_unit": "ms"},
                    solar_event=self._solar_event,
                ),
            )

        def _fetch_air():
            # AOD improves the forecast but must not make point forecasts fail;
            # CleanAirGate falls back to visibility when it is absent.
            try:
                return self._get_json(
                    self.AIR_QUALITY_ENDPOINT,
                    self._air_quality_params(coords, target_utc),
                )
            except Exception:
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            weather_future = pool.submit(_fetch_weather)
            air_future = pool.submit(_fetch_air)
            weather_payload = weather_future.result()
            air_payload = air_future.result()

        weather_results = (
            weather_payload if isinstance(weather_payload, list) else [weather_payload]
        )
        if len(weather_results) != len(coords):
            raise ValueError("Open-Meteo returned an incomplete sunward profile")
        snapshots = [
            self._snapshot_from_payload(item, target_utc, weather_time_utc=target_utc, solar_event=self._solar_event)
            for item in weather_results
        ]

        aod_values: list[float | None] = [None] * len(coords)
        if air_payload is not None:
            air_results = air_payload if isinstance(air_payload, list) else [air_payload]
            if len(air_results) == len(coords):
                aod_values = [self._aod_at_time(item, target_utc) for item in air_results]

        for snapshot, aod in zip(snapshots, aod_values):
            snapshot.aerosol_optical_depth = aod

        centre = snapshots[0]
        centre.sunward_profile = SunwardProfile(
            azimuth_deg=float(azimuth_deg) % 360.0,
            distances_km=distances,
            cloud_low_pct=[s.cloud_low_pct for s in snapshots],
            cloud_mid_pct=[s.cloud_mid_pct for s in snapshots],
            cloud_high_pct=[s.cloud_high_pct for s in snapshots],
            aerosol_optical_depth=aod_values,
            wind_speed_850_m_s=[s.wind_speed_850_m_s for s in snapshots],
            wind_direction_850_deg=[s.wind_direction_850_deg for s in snapshots],
            wind_speed_700_m_s=[s.wind_speed_700_m_s for s in snapshots],
            wind_direction_700_deg=[s.wind_direction_700_deg for s in snapshots],
            wind_speed_400_m_s=[s.wind_speed_400_m_s for s in snapshots],
            wind_direction_400_deg=[s.wind_direction_400_deg for s in snapshots],
        )
        return centre

    def _fetch_many(
        self,
        coords: list[tuple[float, float]],
        time: datetime,
        *,
        sunset_offset: timedelta | None = None,
        window_days: int = 1,
    ) -> list[WeatherSnapshot]:
        if not coords:
            return []
        query_utc = self._as_utc(time)

        out: list[WeatherSnapshot] = []
        for i in range(0, len(coords), self.MAX_COORDS_PER_REQUEST):
            chunk = coords[i:i + self.MAX_COORDS_PER_REQUEST]
            payload = self._get_json(
                self.ENDPOINT,
                self._params(chunk, query_utc, window_days=window_days, solar_event=self._solar_event),
            )
            results = payload if isinstance(payload, list) else [payload]
            if sunset_offset is None:
                out.extend(
                    self._snapshot_from_payload(r, query_utc, solar_event=self._solar_event)
                    for r in results
                )
            else:
                out.extend(
                    self._snapshot_for_sunset(r, query_utc, sunset_offset, solar_event=self._solar_event)
                    for r in results
                )
        return out

    @staticmethod
    def _as_utc(time: datetime) -> datetime:
        if time.tzinfo is None:
            time = time.replace(tzinfo=timezone.utc)
        return time.astimezone(timezone.utc)

    @classmethod
    def _params(
        cls,
        coords: list[tuple[float, float]],
        query_utc: datetime,
        *,
        window_days: int,
        hourly: str | None = None,
        extra: dict | None = None,
        solar_event: SolarEvent | str = SolarEvent.SUNSET,
    ) -> dict:
        params = {
            "latitude": ",".join(f"{lat:.4f}" for lat, _ in coords),
            "longitude": ",".join(f"{lon:.4f}" for _, lon in coords),
            "hourly": hourly or cls.HOURLY,
            "daily": spec_for(solar_event).daily_field,
            "timezone": "UTC",
            "start_date": (query_utc - timedelta(days=window_days)).strftime("%Y-%m-%d"),
            "end_date": (query_utc + timedelta(days=window_days)).strftime("%Y-%m-%d"),
        }
        if extra:
            params.update(extra)
        return params

    @staticmethod
    def _air_quality_params(
        coords: list[tuple[float, float]], query_utc: datetime
    ) -> dict:
        day = query_utc.strftime("%Y-%m-%d")
        return {
            "latitude": ",".join(f"{lat:.4f}" for lat, _ in coords),
            "longitude": ",".join(f"{lon:.4f}" for _, lon in coords),
            "hourly": "aerosol_optical_depth",
            "timezone": "UTC",
            "start_date": day,
            "end_date": day,
        }

    @staticmethod
    def _aod_at_time(data: dict, query_utc: datetime) -> float | None:
        from datetime import datetime as _dt

        hourly = data.get("hourly") or {}
        times_raw = hourly.get("time") or []
        values = hourly.get("aerosol_optical_depth") or []
        if not times_raw or not values:
            return None
        times = []
        for value in times_raw:
            parsed = _dt.fromisoformat(value)
            parsed = (
                parsed.replace(tzinfo=timezone.utc)
                if parsed.tzinfo is None
                else parsed.astimezone(timezone.utc)
            )
            times.append(parsed)
        idx = min(
            range(len(times)),
            key=lambda i: abs((times[i] - query_utc).total_seconds()),
        )
        if idx >= len(values) or values[idx] is None:
            return None
        return float(values[idx])

    def _get_json(self, url: str, params: dict):
        if self._session is not None:
            resp = self._session.get(url, params=params, timeout=self._timeout)
            resp.raise_for_status()
            return resp.json()
        import json
        import time as time_module
        from urllib.error import HTTPError
        from urllib.parse import urlencode
        from urllib.request import urlopen

        request_url = f"{url}?{urlencode(params)}"
        for attempt in range(3):
            try:
                with urlopen(request_url, timeout=self._timeout) as fh:
                    return json.loads(fh.read().decode("utf-8"))
            except HTTPError as exc:
                if exc.code != 429 or attempt == 2:
                    raise
                retry_header = exc.headers.get("Retry-After")
                try:
                    delay = float(retry_header) if retry_header else 1.5 * (attempt + 1)
                except ValueError:
                    delay = 1.5 * (attempt + 1)
                time_module.sleep(min(delay, 10.0))

        raise RuntimeError("unreachable")

    @classmethod
    def _snapshot_for_sunset(
        cls,
        data: dict,
        query_utc: datetime,
        score_offset: timedelta,
        *,
        solar_event: SolarEvent | str = SolarEvent.SUNSET,
    ) -> WeatherSnapshot:
        event = cls._nearest_event(data, query_utc, solar_event=solar_event)
        weather_time = (event or query_utc) - score_offset
        return cls._snapshot_from_payload(
            data, query_utc, weather_time_utc=weather_time, solar_event=solar_event
        )

    @staticmethod
    def _nearest_event(
        data: dict, query_utc: datetime, *, solar_event: SolarEvent | str = SolarEvent.SUNSET
    ) -> datetime | None:
        from datetime import datetime as _dt

        daily = data.get("daily") or {}
        events = [s for s in (daily.get(spec_for(solar_event).daily_field) or []) if s is not None]
        if not events:
            return None
        event_times = [
            _dt.fromisoformat(s).replace(tzinfo=timezone.utc) for s in events
        ]
        return min(event_times, key=lambda s: abs((s - query_utc).total_seconds()))

    @classmethod
    def _snapshot_from_payload(
        cls,
        data: dict,
        query_utc: datetime,
        *,
        weather_time_utc: datetime | None = None,
        solar_event: SolarEvent | str = SolarEvent.SUNSET,
    ) -> WeatherSnapshot:
        """Pure transform: pick the hour nearest the query time, assemble snapshot."""
        from datetime import datetime as _dt

        hourly = data["hourly"]
        times = [
            _dt.fromisoformat(t).replace(tzinfo=timezone.utc) for t in hourly["time"]
        ]
        # Index of the hour closest to the requested weather instant. Sunset
        # selection may use a separate reference instant (the rough evening
        # hint) so the correct local date is retained around UTC rollovers.
        target_utc = weather_time_utc or query_utc
        idx = min(
            range(len(times)),
            key=lambda i: abs((times[i] - target_utc).total_seconds()),
        )

        def at(key: str) -> float | None:
            seq = hourly.get(key)
            if not seq or seq[idx] is None:
                return None
            return float(seq[idx])

        # The event time lands in the (event-generic) ``sunset_time`` slot.
        sunset_time = cls._nearest_event(data, query_utc, solar_event=solar_event)

        return WeatherSnapshot(
            cloud_low_pct=at("cloud_cover_low") or 0.0,
            cloud_mid_pct=at("cloud_cover_mid") or 0.0,
            cloud_high_pct=at("cloud_cover_high") or 0.0,
            humidity_pct=at("relative_humidity_2m") or 0.0,
            source_label=f"open-meteo@{times[idx].strftime('%Y-%m-%dT%HZ')}",
            retrieved_at=_dt.now(timezone.utc),
            visibility_m=at("visibility"),
            cloud_base_m=None,
            sunset_time=sunset_time,
            wind_speed_850_m_s=at("wind_speed_850hPa"),
            wind_direction_850_deg=at("wind_direction_850hPa"),
            wind_speed_700_m_s=at("wind_speed_700hPa"),
            wind_direction_700_deg=at("wind_direction_700hPa"),
            wind_speed_400_m_s=at("wind_speed_400hPa"),
            wind_direction_400_deg=at("wind_direction_400hPa"),
        )


class HRRRSource:
    """Fetch HRRR cloud cover + 2m RH for a single (lat, lon, time) query.

    HRRR is operational only for CONUS. Time should be UTC; we pick the most
    recent run cycle <= time and a forecast hour that lands closest to `time`.
    """

    DEFAULT_CACHE_DIR = Path("research/data/cache/hrrr")

    def __init__(self, cache_dir: Path | None = None):
        self.cache_dir = Path(cache_dir or self.DEFAULT_CACHE_DIR)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        # Per-instance in-memory cache of parsed datasets keyed by (run_dt, fxx).
        # Herbie's on-disk GRIB2 cache avoids re-downloading, but xarray parsing
        # still costs seconds per call; the map notebook makes hundreds of
        # same-cycle calls, so memoizing the parsed tuple here is the win.
        self._ds_cache: dict[tuple[datetime, int], tuple[xr.Dataset, xr.Dataset]] = {}

    def fetch(self, lat: float, lon: float, time: "datetime") -> WeatherSnapshot:
        from datetime import timezone, timedelta

        # Pick a recent HRRR cycle (HRRR runs hourly) and the right forecast hour.
        # HRRR data typically becomes available ~1–1.5 h after the run time.
        # We use a 2-hour lag (run_dt = time - 2h, fxx=2) so the forecast
        # always references a published cycle, even for near-real-time queries.
        if time.tzinfo is None:
            time = time.replace(tzinfo=timezone.utc)
        run_dt = time.replace(minute=0, second=0, microsecond=0) - timedelta(hours=2)
        fxx = 2

        ds_clouds, ds_rh = self._load_datasets(run_dt, fxx)

        run_label = f"hrrr@{run_dt.strftime('%Y-%m-%dT%HZ')}+f{fxx:02d}"
        return self._snapshot_from_datasets(
            ds_clouds=ds_clouds,
            ds_rh=ds_rh,
            lat=lat, lon=lon,
            run_label=run_label,
            retrieved_at=datetime.now(timezone.utc),
        )

    def _load_datasets(self, run_dt: datetime, fxx: int) -> tuple[xr.Dataset, xr.Dataset]:
        key = (run_dt, fxx)
        cached = self._ds_cache.get(key)
        if cached is not None:
            return cached

        from herbie import Herbie

        H = Herbie(
            run_dt.strftime("%Y-%m-%d %H:%M"),
            model="hrrr",
            product="sfc",
            fxx=fxx,
            save_dir=self.cache_dir,
        )
        # H.xarray for the cloud regex returns a list of 3 Datasets (one per layer); merge into one.
        cloud_list = H.xarray(":(?:HCDC|MCDC|LCDC):")
        ds_clouds = xr.merge(cloud_list, compat="override")
        ds_rh = H.xarray(":RH:2 m above ground")

        self._ds_cache[key] = (ds_clouds, ds_rh)
        return ds_clouds, ds_rh

    @staticmethod
    def _snapshot_from_datasets(
        ds_clouds: xr.Dataset,
        ds_rh: xr.Dataset,
        lat: float, lon: float,
        run_label: str,
        retrieved_at: "datetime",
    ) -> WeatherSnapshot:
        """Pure transform: pick the nearest grid point and assemble a snapshot."""
        # HRRR has 2D latitude/longitude arrays on (y, x).
        yi, xi = _nearest_grid_index(ds_clouds.latitude.values, ds_clouds.longitude.values, lat, lon)
        yi_rh, xi_rh = _nearest_grid_index(ds_rh.latitude.values, ds_rh.longitude.values, lat, lon)

        # cfgrib uses lower-case GRIB shortnames:
        #   HCDC -> 'hcc', MCDC -> 'mcc', LCDC -> 'lcc', RH at 2m -> 'r2'.
        hcc = float(ds_clouds["hcc"].isel(y=yi, x=xi).item())
        mcc = float(ds_clouds["mcc"].isel(y=yi, x=xi).item())
        lcc = float(ds_clouds["lcc"].isel(y=yi, x=xi).item())
        rh = float(ds_rh["r2"].isel(y=yi_rh, x=xi_rh).item())

        return WeatherSnapshot(
            cloud_low_pct=lcc,
            cloud_mid_pct=mcc,
            cloud_high_pct=hcc,
            humidity_pct=rh,
            source_label=run_label,
            retrieved_at=retrieved_at,
        )


def _nearest_grid_index(lat_arr: np.ndarray, lon_arr: np.ndarray, lat: float, lon: float) -> tuple[int, int]:
    """Return (yi, xi) of the grid point nearest (lat, lon).

    Applies a cos(lat) longitude correction so degrees-of-longitude are scaled
    to their actual geographic distance — without it, a degree of longitude is
    treated as equal to a degree of latitude, which biases nearest-neighbor
    selection by ~1 grid cell at mid-latitudes.
    """
    cos_lat = np.cos(np.radians(lat))
    d2 = (lat_arr - lat) ** 2 + ((lon_arr - lon) * cos_lat) ** 2
    yi, xi = np.unravel_index(np.argmin(d2), d2.shape)
    return int(yi), int(xi)
