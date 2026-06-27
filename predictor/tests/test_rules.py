# predictor/tests/test_rules.py
from dataclasses import replace
from datetime import datetime, timezone, timedelta

import numpy as np
import pytest

from predictor.clouds import CloudLayer
from predictor.cross_section import SunwardCrossSection
from predictor.features import derive
from predictor.fetch import FakeSource, WeatherSnapshot
from predictor.ray_path import RayClearance
from predictor.rules import (
    BoundaryConfidence,
    CleanAirGate,
    HumidityFactor,
    LowCloudObstruction,
    MidHighCloudPresence,
    RuleBasedPredictor,
    SolarAngleAtSunset,
    SunwardIlluminationGate,
)
from predictor.spatial import SunwardProfile


def _xsec_with_low_deck(distances_km, deck_at_idx=None, aod_per_column=None):
    """Minimal cross-section; an opaque low deck (0–1000 m) at one column if given."""
    n = len(distances_km)
    heights = [0.0, 5000.0, 10000.0]
    empty = np.full((3, n), np.nan)
    layers = [[] for _ in range(n)]
    if deck_at_idx is not None:
        layers[deck_at_idx] = [
            CloudLayer(0.0, 1000.0, 1000.0, "liquid", 1.0, "condensate", optical_depth=50.0)
        ]
    return SunwardCrossSection(
        distances_km=list(distances_km), heights_m=heights,
        relative_humidity_pct=empty.copy(), vertical_velocity_pa_s=empty.copy(),
        temperature_k=empty.copy(), mask=np.ones((3, n), dtype=bool),
        cloud_layers=layers, observer=(30.0, 120.0), azimuth_deg=270.0,
        target_time=datetime(2026, 6, 27, tzinfo=timezone.utc),
        aerosol_optical_depth_per_column=aod_per_column,
    )


def _detail_snapshot(cloud_base_m):
    t = datetime(2026, 6, 27, 9, tzinfo=timezone.utc)
    return WeatherSnapshot(
        cloud_low_pct=0.0, cloud_mid_pct=0.0, cloud_high_pct=50.0, humidity_pct=50.0,
        source_label="test", retrieved_at=t, cloud_base_m=cloud_base_m, sunset_time=t,
    )


def test_mid_high_cloud_zero_cover_scores_zero(base_features):
    f = replace(base_features, cloud_mid_pct=0, cloud_high_pct=0)
    assert MidHighCloudPresence().evaluate(f) == 0.0


def test_mid_high_cloud_full_cover_saturates_to_one(base_features):
    # Presence gate: a full mid/high overcast still has a canvas → gate passes.
    # (Whether the amount is *ideal* is CloudCoverSweetSpot's concern.)
    f = replace(base_features, cloud_mid_pct=100, cloud_high_pct=100)
    assert MidHighCloudPresence().evaluate(f) == 1.0


def test_mid_high_cloud_sweet_spot_scores_one(base_features):
    # Average mid+high = 50 → well past the 20% saturation → 1.0
    f = replace(base_features, cloud_mid_pct=50, cloud_high_pct=50)
    assert MidHighCloudPresence().evaluate(f) == 1.0


def test_mid_high_cloud_presence_ramp(base_features):
    # Presence ramp: 0 at 0%, linear to 1.0 by 20%. Avg = 10 → 0.5.
    f = replace(base_features, cloud_mid_pct=10, cloud_high_pct=10)
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


def test_clean_air_prefers_aod_over_good_surface_visibility(base_features):
    f = replace(
        base_features,
        visibility_m=30_000.0,
        aerosol_optical_depth=0.8,
    )
    assert CleanAirGate().evaluate(f) == 0.0


def test_clean_air_uses_worst_of_local_and_sunward_aod(base_features):
    f = replace(
        base_features,
        aerosol_optical_depth=0.1,
        sunward_aod_mean=0.5,
    )
    assert abs(CleanAirGate().evaluate(f) - 0.4) < 1e-9


def test_low_cloud_obstruction_uses_sunward_path_when_available(base_features):
    f = replace(
        base_features,
        cloud_low_pct=5.0,
        sunward_obstruction_pct=100.0,
    )
    assert LowCloudObstruction().evaluate(f) == 0.0


def test_sunward_illumination_passes_near_boundary(base_features):
    f = replace(
        base_features,
        cloud_base_m=7000.0,
        sunward_aod_mean=0.1,
        sunward_profile_max_km=800.0,
        sunward_cloud_boundary_km=150.0,
    )
    assert SunwardIlluminationGate().evaluate(f) == 1.0


