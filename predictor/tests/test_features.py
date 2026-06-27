from datetime import datetime, timezone
import pytest
import predictor.features as features_mod
from predictor.features import (
    Features,
    analyze_sunward_profile,
    compute_sunset,
    derive,
    estimate_cloud_base_m,
    select_canvas_layer,
)
from predictor.fetch import WeatherSnapshot
from predictor.spatial import SunwardProfile


def test_features_dataclass_holds_fields():
    f = Features(
        cloud_low_pct=10, cloud_mid_pct=50, cloud_high_pct=40,
        humidity_pct=60,
        sunset_time=datetime(2026, 5, 20, 23, 30, tzinfo=timezone.utc),
        query_time=datetime(2026, 5, 20, 23, 20, tzinfo=timezone.utc),
        location=(42.36, -71.06),
    )
    assert f.cloud_high_pct == 40


def test_compute_sunset_for_boston_late_may():
    # Boston sunset on 2026-05-20 is approximately 20:08 EDT = 00:08 UTC next day.
    dt = datetime(2026, 5, 21, 0, 0, tzinfo=timezone.utc)
    sunset = compute_sunset(lat=42.36, lon=-71.06, dt=dt)
    assert isinstance(sunset, datetime)
    assert sunset.tzinfo is not None


def test_derive_skips_astral_when_snapshot_supplies_sunset(monkeypatch):
    """A source-reported sunset must short-circuit the astral fallback."""
    def _boom(*args, **kwargs):  # pragma: no cover - must never run here
        raise AssertionError("compute_sunset should not be called when sunset is known")

    monkeypatch.setattr(features_mod, "compute_sunset", _boom)
    source_sunset = datetime(2026, 5, 21, 0, 8, tzinfo=timezone.utc)
    snap = WeatherSnapshot(
        cloud_low_pct=10.0, cloud_mid_pct=50.0, cloud_high_pct=40.0,
        humidity_pct=60.0, source_label="test", retrieved_at=source_sunset,
        sunset_time=source_sunset,
    )
    feats = derive(snap, 42.36, -71.06, datetime(2026, 5, 21, 0, 0, tzinfo=timezone.utc))
    assert feats.sunset_time == source_sunset


def test_canvas_base_uses_elevated_deck_not_low_obstruction():
    assert select_canvas_layer(80.0, 40.0, 60.0) == "high"
    assert estimate_cloud_base_m(80.0, 40.0, 60.0) == 7000.0


def test_canvas_base_falls_back_to_low_for_low_only_case():
    assert select_canvas_layer(65.0, 0.0, 0.0) == "low"
    assert estimate_cloud_base_m(65.0, 0.0, 0.0) == 1000.0


def test_sunward_profile_extracts_boundary_obstruction_aod_and_motion():
    profile = SunwardProfile(
        azimuth_deg=270.0,
        distances_km=[0.0, 50.0, 100.0, 150.0, 250.0],
        cloud_low_pct=[5.0, 10.0, 30.0, 40.0, 5.0],
        cloud_mid_pct=[70.0, 65.0, 55.0, 10.0, 0.0],
        cloud_high_pct=[0.0] * 5,
        aerosol_optical_depth=[0.10, 0.20, None, 0.30, 0.20],
        wind_speed_850_m_s=[None] * 5,
        wind_direction_850_deg=[None] * 5,
        wind_speed_700_m_s=[20.0] * 5,
        # Wind from east travels west, exactly along azimuth 270°.
        wind_direction_700_deg=[90.0] * 5,
        wind_speed_400_m_s=[None] * 5,
        wind_direction_400_deg=[None] * 5,
    )

    result = analyze_sunward_profile(profile, "mid")

    assert 135.0 < result["sunward_cloud_boundary_km"] < 140.0
    assert result["sunward_obstruction_pct"] == 40.0
    assert result["sunward_aod_mean"] == 0.2
    assert abs(result["boundary_motion_m_s"] - 20.0) < 1e-9


# ---------------------------------------------------------------------------
# FA-T1: advect the sunward boundary to sunset by the cloud-height wind
# ---------------------------------------------------------------------------

