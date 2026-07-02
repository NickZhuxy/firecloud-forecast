"""Stage C nowcast orchestration (#84) — offline, synthetic frames."""
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from predictor.cloud_motion import MotionVector
from predictor.nowcast import DEFAULT_NOWCAST_CONFIG, NowcastStageResult, apply_nowcast
from predictor.satellite import BrightnessTempField, SatelliteUnavailable

_NOW = datetime(2026, 7, 2, 10, 0, tzinfo=timezone.utc)
_LATS = np.array([30.0, 30.25])
_LONS = np.array([118.0, 118.25])


def _times(offset_hr: float) -> np.ndarray:
    t = np.datetime64(int((_NOW + timedelta(hours=offset_hr)).timestamp()), "s")
    return np.full((2, 2), t)


class _RecordingSat:
    def __init__(self, frames=None, exc=None):
        self.frames, self.exc, self.calls = list(frames or []), exc, []

    def fetch_brightness_temp(self, valid_time, bbox=None, band="B13"):
        self.calls.append(valid_time)
        if self.exc is not None:
            raise self.exc
        return self.frames.pop(0)


def _prob():
    return np.full((2, 2), 0.6)


def test_no_eligible_cells_skips_satellite_entirely():
    sat = _RecordingSat()
    res = apply_nowcast(_prob(), _LATS, _LONS, _times(5.0), sat, now=_NOW)
    assert res.applied is False and res.source == "model"
    assert sat.calls == []                       # 门在取数之前
    np.testing.assert_array_equal(res.corrected_probability, _prob())
    assert not res.corrected_mask.any()


def test_past_events_are_not_eligible():
    sat = _RecordingSat()
    res = apply_nowcast(_prob(), _LATS, _LONS, _times(-0.5), sat, now=_NOW)
    assert res.applied is False and sat.calls == []


def test_disabled_config_skips_everything():
    from predictor.nowcast import NowcastStageConfig

    sat = _RecordingSat()
    res = apply_nowcast(
        _prob(), _LATS, _LONS, _times(1.0), sat, now=_NOW,
        config=NowcastStageConfig(enabled=False),
    )
    assert res.applied is False and sat.calls == []


def test_satellite_failure_passes_through_safely():
    sat = _RecordingSat(exc=SatelliteUnavailable("himawari down"))
    res = apply_nowcast(_prob(), _LATS, _LONS, _times(1.0), sat, now=_NOW)
    assert res.applied is False
    assert "himawari down" in res.reason
    np.testing.assert_array_equal(res.corrected_probability, _prob())


def test_regime_none_passes_through():
    frame = BrightnessTempField(
        lats=_LATS, lons=_LONS, brightness_temp_k=np.full((2, 2), 290.0),
        observation_time=_NOW, band="B13", source_label="t", retrieved_at=_NOW,
    )
    warm2 = BrightnessTempField(
        lats=_LATS, lons=_LONS, brightness_temp_k=np.full((2, 2), 290.0),
        observation_time=_NOW - timedelta(minutes=10), band="B13",
        source_label="t", retrieved_at=_NOW,
    )
    sat = _RecordingSat(frames=[warm2, frame])   # 全暖 → 无云掩膜 → regime none
    res = apply_nowcast(_prob(), _LATS, _LONS, _times(1.0), sat, now=_NOW)
    assert res.applied is False
    assert len(sat.calls) == 2                    # 确实取了 2 帧
    np.testing.assert_array_equal(res.corrected_probability, _prob())


# ---- Task 2: banded correction, ascending lats, edge guard ----


def _shifted_frames():
    lats = np.arange(28.0, 31.0, 0.25)
    lons = np.arange(116.0, 119.0, 0.25)
    ny, nx = lats.size, lons.size
    warm, cold = 290.0, 250.0
    # 双向有界的云块——竖直通条会让互相关在垂直方向简并(任意 dy 等价)。
    bt0 = np.full((ny, nx), warm); bt0[4:9, 4:7] = cold
    bt1 = np.full((ny, nx), warm); bt1[4:9, 5:8] = cold
    t0 = _NOW - timedelta(minutes=10)

    def mk(bt, t):
        return BrightnessTempField(
            lats=lats, lons=lons, brightness_temp_k=bt,
            observation_time=t, band="B13", source_label="t", retrieved_at=_NOW,
        )

    return lats, lons, mk(bt0, t0), mk(bt1, _NOW)


