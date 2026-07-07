# predictor/tests/test_ray_path.py
"""Tests for predictor/ray_path.py — FA-G5 parabolic sunward ray trace.

The ray reaching the observer's cloud base h_eff grazes the (equivalent) ground
at vertex l_v = √(2R·h_eff); its height at distance l from the observer is
(l − l_v)²/(2R). Obstruction = an opaque diagnosed cloud layer that the ray
passes through along the sunward path. Golden geometry uses h_eff = 2000 m →
l_v ≈ 159.64 km (so the ray is near the ground around 150–200 km out, and at the
canvas height only at the observer's own column).
"""
import math

import numpy as np
import pytest

from datetime import datetime, timezone

from predictor.clouds import CloudLayer
from predictor.cross_section import SunwardCrossSection
from predictor.ray_path import RayClearance, ray_height_m, trace_ray_clearance

R = 6371.0
VERTEX_2KM = math.sqrt(2.0 * R * 2.0)  # ≈ 159.637 km for a 2000 m base


def _opaque(base_m, top_m):
    """A thick liquid deck → opacity 1.0 (≥ threshold)."""
    return CloudLayer(
        base_m=base_m, top_m=top_m, thickness_m=top_m - base_m,
        phase_hint="liquid", confidence=1.0, source="condensate", signal_margin=5.0,
    )


def _thin(base_m, top_m):
    """A thin glaciated wisp → opacity 0.05 (< threshold)."""
    return CloudLayer(
        base_m=base_m, top_m=top_m, thickness_m=top_m - base_m,
        phase_hint="ice", confidence=0.5, source="rh", signal_margin=1.1,
    )


def _xsec(distances_km, cloud_layers_per_col, aod_per_column=None, rh_ground_per_column=None,
          terrain_per_column=None):
    """Minimal synthetic cross-section: only distances + per-column layers/AOD matter.

    ``rh_ground_per_column`` (FA-A4) fills the lowest-height RH row per column;
    None entries stay NaN (unknown → no hygroscopic amplification).
    ``terrain_per_column`` (FA-G6) is the per-column ground elevation.
    """
    n = len(distances_km)
    heights = [0.0, 5000.0, 10000.0]
    empty = np.full((len(heights), n), np.nan)
    rh = empty.copy()
    if rh_ground_per_column is not None:
        for i, value in enumerate(rh_ground_per_column):
            if value is not None:
                rh[0, i] = value
    return SunwardCrossSection(
        distances_km=list(distances_km),
        heights_m=heights,
        relative_humidity_pct=rh,
        vertical_velocity_pa_s=empty.copy(),
        temperature_k=empty.copy(),
        mask=np.ones((len(heights), n), dtype=bool),
        cloud_layers=cloud_layers_per_col,
        observer=(31.0, 121.0),
        azimuth_deg=270.0,
        target_time=datetime(2026, 6, 26, tzinfo=timezone.utc),
        aerosol_optical_depth_per_column=aod_per_column,
        terrain_elevation_m_per_column=terrain_per_column,
    )


# ---------------------------------------------------------------------------
# ray_height_m
# ---------------------------------------------------------------------------


def test_ray_height_zero_at_vertex():
    assert ray_height_m(VERTEX_2KM, VERTEX_2KM) == pytest.approx(0.0, abs=1e-9)


def test_ray_height_equals_base_at_observer():
    # At the observer (l=0) the grazing ray for a 2000 m base sits at 2000 m.
    assert ray_height_m(0.0, VERTEX_2KM) == pytest.approx(2000.0, abs=1.0)


def test_ray_height_rises_away_from_vertex():
    # Farther from the vertex (toward the observer) the ray is higher.
    near_vertex = ray_height_m(VERTEX_2KM - 10.0, VERTEX_2KM)
    far_from_vertex = ray_height_m(VERTEX_2KM - 100.0, VERTEX_2KM)
    assert far_from_vertex > near_vertex


def test_ray_height_symmetric_about_vertex():
    assert ray_height_m(VERTEX_2KM - 30.0, VERTEX_2KM) == pytest.approx(
        ray_height_m(VERTEX_2KM + 30.0, VERTEX_2KM)
    )


