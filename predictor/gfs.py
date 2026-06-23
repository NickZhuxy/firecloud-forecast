"""GFS 0.25° pressure-level data adapter.

Produces standardized vertical data (``AtmosphericProfile`` for a point,
``AtmosphericCube`` for a bbox region) from the free GFS 0.25° GRIB, for use by
point soundings, the 800 km sunward cross-section, and the national grid.

Key constraint: GFS GRIB byte-range subsetting is per message = per
(variable × level), and each message is the *global* 0.25° field. Download cost
is reduced only by selecting fewer variables/levels, never by bbox; a region is
cropped in memory after parsing. A global cube over 20 levels × 8 variables is
~6.6 GB, so ``fetch_cube`` always crops to the requested bbox.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import xarray as xr

from predictor.profiles import PROFILE_VARS, AtmosphericCube

# GFS cfgrib shortname -> our profile field name.
GFS_VAR_MAP: dict[str, str] = {
    "t": "temperature_k",
    "r": "relative_humidity_pct",
    "q": "specific_humidity_kg_kg",
    "gh": "geopotential_height_m",
    "u": "u_wind_m_s",
    "v": "v_wind_m_s",
    "w": "vertical_velocity_pa_s",
    "clwmr": "cloud_water_kg_kg",
    "icmr": "cloud_ice_kg_kg",
}

CYCLE_HOURS = 6   # GFS runs at 00/06/12/18Z
LAG_HOURS = 4     # pgrb2.0p25 is typically published ~3.5–4 h after the cycle


class GFSUnavailable(RuntimeError):
    """Raised when no usable GFS cycle could be loaded after fallbacks."""


class GFSSource:
    """Fetch GFS 0.25° pressure-level profiles and region cubes."""

    DEFAULT_CACHE_DIR = Path("research/data/cache/gfs")
    DEFAULT_LEVELS_HPA: tuple[float, ...] = (
        1000.0, 975.0, 950.0, 925.0, 900.0, 850.0, 800.0, 750.0, 700.0, 650.0,
        600.0, 550.0, 500.0, 450.0, 400.0, 350.0, 300.0, 250.0, 200.0, 150.0,
    )
    # Half-width (degrees) of the bbox used to crop a single-point fetch.
    POINT_PAD_DEG = 0.5
    MAX_CYCLE_FALLBACK = 2

    def __init__(
        self,
        cache_dir: Path | str | None = None,
        levels: tuple[float, ...] | None = None,
    ):
        self.cache_dir = Path(cache_dir or self.DEFAULT_CACHE_DIR)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.levels = tuple(levels) if levels else self.DEFAULT_LEVELS_HPA
        # Per-instance in-memory cache of parsed datasets keyed by (run_dt, fxx),
        # mirroring HRRRSource: avoids re-parsing for repeated same-cycle queries.
        self._ds_cache: dict[tuple[datetime, int], xr.Dataset] = {}

    # ---- public API -----------------------------------------------------

    def fetch_profile(
        self, lat: float, lon: float, valid_time: datetime
    ) -> "AtmosphericProfile":
        bbox = (
            lat - self.POINT_PAD_DEG, lat + self.POINT_PAD_DEG,
            lon - self.POINT_PAD_DEG, lon + self.POINT_PAD_DEG,
        )
        return self.fetch_cube(bbox, valid_time).profile_at(lat, lon)

    def fetch_cube(
        self, bbox: tuple[float, float, float, float], valid_time: datetime
    ) -> AtmosphericCube:
        valid_utc = _as_utc(valid_time)
        run_dt, fxx = self._select_cycle(valid_utc)
        ds, run_used, fxx_used = self._load_with_fallback(run_dt, fxx)
        return self._cube_from_datasets(
            ds,
            bbox=bbox,
            levels=self.levels,
            run_time=run_used,
            valid_time=valid_utc,
            source_label=f"gfs@{run_used:%Y-%m-%dT%HZ}+f{fxx_used:02d}",
            retrieved_at=datetime.now(timezone.utc),
        )

    # ---- cycle selection / loading -------------------------------------

    @staticmethod
    def _select_cycle(valid_time: datetime) -> tuple[datetime, int]:
        """Most recent published 6-hourly cycle and the nearest forecast hour."""
        valid_utc = _as_utc(valid_time)
        available = valid_utc - timedelta(hours=LAG_HOURS)
        run = available.replace(minute=0, second=0, microsecond=0)
        run -= timedelta(hours=run.hour % CYCLE_HOURS)
        fxx = max(0, round((valid_utc - run).total_seconds() / 3600.0))
        return run, fxx

    def _load_with_fallback(
        self, run_dt: datetime, fxx: int
    ) -> tuple[xr.Dataset, datetime, int]:
        last_exc: Exception | None = None
        for step in range(self.MAX_CYCLE_FALLBACK + 1):
            run = run_dt - timedelta(hours=CYCLE_HOURS * step)
            # Stepping back a cycle keeps the same valid time, so the forecast
            # hour grows by one cycle length per step.
            f = fxx + CYCLE_HOURS * step
            try:
                return self._load_dataset(run, f), run, f
            except Exception as exc:  # noqa: BLE001 — try the previous cycle
                last_exc = exc
        raise GFSUnavailable(
            f"no usable GFS cycle near {run_dt:%Y-%m-%dT%HZ} after "
            f"{self.MAX_CYCLE_FALLBACK} fallbacks"
        ) from last_exc

    def _load_dataset(self, run_dt: datetime, fxx: int) -> xr.Dataset:
        key = (run_dt, fxx)
        cached = self._ds_cache.get(key)
        if cached is not None:
            return cached
        ds = self._download_dataset(run_dt, fxx)
        self._ds_cache[key] = ds
        return ds

    def _download_dataset(self, run_dt: datetime, fxx: int) -> xr.Dataset:
        """Download + parse the GFS pressure-level subset via Herbie (network)."""
        from herbie import Herbie

        H = Herbie(
            run_dt.strftime("%Y-%m-%d %H:%M"),
            model="gfs",
            product="pgrb2.0p25",
            fxx=fxx,
            save_dir=self.cache_dir,
        )
        # Subset to our variables on pressure (mb) levels. cfgrib may split into
        # several datasets by step/type; merge into one isobaric dataset.
        search = r":(?:TMP|RH|SPFH|HGT|UGRD|VGRD|VVEL|CLWMR|ICMR):\d+ mb:"
        parsed = H.xarray(search)
        if isinstance(parsed, list):
            return xr.merge(parsed, compat="override", combine_attrs="override")
        return parsed

    # ---- pure transform (tested with synthetic xarray) -----------------

    @staticmethod
    def _cube_from_datasets(
        ds: xr.Dataset,
        bbox: tuple[float, float, float, float],
        levels: tuple[float, ...],
        run_time: datetime,
        valid_time: datetime,
        source_label: str,
        retrieved_at: datetime,
    ) -> AtmosphericCube:
        lat_min, lat_max, lon_min, lon_max = bbox

        grid_levels = [float(v) for v in np.asarray(ds["isobaricInhPa"].values).ravel()]
        present_levels = sorted(
            (lv for lv in levels if lv in set(grid_levels)), reverse=True
        )
        sub = ds.sel(isobaricInhPa=present_levels)

        lats = np.asarray(sub["latitude"].values, dtype=float)
        grid_lons = np.asarray(sub["longitude"].values, dtype=float)
        uses_0_360 = float(np.nanmax(grid_lons)) > 180.0

        def _norm(x: float) -> float:
            return x % 360.0 if uses_0_360 else ((x + 180.0) % 360.0 - 180.0)

        lat_mask = (lats >= lat_min) & (lats <= lat_max)
        lo, hi = _norm(lon_min), _norm(lon_max)
        if lo <= hi:
            lon_mask = (grid_lons >= lo) & (grid_lons <= hi)
        else:  # bbox crosses the 0/360 seam
            lon_mask = (grid_lons >= lo) | (grid_lons <= hi)

        lat_idx = np.where(lat_mask)[0]
        lon_idx = np.where(lon_mask)[0]
        sub = sub.isel(latitude=lat_idx, longitude=lon_idx)

        out_lats = np.asarray(sub["latitude"].values, dtype=float)
        out_lons = np.asarray(sub["longitude"].values, dtype=float)
        nz, ny, nx = len(present_levels), out_lats.size, out_lons.size

        short_by_field = {v: k for k, v in GFS_VAR_MAP.items()}
        arrays: dict[str, np.ndarray] = {}
        missing: list[str] = []
        for field_name in PROFILE_VARS:
            short = short_by_field[field_name]
            if short in sub.data_vars:
                arr = (
                    sub[short]
                    .transpose("isobaricInhPa", "latitude", "longitude")
                    .values.astype(float)
                )
            else:
                arr = np.full((nz, ny, nx), np.nan)
                missing.append(field_name)
            arrays[field_name] = arr

        return AtmosphericCube(
            lats=out_lats,
            lons=out_lons,
            levels_hpa=np.asarray(present_levels, dtype=float),
            run_time=run_time,
            valid_time=valid_time,
            source_label=source_label,
            retrieved_at=retrieved_at,
            missing=missing,
            **arrays,
        )


def _as_utc(time: datetime) -> datetime:
    if time.tzinfo is None:
        time = time.replace(tzinfo=timezone.utc)
    return time.astimezone(timezone.utc)