def _grid_times(shape, offset_hr):
    t = np.datetime64(int((_NOW + timedelta(hours=offset_hr)).timestamp()), "s")
    return np.full(shape, t)


def test_correction_nudges_toward_advected_position():
    lats, lons, f0, f1 = _shifted_frames()
    prob = np.zeros((lats.size, lons.size)); prob[:, 5] = 1.0
    times = _grid_times(prob.shape, 1.0)
    sat = _RecordingSat(frames=[f0, f1])
    res = apply_nowcast(prob, lats, lons, times, sat, now=_NOW)

    assert res.applied is True and res.source == "satellite"
    assert res.motion.regime == "advective"
    # 东移 1.5°/hr × 1h(受 2° 上限内)→ dcol=+6;混合权 = confidence。
    advected = np.roll(prob, 6, axis=1)
    expected = prob + res.motion.confidence * (advected - prob)
    inner = np.s_[:, 6:]                          # 西侧 6 列是回卷条带,另测
    np.testing.assert_allclose(res.corrected_probability[inner], expected[inner])
    assert res.corrected_mask[:, 6:].any()
    assert res.lead_hr_range == (1.0, 1.0)


def test_wrapped_edge_strip_reverts_to_model():
    lats, lons, f0, f1 = _shifted_frames()
    prob = np.full((lats.size, lons.size), 0.7)
    times = _grid_times(prob.shape, 1.0)
    res = apply_nowcast(prob, lats, lons, times, _RecordingSat(frames=[f0, f1]), now=_NOW)
    # 东移 dcol=+6 → 西侧 6 列是回卷数据:还原为模式值且不进 mask。
    np.testing.assert_array_equal(res.corrected_probability[:, :6], prob[:, :6])
    assert not res.corrected_mask[:, :6].any()


def test_only_eligible_band_cells_change():
    lats, lons, f0, f1 = _shifted_frames()
    prob = np.full((lats.size, lons.size), 0.7)
    times = _grid_times(prob.shape, 5.0)          # 默认全部窗口外
    near = np.datetime64(int((_NOW + timedelta(hours=1)).timestamp()), "s")
    times[:, :6] = near                            # 只有西半有资格
    res = apply_nowcast(prob, lats, lons, times, _RecordingSat(frames=[f0, f1]), now=_NOW)
    assert not res.corrected_mask[:, 6:].any()     # 窗口外的格子不动
    np.testing.assert_array_equal(res.corrected_probability[:, 6:], prob[:, 6:])


def test_ascending_latitude_direction_is_correct():
    # 北移帧(dv>0);升序 lats 下订正必须把场向北(行号增大)搬。
    lats = np.arange(28.0, 31.0, 0.25)
    lons = np.arange(116.0, 119.0, 0.25)
    ny, nx = lats.size, lons.size
    bt0 = np.full((ny, nx), 290.0); bt0[4:7, 4:9] = 250.0
    bt1 = np.full((ny, nx), 290.0); bt1[5:8, 4:9] = 250.0
    t0 = _NOW - timedelta(minutes=10)
    f0 = BrightnessTempField(lats=lats, lons=lons, brightness_temp_k=bt0,
                             observation_time=t0, band="B13", source_label="t",
                             retrieved_at=_NOW)
    f1 = BrightnessTempField(lats=lats, lons=lons, brightness_temp_k=bt1,
                             observation_time=_NOW, band="B13", source_label="t",
                             retrieved_at=_NOW)
    prob = np.zeros((ny, nx)); prob[5, :] = 1.0
    times = _grid_times(prob.shape, 1.0)
    res = apply_nowcast(prob, lats, lons, times, _RecordingSat(frames=[f0, f1]), now=_NOW)
    assert res.applied
    j = 5 + 6                                     # 北移 6 行
    assert res.corrected_probability[j, :].mean() > prob[j, :].mean()
