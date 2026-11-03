"""Time the local fine product, offline (synthetic cube) or against the GFS cache.

Stage timings come from the existing ``predictor.local_field`` progress log lines,
so the library is measured exactly as it runs. Examples::

    uv run python research/experiments/local_field_benchmark.py synthetic \
        --lat 31.23 --lon 121.47 --radius 150 --resolution 0.1
    uv run python research/experiments/local_field_benchmark.py cached \
        --lat 31.23 --lon 121.47 --date 2026-11-04 --event sunset --json out.json

``cached`` downloads GFS on the first run; later runs reuse the disk cache. It
always fetches Open-Meteo snapshots, and reports that time as ``snapshots_s``.
"""
from __future__ import annotations

import argparse
import cProfile
import json
import logging
import pstats
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from predictor.fetch import WeatherSnapshot  # noqa: E402
from predictor.local_field import build_local_field  # noqa: E402
from predictor.profiles import AtmosphericCube  # noqa: E402
from predictor.rules import standard_predictor  # noqa: E402

SYNTHETIC_VALID = datetime(2026, 6, 29, 9, tzinfo=timezone.utc)

_LEVELS = np.array([925.0, 850.0, 700.0, 500.0, 400.0, 300.0])
_GPH = np.array([750.0, 1500.0, 3000.0, 5500.0, 7200.0, 9000.0])
_TEMP = np.array([283.0, 278.0, 270.0, 255.0, 245.0, 233.0])
_Q = np.array([3e-3, 2e-3, 1e-3, 3e-4, 1e-4, 5e-5])

# Log-line prefixes emitted by predictor.local_field, in run order.
_MARKS = {
    "grid": "Local product grid:",
    "cube_fetch": "Local product GFS cube: fetching",
    "cube_loaded": "Local product GFS cube: loaded",
    "weather_fetch": "Local product weather: fetching",
    "weather_loaded": "Local product weather: loaded",
    "scoring_start": "Local product scoring: scoring",
    "scoring_done": "Local product scoring: scored",
}


def heterogeneous_cube(
    lat_range: tuple[float, float],
    lon_range: tuple[float, float],
    step_deg: float = 0.25,
) -> AtmosphericCube:
    """A deterministic cube whose cloud and humidity columns vary by location.

    Low, mid and high condensate follow different sine patterns of the grid
    indices, so neighbouring columns diagnose to different layers and some
    columns are cloud-free.
    """
    lats = np.arange(lat_range[0], lat_range[1] + step_deg / 2, step_deg)
    lons = np.arange(lon_range[0], lon_range[1] + step_deg / 2, step_deg)
    nz, ny, nx = _LEVELS.size, lats.size, lons.size
    jj, ii = np.meshgrid(np.arange(ny), np.arange(nx), indexing="ij")
    # Cloud bands are ~1000 km wide, so a canvas usually has a clear sunward edge
    # within reach; a small-scale factor still makes neighbouring columns differ.
    detail = 0.6 + 0.4 * np.sin(1.3 * jj + 0.9 * ii)
    band = np.clip(np.sin(0.16 * ii + 0.05 * jj - 3.2), 0.0, None)
    low = np.zeros((ny, nx))
    mid = band * detail
    high = np.clip(np.sin(0.16 * ii + 0.05 * jj - 4.0), 0.0, None) * detail

    water = np.zeros((nz, ny, nx))
    water[0] = water[1] = 3e-4 * low
    water[2] = water[3] = 5e-4 * mid
    ice = np.zeros((nz, ny, nx))
    ice[4] = ice[5] = 2e-4 * high
    cloudiness = np.clip(water / 5e-4 + ice / 2e-4, 0.0, 1.0)

    def column(values):
        return np.broadcast_to(np.asarray(values, float)[:, None, None], (nz, ny, nx)).copy()

    return AtmosphericCube(
        lats=lats, lons=lons, levels_hpa=_LEVELS.copy(),
        temperature_k=column(_TEMP),
        relative_humidity_pct=30.0 + 65.0 * cloudiness,
        specific_humidity_kg_kg=column(_Q),
        geopotential_height_m=column(_GPH),
        u_wind_m_s=column(np.zeros(nz)), v_wind_m_s=column(np.zeros(nz)),
        vertical_velocity_pa_s=column(np.zeros(nz)),
        cloud_water_kg_kg=water, cloud_ice_kg_kg=ice,
        run_time=SYNTHETIC_VALID, valid_time=SYNTHETIC_VALID,
        source_label="gfs@synthetic", retrieved_at=SYNTHETIC_VALID, missing=[],
    )


def synthetic_snapshot(lat: float = 0.0, lon: float = 0.0) -> WeatherSnapshot:
    """Point weather that varies smoothly with location, so modifiers differ by cell."""
    wave = np.sin(3.0 * lat) * np.cos(2.0 * lon)
    return WeatherSnapshot(
        cloud_low_pct=10.0, cloud_mid_pct=float(45.0 + 25.0 * wave),
        cloud_high_pct=20.0, humidity_pct=float(55.0 + 30.0 * wave),
        source_label="synthetic", retrieved_at=SYNTHETIC_VALID,
        sunset_time=SYNTHETIC_VALID, aerosol_optical_depth=0.1,
    )


