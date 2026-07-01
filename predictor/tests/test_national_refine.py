"""Stage B refinement engine (#59), offline with a synthetic cube."""
from datetime import datetime, timezone

import numpy as np
import pytest

from predictor.national_refine import (
    REFINE_SUNWARD_DISTANCES_KM,
    RefineResult,
    _PlaceholderSource,
    _synthesize_snapshot,
)

_VALID = datetime(2026, 6, 29, 9, tzinfo=timezone.utc)


def test_refine_distances_are_50km_steps_to_800():
    assert REFINE_SUNWARD_DISTANCES_KM[0] == 0.0
    assert REFINE_SUNWARD_DISTANCES_KM[-1] == 800.0
    assert all(
        b - a == 50.0
        for a, b in zip(REFINE_SUNWARD_DISTANCES_KM, REFINE_SUNWARD_DISTANCES_KM[1:])
    )


def test_placeholder_source_never_fetches():
    with pytest.raises(NotImplementedError):
        _PlaceholderSource().fetch(30.0, 120.0, _VALID)


def test_synthesize_snapshot_maps_surface_fields():
    surface = {
        "cloud_low_pct": np.array([[3.0, 4.0]]),
        "cloud_mid_pct": np.array([[55.0, 60.0]]),
        "cloud_high_pct": np.array([[10.0, 0.0]]),
        "humidity_pct": np.array([[48.0, 50.0]]),
        "visibility_m": np.array([[24000.0, np.nan]]),
        "aod": np.array([[0.12, np.nan]]),
    }
    snap = _synthesize_snapshot(surface, 0, 0, _VALID)
    assert snap.cloud_low_pct == 3.0
    assert snap.cloud_mid_pct == 55.0
    assert snap.humidity_pct == 48.0
    assert snap.visibility_m == 24000.0
    assert snap.aerosol_optical_depth == 0.12
    assert snap.source_label == "national-refine"
    # NaN optional fields collapse to None; missing keys tolerated.
    snap2 = _synthesize_snapshot(surface, 0, 1, _VALID)
    assert snap2.visibility_m is None
    assert snap2.aerosol_optical_depth is None
    snap3 = _synthesize_snapshot(
        {k: v for k, v in surface.items() if k not in ("aod", "visibility_m")}, 0, 0, _VALID
    )
    assert snap3.visibility_m is None
    assert snap3.aerosol_optical_depth is None
