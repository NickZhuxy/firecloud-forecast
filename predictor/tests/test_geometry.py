# predictor/tests/test_geometry.py
"""Tests for predictor/geometry.py — pure analytic geometry functions."""
import math

import pytest

from predictor.geometry import (
    AerosolGroundRange,
    GeometryResult,
    EARTH_RADIUS_KM,
    OverheadWindow,
    advect_boundary_km,
    aerosol_ground_height_m,
    characteristic_duration_min,
    compute_geometry,
    equivalent_cloud_base_m,
    equivalent_cloud_base_from_aod_m,
    equivalent_cloud_base_range_from_aod_m,
    hygroscopic_growth_factor,
    max_penetration_km,
    overhead_firecloud_window,
    representative_terminator_speed_km_min,
    sunset_speed_km_min,
    total_observed_duration_min,
    viewing_elevation_deg,
    viewing_extension_min,
)


# ---------------------------------------------------------------------------
# max_penetration_km
# ---------------------------------------------------------------------------


def test_max_penetration_zero_base_returns_zero():
    assert max_penetration_km(0) == 0.0


def test_max_penetration_negative_base_returns_zero():
    assert max_penetration_km(-500) == 0.0


def test_max_penetration_5000m_approx():
    # 2 * sqrt(2 * 6371 * 5) ≈ 505.5 km
    expected = 2.0 * math.sqrt(2.0 * EARTH_RADIUS_KM * 5.0)
    result = max_penetration_km(5000)
    assert abs(result - expected) < 1.0


def test_max_penetration_monotonically_increasing():
    bases = [1000, 2000, 5000, 8000, 12000]
    values = [max_penetration_km(b) for b in bases]
    for a, b in zip(values, values[1:]):
        assert a < b


def test_max_penetration_scales_as_sqrt():
    # Doubling the base should multiply reach by sqrt(2)
    r1 = max_penetration_km(4000)
    r2 = max_penetration_km(8000)
    assert abs(r2 / r1 - math.sqrt(2.0)) < 1e-9


# ---------------------------------------------------------------------------
# sunset_speed_km_min
# ---------------------------------------------------------------------------


def test_sunset_speed_equator_approx_27_8():
    speed = sunset_speed_km_min(0.0)
    # R * 0.25 * pi/180 ≈ 27.8 km/min
    assert abs(speed - 27.8) < 0.5


def test_sunset_speed_60deg_half_of_equator():
    speed_eq = sunset_speed_km_min(0.0)
    speed_60 = sunset_speed_km_min(60.0)
    # cos(60°) = 0.5
    assert abs(speed_60 - speed_eq * 0.5) < 1e-9


def test_sunset_speed_equator_greater_than_60deg():
    assert sunset_speed_km_min(0.0) > sunset_speed_km_min(60.0)


def test_sunset_speed_symmetric_about_equator():
    # Northern and southern hemisphere at same absolute latitude
    assert sunset_speed_km_min(45.0) == pytest.approx(sunset_speed_km_min(-45.0))


def test_sunset_speed_decreases_with_abs_lat():
    lats = [0, 15, 30, 45, 60, 75]
    speeds = [sunset_speed_km_min(lat) for lat in lats]
    for a, b in zip(speeds, speeds[1:]):
        assert a > b


# ---------------------------------------------------------------------------
# equivalent_cloud_base_m
# ---------------------------------------------------------------------------


def test_equivalent_cloud_base_visibility_none_returns_unchanged():
    assert equivalent_cloud_base_m(5000.0, None) == 5000.0


def test_equivalent_cloud_base_visibility_zero_returns_unchanged():
    # visibility_m <= 0 is treated as unknown → unchanged
    assert equivalent_cloud_base_m(5000.0, 0.0) == 5000.0


def test_equivalent_cloud_base_very_high_visibility_no_reduction():
    # At visibility >= ~195.6 km, beta_0 <= beta_x and the code returns the raw base.
    # Using 200 km (200_000 m) — above that threshold.
    raw = 5000.0
    eff = equivalent_cloud_base_m(raw, 200_000.0)
    assert eff == raw  # beta_0 falls below threshold → unchanged


