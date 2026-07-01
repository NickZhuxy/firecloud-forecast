"""Stage B refinement engine (#59), offline with a synthetic cube."""
from datetime import datetime, timezone

import numpy as np
import pytest

from predictor.national_refine import (
    REFINE_SUNWARD_DISTANCES_KM,
    RefineResult,
    _PlaceholderSource,
    _bbox_cell_count,
    _candidate_groups,
    _group_bbox,
    _synthesize_snapshot,
)
from predictor.spatial import build_sunward_path

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


def test_candidate_groups_key_by_hour_and_tile():
    mask = np.array([[True, False], [True, True]])
    selected = np.array([[0, 0], [1, 0]])
    lats = np.array([24.0, 31.0])     # tiles 4, 6 at tile_deg=5
    lons = np.array([100.0, 118.0])   # tiles 20, 23
    groups = _candidate_groups(mask, selected, lats, lons, tile_deg=5.0)
    # (0,0) hour0 tile(4,20); (1,0) hour1 tile(6,20); (1,1) hour0 tile(6,23)
    assert groups[(0, 4, 20)] == [(0, 0)]
    assert groups[(1, 6, 20)] == [(1, 0)]
    assert groups[(0, 6, 23)] == [(1, 1)]
    assert (0, 4, 23) not in groups  # masked-out cell excluded


def test_group_bbox_covers_every_member_sunward_path():
    lats = np.array([30.0, 31.0])
    lons = np.array([118.0, 120.0])
    event_times = np.full((2, 2), np.datetime64(int(_VALID.timestamp()), "s"))
    cells = [(0, 0), (1, 1)]
    dist = (0.0, 100.0, 200.0)
    bbox = _group_bbox(cells, lats, lons, event_times, 270.0, dist, margin_deg=0.5)
    lat_min, lat_max, lon_min, lon_max = bbox
    for j, i in cells:
        for s in build_sunward_path(
            float(lats[j]), float(lons[i]), _VALID, azimuth_deg=270.0, distances_km=dist
        ).samples:
            assert lat_min <= s.lat <= lat_max
            assert lon_min <= s.lon <= lon_max


def test_bbox_cell_count_uses_quarter_degree():
    # 10° x 5° at 0.25° => 41 x 21 = 861 cells.
    assert _bbox_cell_count((20.0, 25.0, 100.0, 110.0)) == 41 * 21