# ---------------------------------------------------------------------------
# trace_ray_clearance
# ---------------------------------------------------------------------------


def test_clear_sky_is_clear():
    xs = _xsec([0, 50, 100, 150, 200], [[], [], [], [], []])
    result = trace_ray_clearance(xs, observer_cloud_base_eff_m=2000.0)
    assert isinstance(result, RayClearance)
    assert result.clear is True
    assert result.blocked_at_km is None


def test_opaque_low_cloud_on_path_blocks():
    # Near the vertex (~160 km) the ray is only a few metres up, so a thick low
    # deck at 150 km intercepts it.
    xs = _xsec([0, 50, 100, 150, 200], [[], [], [], [_opaque(0.0, 2000.0)], []])
    result = trace_ray_clearance(xs, observer_cloud_base_eff_m=2000.0)
    assert result.clear is False
    assert result.blocked_at_km == pytest.approx(150.0)
    assert result.blocked_layer is not None


def test_canvas_over_observer_does_not_self_block():
    # The canvas deck at the observer's own column sits at the ray height there
    # (= base), but the observer column must be skipped, so it is not obstruction.
    xs = _xsec([0, 50, 100, 150, 200], [[_opaque(1900.0, 2100.0)], [], [], [], []])
    result = trace_ray_clearance(xs, observer_cloud_base_eff_m=2000.0)
    assert result.clear is True


def test_high_cloud_above_the_ray_does_not_block():
    # A thick deck at 5–7 km sits far above the ~7 m ray height at 150 km.
    xs = _xsec([0, 50, 100, 150, 200], [[], [], [], [_opaque(5000.0, 7000.0)], []])
    result = trace_ray_clearance(xs, observer_cloud_base_eff_m=2000.0)
    assert result.clear is True


def test_thin_cloud_below_opacity_threshold_does_not_block():
    xs = _xsec([0, 50, 100, 150, 200], [[], [], [], [_thin(0.0, 500.0)], []])
    result = trace_ray_clearance(xs, observer_cloud_base_eff_m=2000.0)
    assert result.clear is True


def test_nonpositive_effective_base_is_not_clear():
    # Aerosol correction pushed the base to/below ground → light can't reach it.
    xs = _xsec([0, 50, 100, 150, 200], [[], [], [], [], []])
    result = trace_ray_clearance(xs, observer_cloud_base_eff_m=0.0)
    assert result.clear is False


def test_nan_effective_base_is_not_clear():
    # A non-finite base is invalid, not vacuously clear.
    xs = _xsec([0, 50, 100, 150, 200], [[], [], [], [], []])
    result = trace_ray_clearance(xs, observer_cloud_base_eff_m=float("nan"))
    assert result.clear is False


def test_opacity_threshold_is_inclusive():
    # opacity = min(1, 1000/2000)·1.0·1.0 = 0.5 exactly → blocks (>= threshold).
    exactly_half = CloudLayer(
        base_m=0.0, top_m=1000.0, thickness_m=1000.0,
        phase_hint="liquid", confidence=1.0, source="condensate", signal_margin=5.0,
    )
    xs = _xsec([0, 50, 100, 150, 200], [[], [], [], [exactly_half], []])
    assert trace_ray_clearance(xs, 2000.0).clear is False
    # thickness 900 → opacity 0.45 < 0.5 → does not block.
    below = CloudLayer(
        base_m=0.0, top_m=900.0, thickness_m=900.0,
        phase_hint="liquid", confidence=1.0, source="condensate", signal_margin=5.0,
    )
    xs2 = _xsec([0, 50, 100, 150, 200], [[], [], [], [below], []])
    assert trace_ray_clearance(xs2, 2000.0).clear is True


def test_obstruction_height_bound_is_inclusive():
    # At 50 km the ray is ~943 m; a thick deck whose base sits exactly there blocks
    # (base <= h inclusive); a base 1 m above the ray does not.
    h50 = ray_height_m(50.0, VERTEX_2KM)
    at_base = _opaque(h50, h50 + 2000.0)
    xs = _xsec([0, 50, 100, 150, 200], [[], [at_base], [], [], []])
    assert trace_ray_clearance(xs, 2000.0).clear is False
    above = _opaque(h50 + 1.0, h50 + 2000.0)
    xs2 = _xsec([0, 50, 100, 150, 200], [[], [above], [], [], []])
    assert trace_ray_clearance(xs2, 2000.0).clear is True


