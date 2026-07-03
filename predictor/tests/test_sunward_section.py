# predictor/tests/test_sunward_section.py
"""Tests for predictor/sunward_section.py — assemble the 2-D sunward cross-section
from a GFS cube along the sunward path (#62 plumbing), offline with a synthetic cube.
"""
from datetime import datetime, timezone

import numpy as np
import pytest

from predictor.cross_section import SunwardCrossSection
from predictor.fetch import FakeSource, WeatherSnapshot
from predictor.profiles import AtmosphericCube
from predictor.ray_path import trace_ray_clearance
from predictor.rules import standard_predictor
from predictor.spatial import build_sunward_path
from predictor.sunward_section import (
    assemble_sunward_cross_section,
    score_point_with_cube,
    score_point_with_sunward_section,
    sunward_cross_section_for_point,
)

_RUN = datetime(2026, 6, 27, 0, tzinfo=timezone.utc)
_VALID = datetime(2026, 6, 27, 9, tzinfo=timezone.utc)
_RET = datetime(2026, 6, 27, 8, tzinfo=timezone.utc)

# A plausible descending-pressure column; the low deck (925/850 hPa) sits ~750–1500 m,
# the mid deck (700/500 hPa) ~3000–5500 m.
_LEVELS = np.array([925.0, 850.0, 700.0, 500.0, 400.0, 300.0])
_GPH = np.array([750.0, 1500.0, 3000.0, 5500.0, 7200.0, 9000.0])
_TEMP = np.array([283.0, 278.0, 270.0, 255.0, 245.0, 233.0])
_Q = np.array([3e-3, 2e-3, 1e-3, 3e-4, 1e-4, 5e-5])


def _uniform_cube(clw) -> AtmosphericCube:
    """A cube whose every grid column is the same profile, with condensate ``clw``."""
    lats = np.array([28.0, 30.0, 32.0])
    lons = np.array([110.0, 115.0, 120.0, 125.0])
    nz, ny, nx = _LEVELS.size, lats.size, lons.size

    def grid(col):
        return np.broadcast_to(np.asarray(col, float)[:, None, None], (nz, ny, nx)).copy()

    zeros = grid(np.zeros(nz))
    return AtmosphericCube(
        lats=lats, lons=lons, levels_hpa=_LEVELS,
        temperature_k=grid(_TEMP),
        relative_humidity_pct=grid(np.full(nz, 30.0)),
        specific_humidity_kg_kg=grid(_Q),
        geopotential_height_m=grid(_GPH),
        u_wind_m_s=zeros, v_wind_m_s=zeros, vertical_velocity_pa_s=zeros,
        cloud_water_kg_kg=grid(clw), cloud_ice_kg_kg=grid(np.zeros(nz)),
        run_time=_RUN, valid_time=_VALID, source_label="gfs@test", retrieved_at=_RET,
        missing=[],
    )


_CLEAR = np.zeros(6)
_MID_DECK = np.array([0.0, 0.0, 5e-4, 5e-4, 0.0, 0.0])   # ~3000–5500 m
_LOW_DECK = np.array([5e-4, 5e-4, 0.0, 0.0, 0.0, 0.0])   # ~750–1500 m
_LOW_AND_HIGH = np.array([5e-4, 5e-4, 0.0, 0.0, 5e-4, 5e-4])  # low ~750–1500 + high ~7200–9000
_HIGH_DECK = np.array([0.0, 0.0, 0.0, 0.0, 5e-4, 5e-4])  # high ~7200–9000 m only


def _path(distances_km, *, domain=None):
    return build_sunward_path(
        30.0, 120.0, _VALID, azimuth_deg=270.0, distances_km=distances_km,
        elevation_fn=lambda la, lo: 0.0, domain=domain,
    )


# ---------------------------------------------------------------------------
# assemble_sunward_cross_section
# ---------------------------------------------------------------------------


def test_assemble_returns_cross_section_aligned_with_path():
    path = _path([0.0, 100.0, 200.0, 400.0])
    xsec = assemble_sunward_cross_section(path, _uniform_cube(_MID_DECK))
    assert isinstance(xsec, SunwardCrossSection)
    assert xsec.distances_km == [0.0, 100.0, 200.0, 400.0]
    assert len(xsec.cloud_layers) == 4


def test_assemble_diagnoses_cloud_in_every_column():
    path = _path([0.0, 100.0, 200.0, 400.0])
    xsec = assemble_sunward_cross_section(path, _uniform_cube(_MID_DECK))
    for column in xsec.cloud_layers:
        assert len(column) >= 1  # the mid deck is diagnosed at each column


def test_assemble_clear_sky_has_no_layers():
    path = _path([0.0, 100.0, 200.0, 400.0])
    xsec = assemble_sunward_cross_section(path, _uniform_cube(_CLEAR))
    for column in xsec.cloud_layers:
        assert column == []