class SyntheticSource:
    """``predictor.source`` stand-in returning ``synthetic_snapshot(lat, lon)``."""

    def fetch(self, lat, lon, valid_time):
        return synthetic_snapshot(lat, lon)


class _CubeSource:
    def __init__(self, cube):
        self._cube = cube

    def fetch_cube(self, bbox, valid_time):
        return self._cube


class _MarkRecorder(logging.Handler):
    """Record the first time each progress line appears."""

    def __init__(self):
        super().__init__(logging.INFO)
        self.times: dict[str, float] = {}

    def emit(self, record):
        message = record.getMessage()
        for name, prefix in _MARKS.items():
            if name not in self.times and message.startswith(prefix):
                self.times[name] = time.perf_counter()


def _timed(run):
    """Run ``run()`` and return ``(result, marks, start, end)``."""
    logger = logging.getLogger("predictor.local_field")
    recorder = _MarkRecorder()
    previous = logger.level
    logger.addHandler(recorder)
    logger.setLevel(logging.INFO)
    start = time.perf_counter()
    try:
        result = run()
    finally:
        end = time.perf_counter()
        logger.removeHandler(recorder)
        logger.setLevel(previous)
    return result, recorder.times, start, end


def _span(marks: dict, first: str, last: str) -> float:
    if first in marks and last in marks:
        return max(0.0, marks[last] - marks[first])
    return 0.0


def _stage_timings(marks: dict, start: float, end: float) -> dict:
    return {
        "bbox_s": _span(marks, "grid", "cube_fetch"),
        "cube_s": _span(marks, "cube_fetch", "cube_loaded"),
        "snapshots_s": _span(marks, "weather_fetch", "weather_loaded"),
        "scoring_s": _span(marks, "scoring_start", "scoring_done"),
        "render_s": max(0.0, end - marks["scoring_done"]) if "scoring_done" in marks else 0.0,
        "total_s": end - start,
    }


def run_synthetic(
    center: tuple[float, float],
    radius_km: float,
    resolution_deg: float,
) -> dict:
    """Score a local grid on a synthetic cube; no network, no rendering."""
    lat, lon = center
    # Wide enough for every cell's 800 km path in any direction.
    cube = heterogeneous_cube((lat - 10.0, lat + 10.0), (lon - 14.0, lon + 14.0))
    predictor = standard_predictor(SyntheticSource())
    field, marks, start, end = _timed(
        lambda: build_local_field(
            predictor, _CubeSource(cube), lat, lon, SYNTHETIC_VALID,
            radius_km=radius_km, resolution_deg=resolution_deg,
        )
    )
    timings = _stage_timings(marks, start, end)
    return {
        "mode": "synthetic",
        "n_cells": int(field.probability.size),
        **timings,
        "probability": np.asarray(field.probability),
    }


def run_cached(
    center: tuple[float, float],
    target_date: date,
    event: str,
    radius_km: float,
    resolution_deg: float,
    *,
    region: str = "china",
    output_dir: Path = _ROOT / "research" / "data" / "cache" / "bench" / "out",
) -> dict:
    """Generate the real local product with satellite correction off."""
    from predictor.local_product import generate_local_product

    artifacts, marks, start, end = _timed(
        lambda: generate_local_product(
            target_date, output_dir, center[0], center[1],
            solar_event=event, radius_km=radius_km, resolution_deg=resolution_deg,
            satellite=False, region=region,
        )
    )
    metadata = json.loads(Path(artifacts.metadata_path).read_text(encoding="utf-8"))
    timings = _stage_timings(marks, start, end)
    return {
        "mode": "cached",
        "n_cells": metadata.get("grid", {}).get("n_points") or metadata.get("n_points"),
        **timings,
        "total_without_snapshots_s": timings["total_s"] - timings["snapshots_s"],
        "metadata_path": str(artifacts.metadata_path),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("mode", choices=["synthetic", "cached"])
    parser.add_argument("--lat", type=float, default=31.23)
    parser.add_argument("--lon", type=float, default=121.47)
    parser.add_argument("--date", type=date.fromisoformat, default=None)
    parser.add_argument("--event", choices=["sunrise", "sunset"], default="sunset")
    parser.add_argument("--region", default="china")
    parser.add_argument("--radius", type=float, default=150.0)
    parser.add_argument("--resolution", type=float, default=0.1)
    parser.add_argument("--profile", type=Path, default=None, help="write cProfile stats")
    parser.add_argument("--json", type=Path, default=None, help="write timings as JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    center = (args.lat, args.lon)

    def run():
        if args.mode == "synthetic":
            return run_synthetic(center, args.radius, args.resolution)
        return run_cached(
            center, args.date or date.today(), args.event, args.radius, args.resolution,
            region=args.region,
        )

    profiler = cProfile.Profile() if args.profile else None
    if profiler is not None:
        profiler.enable()
    result = run()
    if profiler is not None:
        profiler.disable()
        args.profile.parent.mkdir(parents=True, exist_ok=True)
        profiler.dump_stats(str(args.profile))
        pstats.Stats(str(args.profile)).sort_stats("cumulative").print_stats(25)

    report = {k: v for k, v in result.items() if k != "probability"}
    print(json.dumps(report, indent=2))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