def test_sunward_illumination_fails_when_no_edge_within_physical_reach(base_features):
    f = replace(
        base_features,
        cloud_base_m=3500.0,
        sunward_aod_mean=None,
        sunward_profile_max_km=800.0,
        sunward_cloud_boundary_km=None,
    )
    assert SunwardIlluminationGate().evaluate(f) == 0.0


def test_sunward_illumination_skips_without_profile(base_features):
    assert SunwardIlluminationGate().evaluate(base_features) is None


# --- FA-G5 second cut: gate consumes the ray-trace clearance when present -----


def test_sunward_illumination_clear_ray_trace_keeps_scalar_pass(base_features):
    # A clear path does not override the geometry: with a valid sunward edge within
    # reach the scalar still passes (1.0); the clear trace simply does not veto.
    f = replace(
        base_features, cloud_base_m=7000.0, sunward_aod_mean=0.1,
        sunward_profile_max_km=800.0, sunward_cloud_boundary_km=150.0,
        sunward_ray_clearance=RayClearance(True, None, None, None, 5),
    )
    assert SunwardIlluminationGate().evaluate(f) == 1.0


def test_sunward_illumination_clear_alone_does_not_force_pass(base_features):
    # Clear trace but no 1-D geometry → the gate is omitted (None), NOT a free pass:
    # the trace samples coarsely and cannot, by itself, confirm a sunward edge.
    f = replace(base_features, sunward_ray_clearance=RayClearance(True, None, None, None, 5))
    assert SunwardIlluminationGate().evaluate(f) is None


def test_sunward_illumination_blocked_ray_trace_fails(base_features):
    f = replace(base_features, sunward_ray_clearance=RayClearance(False, 150.0, 800.0, None, 5))
    assert SunwardIlluminationGate().evaluate(f) == 0.0


def test_sunward_illumination_blocked_vetoes_even_without_profile(base_features):
    # The obstruction veto works even when the 1-D scalar would be None.
    f = replace(base_features, sunward_ray_clearance=RayClearance(False, 200.0, 100.0, None, 6))
    assert SunwardIlluminationGate().evaluate(f) == 0.0


def test_sunward_illumination_ray_trace_overrides_scalar(base_features):
    # The scalar heuristic would PASS (edge within reach), but the ray trace finds
    # an opaque deck on the path → the faithful 2-D result wins → gate fails.
    f = replace(
        base_features, cloud_base_m=7000.0, sunward_aod_mean=0.1,
        sunward_profile_max_km=800.0, sunward_cloud_boundary_km=150.0,
        sunward_ray_clearance=RayClearance(False, 200.0, 100.0, None, 6),
    )
    assert SunwardIlluminationGate().evaluate(f) == 0.0


def test_derive_sets_ray_clearance_from_cross_section():
    # A high canvas (7 km, vertex ~298 km) with an opaque low deck at the ~300 km
    # column → the descending ray is blocked → clearance.clear is False.
    xsec = _xsec_with_low_deck([0.0, 100.0, 200.0, 300.0, 400.0], deck_at_idx=3)
    feats = derive(
        _detail_snapshot(7000.0), 30.0, 120.0,
        datetime(2026, 6, 27, 9, tzinfo=timezone.utc), sunward_cross_section=xsec,
    )
    assert feats.sunward_ray_clearance is not None
    assert feats.sunward_ray_clearance.clear is False


def test_derive_ray_clearance_clear_when_path_open():
    xsec = _xsec_with_low_deck([0.0, 100.0, 200.0, 300.0, 400.0], deck_at_idx=None)
    feats = derive(
        _detail_snapshot(7000.0), 30.0, 120.0,
        datetime(2026, 6, 27, 9, tzinfo=timezone.utc), sunward_cross_section=xsec,
    )
    assert feats.sunward_ray_clearance.clear is True


def test_derive_without_cross_section_leaves_clearance_none():
    feats = derive(
        _detail_snapshot(7000.0), 30.0, 120.0,
        datetime(2026, 6, 27, 9, tzinfo=timezone.utc),
    )
    assert feats.sunward_ray_clearance is None


def _sunward_profile_for_advection():
    # A mid canvas with the sunward edge detected ~138.9 km out, and a 20 m/s 700 hPa
    # wind from the east (travels west = azimuth 270°) → +20 m/s outward advection.
    return SunwardProfile(
        azimuth_deg=270.0,
        distances_km=[0.0, 50.0, 100.0, 150.0, 250.0],
        cloud_low_pct=[5.0, 10.0, 30.0, 40.0, 5.0],
        cloud_mid_pct=[70.0, 65.0, 55.0, 10.0, 0.0],
        cloud_high_pct=[0.0] * 5,
        aerosol_optical_depth=[None] * 5,
        wind_speed_850_m_s=[None] * 5, wind_direction_850_deg=[None] * 5,
        wind_speed_700_m_s=[20.0] * 5, wind_direction_700_deg=[90.0] * 5,
        wind_speed_400_m_s=[None] * 5, wind_direction_400_deg=[None] * 5,
    )


