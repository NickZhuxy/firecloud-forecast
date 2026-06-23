"""Thermodynamic conversions and physical constants.

Central home for unit conversions and magic constants so scoring/diagnosis code
never hardcodes them (acceptance criterion of #6). All functions accept scalars
or numpy arrays and propagate NaN for missing inputs.
"""
from __future__ import annotations

import numpy as np

# --- constants -------------------------------------------------------------
EARTH_MEAN_RADIUS_M = 6_371_000.0   # for geopotential <-> geometric height
EPSILON = 0.622                     # ratio of molar masses water/dry air (Rd/Rv)
# Magnus coefficients over liquid water (Bolton 1980), es in hPa, T in °C.
_MAGNUS_A = 17.67
_MAGNUS_B = 243.5
_ES_0C_HPA = 6.112
_T0_K = 273.15


def saturation_vapor_pressure_hpa(t_k):
    """Saturation vapor pressure over liquid water (hPa) from temperature (K)."""
    t_c = np.asarray(t_k, dtype=float) - _T0_K
    return _ES_0C_HPA * np.exp(_MAGNUS_A * t_c / (t_c + _MAGNUS_B))


def specific_humidity_to_rh(q_kg_kg, t_k, p_hpa):
    """Relative humidity (%, clamped to 0–100) from specific humidity, T, p."""
    q = np.asarray(q_kg_kg, dtype=float)
    # Vapor pressure from specific humidity: e = p·q / (ε + (1-ε)·q).
    e = p_hpa * q / (EPSILON + (1.0 - EPSILON) * q)
    rh = 100.0 * e / saturation_vapor_pressure_hpa(t_k)
    return np.clip(rh, 0.0, 100.0)


def dewpoint_k(t_k, rh_pct):
    """Dewpoint (K) from temperature (K) and relative humidity (%).

    Inverts the Magnus formula. RH is clamped to (0, 100]; the result never
    exceeds the input temperature.
    """
    rh = np.clip(np.asarray(rh_pct, dtype=float), 1e-3, 100.0)
    es = saturation_vapor_pressure_hpa(t_k)
    e = rh / 100.0 * es
    gamma = np.log(e / _ES_0C_HPA)
    td_c = _MAGNUS_B * gamma / (_MAGNUS_A - gamma)
    td_k = td_c + _T0_K
    return np.minimum(td_k, np.asarray(t_k, dtype=float))


def geopotential_to_geometric_height(geopotential_height_m, lat_deg=None):
    """Geometric height (m, true altitude) from geopotential height (m).

    Geopotential height H folds gravity's decrease with altitude into an
    energy-based coordinate; geometric height z is the true distance above the
    surface. They relate by H = R·z / (R + z), inverted here as
    z = R·H / (R − H) with R the Earth's mean radius. The ``lat_deg`` argument
    is accepted for future latitude-dependent gravity refinement; the mean-radius
    form is within ~0.1% through the troposphere.
    """
    h = np.asarray(geopotential_height_m, dtype=float)
    return EARTH_MEAN_RADIUS_M * h / (EARTH_MEAN_RADIUS_M - h)
