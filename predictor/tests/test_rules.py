# predictor/tests/test_rules.py
from dataclasses import replace
from datetime import datetime, timezone, timedelta

from predictor.fetch import FakeSource, WeatherSnapshot
from predictor.rules import (
    HumidityFactor,
    LowCloudObstruction,
    MidHighCloudPresence,
    RuleBasedPredictor,
    SolarAngleAtSunset,
)


def test_mid_high_cloud_zero_cover_scores_zero(base_features):
    f = replace(base_features, cloud_mid_pct=0, cloud_high_pct=0)
    assert MidHighCloudPresence().evaluate(f) == 0.0


def test_mid_high_cloud_full_cover_scores_zero(base_features):
    f = replace(base_features, cloud_mid_pct=100, cloud_high_pct=100)
    assert MidHighCloudPresence().evaluate(f) == 0.0


def test_mid_high_cloud_sweet_spot_scores_one(base_features):
    # Average mid+high = 50 → in [30, 70] plateau → 1.0
    f = replace(base_features, cloud_mid_pct=50, cloud_high_pct=50)
    assert MidHighCloudPresence().evaluate(f) == 1.0


def test_mid_high_cloud_low_end_ramp(base_features):
    # Avg = 15 → linear from 0 at 0% to 1 at 30%  → 0.5
    f = replace(base_features, cloud_mid_pct=10, cloud_high_pct=20)
    assert abs(MidHighCloudPresence().evaluate(f) - 0.5) < 1e-9


def test_low_cloud_zero_scores_one(base_features):
    f = replace(base_features, cloud_low_pct=0)
    assert LowCloudObstruction().evaluate(f) == 1.0


def test_low_cloud_small_scores_one(base_features):
    f = replace(base_features, cloud_low_pct=15)
    assert LowCloudObstruction().evaluate(f) == 1.0


def test_low_cloud_full_scores_zero(base_features):
    f = replace(base_features, cloud_low_pct=100)
    assert LowCloudObstruction().evaluate(f) == 0.0


def test_low_cloud_mid_range_linear(base_features):
    # Linear ramp from 1.0 at 20% to 0.0 at 100% → at 60% should be 0.5
    f = replace(base_features, cloud_low_pct=60)
    assert abs(LowCloudObstruction().evaluate(f) - 0.5) < 1e-9


def test_solar_angle_at_sunset_peaks_within_30min(base_features):
    sunset = datetime(2026, 5, 20, 23, 30, tzinfo=timezone.utc)
    f = replace(base_features, sunset_time=sunset, query_time=sunset - timedelta(minutes=15))
    assert SolarAngleAtSunset().evaluate(f) == 1.0


def test_solar_angle_far_from_sunset_scores_zero(base_features):
    sunset = datetime(2026, 5, 20, 23, 30, tzinfo=timezone.utc)
    f = replace(base_features, sunset_time=sunset, query_time=sunset - timedelta(hours=4))
    assert SolarAngleAtSunset().evaluate(f) == 0.0


def test_solar_angle_ramp_45_min_before(base_features):
    # 45 min before sunset → halfway through the [30, 60] ramp → 0.5
    sunset = datetime(2026, 5, 20, 23, 30, tzinfo=timezone.utc)
    f = replace(base_features, sunset_time=sunset, query_time=sunset - timedelta(minutes=45))
    assert abs(SolarAngleAtSunset().evaluate(f) - 0.5) < 1e-9


def test_humidity_sweet_spot(base_features):
    f = replace(base_features, humidity_pct=60)
    assert HumidityFactor().evaluate(f) == 1.0


def test_humidity_too_dry(base_features):
    f = replace(base_features, humidity_pct=10)
    assert HumidityFactor().evaluate(f) == 0.0


def test_humidity_too_wet(base_features):
    f = replace(base_features, humidity_pct=100)
    assert HumidityFactor().evaluate(f) == 0.0


# Task 10: RuleBasedPredictor tests
def _make_fake_source():
    snap = WeatherSnapshot(
        cloud_low_pct=10.0, cloud_mid_pct=50.0, cloud_high_pct=40.0,
        humidity_pct=60.0, source_label="fake",
        retrieved_at=datetime(2026, 5, 20, tzinfo=timezone.utc),
    )
    return FakeSource(snap)


def test_predictor_returns_forecast_with_named_components():
    p = RuleBasedPredictor(
        rules=[MidHighCloudPresence(), LowCloudObstruction(), HumidityFactor()],
        weights={"mid_high_cloud_presence": 1.0, "low_cloud_obstruction": 1.0, "humidity": 1.0},
        source=_make_fake_source(),
    )
    f = p.score(lat=42.36, lon=-71.06, time=datetime(2026, 5, 20, 23, 20, tzinfo=timezone.utc))
    assert set(f.components.keys()) == {"mid_high_cloud_presence", "low_cloud_obstruction", "humidity"}
    assert 0.0 <= f.probability <= 1.0
    assert f.explanation  # non-empty


def test_predictor_default_combiner_is_weighted_average():
    rule = MidHighCloudPresence()
    p = RuleBasedPredictor(rules=[rule], weights={rule.name: 2.0}, source=_make_fake_source())
    f = p.score(lat=42.36, lon=-71.06, time=datetime(2026, 5, 20, 23, 20, tzinfo=timezone.utc))
    # Single rule → probability equals that rule's score regardless of weight magnitude.
    assert f.probability == f.components["mid_high_cloud_presence"]


def test_predictor_unset_weight_defaults_to_one():
    """A rule with no entry in `weights` should still contribute with weight 1.0."""
    p = RuleBasedPredictor(
        rules=[MidHighCloudPresence(), HumidityFactor()],
        weights={"mid_high_cloud_presence": 3.0},  # humidity weight omitted
        source=_make_fake_source(),
    )
    f = p.score(lat=42.36, lon=-71.06, time=datetime(2026, 5, 20, 23, 20, tzinfo=timezone.utc))
    # Both rules score 1.0 for this fake snapshot → weighted avg = 1.0.
    assert f.probability == 1.0
