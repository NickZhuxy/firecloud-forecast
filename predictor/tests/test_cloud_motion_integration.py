"""Live Himawari-9 motion nowcast — the real example for #16.

Excluded from the default run (downloads two full-disk frames, needs the
``satpy`` extra). Run with:  uv run pytest -m integration -k motion

Uses two consecutive Shanghai-sunset slots from spike #14: 2026-06-22 10:50 & 11:00 UTC.
"""
from datetime import datetime, timezone

import numpy as np
import pytest

from predictor.cloud_motion import estimate_motion, nowcast_correction
from predictor.satellite import Himawari9Source

_SHANGHAI = (31.23, 121.47)
_BBOX = (29.5, 33.0, 119.5, 123.0)   # small box → fast resample
_T0 = datetime(2026, 6, 22, 10, 50, tzinfo=timezone.utc)
_T1 = datetime(2026, 6, 22, 11, 0, tzinfo=timezone.utc)


@pytest.mark.integration
def test_real_himawari_consecutive_frames_estimate_motion():
    src = Himawari9Source()
    f0 = src.fetch_brightness_temp(_T0, bbox=_BBOX)
    f1 = src.fetch_brightness_temp(_T1, bbox=_BBOX)
    assert f0.brightness_temp_k.shape == f1.brightness_temp_k.shape

    motion = estimate_motion([f0, f1])
    assert motion.regime in {"advective", "convective", "none"}
    assert np.isfinite(motion.speed_deg_per_hr)
    assert 0.0 <= motion.confidence <= 1.0
    # A 10-min IR drift over Shanghai is physically bounded (well under ~30 deg/hr).
    assert motion.speed_deg_per_hr < 30.0

    # The real motion drives a bounded correction of a synthetic model field.
    lats = f1.lats
    lons = f1.lons
    model = np.zeros((lats.size, lons.size))
    model[lats.size // 3 : 2 * lats.size // 3, lons.size // 3 : 2 * lons.size // 3] = 0.7
    c = nowcast_correction(model, lats, lons, motion, lead_time_hr=1.0)
    assert c.corrected_field.shape == model.shape
    assert c.corrected_field.min() >= 0.0 and c.corrected_field.max() <= 1.0
    mag = float(np.hypot(*c.displacement_deg))
    assert mag <= 2.0 + 1e-9          # bounded by max_displacement_deg
