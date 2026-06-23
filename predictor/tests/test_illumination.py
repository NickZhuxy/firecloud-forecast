"""Unit tests for diagnosed-layer illumination/obstruction (#13)."""
from predictor.clouds import CloudLayer
from predictor.illumination import (
    LayerContribution,
    assess_layer_contributions,
    canvas_layer_from_diagnosis,
    cloud_base_from_diagnosis,
)


def _layer(base, top, *, phase="liquid", conf=0.8):
    return CloudLayer(base, top, top - base, phase, conf, "condensate", signal_margin=10.0)


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
