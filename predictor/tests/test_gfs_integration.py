"""Live GFS integration check — excluded from the default run.

Run explicitly with:  uv run pytest -m integration -k gfs
"""
from datetime import datetime, timezone

import numpy as np
import pytest

from predictor.gfs import GFSSource


@pytest.mark.integration
def test_shanghai_profile_is_complete_from_live_gfs():
    src = GFSSource()
    # A few hours back guarantees a published cycle and a clean forecast hour.
    valid = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    profile = src.fetch_profile(31.23, 121.47, valid)

    assert profile.levels_hpa.size >= 15
    # Core thermodynamic/geometry variables must be present and finite.
    for var in ("temperature_k", "relative_humidity_pct", "geopotential_height_m"):
        col = getattr(profile, var)
        assert col.shape == profile.levels_hpa.shape
        assert np.isfinite(col).any()
    assert "gfs@" in profile.source_label


@pytest.mark.integration
def test_repeated_fetch_hits_cache_without_redownload():
    src = GFSSource()
    valid = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    src.fetch_profile(31.23, 121.47, valid)
    cache_size = len(src._ds_cache)
    src.fetch_profile(31.50, 121.00, valid)  # same cycle, nearby point
    assert len(src._ds_cache) == cache_size  # no new dataset parsed