def test_fa_t1_advecting_boundary_out_of_reach_drops_illumination_gate():
    # FA-T1 composite metamorphic: holding everything else fixed, advecting the
    # sunward edge outward to sunset (here ~+216 km over 3 h) pushes it beyond the
    # grazing reach (~319 km for a 2 km base) → the illumination gate falls 1.0 → 0.
    t0 = datetime(2026, 6, 27, 9, 0, tzinfo=timezone.utc)
    sunset = datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc)  # Δt = 3 h
    snap = WeatherSnapshot(
        cloud_low_pct=0.0, cloud_mid_pct=60.0, cloud_high_pct=0.0, humidity_pct=50.0,
        source_label="t", retrieved_at=t0, cloud_base_m=2000.0, sunset_time=sunset,
        sunward_profile=_sunward_profile_for_advection(),
    )
    gate = SunwardIlluminationGate()
    at_valid = gate.evaluate(derive(snap, 30.0, 120.0, t0, valid_time=sunset))   # Δt=0
    at_sunset = gate.evaluate(derive(snap, 30.0, 120.0, t0, valid_time=t0))      # Δt=3h
    assert at_valid == 1.0
    assert at_sunset == 0.0
    assert at_sunset <= at_valid


def test_fa_t1_derive_default_valid_time_advects_to_sunset():
    # The production seam: score()/score_snapshot() call derive() WITHOUT valid_time,
    # so it defaults to the query time and Δt = sunset − time drives the advection.
    # Here the query is 3 h before sunset with +20 m/s outward wind → +216 km.
    t0 = datetime(2026, 6, 27, 9, 0, tzinfo=timezone.utc)
    sunset = datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc)  # Δt = 3 h
    snap = WeatherSnapshot(
        cloud_low_pct=0.0, cloud_mid_pct=60.0, cloud_high_pct=0.0, humidity_pct=50.0,
        source_label="t", retrieved_at=t0, cloud_base_m=7000.0, sunset_time=sunset,
        sunward_profile=_sunward_profile_for_advection(),
    )
    feats = derive(snap, 30.0, 120.0, t0)   # no valid_time → default = t0
    raw = feats.sunward_cloud_boundary_raw_km
    assert raw == pytest.approx(138.889, abs=0.1)
    assert feats.sunward_cloud_boundary_km == pytest.approx(raw + 216.0)


def test_derive_observer_column_aod_lowers_effective_base_and_blocks():
    # FA-A2 local channel: a low 2 km canvas with NO cloud anywhere on the path, but
    # the OBSERVER's own column (index 0) is very turbid (AOD 0.8 → h_x ≈ 6 km). That
    # drives the effective base to/below 0, so the ray cannot reach the canvas →
    # clearance is not clear. Clean elsewhere, so the only cause is the observer column.
    xsec = _xsec_with_low_deck(
        [0.0, 100.0, 200.0, 300.0, 400.0], deck_at_idx=None,
        aod_per_column=[0.8, None, None, None, None],
    )
    feats = derive(
        _detail_snapshot(2000.0), 30.0, 120.0,
        datetime(2026, 6, 27, 9, tzinfo=timezone.utc), sunward_cross_section=xsec,
    )
    assert feats.sunward_ray_clearance.clear is False


def test_derive_clean_observer_column_keeps_clear():
    # Same scene, observer column clean (AOD 0.0) → effective base stays at 2 km, no
    # cloud and no upstream excess → clear. Pins that index 0 (not another column)
    # is the effective-base source.
    xsec = _xsec_with_low_deck(
        [0.0, 100.0, 200.0, 300.0, 400.0], deck_at_idx=None,
        aod_per_column=[0.0, None, None, None, None],
    )
    feats = derive(
        _detail_snapshot(2000.0), 30.0, 120.0,
        datetime(2026, 6, 27, 9, tzinfo=timezone.utc), sunward_cross_section=xsec,
    )
    assert feats.sunward_ray_clearance.clear is True