def test_assemble_out_of_domain_column_is_masked_and_layerless():
    # Domain excludes the 400 km sample (it lands near lon 115.85, west of 117).
    path = _path([0.0, 100.0, 200.0, 400.0], domain=(20.0, 40.0, 117.0, 130.0))
    assert path.samples[-1].in_domain is False
    xsec = assemble_sunward_cross_section(path, _uniform_cube(_MID_DECK))
    assert xsec.cloud_layers[-1] == []
    assert not xsec.mask[:, -1].any()      # whole column masked out
    assert xsec.mask[:, 0].any()           # observer column has real data


# ---------------------------------------------------------------------------
# Per-column AOD injection (FA-A2)
# ---------------------------------------------------------------------------


def test_assemble_fills_per_column_aod_from_injected_fn():
    path = _path([0.0, 100.0, 200.0, 400.0])
    # aod_fn keyed on longitude so each column gets a distinct, checkable value.
    xsec = assemble_sunward_cross_section(
        path, _uniform_cube(_CLEAR), aod_fn=lambda la, lo: round(abs(lo) / 1000.0, 4)
    )
    expected = [round(abs(s.lon) / 1000.0, 4) for s in path.samples]
    assert xsec.aerosol_optical_depth_per_column == expected


def test_assemble_out_of_domain_column_has_none_aod():
    path = _path([0.0, 100.0, 200.0, 400.0], domain=(20.0, 40.0, 117.0, 130.0))
    assert path.samples[-1].in_domain is False
    xsec = assemble_sunward_cross_section(
        path, _uniform_cube(_CLEAR), aod_fn=lambda la, lo: 0.2
    )
    assert xsec.aerosol_optical_depth_per_column[-1] is None
    assert xsec.aerosol_optical_depth_per_column[0] == 0.2


def test_assemble_without_aod_fn_leaves_aod_none():
    path = _path([0.0, 100.0, 200.0])
    xsec = assemble_sunward_cross_section(path, _uniform_cube(_CLEAR))
    assert xsec.aerosol_optical_depth_per_column is None


# ---------------------------------------------------------------------------
# End-to-end: the assembled cross-section drives the FA-G5 ray trace (#62 → FA-G5)
# ---------------------------------------------------------------------------


def test_assembled_section_feeds_ray_trace_blocked_by_low_deck():
    # Canvas base at 5 km (vertex ~252 km); a uniform low deck (~750–1500 m) lies on
    # the descending ray and blocks it.
    path = _path([0.0, 50.0, 100.0, 150.0, 250.0, 400.0])
    xsec = assemble_sunward_cross_section(path, _uniform_cube(_LOW_DECK))
    result = trace_ray_clearance(xsec, observer_cloud_base_eff_m=5000.0)
    assert result.clear is False
    assert result.blocked_at_km is not None


def test_assembled_section_feeds_ray_trace_clear_when_no_low_deck():
    path = _path([0.0, 50.0, 100.0, 150.0, 250.0, 400.0])
    xsec = assemble_sunward_cross_section(path, _uniform_cube(_CLEAR))
    result = trace_ray_clearance(xsec, observer_cloud_base_eff_m=5000.0)
    assert result.clear is True


# ---------------------------------------------------------------------------
# sunward_cross_section_for_point — I/O orchestrator (offline via a fake source)
# ---------------------------------------------------------------------------


class _FakeCubeSource:
    """Stub WeatherSource exposing only fetch_cube, returning a canned cube."""

    def __init__(self, cube):
        self._cube = cube
        self.calls = []

    def fetch_cube(self, bbox, time):
        self.calls.append((bbox, time))
        return self._cube


def test_orchestrator_fetches_path_bbox_and_assembles():
    src = _FakeCubeSource(_uniform_cube(_MID_DECK))
    xsec = sunward_cross_section_for_point(
        src, 30.0, 120.0, _VALID, azimuth_deg=270.0,
        distances_km=[0.0, 100.0, 400.0], elevation_fn=lambda la, lo: 0.0,
    )
    assert isinstance(xsec, SunwardCrossSection)
    assert len(src.calls) == 1
    bbox, when = src.calls[0]
    lat_min, lat_max, lon_min, lon_max = bbox
    # The 400 km westward sample (~lon 115.85) must be inside the fetched bbox.
    assert lon_min < 115.85 < lon_max
    assert lat_min < 30.0 < lat_max
    assert when == _VALID


# ---------------------------------------------------------------------------
# score_point_with_sunward_section — activate FA-G5 in a real scoring flow
# ---------------------------------------------------------------------------