def test_metamorphic_more_obstruction_never_increases_clearance():
    # Adding an opaque deck onto the lit path can only flip clear True→False.
    base_cols = [[], [], [], [], []]
    clear_before = trace_ray_clearance(
        _xsec([0, 50, 100, 150, 200], base_cols), observer_cloud_base_eff_m=2000.0
    ).clear
    with_block = [[], [], [], [_opaque(0.0, 2000.0)], []]
    clear_after = trace_ray_clearance(
        _xsec([0, 50, 100, 150, 200], with_block), observer_cloud_base_eff_m=2000.0
    ).clear
    assert clear_before is True
    assert clear_after is False
    # And a second opaque deck keeps it blocked (monotone).
    with_two = [[], [_opaque(0.0, 3000.0)], [], [_opaque(0.0, 2000.0)], []]
    assert trace_ray_clearance(
        _xsec([0, 50, 100, 150, 200], with_two), observer_cloud_base_eff_m=2000.0
    ).clear is False


# ---------------------------------------------------------------------------
# Per-column aerosol path extinction (FA-A2)
#
# With a 2000 m effective base the vertex is ~159.6 km, so the ray is only ~7 m up
# at 150 km. A dense upstream column (high AOD → tall equivalent opaque ground h_x)
# there extinguishes the grazing ray even with no cloud present.
# ---------------------------------------------------------------------------

_CLEAR5 = [[], [], [], [], []]


def test_dense_upstream_aerosol_blocks_clear_sky_ray():
    # No clouds anywhere; AOD=0.5 at the 150 km column (h_x≈5 km) ≫ ray height → block.
    aod = [None, None, None, 0.5, None]
    result = trace_ray_clearance(
        _xsec([0, 50, 100, 150, 200], _CLEAR5, aod_per_column=aod),
        observer_cloud_base_eff_m=2000.0,
    )
    assert result.clear is False
    assert result.blocked_at_km == pytest.approx(150.0)
    assert result.blocked_layer is None          # aerosol block, not a cloud layer
    assert result.blocked_height_m == pytest.approx(ray_height_m(150.0, VERTEX_2KM))


def test_removing_aerosol_clears_the_ray():
    aod = [None, None, None, None, None]
    result = trace_ray_clearance(
        _xsec([0, 50, 100, 150, 200], _CLEAR5, aod_per_column=aod),
        observer_cloud_base_eff_m=2000.0,
    )
    assert result.clear is True


def test_clean_uniform_aerosol_below_threshold_does_not_block():
    # AOD=0.03 → beta_0=0.015 < beta_x=0.02 → h_x=0 → no opaque ground anywhere.
    aod = [0.03, 0.03, 0.03, 0.03, 0.03]
    result = trace_ray_clearance(
        _xsec([0, 50, 100, 150, 200], _CLEAR5, aod_per_column=aod),
        observer_cloud_base_eff_m=2000.0,
    )
    assert result.clear is True


def test_observer_column_aerosol_does_not_self_block():
    # Dense AOD only at the observer's own column (distance 0) is skipped, like clouds.
    aod = [0.8, None, None, None, None]
    result = trace_ray_clearance(
        _xsec([0, 50, 100, 150, 200], _CLEAR5, aod_per_column=aod),
        observer_cloud_base_eff_m=2000.0,
    )
    assert result.clear is True


def test_missing_per_column_aod_matches_no_aerosol_behaviour():
    # aerosol_optical_depth_per_column=None (default) must trace exactly as before.
    with_block = [[], [], [], [_opaque(0.0, 2000.0)], []]
    none_aod = trace_ray_clearance(
        _xsec([0, 50, 100, 150, 200], with_block, aod_per_column=None), 2000.0
    )
    explicit_none = trace_ray_clearance(
        _xsec([0, 50, 100, 150, 200], with_block, aod_per_column=[None] * 5), 2000.0
    )
    assert none_aod.clear is False and explicit_none.clear is False
    assert none_aod.blocked_at_km == explicit_none.blocked_at_km