def test_equivalent_cloud_base_moderate_high_visibility_reduces_base():
    # 100 km visibility still has beta_0 > beta_x, so there is a reduction (~27%);
    # the effective base should be strictly less than the raw base but > 0.
    raw = 5000.0
    eff = equivalent_cloud_base_m(raw, 100_000.0)
    assert 0.0 < eff < raw


def test_equivalent_cloud_base_low_visibility_substantial_reduction():
    # 3 km visibility (hazy) should substantially reduce the effective base.
    raw = 5000.0
    eff = equivalent_cloud_base_m(raw, 3000.0)
    assert eff < raw * 0.8


def test_equivalent_cloud_base_never_negative():
    # Even with extremely low visibility, floor is 0.
    eff = equivalent_cloud_base_m(500.0, 100.0)
    assert eff >= 0.0


def test_equivalent_cloud_base_floors_at_zero_not_below():
    eff = equivalent_cloud_base_m(1000.0, 500.0)
    assert eff == 0.0 or eff > 0.0
    assert eff >= 0.0


def test_equivalent_cloud_base_custom_scale_height():
    # Larger scale height → aerosol column extends higher → more reduction
    eff_small = equivalent_cloud_base_m(5000.0, 5000.0, scale_height_m=1000.0)
    eff_large = equivalent_cloud_base_m(5000.0, 5000.0, scale_height_m=3000.0)
    # Note: if both floor at 0 this comparison still passes (0 == 0 is ok);
    # ensure larger scale height gives smaller or equal effective base.
    assert eff_large <= eff_small + 1e-9


def test_equivalent_cloud_base_from_aod_unknown_is_unchanged():
    assert equivalent_cloud_base_from_aod_m(7000.0, None) == 7000.0


def test_equivalent_cloud_base_from_aod_reduces_height_as_column_dirties():
    clean = equivalent_cloud_base_from_aod_m(7000.0, 0.1)
    dirty = equivalent_cloud_base_from_aod_m(7000.0, 0.5)
    assert 0.0 < dirty < clean < 7000.0


# ---------------------------------------------------------------------------
# aerosol_ground_height_m (FA-A2) — the equivalent opaque-ground height h_x
# alone, so the per-column ray trace can apply it without a cloud base.
# ---------------------------------------------------------------------------


def test_aerosol_ground_height_unknown_aod_is_zero():
    assert aerosol_ground_height_m(None) == 0.0


def test_aerosol_ground_height_nonpositive_aod_is_zero():
    assert aerosol_ground_height_m(0.0) == 0.0
    assert aerosol_ground_height_m(-0.3) == 0.0


def test_aerosol_ground_height_below_threshold_is_zero():
    # beta_0 = AOD/H = 0.04/2 = 0.02 km^-1 == beta_x → already at the threshold, h_x=0.
    assert aerosol_ground_height_m(0.04) == 0.0


def test_aerosol_ground_height_dirty_matches_closed_form():
    # h_x = H·ln(beta_0/beta_x) = 2000·ln((0.1/2)/0.02) = 2000·ln(2.5).
    assert aerosol_ground_height_m(0.1) == pytest.approx(2000.0 * math.log(2.5))


def test_aerosol_ground_height_monotonic_in_aod():
    assert aerosol_ground_height_m(0.5) > aerosol_ground_height_m(0.1) > 0.0


def test_aerosol_ground_height_custom_scale_height():
    # H = 1 km: beta_0 = 0.1/1 = 0.1 → h_x = 1000·ln(0.1/0.02) = 1000·ln(5).
    assert aerosol_ground_height_m(0.1, scale_height_m=1000.0) == pytest.approx(
        1000.0 * math.log(5.0)
    )


