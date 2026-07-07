"""Unit tests for satellite IR cloud-top retrieval/correction (#15)."""
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from predictor.cloud_top import (
    CloudTopRetrieval,
    colocate_and_correct,
    correct_cloud_top,
    retrieve_cloud_top,
)
from predictor.profiles import NormalizedProfile

_T = datetime(2026, 6, 23, 11, tzinfo=timezone.utc)


def _profile(heights, temps) -> NormalizedProfile:
    h = np.asarray(heights, dtype=float)
    t = np.asarray(temps, dtype=float)
    n = h.size
    return NormalizedProfile(
        lat=31.0, lon=121.0,
        pressure_hpa=np.linspace(1000, 200, n),
        geometric_height_m=h, geopotential_height_m=h,
        temperature_k=t,
        relative_humidity_pct=np.full(n, 50.0), dewpoint_k=t - 5,
        specific_humidity_kg_kg=np.full(n, 0.003),
        u_wind_m_s=np.zeros(n), v_wind_m_s=np.zeros(n), vertical_velocity_pa_s=np.zeros(n),
        cloud_water_kg_kg=np.full(n, np.nan), cloud_ice_kg_kg=np.full(n, np.nan),
        run_time=_T, valid_time=_T, source_label="gfs@test", retrieved_at=_T, missing=[],
    )


_STD = _profile(
    [0, 1000, 2000, 4000, 6000, 8000, 10000, 12000],
    [295, 289, 282, 269, 256, 243, 228, 218],
)


def test_single_crossing_interpolates_height():
    r = retrieve_cloud_top(250.0, _STD)
    assert isinstance(r, CloudTopRetrieval)
    assert r.n_solutions == 1
    # 250 K lies between 256 K (6000 m) and 243 K (8000 m) → ~6923 m.
    assert 6800 < r.height_m < 7000
    assert r.confidence > 0.7
    assert r.temperature_k == 250.0


def test_colder_than_profile_minimum_clamps_high_with_low_confidence():
    r = retrieve_cloud_top(210.0, _STD)  # colder than the 218 K top
    assert r.height_m == 12000.0          # clamped to the coldest level
    assert r.confidence < 0.6
    assert "cold" in r.reason.lower() or "min" in r.reason.lower()


def test_warmer_than_surface_is_no_cloud_fallback():
    r = retrieve_cloud_top(300.0, _STD)   # warmer than the 295 K surface
    assert r.height_m is None
    assert r.confidence < 0.3
    assert r.n_solutions == 0


def test_inversion_yields_multiple_solutions_and_lower_confidence():
    inv = _profile([0, 1000, 2000, 3000, 5000], [290, 284, 288, 280, 265])
    r = retrieve_cloud_top(286.0, inv)
    assert r.n_solutions >= 2
    # Ambiguous inversion → pick the highest candidate, flag low confidence.
    assert r.height_m >= 2000.0
    assert r.confidence < 0.7
    assert "inversion" in r.reason.lower()


def test_near_isothermal_crossing_reduces_confidence():
    iso = _profile([0, 2000, 4000, 6000], [280, 250.4, 250.0, 235])
    near = retrieve_cloud_top(250.2, iso)   # crossing inside the ~isothermal 2–4 km layer
    sharp = retrieve_cloud_top(250.2, _STD)  # crossing in a strong lapse layer
    assert near.confidence < sharp.confidence


# --- correction (model top + satellite retrieval) ---------------------------

def test_correction_keeps_model_top_when_no_retrieval():
    r = retrieve_cloud_top(300.0, _STD)   # None
    c = correct_cloud_top(7000.0, r)
    assert c.corrected_top_m == 7000.0
    assert c.source == "model"


def test_correction_adopts_satellite_top_when_consistent():
    r = retrieve_cloud_top(250.0, _STD)   # ~6923 m
    c = correct_cloud_top(7000.0, r)      # model says 7000 m → consistent
    assert abs(c.corrected_top_m - r.height_m) < 1.0
    assert c.source == "satellite"
    assert c.confidence > 0.6


def test_correction_flags_semi_transparent_when_satellite_far_below_model():
    r = retrieve_cloud_top(282.0, _STD)   # ~2000 m (warm → low IR top)
    c = correct_cloud_top(11000.0, r)     # model says 11 km high deck
    assert c.confidence < 0.6
    assert "thin" in c.reason.lower() or "semi" in c.reason.lower() or "transparent" in c.reason.lower()


# --- co-location (satellite Tb + model valid time + position) ----------------

def test_colocate_uses_satellite_top_when_observation_is_fresh():
    obs = _T  # same instant as the model valid time → within tolerance
    c = colocate_and_correct(250.0, obs, _T, 7000.0, _STD)
    assert c.source == "satellite"
    assert abs(c.corrected_top_m - 6923) < 120  # the ~6923 m crossing
    assert c.confidence > 0.6


def test_colocate_falls_back_to_model_when_no_observation():
    c = colocate_and_correct(None, _T, _T, 7000.0, _STD)
    assert c.source == "model"
    assert c.corrected_top_m == 7000.0


def test_colocate_falls_back_to_model_when_brightness_is_nan():
    c = colocate_and_correct(np.nan, _T, _T, 7000.0, _STD)
    assert c.source == "model"
    assert c.corrected_top_m == 7000.0


def test_colocate_falls_back_when_time_gap_too_large():
    stale = _T - timedelta(hours=2)  # 120 min >> 30 min tolerance
    c = colocate_and_correct(250.0, stale, _T, 7000.0, _STD)
    assert c.source == "model"
    assert c.corrected_top_m == 7000.0
    assert "gap" in c.reason.lower() or "stale" in c.reason.lower()


# ---------------------------------------------------------------------------
# FA-C6: IR top → base inference (manual §4.2.1(1) workflow companion)
# ---------------------------------------------------------------------------


def test_adopted_satellite_top_shifts_base_preserving_model_thickness():
    from predictor.cloud_top import CloudTopCorrection, infer_base_from_corrected_top

    correction = CloudTopCorrection(2800.0, 0.9, "satellite-corrected top", "satellite")
    base = infer_base_from_corrected_top(2043.0, 3110.0, correction)
    assert base == pytest.approx(2800.0 - (3110.0 - 2043.0))


def test_kept_model_top_keeps_model_base():
    from predictor.cloud_top import CloudTopCorrection, infer_base_from_corrected_top

    correction = CloudTopCorrection(3110.0, 0.0, "no satellite top; kept model top", "model")
    assert infer_base_from_corrected_top(2043.0, 3110.0, correction) == 2043.0
