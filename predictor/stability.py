"""FA-C4 (#86): conditional-instability diagnosis from a normalized profile.

Manual §1.4.1: lift a surface parcel (dry adiabat to the LCL, moist above —
``thermo.parcel_profile_k``); where the state curve sits RIGHT of the
environment temperature profile the atmosphere is conditionally unstable, and
the thickness of that right-offset region IS the convective development height
(= convective cloud height). Manual §2.2 grades cumulus by that thickness:
a few hundred metres → humilis (wide ≫ tall), up to ~1.x km → mediocris,
**≥ 2 km → congestus** (tall ≫ wide — the regime whose firecloud follows the
§1.2.3 vertical-line model instead of the stratiform parabola).

The manual also concedes humilis vs convective stratocumulus can be genuinely
ambiguous, so the classification carries an explicit ``marginal`` flag near
the congestus threshold instead of pretending a hard cut.

Theory note: research/theory/fa-c4-skewt-stability-convective-regime.md.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from predictor.profiles import NormalizedProfile
from predictor.thermo import lcl_height_m, parcel_profile_k


@dataclass(frozen=True)
class StabilityConfig:
    # Manual §2.2 thresholds on the right-offset (unstable) depth. 长三角
    # empirical grading — configurable for other climates.
    congestus_min_depth_m: float = 2000.0
    mediocris_min_depth_m: float = 400.0
    # |depth − congestus threshold| within this band → marginal=True (the
    # humilis/stratocumulus ambiguity the manual warns about).
    marginal_band_m: float = 500.0


DEFAULT_STABILITY_CONFIG = StabilityConfig()


@dataclass
class StabilityDiagnosis:
    lcl_m: float                    # absolute height (profile frame) of the LCL
    unstable_top_m: float | None    # top of the first contiguous right-offset run
    unstable_depth_m: float
    regime: str                     # stratiform | cumulus_humilis | cumulus_mediocris | cumulus_congestus
    marginal: bool


def diagnose_stability(
    profile: NormalizedProfile,
    config: StabilityConfig = DEFAULT_STABILITY_CONFIG,
) -> StabilityDiagnosis:
    """Grade conditional instability by lifting the profile's surface level."""
    heights = np.asarray(profile.geometric_height_m, dtype=float)
    env_t = np.asarray(profile.temperature_k, dtype=float)
    pressures = np.asarray(profile.pressure_hpa, dtype=float)

    usable = np.isfinite(heights) & np.isfinite(env_t) & np.isfinite(pressures)
    heights, env_t, pressures = heights[usable], env_t[usable], pressures[usable]
    if heights.size < 2:
        return StabilityDiagnosis(
            lcl_m=float("nan"), unstable_top_m=None, unstable_depth_m=0.0,
            regime="stratiform", marginal=False,
        )

    t0 = float(env_t[0])
    td0 = float(np.asarray(profile.dewpoint_k, dtype=float)[usable][0])
    lcl_abs = heights[0] + lcl_height_m(t0, td0)
    parcel = parcel_profile_k(heights, pressures, t0, td0)

    # Right-offset region at/above the LCL: state curve warmer than environment.
    offset = (parcel > env_t) & (heights >= lcl_abs)
    if not offset.any():
        return StabilityDiagnosis(
            lcl_m=float(lcl_abs), unstable_top_m=None, unstable_depth_m=0.0,
            regime="stratiform", marginal=False,
        )

    # First contiguous run above the LCL (manual: its top = convective height).
    first = int(np.argmax(offset))
    last = first
    while last + 1 < offset.size and offset[last + 1]:
        last += 1
    top = float(heights[last])
    depth = top - max(float(heights[first]), float(lcl_abs))

    if depth >= config.congestus_min_depth_m:
        regime = "cumulus_congestus"
    elif depth >= config.mediocris_min_depth_m:
        regime = "cumulus_mediocris"
    elif depth > 0.0:
        regime = "cumulus_humilis"
    else:
        regime = "stratiform"
    marginal = abs(depth - config.congestus_min_depth_m) <= config.marginal_band_m

    return StabilityDiagnosis(
        lcl_m=float(lcl_abs),
        unstable_top_m=top,
        unstable_depth_m=float(depth),
        regime=regime,
        marginal=marginal,
    )
