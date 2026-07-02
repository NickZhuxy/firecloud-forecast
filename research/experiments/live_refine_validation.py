"""Live-GFS validation of Stage B national refinement (#59) — run where network works.

Measures the REAL cost of turning refinement on in the national product: it runs
``build_national_field`` twice on live GFS — screen-only, then refine-on with a
shared ``GFSSource`` as the cube source — and prints candidates, cubes fetched,
cells refined, wall time, peak memory, download bytes, and how much the refined
field moves vs the screen. Use it to size PR-B's tile / threshold / caching policy.

Cannot run in a no-egress sandbox (GFS lives on AWS S3). Run on a networked host:

    PYTHONPATH=. uv run --no-sync python research/experiments/live_refine_validation.py \
        --date 2026-06-30 --event sunset --bbox 20 42 100 122 --threshold 0.50

First run downloads GFS GRIB (pressure cube ≈ 180 MB per distinct cycle, global
per-message — bbox does NOT reduce download; it only clips the in-memory cube).
The shared GFSSource caches each (cycle, fxx) dataset, so same-cycle tiles reuse
one download. Re-runs hit the on-disk Herbie cache.
"""
from __future__ import annotations

import argparse
import time
from datetime import date

import numpy as np

from predictor.gfs import GFSSource
from predictor.national_physics import NationalPhysicsConfig
from predictor.national_field import build_national_field
from predictor.solar_event import SolarEvent


def _parse_date(s: str) -> date:
    y, m, d = (int(x) for x in s.split("-"))
    return date(y, m, d)


def _summary(tag, field, seconds):
    finite = field.probability[np.isfinite(field.probability)]
    lo = float(finite.min()) if finite.size else float("nan")
    hi = float(finite.max()) if finite.size else float("nan")
    ge = float(np.mean(finite >= 0.50)) if finite.size else float("nan")
    print(
        f"[{tag}] wall={seconds:6.1f}s  peak_mem={field.peak_mem_mb:6.1f}MB  "
        f"grid={field.probability.shape}  prob[min..max]={lo:.3f}..{hi:.3f}  "
        f">=0.50 frac={ge:.3f}  surface_fetches={field.surface_fetches}  "
        f"dl_MB={None if field.download_bytes is None else round(field.download_bytes/1e6, 1)}"
    )
    return field.probability


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", type=_parse_date, required=True)
    ap.add_argument("--event", choices=["sunset", "sunrise"], default="sunset")
    ap.add_argument("--bbox", type=float, nargs=4, metavar=("LATMIN", "LATMAX", "LONMIN", "LONMAX"),
                    default=[20.0, 42.0, 100.0, 122.0])
    ap.add_argument("--threshold", type=float, default=0.50)
    ap.add_argument("--tile-deg", type=float, default=5.0)
    args = ap.parse_args()

    bbox = tuple(args.bbox)
    event = SolarEvent(args.event)
    print(f"date={args.date} event={event.value} bbox={bbox} threshold={args.threshold} tile_deg={args.tile_deg}")

    # Screen-only (current national product behaviour).
    t0 = time.perf_counter()
    screen = build_national_field(GFSSource(), bbox, args.date, solar_event=event)
    screen_prob = _summary("screen ", screen, time.perf_counter() - t0)

    # Refine-on. ONE shared GFSSource as cube_source so same-cycle tiles reuse a
    # single decoded dataset (per-cycle download, not per-tile).
    cfg = NationalPhysicsConfig(enabled=True, refine=True, refine_threshold=args.threshold)
    cube_source = GFSSource()
    t0 = time.perf_counter()
    refined = build_national_field(
        GFSSource(), bbox, args.date, solar_event=event,
        physics_config=cfg, cube_source=cube_source,
    )
    refined_prob = _summary("refine ", refined, time.perf_counter() - t0)

    ref = refined.physics.get("refinement", {}) if refined.physics else {}
    print(
        f"[refine ] status={ref.get('status')} cells_refined={ref.get('cells_refined')} "
        f"cubes_fetched={ref.get('cubes_fetched')} tiles={ref.get('tiles')} "
        f"tile_deg={ref.get('tile_deg')}"
    )

    delta = np.abs(refined_prob - screen_prob)
    changed = int(np.count_nonzero(delta > 1e-9))
    print(
        f"[delta  ] cells_moved={changed}  mean|Δ|={float(np.nanmean(delta)):.4f}  "
        f"max|Δ|={float(np.nanmax(delta)):.4f}  "
        f"screen>=0.50={int(np.nansum(screen_prob >= 0.50))} -> "
        f"refine>=0.50={int(np.nansum(refined_prob >= 0.50))}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
