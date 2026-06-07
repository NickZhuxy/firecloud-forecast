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


# ---------------------------------------------------------------------------
# Gate × modifier combiner (paper §6.2)
# ---------------------------------------------------------------------------

from predictor.rules import gate_modifier_combiner, weighted_average


def test_gate_zero_forces_composite_to_zero():
    """Any gate score of 0 must collapse the composite to 0 regardless of modifiers."""
    combiner = gate_modifier_combiner(gate_names={"g1", "g2"})
    components = {"g1": 0.0, "g2": 0.9, "m1": 1.0, "m2": 0.8}
    weights = {"g1": 1.0, "g2": 1.0, "m1": 1.0, "m2": 1.0}
    assert combiner(components, weights) == 0.0


def test_gate_modifier_all_gates_one_returns_modifier_average():
    """When all gates pass with score 1, the composite equals the modifier average."""
    combiner = gate_modifier_combiner(gate_names={"g1", "g2"})
    components = {"g1": 1.0, "g2": 1.0, "m1": 0.4, "m2": 0.6}
    weights = {"g1": 1.0, "g2": 1.0, "m1": 1.0, "m2": 1.0}
    # gate=1, modifier = 0.5, P = 0.5
    assert abs(combiner(components, weights) - 0.5) < 1e-12


def test_gate_modifier_no_modifiers_returns_pure_gate():
    """With an empty modifier set, the composite equals the gate score alone."""
    combiner = gate_modifier_combiner(gate_names={"g1", "g2"})
    components = {"g1": 0.8, "g2": 0.5}
    weights = {"g1": 1.0, "g2": 1.0}
    # weighted geometric mean = (0.8 * 0.5) ** 0.5 = sqrt(0.4) ≈ 0.632
    assert abs(combiner(components, weights) - (0.8 * 0.5) ** 0.5) < 1e-12


def test_gate_modifier_no_gates_returns_pure_modifier_average():
    """Empty gate set degenerates to weighted-average semantics."""
    combiner = gate_modifier_combiner(gate_names=set())
    components = {"m1": 0.6, "m2": 0.2}
    weights = {"m1": 1.0, "m2": 1.0}
    # No gates → gate=1; modifier = (0.6 + 0.2)/2 = 0.4
    assert abs(combiner(components, weights) - 0.4) < 1e-12


def test_gate_weight_asymmetry_affects_intermediate_values_only():
    """Gate weights bias the geometric mean for intermediate scores, but cannot rescue a 0."""
    components = {"g1": 0.04, "g2": 0.81}
    # Equal-weight: (0.04 * 0.81) ** 0.5 = sqrt(0.0324) = 0.18
    eq = gate_modifier_combiner({"g1", "g2"})(components, {"g1": 1.0, "g2": 1.0})
    assert abs(eq - 0.18) < 1e-9
    # Heavy weight on g2: 0.04 ** 0.1 * 0.81 ** 0.9 ≈ 0.591  (g2 dominates → result closer to g2)
    skewed = gate_modifier_combiner({"g1", "g2"})(components, {"g1": 1.0, "g2": 9.0})
    assert skewed > eq
    # But even with weight 1000 on g2, weight 1 on g1, g1=0 still forces zero:
    zero = gate_modifier_combiner({"g1", "g2"})(
        {"g1": 0.0, "g2": 0.81}, {"g1": 1.0, "g2": 1000.0}
    )
    assert zero == 0.0


