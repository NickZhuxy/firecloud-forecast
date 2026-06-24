"""Live GFS surface-grid integration check — excluded from the default run.

Run explicitly:  uv run pytest -m integration -k surface
"""
from datetime import datetime, timezone

import numpy as np
import pytest

from predictor.gfs import GFSSource
from predictor.national_field import build_national_field


@pytest.mark.integration
def test_surface_grid_over_china_is_complete_from_live_gfs():
    src = GFSSource()
    valid = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    # bbox = (lat_min, lat_max, lon_min, lon_max) — a small East China box.
    grid = src.fetch_surface_grid((30.0, 34.0, 118.0, 122.0), valid)

    assert grid.lats.size >= 3 and grid.lons.size >= 3
    # Cloud cover must be a real, finite percentage field (shortnames lcc/mcc/hcc).
    for cover in (grid.cloud_low_pct, grid.cloud_mid_pct, grid.cloud_high_pct):
        assert cover.shape == (grid.lats.size, grid.lons.size)
        assert np.isfinite(cover).any()
    # RH (r2) and visibility (vis) shortnames resolve to finite fields.
    assert "r2" not in grid.missing, "GFS 2 m RH shortname mismatch"
    assert "vis" not in grid.missing, "GFS surface visibility shortname mismatch"
    assert np.isfinite(grid.humidity_pct).any()


@pytest.mark.integration
def test_build_national_field_from_live_gfs():
    src = GFSSource()
    valid = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    field = build_national_field(src, (18.0, 40.0, 100.0, 124.0), valid.date())
    assert field.n_points > 1000
    assert field.surface_fetches >= 2
    assert field.additional_surface_fetches == field.surface_fetches - 1
    assert field.decoded_input_bytes > 0
    assert field.download_bytes is not None and field.download_bytes > 0
    assert field.additional_download_bytes is not None
    assert np.all((field.probability >= 0.0) & (field.probability <= 1.0))
    assert field.runtime_s >= 0.0 and field.peak_mem_mb > 0.0
