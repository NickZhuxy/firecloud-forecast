"""Unit tests for diagnosed-layer illumination/obstruction (#13)."""
import math

import pytest

from predictor.clouds import CloudLayer
from predictor.illumination import (
    LayerContribution,
    _layer_opacity,
    assess_layer_contributions,
    canvas_layer_from_diagnosis,
    cloud_base_from_diagnosis,
)


def _layer(base, top, *, phase="liquid", conf=0.8, optical_depth=float("nan")):
    return CloudLayer(
        base, top, top - base, phase, conf, "condensate",
        signal_margin=10.0, optical_depth=optical_depth,
    )


def test_canvas_prefers_highest_deck():
    low = _layer(800, 1500)
    high = _layer(7000, 9000)
    assert canvas_layer_from_diagnosis([low, high]) is high


def test_canvas_none_when_no_layers():
    assert canvas_layer_from_diagnosis([]) is None
    assert cloud_base_from_diagnosis([]) is None


def test_cloud_base_from_diagnosis_is_canvas_base():
    layers = [_layer(800, 1500), _layer(6000, 8000)]
    assert cloud_base_from_diagnosis(layers) == 6000


def test_contributions_one_per_layer_with_geometry():
    layers = [_layer(1000, 2000), _layer(7000, 9000)]
    contribs = assess_layer_contributions(layers, lat=31.0)
    assert len(contribs) == 2
    assert all(isinstance(c, LayerContribution) for c in contribs)
    # Higher deck is lit longer (duration scales with sqrt(base)).
    by_base = sorted(contribs, key=lambda c: c.base_m)
    assert by_base[1].duration_min > by_base[0].duration_min


def test_lower_layer_obstructs_upper_canvas():
    low = _layer(800, 1500)
    high = _layer(7000, 9000)
    contribs = {c.base_m: c for c in assess_layer_contributions([low, high], lat=31.0)}
    assert contribs[7000.0].obstructed is True     # has a layer below it
    assert contribs[800.0].obstructed is False      # nothing below
    assert contribs[7000.0].is_canvas is True       # highest deck is the canvas


def test_single_layer_not_obstructed():
    contribs = assess_layer_contributions([_layer(3000, 5000)], lat=31.0)
    assert contribs[0].obstructed is False
    assert contribs[0].is_canvas is True


# ---------------------------------------------------------------------------
# FA-C1: _layer_opacity uses cloud optical depth when available (manual §1.3.2)
# opacity = (1 − exp(−τ)) × confidence; falls back to thickness×phase when τ NaN.
# ---------------------------------------------------------------------------


def test_opacity_uses_optical_depth_when_present():
    # τ=5 → (1−e⁻⁵)·0.8 ≈ 0.795; τ=0.1 → (1−e⁻⁰·¹)·0.8 ≈ 0.076.
    opaque = _layer(2000, 4000, conf=0.8, optical_depth=5.0)
    thin = _layer(2000, 4000, conf=0.8, optical_depth=0.1)
    assert _layer_opacity(opaque) == pytest.approx((1 - math.exp(-5.0)) * 0.8, abs=1e-6)
    assert _layer_opacity(thin) == pytest.approx((1 - math.exp(-0.1)) * 0.8, abs=1e-6)


def test_optical_depth_overrides_thickness_proxy():
    # A geometrically THIN deck that is optically thick must read as opaque...
    thin_but_dense = _layer(2000, 2100, conf=1.0, optical_depth=5.0)  # 100 m thick
    assert _layer_opacity(thin_but_dense) > 0.9
    # ...and a geometrically THICK deck that is optically thin must read as sheer.
    thick_but_wispy = _layer(2000, 5000, conf=1.0, optical_depth=0.1)  # 3 km thick
    assert _layer_opacity(thick_but_wispy) < 0.2


def test_opacity_falls_back_to_thickness_when_optical_depth_nan():
    # Default optical_depth is NaN → unchanged thickness×phase×confidence proxy.
    layer = _layer(1000, 3000, phase="liquid", conf=0.8)  # thickness 2000 → factor 1.0
    assert _layer_opacity(layer) == pytest.approx(1.0 * 1.0 * 0.8, abs=1e-9)


def test_optical_depth_zero_is_transparent():
    assert _layer_opacity(_layer(2000, 4000, conf=0.8, optical_depth=0.0)) == pytest.approx(0.0)