def test_gate_modifier_olympic_peninsula_scenario(base_features):
    """Reproduce paper §7.2: gate × modifier returns 0 for the Olympic Peninsula case.

    HRRR-observed atmospheric state at the representative grid point: mid+high
    cloud coverage 0%, low cloud 18%, query 38 min before sunset, humidity 86%.
    """
    p = RuleBasedPredictor(
        rules=[
            MidHighCloudPresence(),
            LowCloudObstruction(),
            SolarAngleAtSunset(),
            HumidityFactor(),
        ],
        weights={
            "mid_high_cloud_presence": 1.0,
            "low_cloud_obstruction": 1.0,
            "solar_angle": 1.0,
            "humidity": 0.3,
        },
        source=FakeSource(
            WeatherSnapshot(
                cloud_low_pct=18.0,
                cloud_mid_pct=0.0,
                cloud_high_pct=0.0,
                humidity_pct=86.0,
                source_label="fake",
                retrieved_at=datetime(2026, 5, 21, tzinfo=timezone.utc),
            )
        ),
        combiner=gate_modifier_combiner(
            gate_names={"mid_high_cloud_presence", "low_cloud_obstruction", "solar_angle"}
        ),
    )
    # 38 min before sunset: solar_angle ramp gives (60 - 38) / 30 ≈ 0.733
    f = p.score(
        lat=47.70,
        lon=-124.80,
        time=datetime(2026, 5, 21, 3, 30, tzinfo=timezone.utc),
    )
    # mid_high_cloud_presence = 0 → gate = 0 → P = 0
    assert f.components["mid_high_cloud_presence"] == 0.0
    assert f.probability == 0.0
    assert "Composite=0.00" in f.explanation


def test_gate_modifier_vs_weighted_average_disagree_when_gate_zero(base_features):
    """The architectural improvement: same component scores, different combiners → different result.

    With the Olympic Peninsula configuration, weighted-sum returns ~0.6+, gate × modifier returns 0.
    This is the paper's central empirical demonstration.
    """
    components = {
        "mid_high_cloud_presence": 0.0,
        "low_cloud_obstruction": 1.0,
        "solar_angle": 1.0,
        "humidity": 0.6,
    }
    weights = {
        "mid_high_cloud_presence": 2.0,
        "low_cloud_obstruction": 2.0,
        "solar_angle": 1.5,
        "humidity": 1.0,
    }
    # Weighted-sum: (0 + 2 + 1.5 + 0.6) / 6.5 ≈ 0.631 (paper Table 6)
    wa = weighted_average(components, weights)
    assert abs(wa - 0.631) < 0.01

    # Gate × modifier: gate has a 0, so P = 0
    gm = gate_modifier_combiner(
        gate_names={"mid_high_cloud_presence", "low_cloud_obstruction", "solar_angle"}
    )(components, weights)
    assert gm == 0.0


def test_gate_modifier_zero_weight_treated_as_absent():
    """A gate with weight 0 should not contribute to the gate score."""
    combiner = gate_modifier_combiner(gate_names={"g1", "g2"})
    # g2 has weight 0 → only g1 contributes
    result = combiner({"g1": 0.5, "g2": 0.0}, {"g1": 1.0, "g2": 0.0})
    # Effectively gate = 0.5 (g1 alone), no modifiers → P = 0.5
    assert abs(result - 0.5) < 1e-12


def test_predictor_score_uses_gate_modifier_combiner_end_to_end():
    """RuleBasedPredictor.score() correctly applies gate_modifier_combiner via DI."""
    snap = WeatherSnapshot(
        cloud_low_pct=10.0,
        cloud_mid_pct=50.0,
        cloud_high_pct=50.0,
        humidity_pct=60.0,
        source_label="fake",
        retrieved_at=datetime(2026, 5, 20, tzinfo=timezone.utc),
    )
    p = RuleBasedPredictor(
        rules=[MidHighCloudPresence(), LowCloudObstruction(), HumidityFactor()],
        weights={
            "mid_high_cloud_presence": 1.0,
            "low_cloud_obstruction": 1.0,
            "humidity": 0.3,
        },
        source=FakeSource(snap),
        combiner=gate_modifier_combiner(
            gate_names={"mid_high_cloud_presence", "low_cloud_obstruction"}
        ),
    )
    # All gates pass with score 1; modifier (humidity at 60%) gives 1.0 → composite = 1.0
    f = p.score(lat=42.36, lon=-71.06, time=datetime(2026, 5, 20, 23, 20, tzinfo=timezone.utc))
    assert f.probability == 1.0
