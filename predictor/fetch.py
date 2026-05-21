"""Weather data acquisition.

Defines a WeatherSource protocol so callers can swap HRRR / GFS / OpenMeteo.
Real implementations live alongside FakeSource (used by tests).
"""
from __future__ import annotations
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

import numpy as np
import xarray as xr

# Note: herbie is heavy; import lazily inside fetch() so unit tests don't pay the cost.


@dataclass
class WeatherSnapshot:
    cloud_low_pct: float
    cloud_mid_pct: float
    cloud_high_pct: float
    humidity_pct: float
    source_label: str          # e.g. "hrrr@2026-05-20T18Z+f01"
    retrieved_at: datetime

    def to_dict(self) -> dict:
        d = asdict(self)
        d["retrieved_at"] = self.retrieved_at.isoformat()
        return d


class WeatherSource(Protocol):
    def fetch(self, lat: float, lon: float, time: datetime) -> WeatherSnapshot: ...


@dataclass
class FakeSource:
    """Test fixture — returns a pre-built WeatherSnapshot for any query."""
    snapshot: WeatherSnapshot

    def fetch(self, lat: float, lon: float, time: datetime) -> WeatherSnapshot:
        return self.snapshot


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