def _detail_snapshot():
    return WeatherSnapshot(
        cloud_low_pct=0.0, cloud_mid_pct=0.0, cloud_high_pct=60.0, humidity_pct=50.0,
        source_label="t", retrieved_at=_VALID, sunset_time=_VALID,
        aerosol_optical_depth=0.1,
    )


def test_score_point_with_section_vetoes_gate_on_path_obstruction():
    # A high canvas (~7 km) is diagnosed at the observer, but a low deck lies on the
    # ray path → the assembled cross-section makes trace_ray_clearance veto the
    # sunward gate. This proves FA-G5 is wired end-to-end through scoring.
    predictor = standard_predictor(FakeSource(snapshot=_detail_snapshot()))
    cube_source = _FakeCubeSource(_uniform_cube(_LOW_AND_HIGH))
    fc = score_point_with_sunward_section(
        predictor, cube_source, 30.0, 120.0, _VALID,
        azimuth_deg=270.0, distances_km=[0.0, 100.0, 200.0, 300.0, 400.0],
    )
    assert fc.components["sunward_illumination"] == 0.0


def test_score_point_with_section_returns_forecast():
    predictor = standard_predictor(FakeSource(snapshot=_detail_snapshot()))
    cube_source = _FakeCubeSource(_uniform_cube(_CLEAR))
    fc = score_point_with_sunward_section(
        predictor, cube_source, 30.0, 120.0, _VALID,
        azimuth_deg=270.0, distances_km=[0.0, 100.0, 200.0],
    )
    assert 0.0 <= fc.probability <= 1.0


# ---------------------------------------------------------------------------
# FA-A2 end-to-end: per-column path aerosol extinction vetoes the gate
# ---------------------------------------------------------------------------

# A high-only canvas: the diagnosed observer base is ~6.36 km (deck 6356–9013 m), so
# the grazing ray stays low (≲3 km) over the whole sampled path and the high deck
# never blocks it. Vertex for a 6.36 km base ≈ 285 km.
_FA_A2_DISTANCES = [0.0, 100.0, 200.0, 300.0, 400.0]


def test_dense_upstream_aerosol_vetoes_sunward_gate_end_to_end():
    # Observer air is clean, but dense aerosol (AOD 0.6) sits on the upstream light
    # path (lon < 118 → the 200–400 km columns, around the ~285 km vertex). The
    # per-column trace extinguishes the ray → the sunward gate is vetoed.
    predictor = standard_predictor(FakeSource(snapshot=_detail_snapshot()))
    cube_source = _FakeCubeSource(_uniform_cube(_HIGH_DECK))
    fc = score_point_with_sunward_section(
        predictor, cube_source, 30.0, 120.0, _VALID,
        azimuth_deg=270.0, distances_km=_FA_A2_DISTANCES,
        aod_fn=lambda la, lo: 0.6 if lo < 118.0 else 0.0,
    )
    assert fc.components["sunward_illumination"] == 0.0


def test_clean_path_aerosol_does_not_veto_sunward_gate_end_to_end():
    # Same scene, but uniformly clean aerosol (below the opaque threshold) → ray is
    # clear, the gate falls through to its 1-D geometry branch, and since the FakeSource
    # snapshot carries no sunward transect that branch returns None. So the component
    # is ABSENT (not 0.0): path extinction did not veto. (The over-veto failure mode
    # would instead put a 0.0 here, which this pins against.)
    predictor = standard_predictor(FakeSource(snapshot=_detail_snapshot()))
    cube_source = _FakeCubeSource(_uniform_cube(_HIGH_DECK))
    fc = score_point_with_sunward_section(
        predictor, cube_source, 30.0, 120.0, _VALID,
        azimuth_deg=270.0, distances_km=_FA_A2_DISTANCES,
        aod_fn=lambda la, lo: 0.03,
    )
    assert "sunward_illumination" not in fc.components


def test_score_point_with_cube_matches_fetching_variant():
    # The shared-cube core (#62) must reproduce the fetch-per-point entry exactly,
    # given the same predictor + cube + snapshot.
    snapshot = _detail_snapshot()
    cube = _uniform_cube(_LOW_AND_HIGH)
    predictor = standard_predictor(FakeSource(snapshot=snapshot))
    dist = [0.0, 100.0, 200.0, 300.0, 400.0]
    fetched = score_point_with_sunward_section(
        predictor, _FakeCubeSource(cube), 30.0, 120.0, _VALID, distances_km=dist,
    )
    shared = score_point_with_cube(
        predictor, cube, snapshot, 30.0, 120.0, _VALID, distances_km=dist,
    )
    assert shared.probability == pytest.approx(fetched.probability)
    assert shared.components == fetched.components


