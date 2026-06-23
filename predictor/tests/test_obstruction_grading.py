"""Graded obstruction + scoring/output integration (#31)."""
from datetime import datetime, timezone

from predictor.clouds import CloudLayer
from predictor.illumination import (
    assess_layer_contributions,
    canvas_obstruction_fraction,
)
from predictor.rules import LowCloudObstruction
from predictor.features import Features


def _layer(base, top, *, phase="liquid", conf=0.8):
    return CloudLayer(base, top, top - base, phase, conf, "condensate", signal_margin=10.0)


def test_obstruction_fraction_is_graded_by_thickness_and_phase():
    canvas = _layer(7000, 9000)
    thick_liquid = _layer(800, 2800, phase="liquid")   # 2000 m → fully opaque
    contribs = {round(c.base_m): c for c in assess_layer_contributions([thick_liquid, canvas], lat=31.0)}
    assert contribs[7000].obstruction_fraction == 1.0      # fully blocked
    assert contribs[800].obstruction_fraction == 0.0       # nothing below it
    assert contribs[7000].obstructed is True


def test_thin_ice_obstructs_far_less_than_thick_liquid():
    canvas = _layer(8000, 10000)
    thin_ice = _layer(3000, 3400, phase="ice")   # thin + glaciated → low opacity
    thick_liquid = _layer(3000, 5000, phase="liquid")
    ice_obstr = canvas_obstruction_fraction([thin_ice, canvas])
    liq_obstr = canvas_obstruction_fraction([thick_liquid, canvas])
    assert 0.0 < ice_obstr < liq_obstr


def test_canvas_obstruction_none_without_layers():
    assert canvas_obstruction_fraction([]) is None


def test_low_cloud_obstruction_prefers_diagnosed_signal():
    rule = LowCloudObstruction()
    # Diagnosed obstruction 90% should dominate even when cloud_low_pct is small.
    f = Features(
        cloud_low_pct=5.0, cloud_mid_pct=50.0, cloud_high_pct=40.0, humidity_pct=60.0,
        sunset_time=datetime(2026, 6, 23, 10, 30, tzinfo=timezone.utc),
        query_time=datetime(2026, 6, 23, 10, 20, tzinfo=timezone.utc),
        location=(31.0, 121.0),
        diagnosed_obstruction_pct=90.0,
    )
    score = rule.evaluate(f)
    # 90% obstruction → heavily penalized (well below the clear-sky 1.0).
    assert score < 0.2


def test_low_cloud_obstruction_unchanged_without_diagnosis():
    rule = LowCloudObstruction()
    f = Features(
        cloud_low_pct=10.0, cloud_mid_pct=50.0, cloud_high_pct=40.0, humidity_pct=60.0,
        sunset_time=datetime(2026, 6, 23, 10, 30, tzinfo=timezone.utc),
        query_time=datetime(2026, 6, 23, 10, 20, tzinfo=timezone.utc),
        location=(31.0, 121.0),
    )
    # No diagnosed obstruction, no sunward transect → falls back to cloud_low_pct (10% → 1.0).
    assert rule.evaluate(f) == 1.0