def test_aerosol_ground_height_consistent_with_equivalent_base():
    # equivalent_cloud_base_from_aod_m is just cloud_base − h_x, floored at 0.
    h_x = aerosol_ground_height_m(0.3)
    assert equivalent_cloud_base_from_aod_m(10000.0, 0.3) == pytest.approx(10000.0 - h_x)


# ---------------------------------------------------------------------------
# advect_boundary_km (FA-T1): move the sunward boundary by signed wind over Δt
# ---------------------------------------------------------------------------


def test_advect_boundary_closed_form():
    # 100 km + 10 m/s · 1800 s / 1000 = 118 km.
    assert advect_boundary_km(100.0, 10.0, 1800.0) == pytest.approx(118.0)


def test_advect_boundary_outward_increases_inward_decreases():
    assert advect_boundary_km(100.0, 20.0, 1800.0) > 100.0   # cloud moving sunward
    assert advect_boundary_km(100.0, -20.0, 1800.0) < 100.0  # cloud moving toward observer


def test_advect_boundary_floors_at_zero():
    # Strong inward wind cannot push the boundary negative.
    assert advect_boundary_km(10.0, -100.0, 1800.0) == 0.0


def test_advect_boundary_zero_dt_is_identity():
    assert advect_boundary_km(123.0, 25.0, 0.0) == 123.0


def test_advect_boundary_matches_manual_section_4_2_magnitude():
    # Manual §4.2: a mid-cloud gap advects ~40 km in 30 min at ~22 m/s.
    assert advect_boundary_km(0.0, 22.0, 1800.0) == pytest.approx(39.6, abs=0.1)


# ---------------------------------------------------------------------------
# characteristic_duration_min
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# representative_terminator_speed_km_min (FA-G4): statistical mid of the cos-lat
# physical speed and the manual appendix's ~20 km/min central value.
# ---------------------------------------------------------------------------


def test_representative_speed_is_mean_of_physical_and_manual():
    for lat in (10.0, 22.5, 31.0, 47.7):
        assert representative_terminator_speed_km_min(lat) == pytest.approx(
            0.5 * (sunset_speed_km_min(lat) + 20.0)
        )


def test_representative_speed_between_manual_and_physical_at_low_lat():
    # Where cos-lat overestimates (low latitude, cos-lat > 20), the blend sits
    # between the manual (~20) and the physical cos-lat value.
    lat = 22.5
    assert 20.0 < representative_terminator_speed_km_min(lat) < sunset_speed_km_min(lat)


def test_representative_speed_decreases_with_abs_lat():
    assert representative_terminator_speed_km_min(20.0) > representative_terminator_speed_km_min(50.0)


def test_characteristic_duration_uses_representative_speed():
    # The reported duration now divides by the representative (blended) speed.
    h = 5000.0
    lat = 31.0
    L_km = math.sqrt(2.0 * EARTH_RADIUS_KM * (h / 1000.0))
    expected = 2.0 * L_km / representative_terminator_speed_km_min(lat)
    assert characteristic_duration_min(h, lat) == pytest.approx(expected)


def test_characteristic_duration_zero_base_returns_zero():
    assert characteristic_duration_min(0.0, lat=45.0) == 0.0


def test_characteristic_duration_negative_base_returns_zero():
    assert characteristic_duration_min(-100.0, lat=45.0) == 0.0


def test_characteristic_duration_positive_and_finite():
    dur = characteristic_duration_min(5000.0, lat=45.0)
    assert dur > 0.0
    assert math.isfinite(dur)


def test_characteristic_duration_scales_roughly_as_sqrt():
    # Duration ∝ sqrt(h_eff), so base=8000 should give ~2x duration of base=2000
    dur_2000 = characteristic_duration_min(2000.0, lat=45.0)
    dur_8000 = characteristic_duration_min(8000.0, lat=45.0)
    ratio = dur_8000 / dur_2000
    # sqrt(8000/2000) = 2.0
    assert abs(ratio - 2.0) < 0.01


