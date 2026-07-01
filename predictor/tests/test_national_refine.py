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
    refine_field,
)
from predictor.profiles import AtmosphericCube
from predictor.rules import standard_predictor
from predictor.spatial import build_sunward_path
from predictor.sunward_section import score_point_with_cube

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


_LEVELS = np.array([925.0, 850.0, 700.0, 500.0, 400.0, 300.0])
_GPH = np.array([750.0, 1500.0, 3000.0, 5500.0, 7200.0, 9000.0])
_TEMP = np.array([283.0, 278.0, 270.0, 255.0, 245.0, 233.0])
_Q = np.array([3e-3, 2e-3, 1e-3, 3e-4, 1e-4, 5e-5])
_MID = np.array([0.0, 0.0, 5e-4, 5e-4, 0.0, 0.0])


def _cube(low_cloud=np.zeros(6)) -> AtmosphericCube:
    lats = np.arange(26.0, 34.01, 0.5)
    lons = np.arange(112.0, 122.01, 0.5)
    nz, ny, nx = _LEVELS.size, lats.size, lons.size

    def grid(col):
        return np.broadcast_to(np.asarray(col, float)[:, None, None], (nz, ny, nx)).copy()

    return AtmosphericCube(
        lats=lats, lons=lons, levels_hpa=_LEVELS,
        temperature_k=grid(_TEMP), relative_humidity_pct=grid(np.full(nz, 30.0)),
        specific_humidity_kg_kg=grid(_Q), geopotential_height_m=grid(_GPH),
        u_wind_m_s=grid(np.zeros(nz)), v_wind_m_s=grid(np.zeros(nz)),
        vertical_velocity_pa_s=grid(np.zeros(nz)),
        cloud_water_kg_kg=grid(_MID + low_cloud), cloud_ice_kg_kg=grid(np.zeros(nz)),
        run_time=_VALID, valid_time=_VALID, source_label="gfs@test", retrieved_at=_VALID,
        missing=[],
    )


class _FakeCubeSource:
    def __init__(self, cube):
        self._cube = cube
        self.calls = 0

    def fetch_cube(self, bbox, time):
        self.calls += 1
        return self._cube


def _surface(shape, low=0.0):
    return {
        "cloud_low_pct": np.full(shape, low),
        "cloud_mid_pct": np.full(shape, 55.0),
        "cloud_high_pct": np.full(shape, 0.0),
        "humidity_pct": np.full(shape, 50.0),
        "visibility_m": np.full(shape, 25000.0),
    }


def _grids():
    lats = np.array([28.0, 30.0])
    lons = np.array([118.0, 120.0])
    event_times = np.full((2, 2), np.datetime64(int(_VALID.timestamp()), "s"))
    selected_time = np.zeros((2, 2), dtype=int)
    return lats, lons, event_times, selected_time


def test_refine_only_candidates_change_others_keep_screen():
    lats, lons, ev, sel = _grids()
    screen = np.array([[0.9, 0.1], [0.1, 0.8]])
    src = _FakeCubeSource(_cube())
    res = refine_field(
        src, lats, lons, screen, ev, sel, (_VALID,), _surface((2, 2)),
        threshold=0.5, distances_km=(0.0, 100.0, 200.0),
    )
    assert isinstance(res, RefineResult)
    assert res.refined_probability[0, 1] == 0.1   # non-candidate unchanged
    assert res.refined_probability[1, 0] == 0.1
    assert res.refined_mask.tolist() == [[True, False], [False, True]]
    assert res.cells_refined == 2


def test_refine_one_cube_per_group():
    lats, lons, ev, sel = _grids()
    screen = np.array([[0.9, 0.9], [0.9, 0.9]])   # 4 candidates, same tile+hour
    src = _FakeCubeSource(_cube())
    res = refine_field(
        src, lats, lons, screen, ev, sel, (_VALID,), _surface((2, 2)),
        threshold=0.5, tile_deg=50.0, distances_km=(0.0, 100.0, 200.0),
    )
    assert src.calls == 1           # ONE shared cube
    assert res.cubes_fetched == 1
    assert res.tiles == 1
    assert res.cells_refined == 4


def test_refined_cell_equals_standalone_score_point_with_cube():
    lats, lons, ev, sel = _grids()
    screen = np.array([[0.9, 0.1], [0.1, 0.1]])
    cube = _cube()
    surface = _surface((2, 2))
    dist = (0.0, 100.0, 200.0)
    res = refine_field(
        _FakeCubeSource(cube), lats, lons, screen, ev, sel, (_VALID,), surface,
        threshold=0.5, distances_km=dist,
    )
    predictor = standard_predictor(_PlaceholderSource())
    snap = _synthesize_snapshot(surface, 0, 0, _VALID)
    expected = score_point_with_cube(
        predictor, cube, snap, 28.0, 118.0, _VALID, distances_km=dist
    ).probability
    assert res.refined_probability[0, 0] == expected


def test_refine_guard_rejects_oversize_cube():
    lats, lons, ev, sel = _grids()
    screen = np.array([[0.9, 0.1], [0.1, 0.1]])
    with pytest.raises(ValueError, match="max_cube_cells"):
        refine_field(
            _FakeCubeSource(_cube()), lats, lons, screen, ev, sel, (_VALID,), _surface((2, 2)),
            threshold=0.5, distances_km=(0.0, 100.0, 200.0), max_cube_cells=5,
        )


def test_refine_westward_low_cloud_lowers_probability():
    # Metamorphic: obstruction must enter through the CUBE (diagnosed/sunward obstruction
    # outranks the snapshot's low cloud in LowCloudObstruction), so perturb cube low cloud.
    lats, lons, ev, sel = _grids()
    screen = np.array([[0.9, 0.1], [0.1, 0.1]])
    dist = (0.0, 100.0, 200.0)
    clear = refine_field(
        _FakeCubeSource(_cube()), lats, lons, screen, ev, sel, (_VALID,), _surface((2, 2)),
        threshold=0.5, distances_km=dist,
    ).refined_probability[0, 0]
    low = np.array([8e-4, 8e-4, 0.0, 0.0, 0.0, 0.0])   # add 925/850 hPa cloud water
    obstructed = refine_field(
        _FakeCubeSource(_cube(low_cloud=low)), lats, lons, screen, ev, sel, (_VALID,), _surface((2, 2)),
        threshold=0.5, distances_km=dist,
    ).refined_probability[0, 0]
    assert obstructed < clear
