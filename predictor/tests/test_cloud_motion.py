"""Satellite cloud-edge motion nowcasting (#16): offline + metamorphic tests."""
from datetime import datetime, timedelta, timezone

import numpy as np

from predictor.cloud_motion import (
    CloudMotionConfig,
    MotionVector,
    NowcastCorrection,
    cloud_mask,
    estimate_motion,
    nowcast_correction,
)
from predictor.satellite import BrightnessTempField

_T = datetime(2026, 6, 21, 11, 0, tzinfo=timezone.utc)
_CFG = CloudMotionConfig()


def _grid():
    lats = np.arange(35.0, 25.0, -0.25)   # 40 rows, descending (north→south)
    lons = np.arange(115.0, 125.0, 0.25)  # 40 cols, ascending (west→east)
    return lats, lons


def _frame(lats, lons, t, *, row0=14, col0=14, h=6, w=6, blob_bt=220.0, bg_bt=290.0):
    bt = np.full((lats.size, lons.size), float(bg_bt))
    bt[row0:row0 + h, col0:col0 + w] = float(blob_bt)
    return BrightnessTempField(
        lats=lats, lons=lons, brightness_temp_k=bt,
        observation_time=t, band="B13", source_label="himawari9@test", retrieved_at=t,
    )


# --- boundary / motion estimation -------------------------------------------

def test_cloud_mask_marks_cold_pixels():
    lats, lons = _grid()
    f = _frame(lats, lons, _T)
    mask = cloud_mask(f, _CFG)
    assert mask.dtype == bool
    assert mask.sum() == 36                       # the 6×6 cold blob
    assert mask[16, 16] and not mask[0, 0]


def test_estimate_motion_recovers_eastward_shift():
    lats, lons = _grid()
    f0 = _frame(lats, lons, _T, col0=14)
    f1 = _frame(lats, lons, _T + timedelta(minutes=10), col0=17)  # +3 cols east
    m = estimate_motion([f0, f1], _CFG)
    assert m.regime == "advective"
    assert m.du_deg_per_hr > 0                     # moving east
    assert abs(m.dv_deg_per_hr) < 0.5             # ~no north/south
    # +3 cols × 0.25° / (1/6 h) = +4.5 deg/hr east
    assert abs(m.du_deg_per_hr - 4.5) < 0.6
    assert m.confidence > 0.5


def test_estimate_motion_recovers_northward_shift():
    lats, lons = _grid()
    f0 = _frame(lats, lons, _T, row0=20)
    f1 = _frame(lats, lons, _T + timedelta(minutes=10), row0=17)  # rows decrease = north
    m = estimate_motion([f0, f1], _CFG)
    assert m.dv_deg_per_hr > 0                     # moving north
    assert abs(m.du_deg_per_hr) < 0.5


def test_identical_frames_give_near_zero_motion():
    lats, lons = _grid()
    f0 = _frame(lats, lons, _T)
    f1 = _frame(lats, lons, _T + timedelta(minutes=10))
    m = estimate_motion([f0, f1], _CFG)
    assert m.speed_deg_per_hr < 0.3
    assert m.regime == "advective"
    assert m.confidence > 0.6


def test_single_frame_is_no_motion_fallback():
    lats, lons = _grid()
    m = estimate_motion([_frame(lats, lons, _T)], _CFG)
    assert m.regime == "none"
    assert m.confidence == 0.0
    assert m.n_frames == 1


def test_frame_gap_too_large_is_no_motion():
    lats, lons = _grid()
    f0 = _frame(lats, lons, _T, col0=14)
    f1 = _frame(lats, lons, _T + timedelta(hours=2), col0=17)  # gap >> max_frame_gap
    m = estimate_motion([f0, f1], _CFG)
    assert m.regime == "none"
    assert "gap" in m.reason.lower()


def test_no_cloud_in_frames_is_no_motion():
    lats, lons = _grid()
    warm0 = _frame(lats, lons, _T, blob_bt=290.0)                       # no pixel < threshold
    warm1 = _frame(lats, lons, _T + timedelta(minutes=10), blob_bt=290.0)
    m = estimate_motion([warm0, warm1], _CFG)
    assert m.regime == "none"
    assert "cloud" in m.reason.lower()