def test_nearest_obstruction_wins_aerosol_before_cloud():
    # Aerosol block at 100 km precedes a cloud deck at 150 km → aerosol reported.
    cloud = [[], [], [], [_opaque(0.0, 2000.0)], []]
    aod = [None, None, 0.6, None, None]
    result = trace_ray_clearance(
        _xsec([0, 50, 100, 150, 200], cloud, aod_per_column=aod), 2000.0
    )
    assert result.blocked_at_km == pytest.approx(100.0)
    assert result.blocked_layer is None


def test_nearest_obstruction_wins_cloud_before_aerosol():
    # Cloud deck at 50 km precedes dense aerosol at 150 km → cloud reported.
    cloud = [[], [_opaque(0.0, 2000.0)], [], [], []]
    aod = [None, None, None, 0.6, None]
    result = trace_ray_clearance(
        _xsec([0, 50, 100, 150, 200], cloud, aod_per_column=aod), 2000.0
    )
    assert result.blocked_at_km == pytest.approx(50.0)
    assert result.blocked_layer is not None


def test_metamorphic_more_aerosol_never_increases_clearance():
    cols = [0, 50, 100, 150, 200]
    clear = trace_ray_clearance(_xsec(cols, _CLEAR5, aod_per_column=[None] * 5), 2000.0).clear
    one = trace_ray_clearance(
        _xsec(cols, _CLEAR5, aod_per_column=[None, None, None, 0.5, None]), 2000.0
    ).clear
    denser = trace_ray_clearance(
        _xsec(cols, _CLEAR5, aod_per_column=[None, None, 0.4, 0.9, None]), 2000.0
    ).clear
    assert clear is True
    assert one is False
    assert denser is False


# --- aerosol blocks on UPSTREAM EXCESS over the observer's own ground, not on an
# --- absolute floor (the observer's local haze is already in the effective base).


def test_uniform_aerosol_does_not_block():
    # Every column equally turbid (AOD 0.3, h_x≈4 km > 0): the observer's own haze
    # set the grazing datum (effective base), so no column is *excess* → not blocked.
    aod = [0.3, 0.3, 0.3, 0.3, 0.3]
    result = trace_ray_clearance(
        _xsec([0, 50, 100, 150, 200], _CLEAR5, aod_per_column=aod),
        observer_cloud_base_eff_m=2000.0,
    )
    assert result.clear is True


def test_upstream_cleaner_than_hazy_observer_does_not_block():
    # Observer hazy (AOD 0.5), upstream cleaner (0.1): the ray already grazes above
    # the upstream column's lower equivalent ground → no excess → not blocked.
    aod = [0.5, None, None, 0.1, None]
    result = trace_ray_clearance(
        _xsec([0, 50, 100, 150, 200], _CLEAR5, aod_per_column=aod),
        observer_cloud_base_eff_m=2000.0,
    )
    assert result.clear is True


def test_upstream_excess_over_hazy_observer_blocks():
    # Observer mildly hazy (0.1, h_x≈1.8 km); a denser upstream plume (0.6, h_x≈5.4 km)
    # rises well above the observer's ground → excess intercepts the low ray.
    aod = [0.1, None, None, 0.6, None]
    result = trace_ray_clearance(
        _xsec([0, 50, 100, 150, 200], _CLEAR5, aod_per_column=aod),
        observer_cloud_base_eff_m=2000.0,
    )
    assert result.clear is False
    assert result.blocked_at_km == pytest.approx(150.0)
    assert result.blocked_layer is None


# ---------------------------------------------------------------------------
# FA-A4: hygroscopic growth on the per-column veto (manual §2.4.3 雾霾)
# ---------------------------------------------------------------------------


def test_uniform_aod_and_uniform_humidity_do_not_self_block():
    # Growth is uniform when RH is uniform: every column swells alike, the
    # observer datum swells alike, excess stays 0 — FA-A2's core no-self-veto
    # invariant survives FA-A4 even in dense humid haze.
    aod = [0.5] * 5
    rh = [85.0] * 5
    result = trace_ray_clearance(
        _xsec([0, 50, 100, 150, 200], _CLEAR5, aod_per_column=aod, rh_ground_per_column=rh),
        observer_cloud_base_eff_m=2000.0,
    )
    assert result.clear is True


