"""Real cached-GFS regression benchmark for Stage B refinement (#59, PR-B).

Fulfils the spec's real-sample acceptance: refined national cells must match
the 25 km single-point truth at overlapping coordinates. "Truth" here is the
same engine degraded to one cell — its own sunward-path bbox, its own
``fetch_cube`` call, the same snapshot synthesis — i.e. the deployed
single-point detailed path, while the national field shares one cube per
(hour, tile) group. Agreement proves the shared-cube tiling introduces no
error on real data (crop windows come from the same decoded global dataset).

Needs the on-disk GFS cache left by the #59 §2 live validation (2026-06-30
pressure subsets, ~210 MB each). Skips cleanly when absent. Run with:

    PYTHONPATH=. UV_CACHE_DIR=.uv-cache MPLCONFIGDIR=.uv-cache/matplotlib \
        uv run --no-sync python -m pytest -m integration -k national_refine -q
"""
from datetime import date
from pathlib import Path

import numpy as np
import pytest

from predictor.gfs import GFSSource
from predictor.national_field import build_national_field
from predictor.national_physics import NationalPhysicsConfig
from predictor.national_refine import refine_field
from predictor.solar_event import SolarEvent
from predictor.sunset_grid import (
    hourly_valid_times,
    nearest_valid_time_indices,
    sunset_utc_grid,
)

_DATE = date(2026, 6, 30)
_BBOX = (28.0, 34.0, 116.0, 122.0)   # Yangtze delta — inside the §2 validation area
# Engine equivalence, not product accuracy: modest threshold keeps a healthy
# sample even on a quiet day over this sub-bbox.
_THRESHOLD = 0.40
_MAX_SAMPLES = 12
_CACHE = Path("research/data/cache/gfs/pressure/gfs/20260630")


def _cache_ready() -> bool:
    return any(
        f.stat().st_size > 190_000_000 for f in _CACHE.glob("subset_*")
    ) if _CACHE.is_dir() else False


@pytest.mark.integration
@pytest.mark.skipif(not _cache_ready(), reason="no cached 2026-06-30 GFS pressure subsets")
def test_national_refined_cells_match_single_point_truth():
    src = GFSSource()
    cfg = NationalPhysicsConfig(enabled=True, refine=True, refine_threshold=_THRESHOLD)
    field = build_national_field(
        src, _BBOX, _DATE, solar_event=SolarEvent.SUNSET,
        physics_config=cfg, cube_source=src,
    )

    ref = field.physics["refinement"]
    assert ref["status"] == "run"
    assert ref["cells_refined"] >= 3, "benchmark needs refined cells to sample"
    assert field.refined_mask is not None

    # Reconstruct each cell's event hour with the same pure helpers the
    # national pipeline uses (deterministic on fixed date/grid).
    sunsets = sunset_utc_grid(_DATE, field.lats, field.lons, solar_event=SolarEvent.SUNSET)
    selected = nearest_valid_time_indices(sunsets, field.valid_times)

    cells = np.argwhere(field.refined_mask)
    order = np.argsort(
        field.probability[field.refined_mask], kind="stable"
    )[::-1]
    sampled = [tuple(cells[k]) for k in order[:_MAX_SAMPLES]]

    deltas = []
    for j, i in sampled:
        hour_idx = int(selected[j, i])
        grid = src.fetch_surface_grid(_BBOX, field.valid_times[hour_idx])

        def at(value_grid):
            jj = int(np.abs(np.asarray(grid.lats) - field.lats[j]).argmin())
            ii = int(np.abs(np.asarray(grid.lons) - field.lons[i]).argmin())
            return np.asarray(value_grid, dtype=float)[jj, ii]

        surface_1x1 = {
            "cloud_low_pct": np.array([[at(grid.cloud_low_pct)]]),
            "cloud_mid_pct": np.array([[at(grid.cloud_mid_pct)]]),
            "cloud_high_pct": np.array([[at(grid.cloud_high_pct)]]),
            "humidity_pct": np.array([[at(grid.humidity_pct)]]),
            "visibility_m": np.array([[at(grid.visibility_m)]]),
        }
        standalone = refine_field(
            src,
            np.array([field.lats[j]]),
            np.array([field.lons[i]]),
            np.array([[1.0]]),                     # force the single candidate
            np.array([[sunsets[j, i]]]),
            np.array([[0]], dtype=int),
            (field.valid_times[hour_idx],),
            surface_1x1,
            threshold=0.5,
        )
        assert standalone.cells_refined == 1
        truth = float(standalone.refined_probability[0, 0])
        national = float(field.probability[j, i])
        deltas.append(abs(national - truth))

    deltas = np.asarray(deltas)
    mae = float(deltas.mean())
    p90 = float(np.quantile(deltas, 0.9))
    print(
        f"\n[refine-benchmark] date={_DATE} bbox={_BBOX} threshold={_THRESHOLD} "
        f"refined={ref['cells_refined']} sampled={len(sampled)} "
        f"MAE={mae:.4f} P90={p90:.4f} max={float(deltas.max()):.4f}"
    )
    assert mae <= 0.02
    assert p90 <= 0.05