def test_weak_overlap_lowers_confidence():
    lats, lons = _grid()
    # Cloud jumps far beyond the search radius → masks can't be aligned → low overlap.
    f0 = _frame(lats, lons, _T, col0=8)
    f1 = _frame(lats, lons, _T + timedelta(minutes=10), col0=30)
    m = estimate_motion([f0, f1], _CFG)
    assert m.confidence < _CFG.advective_confidence
    assert "weak" in m.reason.lower()


def test_developing_convection_lowers_confidence():
    lats, lons = _grid()
    # Stratiform: blob just drifts, top temperature steady.
    s0 = _frame(lats, lons, _T, col0=14, blob_bt=235.0)
    s1 = _frame(lats, lons, _T + timedelta(minutes=10), col0=16, blob_bt=235.0)
    strat = estimate_motion([s0, s1], _CFG)
    # Convective: same drift but tops cool sharply (rising/developing).
    c0 = _frame(lats, lons, _T, col0=14, blob_bt=235.0)
    c1 = _frame(lats, lons, _T + timedelta(minutes=10), col0=16, blob_bt=215.0)
    conv = estimate_motion([c0, c1], _CFG)
    assert conv.regime == "convective"
    assert strat.regime == "advective"
    assert conv.confidence < strat.confidence


# --- correction (model field + motion) --------------------------------------

def _model():
    lats, lons = _grid()
    field = np.zeros((lats.size, lons.size))
    field[10:20, 10:20] = 0.8          # a model cloud/probability patch
    return field, lats, lons


def test_nowcast_zero_motion_keeps_model():
    field, lats, lons = _model()
    motion = MotionVector(0.0, 0.0, 0.0, "advective", 0.8, "still", 2)
    c = nowcast_correction(field, lats, lons, motion, 1.0, _CFG)
    assert np.array_equal(c.corrected_field, field)
    assert c.displacement_deg == (0.0, 0.0)


def test_nowcast_displacement_is_bounded():
    field, lats, lons = _model()
    fast = MotionVector(100.0, 0.0, 100.0, "advective", 0.8, "fast", 2)  # absurd speed
    c = nowcast_correction(field, lats, lons, fast, 2.0, _CFG)
    mag = (c.displacement_deg[0] ** 2 + c.displacement_deg[1] ** 2) ** 0.5
    assert mag <= _CFG.max_displacement_deg + 1e-9


def test_nowcast_falls_back_to_model_when_no_motion():
    field, lats, lons = _model()
    none = MotionVector(0.0, 0.0, 0.0, "none", 0.0, "insufficient frames", 1)
    c = nowcast_correction(field, lats, lons, none, 1.0, _CFG)
    assert c.source == "model"
    assert np.array_equal(c.corrected_field, field)


def test_nowcast_longer_lead_gives_larger_displacement():
    field, lats, lons = _model()
    motion = MotionVector(1.0, 0.0, 1.0, "advective", 0.8, "slow east", 2)  # 1 deg/hr
    short = nowcast_correction(field, lats, lons, motion, 0.5, _CFG)
    longer = nowcast_correction(field, lats, lons, motion, 1.5, _CFG)
    assert abs(longer.displacement_deg[0]) >= abs(short.displacement_deg[0])


def test_nowcast_higher_confidence_moves_field_more():
    field, lats, lons = _model()
    lo = MotionVector(2.0, 0.0, 2.0, "advective", 0.3, "lo conf", 2)
    hi = MotionVector(2.0, 0.0, 2.0, "advective", 0.9, "hi conf", 2)
    c_lo = nowcast_correction(field, lats, lons, lo, 1.0, _CFG)
    c_hi = nowcast_correction(field, lats, lons, hi, 1.0, _CFG)
    moved_lo = np.abs(c_lo.corrected_field - field).sum()
    moved_hi = np.abs(c_hi.corrected_field - field).sum()
    assert moved_hi > moved_lo


def test_nowcast_corrected_field_stays_in_unit_range():
    field, lats, lons = _model()
    motion = MotionVector(3.0, -2.0, 3.6, "advective", 0.7, "ne", 2)
    c = nowcast_correction(field, lats, lons, motion, 1.5, _CFG)
    assert c.corrected_field.min() >= 0.0
    assert c.corrected_field.max() <= 1.0
    assert isinstance(c, NowcastCorrection)