def test_humid_upstream_pocket_blocks_at_uniform_aod():
    # Same column AOD everywhere, but an 85% RH pocket at 150 km swells that
    # column's extinction (g≈1.80): its equivalent ground rises ~1.2 km above
    # the dry-observer datum while the grazing ray is only ~7 m up → veto.
    # This is the manual's 雾霾联手 case, the gap FA-A2's note §5 left open.
    aod = [0.5] * 5
    rh = [60.0, 60.0, 60.0, 85.0, 60.0]
    result = trace_ray_clearance(
        _xsec([0, 50, 100, 150, 200], _CLEAR5, aod_per_column=aod, rh_ground_per_column=rh),
        observer_cloud_base_eff_m=2000.0,
    )
    assert result.clear is False
    assert result.blocked_at_km == pytest.approx(150.0)
    assert result.blocked_layer is None


def test_humid_observer_with_dry_upstream_does_not_block():
    # The humid observer column raises the datum; drier upstream columns sit
    # BELOW it (negative excess) → no veto.
    aod = [0.5] * 5
    rh = [85.0, 60.0, 60.0, 60.0, 60.0]
    result = trace_ray_clearance(
        _xsec([0, 50, 100, 150, 200], _CLEAR5, aod_per_column=aod, rh_ground_per_column=rh),
        observer_cloud_base_eff_m=2000.0,
    )
    assert result.clear is True


def test_missing_column_humidity_matches_dry_behaviour():
    # NaN RH rows (the default fixture) must trace bit-identically to the
    # pre-FA-A4 model — dense uniform AOD stays clear.
    aod = [0.5] * 5
    result = trace_ray_clearance(
        _xsec([0, 50, 100, 150, 200], _CLEAR5, aod_per_column=aod),
        observer_cloud_base_eff_m=2000.0,
    )
    assert result.clear is True


# ---------------------------------------------------------------------------
# FA-G6: terrain horizon obscuration (manual §1.2.1 plains assumption relaxed)
# ---------------------------------------------------------------------------


def test_uniform_plateau_does_not_self_block():
    # A uniform 500 m plateau is just a shifted datum — the excess criterion
    # keeps it neutral, so elevated flat regions behave exactly like the sea.
    terrain = [500.0] * 5
    result = trace_ray_clearance(
        _xsec([0, 50, 100, 150, 200], _CLEAR5, terrain_per_column=terrain),
        observer_cloud_base_eff_m=2000.0,
    )
    assert result.clear is True


def test_upstream_ridge_blocks_grazing_ray():
    # Observer at sea level; an 800 m ridge at 150 km where the grazing ray is
    # only ~7 m up — the mountain eats the low sun (cloudless column).
    terrain = [0.0, 0.0, 0.0, 800.0, 0.0]
    result = trace_ray_clearance(
        _xsec([0, 50, 100, 150, 200], _CLEAR5, terrain_per_column=terrain),
        observer_cloud_base_eff_m=2000.0,
    )
    assert result.clear is False
    assert result.blocked_at_km == pytest.approx(150.0)
    assert result.blocked_layer is None  # ground-type block, not a cloud


def test_elevated_observer_sees_over_the_same_ridge():
    # Horizon depression in flat coordinates: a 1000 m observer makes the same
    # 800 m ridge sit BELOW the datum (negative excess) → clear.
    terrain = [1000.0, 0.0, 0.0, 800.0, 0.0]
    result = trace_ray_clearance(
        _xsec([0, 50, 100, 150, 200], _CLEAR5, terrain_per_column=terrain),
        observer_cloud_base_eff_m=2000.0,
    )
    assert result.clear is True


def test_missing_observer_elevation_skips_terrain_checks():
    # No datum → no guessing: an absolute floor would wrongly veto every
    # elevated plateau, so unknown observer elevation disables terrain vetoes.
    terrain = [None, 0.0, 0.0, 800.0, 0.0]
    result = trace_ray_clearance(
        _xsec([0, 50, 100, 150, 200], _CLEAR5, terrain_per_column=terrain),
        observer_cloud_base_eff_m=2000.0,
    )
    assert result.clear is True
