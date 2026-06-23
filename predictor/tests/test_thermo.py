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