def test_boundary_confidence_penalizes_fuzzy_fast_boundary(base_features):
    sharp_slow = replace(
        base_features,
        sunward_boundary_gradient_pct_per_km=1.0,
        boundary_motion_m_s=5.0,
    )
    fuzzy_fast = replace(
        base_features,
        sunward_boundary_gradient_pct_per_km=0.2,
        boundary_motion_m_s=35.0,
    )
    assert BoundaryConfidence().evaluate(sharp_slow) > BoundaryConfidence().evaluate(fuzzy_fast)


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


# ---------------------------------------------------------------------------
# New rules: CleanAirGate, CloudAltitudePreference, CloudCoverSweetSpot
# ---------------------------------------------------------------------------

from predictor.rules import (
    CleanAirGate,
    CloudAltitudePreference,
    CloudCoverSweetSpot,
    standard_predictor,
    gate_modifier_parts,
)


# --- CleanAirGate ---

def test_clean_air_gate_visibility_none_is_permissive(base_features):
    f = replace(base_features, visibility_m=None)
    assert CleanAirGate().evaluate(f) == 1.0


def test_clean_air_gate_high_visibility_passes(base_features):
    f = replace(base_features, visibility_m=25_000.0)
    assert CleanAirGate().evaluate(f) == 1.0


def test_clean_air_gate_low_visibility_blocks(base_features):
    # 3 km < 5 km threshold → score 0
    f = replace(base_features, visibility_m=3_000.0)
    assert CleanAirGate().evaluate(f) == 0.0


def test_clean_air_gate_at_5km_lower_bound_zero(base_features):
    f = replace(base_features, visibility_m=5_000.0)
    assert CleanAirGate().evaluate(f) == 0.0


def test_clean_air_gate_at_20km_upper_bound_one(base_features):
    f = replace(base_features, visibility_m=20_000.0)
    assert CleanAirGate().evaluate(f) == 1.0


def test_clean_air_gate_midpoint_half(base_features):
    # Midpoint of [5, 20] km = 12.5 km → score 0.5
    f = replace(base_features, visibility_m=12_500.0)
    assert abs(CleanAirGate().evaluate(f) - 0.5) < 1e-9


# --- CloudAltitudePreference ---

def test_cloud_altitude_preference_no_cloud_returns_zero(base_features):
    f = replace(base_features, cloud_mid_pct=0.0, cloud_high_pct=0.0)
    assert CloudAltitudePreference().evaluate(f) == 0.0


def test_cloud_altitude_preference_pure_high_returns_one(base_features):
    # Only high cloud (weight 1.0) → score = 1.0
    f = replace(base_features, cloud_mid_pct=0.0, cloud_high_pct=50.0)
    assert CloudAltitudePreference().evaluate(f) == 1.0


def test_cloud_altitude_preference_pure_mid_returns_half(base_features):
    # Only mid cloud (weight 0.5) → score = 0.5
    f = replace(base_features, cloud_mid_pct=50.0, cloud_high_pct=0.0)
    assert CloudAltitudePreference().evaluate(f) == 0.5


def test_cloud_altitude_preference_mixed_equal_parts(base_features):
    # mid=50, high=50 → (1.0*50 + 0.5*50) / 100 = 75/100 = 0.75
    f = replace(base_features, cloud_mid_pct=50.0, cloud_high_pct=50.0)
    assert abs(CloudAltitudePreference().evaluate(f) - 0.75) < 1e-9


def test_cloud_altitude_preference_coverage_amounts_cancel_in_ratio(base_features):
    # Proportions matter, not absolute amounts: 10% mid-only == 50% mid-only == 0.5
    f10 = replace(base_features, cloud_mid_pct=10.0, cloud_high_pct=0.0)
    f50 = replace(base_features, cloud_mid_pct=50.0, cloud_high_pct=0.0)
    assert CloudAltitudePreference().evaluate(f10) == CloudAltitudePreference().evaluate(f50)


# --- CloudCoverSweetSpot ---

def test_cloud_cover_sweet_spot_in_range_returns_one(base_features):
    # avg = (50 + 50) / 2 = 50 → inside [40, 75] → 1.0
    f = replace(base_features, cloud_mid_pct=50.0, cloud_high_pct=50.0)
    assert CloudCoverSweetSpot().evaluate(f) == 1.0


def test_cloud_cover_sweet_spot_no_cloud_returns_zero(base_features):
    f = replace(base_features, cloud_mid_pct=0.0, cloud_high_pct=0.0)
    assert CloudCoverSweetSpot().evaluate(f) == 0.0


def test_cloud_cover_sweet_spot_full_overcast_returns_zero(base_features):
    # avg = 100 → outside [10, 95] upper ramp → 0.0
    f = replace(base_features, cloud_mid_pct=100.0, cloud_high_pct=100.0)
    assert CloudCoverSweetSpot().evaluate(f) == 0.0


