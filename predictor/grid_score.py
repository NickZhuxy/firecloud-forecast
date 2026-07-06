"""Vectorized national-grid scoring (#19).

The per-point Open-Meteo overview tops out at ~190 coarse samples because every
cell is a separate HTTP request. This module scores a whole GFS 0.25° grid at
once with numpy, so the national map can be a fine ~25 km field instead of a few
upsampled blobs.

It deliberately mirrors the scalar ``predictor.rules`` math for the national
*overview* subset of gates/modifiers (the sunward-transect rules need an 800 km
cross-section per point and are not part of the overview). ``test_grid_score``
pins the grid result to the scalar ``RuleBasedPredictor`` within tolerance, so
the two never drift.

The national overview evaluates each cell at its own sunset, so the solar-angle
gate is 1.0 by construction (the caller selects each cell's near-sunset state).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from predictor.rules import STANDARD_WEIGHTS

# Overview rule subset (no sunward illumination / boundary confidence — those
# need a per-point transect). Weights mirror predictor.rules.STANDARD_WEIGHTS.
_GATE_WEIGHTS = {
    "mid_high_cloud_presence": STANDARD_WEIGHTS["mid_high_cloud_presence"],
    "low_cloud_obstruction": STANDARD_WEIGHTS["low_cloud_obstruction"],
    "solar_angle": STANDARD_WEIGHTS["solar_angle"],
    "sunward_illumination": STANDARD_WEIGHTS["sunward_illumination"],
}
_MODIFIER_WEIGHTS = {
    "humidity": STANDARD_WEIGHTS["humidity"],
    "cloud_altitude_preference": STANDARD_WEIGHTS["cloud_altitude_preference"],
    "cloud_cover_sweet_spot": STANDARD_WEIGHTS["cloud_cover_sweet_spot"],
    # FA-A3: local aerosol perception is a quality modifier, not a gate.
    "clean_air": STANDARD_WEIGHTS["clean_air"],
}

_CLEAN_AIR_AOD_POINTS = np.array([
    [0.00, 1.00], [0.10, 1.00], [0.20, 0.90],
    [0.30, 0.75], [0.50, 0.40], [0.80, 0.00],
])


@dataclass
class GridInputs:
    """Gridded scoring inputs (each array the same (ny, nx) shape, percent/SI)."""

    cloud_low_pct: np.ndarray
    cloud_mid_pct: np.ndarray
    cloud_high_pct: np.ndarray
    humidity_pct: np.ndarray
    visibility_m: np.ndarray | None = None
    aerosol_optical_depth: np.ndarray | None = None
    cloud_base_m: np.ndarray | None = None
    sunward_cloud_boundary_km: np.ndarray | None = None
    sunward_profile_max_km: np.ndarray | None = None
    sunward_aod_mean: np.ndarray | None = None


def _trapezoid(x, low0, low1, high1, high0):
    x = np.asarray(x, dtype=float)
    out = np.zeros_like(x)
    rising = (x > low0) & (x < low1)
    out[rising] = (x[rising] - low0) / (low1 - low0)
    out[(x >= low1) & (x <= high1)] = 1.0
    falling = (x > high1) & (x < high0)
    out[falling] = (high0 - x[falling]) / (high0 - high1)
    return out


def _clean_air(visibility_m, aod):
    if aod is not None:
        a = np.asarray(aod, dtype=float)
        xs, ys = _CLEAN_AIR_AOD_POINTS[:, 0], _CLEAN_AIR_AOD_POINTS[:, 1]
        # np.interp clamps below xs[0]/above xs[-1] to the end values; beyond the
        # last breakpoint (0.8) the scalar rule returns 0, which np.interp matches.
        return np.interp(a, xs, ys)
    if visibility_m is None:
        # The scalar rule returns None when neither signal is available; the
        # caller omits the component (FA-A3), mirroring that contract.
        return None
    vis_km = np.asarray(visibility_m, dtype=float) / 1000.0
    return np.clip((vis_km - 5.0) / 15.0, 0.0, 1.0)


def _equivalent_base_from_aod(cloud_base_m, aod):
    base = np.asarray(cloud_base_m, dtype=float)
    if aod is None:
        return base
    a = np.asarray(aod, dtype=float)
    scale_height_km = 2.0
    beta_x = 0.02
    beta_0 = a / scale_height_km
    h_x_m = np.where(
        np.isfinite(a) & (a > 0) & (beta_0 > beta_x),
        scale_height_km * 1000.0 * np.log(beta_0 / beta_x),
        0.0,
    )
    return np.maximum(0.0, base - h_x_m)


def _max_penetration_km(cloud_base_m):
    base = np.asarray(cloud_base_m, dtype=float)
    return np.where(
        np.isfinite(base) & (base > 0),
        2.0 * np.sqrt(2.0 * 6371.0 * (base / 1000.0)),
        0.0,
    )


def _sunward_illumination(cloud_base_m, boundary_km, profile_max_km, aod):
    base = np.asarray(cloud_base_m, dtype=float)
    boundary = np.asarray(boundary_km, dtype=float)
    profile_max = np.asarray(profile_max_km, dtype=float)
    effective_base = _equivalent_base_from_aod(base, aod)
    reach = _max_penetration_km(effective_base)

    score = np.zeros_like(base)
    known_base = np.isfinite(base) & (base > 0) & np.isfinite(profile_max)
    impossible = known_base & (reach <= 0)
    score[impossible] = 0.0

    insufficient_path = known_base & ~np.isfinite(boundary) & (profile_max < reach) & (reach > 0)
    score[insufficient_path] = 1.0

    no_boundary = known_base & ~np.isfinite(boundary) & (profile_max >= reach) & (reach > 0)
    score[no_boundary] = 0.0

    has_boundary = known_base & np.isfinite(boundary) & (reach > 0)
    ratio = np.zeros_like(base)
    ratio[has_boundary] = boundary[has_boundary] / reach[has_boundary]
    score[has_boundary & (ratio <= 0.70)] = 1.0
    score[has_boundary & (ratio >= 1.0)] = 0.0
    ramp = has_boundary & (ratio > 0.70) & (ratio < 1.0)
    score[ramp] = (1.0 - ratio[ramp]) / 0.30
    return np.clip(score, 0.0, 1.0)


def score_grid(inputs: GridInputs) -> np.ndarray:
    """Return the gate × modifier probability field for the whole grid."""
    low = np.asarray(inputs.cloud_low_pct, dtype=float)
    mid = np.asarray(inputs.cloud_mid_pct, dtype=float)
    high = np.asarray(inputs.cloud_high_pct, dtype=float)
    humidity = np.asarray(inputs.humidity_pct, dtype=float)
    canvas = np.maximum(mid, high)

    # Gates.
    g_presence = np.where(canvas <= 0, 0.0, np.minimum(1.0, canvas / 20.0))
    g_obstruction = np.where(low <= 20, 1.0, np.maximum(0.0, 1.0 - (low - 20) / 80.0))
    g_solar = np.ones_like(low)  # each cell evaluated at its own sunset

    gates = {
        "mid_high_cloud_presence": g_presence,
        "low_cloud_obstruction": g_obstruction,
        "solar_angle": g_solar,
    }
    if (
        inputs.cloud_base_m is not None
        and inputs.sunward_cloud_boundary_km is not None
        and inputs.sunward_profile_max_km is not None
    ):
        gates["sunward_illumination"] = _sunward_illumination(
            inputs.cloud_base_m,
            inputs.sunward_cloud_boundary_km,
            inputs.sunward_profile_max_km,
            inputs.sunward_aod_mean,
        )

    # Modifiers.
    total = mid + high
    m_humidity = _trapezoid(humidity, 20, 40, 80, 95)
    m_altitude = np.where(total <= 0, 0.0, (high + 0.5 * mid) / np.where(total <= 0, 1.0, total))
    m_sweet = _trapezoid(canvas, 10, 40, 75, 95)
    modifiers = {
        "humidity": m_humidity,
        "cloud_altitude_preference": m_altitude,
        "cloud_cover_sweet_spot": m_sweet,
    }
    # FA-A3: local aerosol perception joins the modifier layer when a signal
    # exists; with neither AOD nor visibility the component is omitted, exactly
    # like the scalar rule returning None.
    clean = _clean_air(inputs.visibility_m, inputs.aerosol_optical_depth)
    if clean is not None:
        modifiers["clean_air"] = clean

    # Gate layer: weighted geometric mean (a 0 gate forces the product to 0).
    w_gate = sum(_GATE_WEIGHTS[name] for name in gates)
    gate = np.ones_like(low)
    for name, score in gates.items():
        gate = gate * np.power(score, _GATE_WEIGHTS[name] / w_gate)

    # Modifier layer: weighted arithmetic mean over the present components.
    w_mod = sum(_MODIFIER_WEIGHTS[n] for n in modifiers)
    modifier = sum(_MODIFIER_WEIGHTS[n] * m for n, m in modifiers.items()) / w_mod

    return np.clip(gate * modifier, 0.0, 1.0)