def test_characteristic_duration_high_base_greater_than_low_base():
    assert characteristic_duration_min(8000.0, lat=45.0) > characteristic_duration_min(2000.0, lat=45.0)


def test_characteristic_duration_increases_at_higher_lat_due_to_slower_terminator():
    # Slower terminator at higher latitude → terminator dwells longer → longer duration
    dur_45 = characteristic_duration_min(5000.0, lat=45.0)
    dur_60 = characteristic_duration_min(5000.0, lat=60.0)
    assert dur_60 > dur_45


# ---------------------------------------------------------------------------
# compute_geometry
# ---------------------------------------------------------------------------


def test_compute_geometry_none_base_returns_none_reach_and_duration():
    result = compute_geometry(cloud_base_m=None, visibility_m=None, lat=45.0)
    assert isinstance(result, GeometryResult)
    assert result.cloud_base_m is None
    assert result.max_reach_km is None
    assert result.duration_min is None
    # sunset_speed_km_min should still be populated
    assert result.sunset_speed_km_min > 0.0


def test_compute_geometry_with_real_base_populates_fields():
    result = compute_geometry(cloud_base_m=5000.0, visibility_m=30_000.0, lat=45.0)
    assert result.cloud_base_m == 5000.0
    assert result.equivalent_cloud_base_m is not None
    assert result.max_reach_km is not None
    assert result.max_reach_km > 0.0
    assert result.duration_min is not None
    assert result.duration_min > 0.0
    assert result.sunset_speed_km_min > 0.0


def test_compute_geometry_none_visibility_returns_unchanged_equivalent_base():
    result = compute_geometry(cloud_base_m=5000.0, visibility_m=None, lat=45.0)
    assert result.equivalent_cloud_base_m == 5000.0


def test_compute_geometry_numeric_types():
    result = compute_geometry(cloud_base_m=3500.0, visibility_m=20_000.0, lat=42.0)
    assert isinstance(result.max_reach_km, float)
    assert isinstance(result.duration_min, float)
    assert isinstance(result.sunset_speed_km_min, float)


# ---------------------------------------------------------------------------
# viewing_elevation_deg (FA-G3) — manual §1.2.4, θ = h/l − l/(2R)
# Golden values from the manual's worked examples (Shenzhen / Yichun / Qingdao).
# ---------------------------------------------------------------------------


def test_viewing_elevation_shenzhen_boundary_below_horizon():
    # D=200 km, h=2000 m → −0.32° (manual §4.1.1): boundary below the horizon.
    assert viewing_elevation_deg(200.0, 2000.0) == pytest.approx(-0.326, abs=0.02)


def test_viewing_elevation_yichun_boundary():
    # D=166 km, h=7219 m → 1.75° (manual §4.1.1 Yichun).
    assert viewing_elevation_deg(166.0, 7219.0) == pytest.approx(1.745, abs=0.02)


def test_viewing_elevation_qingdao_boundary():
    # D=200 km, h=9200 m → 1.74° (manual §1.2.4 Qingdao).
    assert viewing_elevation_deg(200.0, 9200.0) == pytest.approx(1.736, abs=0.02)


def test_viewing_elevation_farther_boundary_lower_angle():
    near = viewing_elevation_deg(100.0, 5000.0)
    far = viewing_elevation_deg(300.0, 5000.0)
    assert near > far


def test_viewing_elevation_higher_cloud_larger_angle():
    low = viewing_elevation_deg(150.0, 3000.0)
    high = viewing_elevation_deg(150.0, 9000.0)
    assert high > low


def test_viewing_elevation_curvature_can_drive_angle_negative():
    # A low, distant boundary sits below the horizon (curvature term dominates).
    assert viewing_elevation_deg(250.0, 1500.0) < 0.0


def test_viewing_elevation_overhead_when_distance_zero():
    assert viewing_elevation_deg(0.0, 5000.0) == 90.0


# ---------------------------------------------------------------------------
# overhead_firecloud_window (FA-G1) — manual §1.2.2 firecloud triangle
# duration = √(2R·h_eff)/v − D/(2v); relative to the observer's local sunset.
# ---------------------------------------------------------------------------


