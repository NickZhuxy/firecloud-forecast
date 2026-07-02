"""Unit tests for thermodynamic conversions (known samples + boundaries)."""
import math

import numpy as np
import pytest

from predictor import thermo


def test_saturation_vapor_pressure_at_0c_is_611hpa():
    # es(0°C) ≈ 6.112 hPa by the Magnus formula used here.
    assert thermo.saturation_vapor_pressure_hpa(273.15) == pytest.approx(6.112, rel=1e-3)


def test_specific_humidity_to_rh_known_sample():
    # T=15°C, p=850 hPa, q≈0.00626 kg/kg → RH ≈ 50%.
    rh = thermo.specific_humidity_to_rh(0.00626, 288.15, 850.0)
    assert rh == pytest.approx(50.0, abs=1.0)


def test_specific_humidity_to_rh_clamped_to_100():
    # A very moist parcel must not exceed 100% RH.
    rh = thermo.specific_humidity_to_rh(0.05, 288.15, 850.0)
    assert rh == 100.0


def test_dewpoint_equals_temperature_at_saturation():
    t = 288.15
    assert thermo.dewpoint_k(t, 100.0) == pytest.approx(t, abs=0.05)


def test_dewpoint_known_sample():
    # T=15°C, RH=50% → Td ≈ 4.65°C ≈ 277.8 K.
    assert thermo.dewpoint_k(288.15, 50.0) == pytest.approx(277.8, abs=0.3)


def test_dewpoint_never_exceeds_temperature():
    assert thermo.dewpoint_k(300.0, 150.0) <= 300.0  # RH>100 clamped first


def test_geopotential_to_geometric_height_known_sample():
    # H=10000 m geopotential → z ≈ 10015.7 m geometric.
    z = thermo.geopotential_to_geometric_height(10000.0)
    assert z == pytest.approx(10015.7, abs=1.0)
    assert z > 10000.0  # geometric height exceeds geopotential height aloft


def test_geopotential_to_geometric_height_handles_nan():
    assert math.isnan(thermo.geopotential_to_geometric_height(float("nan")))


def test_conversions_are_vectorized():
    q = np.array([0.00626, 0.05])
    rh = thermo.specific_humidity_to_rh(q, np.array([288.15, 288.15]), np.array([850.0, 850.0]))
    assert rh.shape == (2,)
    assert rh[1] == 100.0


# ---- FA-C4 (#86): parcel-lifting primitives ----
# Theory: research/theory/fa-c4-skewt-stability-convective-regime.md §2.1


def test_lcl_height_scales_linearly_with_dewpoint_depression():
    from predictor.thermo import lcl_height_m

    z1 = lcl_height_m(300.0, 295.0)   # 5 K depression
    z2 = lcl_height_m(300.0, 290.0)   # 10 K depression
    assert z2 == pytest.approx(2.0 * z1, rel=1e-6)
    # Manual-implied coefficient 1/(9.8−1.2) km/K ≈ 116.3 m/K (literature 125).
    assert 100.0 <= z1 / 5.0 <= 130.0


def test_lcl_of_saturated_parcel_is_zero():
    from predictor.thermo import lcl_height_m

    assert lcl_height_m(290.0, 290.0) == 0.0
    assert lcl_height_m(290.0, 295.0) == 0.0   # super-saturated clamps to 0


def test_moist_lapse_below_dry_and_converges_when_cold():
    from predictor.thermo import DRY_LAPSE_C_PER_KM, moist_adiabatic_lapse_c_per_km

    warm = moist_adiabatic_lapse_c_per_km(303.0, 1000.0)   # humid warm boundary layer
    cold = moist_adiabatic_lapse_c_per_km(213.0, 200.0)    # near tropopause, dry
    assert 0.0 < warm < DRY_LAPSE_C_PER_KM
    assert warm < 6.5                                      # moist tropical ≈ 4–5 ℃/km
    assert cold > 9.0                                      # §1.1.3 阶段3: Γm → Γd
    assert cold <= DRY_LAPSE_C_PER_KM + 1e-9


def test_parcel_profile_dry_slope_below_lcl_then_gentler():
    import numpy as np

    from predictor.thermo import DRY_LAPSE_C_PER_KM, lcl_height_m, parcel_profile_k

    heights = np.arange(0.0, 6001.0, 500.0)
    pressures = 1000.0 * np.exp(-heights / 8000.0)         # crude but monotone
    t0, td0 = 303.0, 293.0                                 # LCL ≈ 1.16 km
    parcel = parcel_profile_k(heights, pressures, t0, td0)
    lcl = lcl_height_m(t0, td0)

    below = heights <= lcl
    # Dry-adiabatic slope below the LCL (9.8 ℃/km exactly).
    slopes = -np.diff(parcel[below]) / np.diff(heights[below]) * 1000.0
    assert np.allclose(slopes, DRY_LAPSE_C_PER_KM, atol=1e-6)
    # Gentler (moist) slope just above the LCL.
    j = int(np.searchsorted(heights, lcl))
    slope_above = -(parcel[j + 1] - parcel[j]) / (heights[j + 1] - heights[j]) * 1000.0
    assert slope_above < DRY_LAPSE_C_PER_KM - 0.5
    assert parcel.shape == heights.shape
