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


def _xsec(distances_km, cloud_layers_per_col):
    """Minimal synthetic cross-section: only distances + per-column layers matter."""
    n = len(distances_km)
    heights = [0.0, 5000.0, 10000.0]
    empty = np.full((len(heights), n), np.nan)
    return SunwardCrossSection(
        distances_km=list(distances_km),
        heights_m=heights,
        relative_humidity_pct=empty.copy(),
        vertical_velocity_pa_s=empty.copy(),
        temperature_k=empty.copy(),
        mask=np.ones((len(heights), n), dtype=bool),
        cloud_layers=cloud_layers_per_col,
        observer=(31.0, 121.0),
        azimuth_deg=270.0,
        target_time=datetime(2026, 6, 26, tzinfo=timezone.utc),
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
