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