def _advection_profile(wind_dir_700_deg, *, wind_speed_700=20.0):
    # Mid canvas with a boundary near ~138.9 km and a 20 m/s 700 hPa wind whose
    # direction the caller controls (to flip the advection sign).
    return SunwardProfile(
        azimuth_deg=270.0,
        distances_km=[0.0, 50.0, 100.0, 150.0, 250.0],
        cloud_low_pct=[5.0, 10.0, 30.0, 40.0, 5.0],
        cloud_mid_pct=[70.0, 65.0, 55.0, 10.0, 0.0],
        cloud_high_pct=[0.0] * 5,
        aerosol_optical_depth=[None] * 5,
        wind_speed_850_m_s=[None] * 5, wind_direction_850_deg=[None] * 5,
        wind_speed_700_m_s=[wind_speed_700] * 5, wind_direction_700_deg=[wind_dir_700_deg] * 5,
        wind_speed_400_m_s=[None] * 5, wind_direction_400_deg=[None] * 5,
    )


_T0 = datetime(2026, 6, 27, 9, 0, tzinfo=timezone.utc)
_SUNSET_30MIN = datetime(2026, 6, 27, 9, 30, tzinfo=timezone.utc)  # Δt = 1800 s


def test_boundary_not_advected_without_times():
    # Two-arg call (no sunset/valid_time) leaves the boundary at the snapshot time.
    result = analyze_sunward_profile(_advection_profile(90.0), "mid")
    assert result["sunward_cloud_boundary_raw_km"] == result["sunward_cloud_boundary_km"]


def test_boundary_advected_outward_to_sunset():
    # Wind from the east (90°) travels west = azimuth 270° → +20 m/s outward.
    # Over 30 min that is +36 km: the sunward edge recedes by 36 km by sunset.
    p = _advection_profile(90.0)
    raw = analyze_sunward_profile(p, "mid")["sunward_cloud_boundary_km"]
    result = analyze_sunward_profile(p, "mid", sunset_time=_SUNSET_30MIN, valid_time=_T0)
    assert result["sunward_cloud_boundary_raw_km"] == pytest.approx(raw)
    assert result["sunward_cloud_boundary_km"] == pytest.approx(raw + 36.0)


def test_boundary_advected_inward_when_wind_reverses():
    # Wind from the west (270°) travels east = opposite azimuth → −20 m/s inward.
    p = _advection_profile(270.0)
    raw = analyze_sunward_profile(p, "mid")["sunward_cloud_boundary_km"]
    result = analyze_sunward_profile(p, "mid", sunset_time=_SUNSET_30MIN, valid_time=_T0)
    assert result["sunward_cloud_boundary_km"] == pytest.approx(raw - 36.0)
    # boundary_motion_m_s stays the unsigned magnitude (BoundaryConfidence unchanged).
    assert result["boundary_motion_m_s"] == pytest.approx(20.0)


def test_boundary_zero_dt_is_identity():
    p = _advection_profile(90.0)
    raw = analyze_sunward_profile(p, "mid")["sunward_cloud_boundary_km"]
    result = analyze_sunward_profile(p, "mid", sunset_time=_T0, valid_time=_T0)
    assert result["sunward_cloud_boundary_km"] == pytest.approx(raw)


def test_boundary_missing_wind_is_identity_even_with_dt():
    # No canvas-layer wind → no advection (identity), even with Δt > 0. Pins the
    # documented degeneracy: a detected boundary but absent wind stays put.
    p = _advection_profile(None, wind_speed_700=None)  # 700 hPa wind absent
    result = analyze_sunward_profile(p, "mid", sunset_time=_SUNSET_30MIN, valid_time=_T0)
    assert result["sunward_cloud_boundary_km"] == result["sunward_cloud_boundary_raw_km"]
    assert result["boundary_motion_m_s"] is None


# ---------------------------------------------------------------------------
# _observer_column_aod (FA-A2): the observer's own column AOD = index 0
# ---------------------------------------------------------------------------

from types import SimpleNamespace

from predictor.features import _observer_column_aod


def test_observer_column_aod_returns_first_column():
    xs = SimpleNamespace(aerosol_optical_depth_per_column=[0.1, 0.4, None])
    assert _observer_column_aod(xs) == 0.1


def test_observer_column_aod_zero_is_a_real_value_not_none():
    # A clean observer (0.0) must read as 0.0, not be coerced to None.
    xs = SimpleNamespace(aerosol_optical_depth_per_column=[0.0, 0.5])
    assert _observer_column_aod(xs) == 0.0


def test_observer_column_aod_none_when_unknown_or_absent():
    assert _observer_column_aod(SimpleNamespace(aerosol_optical_depth_per_column=None)) is None
    assert _observer_column_aod(SimpleNamespace(aerosol_optical_depth_per_column=[])) is None
    assert _observer_column_aod(SimpleNamespace(aerosol_optical_depth_per_column=[None, 0.4])) is None
