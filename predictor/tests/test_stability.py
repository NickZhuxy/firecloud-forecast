"""FA-C4 (#86): conditional-instability diagnosis — offline synthetic profiles.

Theory: research/theory/fa-c4-skewt-stability-convective-regime.md §2.2/§2.3.
"""
from datetime import datetime, timezone

import numpy as np
import pytest

from predictor.profiles import NormalizedProfile
from predictor.stability import (
    DEFAULT_STABILITY_CONFIG,
    StabilityConfig,
    StabilityDiagnosis,
    diagnose_stability,
)

_T = datetime(2026, 7, 2, 10, tzinfo=timezone.utc)


def _profile(heights, temps, *, surface_dewpoint_k) -> NormalizedProfile:
    h = np.asarray(heights, dtype=float)
    t = np.asarray(temps, dtype=float)
    n = h.size
    dew = np.minimum(t - 20.0, t)          # aloft dewpoints irrelevant here
    dew[0] = surface_dewpoint_k
    return NormalizedProfile(
        lat=31.0, lon=121.0,
        pressure_hpa=1000.0 * np.exp(-h / 8000.0),
        geometric_height_m=h,
        geopotential_height_m=h,
        temperature_k=t,
        relative_humidity_pct=np.full(n, 50.0),
        dewpoint_k=dew,
        specific_humidity_kg_kg=np.full(n, 0.005),
        u_wind_m_s=np.zeros(n), v_wind_m_s=np.zeros(n),
        vertical_velocity_pa_s=np.zeros(n),
        cloud_water_kg_kg=np.full(n, np.nan),
        cloud_ice_kg_kg=np.full(n, np.nan),
        run_time=_T, valid_time=_T,
        source_label="synthetic", retrieved_at=_T,
    )


def _unstable_env(cap_m=5000.0, surface_t=303.0):
    """Textbook conditional instability: 9.8 ℃/km mixed layer to 500 m, then
    7.5 ℃/km aloft, capped by a +10 K inversion at ``cap_m``."""
    heights = np.arange(0.0, 8001.0, 250.0)
    temps = np.empty_like(heights)
    for i, h in enumerate(heights):
        if h <= 500.0:
            temps[i] = surface_t - 9.8 * h / 1000.0
        elif h <= cap_m:
            temps[i] = surface_t - 9.8 * 0.5 - 7.5 * (h - 500.0) / 1000.0
        else:
            # Strong capping inversion: +10 K jump, then warming with height —
            # an isothermal "cap" cannot actually stop a warm moist parcel.
            top_of_layer = surface_t - 9.8 * 0.5 - 7.5 * (cap_m - 500.0) / 1000.0
            temps[i] = top_of_layer + 10.0 + 5.0 * (h - cap_m) / 1000.0
    return heights, temps


def test_stable_isothermal_profile_is_stratiform():
    heights = np.arange(0.0, 8001.0, 250.0)
    diag = diagnose_stability(
        _profile(heights, np.full(heights.size, 280.0), surface_dewpoint_k=278.0)
    )
    assert isinstance(diag, StabilityDiagnosis)
    assert diag.regime == "stratiform"
    assert diag.unstable_depth_m == 0.0
    assert diag.unstable_top_m is None


def test_textbook_instability_is_congestus_with_top_at_cap():
    heights, temps = _unstable_env(cap_m=5000.0)
    diag = diagnose_stability(_profile(heights, temps, surface_dewpoint_k=299.0))
    assert diag.regime == "cumulus_congestus"
    assert diag.unstable_depth_m >= 2000.0
    assert diag.unstable_top_m == pytest.approx(5000.0, abs=550.0)  # cap ± two levels
    assert diag.marginal is False
    assert 300.0 < diag.lcl_m < 700.0        # (303−299)K × 116.3 m/K ≈ 465 m


def test_warming_environment_aloft_shrinks_instability():
    heights, temps = _unstable_env()
    warm = temps.copy()
    warm[1:] += 5.0                          # env aloft warms, surface parcel unchanged
    base = diagnose_stability(_profile(heights, temps, surface_dewpoint_k=299.0))
    warmer = diagnose_stability(_profile(heights, warm, surface_dewpoint_k=299.0))
    assert warmer.unstable_depth_m <= base.unstable_depth_m


def test_surface_heating_never_lowers_convective_top():
    # Heating with a fixed dewpoint RAISES the LCL, so under a hard cap the
    # right-offset *depth* may legitimately shrink — the invariant that holds
    # is that added buoyancy cannot bring the convective TOP down.
    heights, temps = _unstable_env()
    hot = temps.copy()
    hot[0] += 5.0                            # ground heating only
    base = diagnose_stability(_profile(heights, temps, surface_dewpoint_k=299.0))
    hotter = diagnose_stability(_profile(heights, hot, surface_dewpoint_k=299.0))
    assert hotter.unstable_top_m is not None and base.unstable_top_m is not None
    assert hotter.unstable_top_m >= base.unstable_top_m


def test_marginal_band_flags_near_threshold_depth():
    heights, temps = _unstable_env(cap_m=2600.0)   # depth ≈ 2600 − LCL ≈ 2100 m
    diag = diagnose_stability(_profile(heights, temps, surface_dewpoint_k=299.0))
    assert diag.regime == "cumulus_congestus"
    assert diag.marginal is True


def test_threshold_perturbation_does_not_flip_far_case():
    heights, temps = _unstable_env(cap_m=5000.0)
    profile = _profile(heights, temps, surface_dewpoint_k=299.0)
    for delta in (-50.0, 0.0, 50.0):
        cfg = StabilityConfig(
            congestus_min_depth_m=DEFAULT_STABILITY_CONFIG.congestus_min_depth_m + delta
        )
        assert diagnose_stability(profile, cfg).regime == "cumulus_congestus"


def test_shallow_instability_is_humilis():
    heights, temps = _unstable_env(cap_m=800.0)    # depth ≈ 800 − 465 ≈ 335 m
    diag = diagnose_stability(_profile(heights, temps, surface_dewpoint_k=299.0))
    assert diag.regime == "cumulus_humilis"
    assert 0.0 < diag.unstable_depth_m < 400.0
