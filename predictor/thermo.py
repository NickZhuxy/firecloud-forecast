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


# --- FA-C4 (#86): parcel lifting -------------------------------------------
# Theory: research/theory/fa-c4-skewt-stability-convective-regime.md §2.1.
# Manual (人工火烧云预报速成) constants: dry adiabat 9.8 ℃/km (§1.1.3, valid in
# the lowest 3–4 km), mixing-ratio dewpoint line 1.2 ℃/km (§1.4.1). The moist
# pseudo-adiabat has no manual formula ("gentler than dry, converges when the
# vapor is exhausted"), so the standard AMS Glossary / Bolton (1980) form fills
# the gap — it degenerates to the dry rate in cold dry air, matching the
# manual's stage-3 description.
DRY_LAPSE_C_PER_KM = 9.8
DEWPOINT_LINE_C_PER_KM = 1.2
_LV_J_KG = 2.501e6      # latent heat of vaporization
_RD_J_KG_K = 287.04     # gas constant, dry air
_CPD_J_KG_K = 1005.7    # specific heat, dry air, constant pressure


def lcl_height_m(t0_k, td0_k):
    """Lifting condensation level (m above the parcel start), manual-implied.

    The parcel temperature falls at 9.8 ℃/km while its dewpoint falls at
    1.2 ℃/km; they meet after (T−Td)/(9.8−1.2) km ≈ 116 m per kelvin of
    dewpoint depression. A saturated (or super-saturated) parcel is already
    at its LCL → 0.
    """
    depression = float(t0_k) - float(td0_k)
    return max(depression / (DRY_LAPSE_C_PER_KM - DEWPOINT_LINE_C_PER_KM) * 1000.0, 0.0)


def moist_adiabatic_lapse_c_per_km(t_k, p_hpa):
    """Pseudo-adiabatic (moist) lapse rate (℃/km), AMS Glossary form.

    Γm = Γd · (1 + Lv·rs/(Rd·T)) / (1 + Lv²·rs·ε/(cpd·Rd·T²)), with rs the
    saturation mixing ratio at (T, p). Warm humid air → ~4–5 ℃/km; cold dry
    air → Γm → Γd (manual §1.1.3 stage 3).
    """
    t = np.asarray(t_k, dtype=float)
    es = saturation_vapor_pressure_hpa(t)
    rs = EPSILON * es / np.maximum(np.asarray(p_hpa, dtype=float) - es, 1e-6)
    numerator = 1.0 + _LV_J_KG * rs / (_RD_J_KG_K * t)
    denominator = 1.0 + _LV_J_KG**2 * rs * EPSILON / (_CPD_J_KG_K * _RD_J_KG_K * t**2)
    return DRY_LAPSE_C_PER_KM * numerator / denominator


def parcel_profile_k(heights_m, pressures_hpa, t0_k, td0_k):
    """State-curve temperatures (K) of a surface parcel lifted to ``heights_m``.

    Manual §1.4.1: dry adiabat up to the LCL, then the moist adiabat, with the
    local Γm re-evaluated segment by segment (it varies with T and p).
    ``heights_m`` must be ascending and start at the parcel's launch level.
    """
    heights = np.asarray(heights_m, dtype=float)
    pressures = np.asarray(pressures_hpa, dtype=float)
    if heights.size and np.any(np.diff(heights) <= 0):
        raise ValueError("heights_m must be strictly ascending")
    lcl = lcl_height_m(t0_k, td0_k)
    origin = heights[0] if heights.size else 0.0

    parcel = np.empty_like(heights)
    t = float(t0_k)
    previous_h = origin
    for i, h in enumerate(heights):
        # Dry part of this segment (below the LCL, measured from launch level).
        dry_top = min(h, origin + lcl)
        if dry_top > previous_h:
            t -= DRY_LAPSE_C_PER_KM * (dry_top - previous_h) / 1000.0
        # Moist part, integrated with the local lapse at segment start.
        moist_start = max(previous_h, origin + lcl)
        if h > moist_start:
            gamma = float(moist_adiabatic_lapse_c_per_km(t, pressures[i]))
            t -= gamma * (h - moist_start) / 1000.0
        parcel[i] = t
        previous_h = h
    return parcel


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
