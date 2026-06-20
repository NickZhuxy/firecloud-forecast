# predictor/tests/test_geometry.py
"""Tests for predictor/geometry.py — pure analytic geometry functions."""
import math

import pytest

from predictor.geometry import (
    GeometryResult,
    EARTH_RADIUS_KM,
    characteristic_duration_min,
    compute_geometry,
    equivalent_cloud_base_m,
    max_penetration_km,
    sunset_speed_km_min,
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


# ---------------------------------------------------------------------------
# characteristic_duration_min
# ---------------------------------------------------------------------------


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
