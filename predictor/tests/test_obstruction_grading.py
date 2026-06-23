"""Graded obstruction + scoring/output integration (#31)."""
from datetime import datetime, timezone

from predictor.clouds import CloudLayer
from predictor.illumination import (
    assess_layer_contributions,
    canvas_obstruction_fraction,
)
from predictor.rules import LowCloudObstruction
from predictor.features import Features


def _layer(base, top, *, phase="liquid", conf=1.0):
    return CloudLayer(base, top, top - base, phase, conf, "condensate", signal_margin=10.0)


def _features(**over) -> Features:
    base = dict(
        cloud_low_pct=5.0, cloud_mid_pct=50.0, cloud_high_pct=40.0, humidity_pct=60.0,
        sunset_time=datetime(2026, 6, 23, 10, 30, tzinfo=timezone.utc),
        query_time=datetime(2026, 6, 23, 10, 20, tzinfo=timezone.utc),
        location=(31.0, 121.0),
    )
    base.update(over)
    return Features(**base)


def test_obstruction_fraction_is_graded_by_thickness_and_phase():
    canvas = _layer(7000, 9000)
    thick_liquid = _layer(800, 2800, phase="liquid")   # 2000 m, conf 1.0 → fully opaque
    contribs = {round(c.base_m): c for c in assess_layer_contributions([thick_liquid, canvas], lat=31.0)}
    assert contribs[7000].obstruction_fraction == 1.0
    assert contribs[800].obstruction_fraction == 0.0
    assert contribs[7000].obstructed is True


def test_thin_ice_obstructs_far_less_than_thick_liquid():
    canvas = _layer(8000, 10000)
    thin_ice = _layer(3000, 3400, phase="ice")
    thick_liquid = _layer(3000, 5000, phase="liquid")
    assert 0.0 < canvas_obstruction_fraction([thin_ice, canvas]) < canvas_obstruction_fraction([thick_liquid, canvas])


def test_low_confidence_layer_hedges_obstruction():
    # A confidently-diagnosed thick liquid deck fully obstructs; a low-confidence
    # one of identical geometry must NOT — confidence weights the opacity (#31 fix).
    canvas = _layer(8000, 10000)
    confident = _layer(2000, 4000, phase="liquid", conf=1.0)
    shaky = _layer(2000, 4000, phase="liquid", conf=0.27)
    assert canvas_obstruction_fraction([confident, canvas]) == 1.0
    assert canvas_obstruction_fraction([shaky, canvas]) == 0.27


def test_partial_overlap_combines_as_product():
    canvas = _layer(8000, 10000)
    # Two lower decks, each ~half-opaque, combine as 1-(1-o1)(1-o2), not max/sum.
    a = _layer(2000, 3000, phase="liquid", conf=1.0)   # 1000/2000 → 0.5
    b = _layer(4000, 5000, phase="liquid", conf=1.0)   # 0.5
    got = canvas_obstruction_fraction([a, b, canvas])
    assert abs(got - (1 - 0.5 * 0.5)) < 1e-9          # 0.75


def test_nan_or_zero_thickness_yields_no_obstruction():
    canvas = _layer(8000, 10000)
    nan_layer = CloudLayer(2000, float("nan"), float("nan"), "liquid", 1.0, "condensate")
    zero_layer = _layer(2000, 2000, phase="liquid")  # thickness 0
    assert canvas_obstruction_fraction([nan_layer, canvas]) == 0.0
    assert canvas_obstruction_fraction([zero_layer, canvas]) == 0.0


def test_unknown_phase_defaults_to_mixed():
    canvas = _layer(8000, 10000)
    weird = _layer(2000, 4000, phase="slush", conf=1.0)  # 2000 m → thickness 1.0
    # Unknown phase → mixed opacity factor 0.7.
    assert abs(canvas_obstruction_fraction([weird, canvas]) - 0.7) < 1e-9


def test_canvas_obstruction_none_without_layers():
    assert canvas_obstruction_fraction([]) is None


def test_low_cloud_obstruction_prefers_diagnosed_signal():
    rule = LowCloudObstruction()
    f = _features(cloud_low_pct=5.0, diagnosed_obstruction_pct=90.0)
    assert rule.evaluate(f) < 0.2


def test_low_cloud_obstruction_precedence_diagnosed_over_sunward():
    # The PR's core rules change: diagnosed wins over the sunward transect signal.
    rule = LowCloudObstruction()
    low_diag = _features(diagnosed_obstruction_pct=20.0, sunward_obstruction_pct=100.0)
    assert rule.evaluate(low_diag) == 1.0           # uses diagnosed 20% → clear
    high_diag = _features(diagnosed_obstruction_pct=100.0, sunward_obstruction_pct=0.0)
    assert rule.evaluate(high_diag) == 0.0          # uses diagnosed 100% → gated


def test_low_cloud_obstruction_unchanged_without_diagnosis():
    rule = LowCloudObstruction()
    f = _features(cloud_low_pct=10.0)  # no diagnosed, no sunward → cloud_low 10% → 1.0
    assert rule.evaluate(f) == 1.0