def test_more_upstream_aerosol_never_raises_composite_probability():
    # FA-A2 composite metamorphic, through the REAL aod_fn → assemble → trace → gate
    # path: making the upstream path dirtier can only lower the composite. Clean is
    # lit (>0); dense upstream is vetoed (=0). Strictly lower here (non-vacuous).
    predictor = standard_predictor(FakeSource(snapshot=_detail_snapshot()))
    cube_source = _FakeCubeSource(_uniform_cube(_HIGH_DECK))

    def score(aod_fn):
        return score_point_with_sunward_section(
            predictor, cube_source, 30.0, 120.0, _VALID,
            azimuth_deg=270.0, distances_km=_FA_A2_DISTANCES, aod_fn=aod_fn,
        ).probability

    clean = score(lambda la, lo: 0.03)
    dirty_upstream = score(lambda la, lo: 0.6 if lo < 118.0 else 0.0)
    assert dirty_upstream <= clean + 1e-12
    assert clean > 0.0
    assert dirty_upstream == 0.0


# ---- FA-C4 (#86): convective-regime detection in the detailed point path ----


def _convective_cube() -> AtmosphericCube:
    """Uniform columns with a hot humid surface under a conditionally unstable
    lapse, capped by a strong inversion at the top level (manual §1.4.1)."""
    lats = np.array([28.0, 30.0, 32.0])
    lons = np.array([110.0, 115.0, 120.0, 125.0])
    temps = np.array([303.0, 295.65, 285.15, 267.65, 255.75, 270.0])
    rh = np.array([90.0, 85.0, 60.0, 40.0, 30.0, 10.0])
    # normalize() derives dewpoints from specific humidity (the moisture master
    # variable), so the humid surface must be expressed in q: ~23 g/kg at 925
    # hPa/303 K ⇒ Td ≈ 299 K ⇒ LCL ≈ 465 m above the surface level.
    q_humid = np.array([2.3e-2, 1.5e-2, 8e-3, 2e-3, 5e-4, 1e-4])
    nz, ny, nx = _LEVELS.size, lats.size, lons.size

    def grid(col):
        return np.broadcast_to(np.asarray(col, float)[:, None, None], (nz, ny, nx)).copy()

    zeros = grid(np.zeros(nz))
    return AtmosphericCube(
        lats=lats, lons=lons, levels_hpa=_LEVELS,
        temperature_k=grid(temps),
        relative_humidity_pct=grid(rh),
        specific_humidity_kg_kg=grid(q_humid),
        geopotential_height_m=grid(_GPH),
        u_wind_m_s=zeros, v_wind_m_s=zeros, vertical_velocity_pa_s=zeros,
        cloud_water_kg_kg=grid(_MID_DECK), cloud_ice_kg_kg=grid(np.zeros(nz)),
        run_time=_RUN, valid_time=_VALID, source_label="gfs@test", retrieved_at=_RET,
    )


def _no_congestus_config():
    from predictor.stability import StabilityConfig

    return StabilityConfig(congestus_min_depth_m=1e9)   # threshold unreachable


def test_stable_cube_is_labeled_stratiform_with_zero_regression():
    predictor = standard_predictor(FakeSource(snapshot=_detail_snapshot()))
    dist = [0.0, 100.0, 200.0]
    baseline = score_point_with_cube(
        predictor, _uniform_cube(_LOW_AND_HIGH), _detail_snapshot(),
        30.0, 120.0, _VALID, distances_km=dist,
        stability_config=_no_congestus_config(),
    )
    labeled = score_point_with_cube(
        predictor, _uniform_cube(_LOW_AND_HIGH), _detail_snapshot(),
        30.0, 120.0, _VALID, distances_km=dist,
    )
    assert labeled.geometry["cloud_regime"] == "stratiform"
    assert labeled.probability == baseline.probability           # 零回归
    assert "convective_regime_damping" not in labeled.components


def test_congestus_cube_is_damped_labeled_and_explained():
    predictor = standard_predictor(FakeSource(snapshot=_detail_snapshot()))
    dist = [0.0, 100.0, 200.0]
    cube = _convective_cube()
    undamped = score_point_with_cube(
        predictor, cube, _detail_snapshot(), 30.0, 120.0, _VALID,
        distances_km=dist, stability_config=_no_congestus_config(),
    )
    damped = score_point_with_cube(
        predictor, cube, _detail_snapshot(), 30.0, 120.0, _VALID, distances_km=dist,
    )

    geometry = damped.geometry
    assert geometry["cloud_regime"] == "cumulus_congestus"
    assert geometry["unstable_depth_m"] >= 2000.0
    assert geometry["convective_duration_min"] > 0.0
    assert damped.components["convective_regime_damping"] == 0.5
    assert damped.probability == pytest.approx(
        0.5 + (undamped.probability - 0.5) * 0.5
    )
    assert "对流云况" in damped.explanation