def test_overhead_window_shenzhen():
    # h_eff=2 km, D=200 km, v=21 km/min → start 4.76, end 7.60, duration 2.84 min.
    w = overhead_firecloud_window(boundary_km=200.0, cloud_base_eff_m=2000.0,
                                  sunset_speed_km_min=21.0)
    assert isinstance(w, OverheadWindow)
    assert w.start_min == pytest.approx(4.76, abs=0.05)
    assert w.end_min == pytest.approx(7.60, abs=0.05)
    assert w.duration_min == pytest.approx(2.84, abs=0.05)


def test_overhead_window_yichun_low_eff_base():
    # h_eff=4.65 km, D=166 km, v=18 → duration 8.91 min (manual lower bound 8.9).
    w = overhead_firecloud_window(166.0, 4650.0, 18.0)
    assert w.duration_min == pytest.approx(8.91, abs=0.05)


def test_overhead_window_yichun_high_eff_base():
    # h_eff=5.9 km, D=166 km, v=18 → duration 10.62 min (manual upper bound 10.6).
    w = overhead_firecloud_window(166.0, 5900.0, 18.0)
    assert w.duration_min == pytest.approx(10.62, abs=0.05)


def test_overhead_window_none_when_boundary_beyond_reach():
    # D ≥ 2√(2R·h) = max reach → no overhead firecloud.
    reach = max_penetration_km(2000.0)  # ≈ 319 km
    assert overhead_firecloud_window(reach + 50.0, 2000.0, 21.0) is None


def test_overhead_window_none_for_nonpositive_eff_base():
    # Aerosol correction can push the effective base to/below zero → no glow.
    assert overhead_firecloud_window(100.0, 0.0, 21.0) is None


def test_viewing_extension_zero_for_nonpositive_inputs():
    assert viewing_extension_min(0.0, 21.0) == 0.0
    assert viewing_extension_min(2000.0, 0.0) == 0.0


def test_overhead_duration_shrinks_with_farther_boundary():
    near = overhead_firecloud_window(100.0, 5000.0, 20.0).duration_min
    far = overhead_firecloud_window(250.0, 5000.0, 20.0).duration_min
    assert far < near


def test_overhead_duration_grows_with_higher_base():
    low = overhead_firecloud_window(150.0, 3000.0, 20.0).duration_min
    high = overhead_firecloud_window(150.0, 9000.0, 20.0).duration_min
    assert high > low


# ---------------------------------------------------------------------------
# viewing_extension_min + total_observed_duration_min (FA-G2) — manual §1.2.4/§4.1.1
# 5° sky extension uses the RAW cloud base; overhead uses the equivalent base.
# ---------------------------------------------------------------------------


def test_viewing_extension_shenzhen():
    # h=2 km, v=21: 2/tan(5°)=22.86 km, /21 = 1.09 min.
    assert viewing_extension_min(2000.0, 21.0) == pytest.approx(1.09, abs=0.03)


def test_total_duration_shenzhen():
    # overhead 2.84 + extension 1.09 = 3.93 min (manual ~3.9).
    total = total_observed_duration_min(boundary_km=200.0, cloud_base_eff_m=2000.0,
                                        cloud_base_raw_m=2000.0, sunset_speed_km_min=21.0)
    assert total == pytest.approx(3.93, abs=0.06)


def test_total_duration_yichun_range_matches_manual_13_to_15():
    # Manual: 13.5–15.2 min. overhead(h_eff) uses 4.65/5.9 km; extension uses raw 7.291 km.
    low = total_observed_duration_min(166.0, 4650.0, 7291.0, 18.0)
    high = total_observed_duration_min(166.0, 5900.0, 7291.0, 18.0)
    assert low == pytest.approx(13.5, abs=0.2)
    assert high == pytest.approx(15.2, abs=0.2)