def test_cloud_cover_sweet_spot_inside_peak_plateau(base_features):
    # avg = (60 + 70) / 2 = 65 → inside [40, 75] → 1.0
    f = replace(base_features, cloud_mid_pct=60.0, cloud_high_pct=70.0)
    assert CloudCoverSweetSpot().evaluate(f) == 1.0


# ---------------------------------------------------------------------------
# standard_predictor end-to-end
# ---------------------------------------------------------------------------

def _good_canvas_snapshot():
    """A snapshot with good conditions: mid+high cloud, low humidity, good vis."""
    sunset = datetime(2026, 5, 20, 23, 30, tzinfo=timezone.utc)
    return WeatherSnapshot(
        cloud_low_pct=10.0,
        cloud_mid_pct=50.0,
        cloud_high_pct=40.0,
        humidity_pct=60.0,
        source_label="fake",
        retrieved_at=datetime(2026, 5, 20, tzinfo=timezone.utc),
        visibility_m=30_000.0,
        sunset_time=sunset,
    )


def test_standard_predictor_has_seven_component_names():
    src = FakeSource(_good_canvas_snapshot())
    pred = standard_predictor(src)
    sunset = datetime(2026, 5, 20, 23, 30, tzinfo=timezone.utc)
    f = pred.score(lat=42.36, lon=-71.06, time=sunset)
    expected_names = {
        "mid_high_cloud_presence",
        "low_cloud_obstruction",
        "solar_angle",
        "clean_air",
        "humidity",
        "cloud_altitude_preference",
        "cloud_cover_sweet_spot",
    }
    assert set(f.components.keys()) == expected_names


def test_standard_predictor_returns_gate_and_modifier_scores():
    src = FakeSource(_good_canvas_snapshot())
    pred = standard_predictor(src)
    sunset = datetime(2026, 5, 20, 23, 30, tzinfo=timezone.utc)
    f = pred.score(lat=42.36, lon=-71.06, time=sunset)
    assert f.gate_score is not None
    assert f.modifier_score is not None


def test_standard_predictor_probability_in_unit_interval():
    src = FakeSource(_good_canvas_snapshot())
    pred = standard_predictor(src)
    sunset = datetime(2026, 5, 20, 23, 30, tzinfo=timezone.utc)
    f = pred.score(lat=42.36, lon=-71.06, time=sunset)
    assert 0.0 <= f.probability <= 1.0


def test_standard_predictor_no_canvas_gives_probability_zero():
    # mid=0, high=0 → MidHighCloudPresence gate = 0 → P = 0
    snap = WeatherSnapshot(
        cloud_low_pct=5.0,
        cloud_mid_pct=0.0,
        cloud_high_pct=0.0,
        humidity_pct=60.0,
        source_label="fake",
        retrieved_at=datetime(2026, 5, 20, tzinfo=timezone.utc),
        visibility_m=30_000.0,
        sunset_time=datetime(2026, 5, 20, 23, 30, tzinfo=timezone.utc),
    )
    src = FakeSource(snap)
    pred = standard_predictor(src)
    sunset = datetime(2026, 5, 20, 23, 30, tzinfo=timezone.utc)
    f = pred.score(lat=42.36, lon=-71.06, time=sunset)
    assert f.probability == 0.0


def test_standard_predictor_score_at_sunset_has_nonzero_gate():
    # Querying exactly at sunset_time → solar_angle = 1.0 (within ±30 min)
    src = FakeSource(_good_canvas_snapshot())
    pred = standard_predictor(src)
    sunset = datetime(2026, 5, 20, 23, 30, tzinfo=timezone.utc)
    f = pred.score(lat=42.36, lon=-71.06, time=sunset)
    # solar_angle component should be 1.0 at sunset
    assert f.components["solar_angle"] == 1.0


# ---------------------------------------------------------------------------
# gate_modifier_parts
# ---------------------------------------------------------------------------

def test_gate_modifier_parts_one_gate_zero_gives_gate_zero():
    components = {"g1": 0.0, "m1": 1.0}
    weights = {"g1": 1.0, "m1": 1.0}
    gate, modifier = gate_modifier_parts(components, weights, gate_names={"g1"})
    assert gate == 0.0


def test_gate_modifier_parts_all_gates_one_modifier_half():
    components = {"g1": 1.0, "m1": 0.5}
    weights = {"g1": 1.0, "m1": 1.0}
    gate, modifier = gate_modifier_parts(components, weights, gate_names={"g1"})
    assert gate == 1.0
    assert abs(modifier - 0.5) < 1e-9