def test_total_duration_none_when_no_overhead_firecloud():
    reach = max_penetration_km(2000.0)
    assert total_observed_duration_min(reach + 50.0, 2000.0, 2000.0, 21.0) is None


# ---------------------------------------------------------------------------
# equivalent_cloud_base_range_from_aod_m (FA-A1) — manual §1.3.3 / Table 4.1
# Sweep aerosol scale height H∈[0.5,4] km; h_x non-monotonic, peaks ~2.75 km
# at H≈3 for AOD=0.15.
# ---------------------------------------------------------------------------


def test_aerosol_range_unknown_aod_is_none():
    assert equivalent_cloud_base_range_from_aod_m(9200.0, None) is None


def test_aerosol_range_table_4_1_peak_h_x():
    r = equivalent_cloud_base_range_from_aod_m(9200.0, 0.15)
    assert isinstance(r, AerosolGroundRange)
    # Table 4.1: h_x peaks ≈ 2.75 km near H = 3.0 km.
    assert r.h_x_max_m == pytest.approx(2750.0, abs=30.0)
    assert r.scale_height_at_max_h_x_km == pytest.approx(3.0, abs=0.01)
    # H = 0.5 km row gives the minimum h_x ≈ 1.35 km.
    assert r.h_x_min_m == pytest.approx(1354.0, abs=30.0)


def test_aerosol_range_is_non_monotonic_peak_interior():
    # The peak h_x must come from an interior H, not an endpoint (non-monotonicity).
    r = equivalent_cloud_base_range_from_aod_m(9200.0, 0.15)
    assert 0.5 < r.scale_height_at_max_h_x_km < 4.0


def test_aerosol_range_eff_base_is_cloud_base_minus_h_x():
    r = equivalent_cloud_base_range_from_aod_m(9200.0, 0.15)
    # The largest h_x gives the smallest effective base, and vice versa.
    assert r.eff_base_min_m == pytest.approx(9200.0 - r.h_x_max_m, abs=1.0)
    assert r.eff_base_max_m == pytest.approx(9200.0 - r.h_x_min_m, abs=1.0)


def test_aerosol_range_consistent_with_fixed_H_function_at_2km():
    # The fixed-H=2000m scalar function must equal the H=2.0 km sample of the sweep.
    fixed = equivalent_cloud_base_from_aod_m(9200.0, 0.15, scale_height_m=2000.0)
    r = equivalent_cloud_base_range_from_aod_m(9200.0, 0.15, scale_heights_km=(2.0,))
    assert r.eff_base_min_m == pytest.approx(fixed, abs=1.0)


# ---------------------------------------------------------------------------
# compute_geometry enrichment (FA-G1/G2/G3 + FA-A1 wired in, additive)
# ---------------------------------------------------------------------------


def test_compute_geometry_populates_new_fields_when_boundary_given():
    # High deck (7 km) so the aerosol-corrected base stays positive and a
    # window exists; a 2 km base under AOD=0.15 would correct below ground.
    result = compute_geometry(
        cloud_base_m=7000.0, visibility_m=None, lat=22.5,
        aerosol_optical_depth=0.15, boundary_km=200.0, cloud_base_raw_m=7000.0,
        sunset_speed_km_min=21.0,
    )
    assert isinstance(result.overhead_window, OverheadWindow)
    assert result.total_duration_min is not None
    assert result.boundary_elevation_deg is not None
    assert isinstance(result.aerosol_ground_range, AerosolGroundRange)


def test_compute_geometry_new_fields_none_without_boundary():
    result = compute_geometry(cloud_base_m=5000.0, visibility_m=None, lat=45.0)
    assert result.overhead_window is None
    assert result.total_duration_min is None
    assert result.boundary_elevation_deg is None
    # Existing behaviour unchanged.
    assert result.max_reach_km is not None
    assert result.duration_min is not None


# ---- FA-C4 (#86): convective vertical-line duration (manual §1.2.3) ----


def test_convective_duration_scales_with_sqrt_cloud_top():
    from predictor.geometry import convective_duration_min

    d1 = convective_duration_min(2500.0, lat=31.0)
    d4 = convective_duration_min(10000.0, lat=31.0)
    assert d4 == pytest.approx(2.0 * d1, rel=1e-6)   # √(4h) = 2√h


def test_convective_duration_yichun_magnitude():
    from predictor.geometry import convective_duration_min

    # Manual's Yichun case quotes v = 18 km/min at 47.7°N; a 10 km congestus
    # top then sustains ≈ √(2·6371·10)/18 ≈ 20 min. Allow the FA-G4 blended
    # speed to move this within 15–25 min.
    d = convective_duration_min(10000.0, lat=47.7)
    assert 15.0 <= d <= 25.0


def test_convective_duration_degenerate_inputs():
    from predictor.geometry import convective_duration_min

    assert convective_duration_min(0.0, lat=31.0) == 0.0
    assert convective_duration_min(-100.0, lat=31.0) == 0.0


def test_convective_duration_is_half_the_stratiform_characteristic():
    from predictor.geometry import characteristic_duration_min, convective_duration_min

    # Same h: the stratiform triangle spans 2L/v, the vertical-line model L/v.
    h, lat = 6000.0, 31.0
    assert convective_duration_min(h, lat) == pytest.approx(
        characteristic_duration_min(h, lat) / 2.0, rel=1e-9
    )


# ---------------------------------------------------------------------------
# hygroscopic_growth_factor (FA-A4) — bounded Hänel power law g(RH)
# ---------------------------------------------------------------------------


def test_hygroscopic_growth_unity_at_or_below_reference():
    # Dry regime (IMPROVE f(RH)≈1 below 60%): strictly no amplification, so
    # every RH≤60 scenario stays bit-exact with the pre-FA-A4 model.
    assert hygroscopic_growth_factor(60.0) == 1.0
    assert hygroscopic_growth_factor(35.0) == 1.0
    assert hygroscopic_growth_factor(None) == 1.0  # missing RH → no amplification


def test_hygroscopic_growth_monotone_and_capped_at_fog_regime():
    rhs = [60.0, 65.0, 70.0, 75.0, 80.0, 85.0, 90.0]
    gs = [hygroscopic_growth_factor(r) for r in rhs]
    assert all(later >= earlier for earlier, later in zip(gs, gs[1:]))
    # Above ~90% RH is fog/activation territory (manual §2.4.3 hands that to
    # visibility/cloud signals); the power law is capped, not divergent.
    assert hygroscopic_growth_factor(97.0) == hygroscopic_growth_factor(90.0)
    # Pin the Hänel form at one point: g(80) = (0.40/0.20)^0.6.
    assert hygroscopic_growth_factor(80.0) == pytest.approx((0.40 / 0.20) ** 0.6)


def test_equivalent_base_lowered_further_by_humid_boundary_layer():
    # FA-A4: the same column AOD swells at high RH → the equivalent opaque
    # ground rises → the effective canvas base drops further than when dry.
    dry = equivalent_cloud_base_from_aod_m(5000.0, 0.4)
    humid = equivalent_cloud_base_from_aod_m(5000.0, 0.4, rh_pct=84.0)
    assert humid < dry
    # No RH / dry RH degrade bit-exact to the pre-FA-A4 result.
    assert equivalent_cloud_base_from_aod_m(5000.0, 0.4, rh_pct=None) == dry
    assert equivalent_cloud_base_from_aod_m(5000.0, 0.4, rh_pct=55.0) == dry


def test_aerosol_ground_height_amplified_by_humidity():
    dry = aerosol_ground_height_m(0.5)
    humid = aerosol_ground_height_m(0.5, rh_pct=85.0)
    # h_x = H·ln(AOD·g/(H·β_x)): g enters the log, so the rise is H·ln(g).
    assert humid == pytest.approx(dry + 2000.0 * math.log(hygroscopic_growth_factor(85.0)))
