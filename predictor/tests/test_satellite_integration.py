"""Live Himawari-9 IR sample — the real example required by #15 (AC 5).

Excluded from the default run (downloads ~tens of MB and needs the ``satpy``
extra). Run explicitly with:  uv run pytest -m integration -k himawari

Uses the Shanghai sunset slot verified in spike #14: 2026-06-22 11:00 UTC.
"""
from datetime import datetime, timezone

import numpy as np
import pytest

from predictor.cloud_top import colocate_and_correct
from predictor.profiles import NormalizedProfile
from predictor.satellite import Himawari9Source

_SHANGHAI = (31.23, 121.47)
_SLOT = datetime(2026, 6, 22, 11, 0, tzinfo=timezone.utc)


def _wide_profile() -> NormalizedProfile:
    """A synthetic column warm at the surface and cold aloft, so any physical IR
    window brightness temperature lands on a real crossing."""
    h = np.array([0.0, 1000, 2000, 4000, 6000, 8000, 10000, 12000, 14000])
    t = np.array([305.0, 298, 291, 277, 263, 249, 234, 220, 210])
    n = h.size
    return NormalizedProfile(
        lat=_SHANGHAI[0], lon=_SHANGHAI[1],
        pressure_hpa=np.linspace(1000, 150, n),
        geometric_height_m=h, geopotential_height_m=h, temperature_k=t,
        relative_humidity_pct=np.full(n, 60.0), dewpoint_k=t - 5,
        specific_humidity_kg_kg=np.full(n, 0.004),
        u_wind_m_s=np.zeros(n), v_wind_m_s=np.zeros(n), vertical_velocity_pa_s=np.zeros(n),
        cloud_water_kg_kg=np.full(n, np.nan), cloud_ice_kg_kg=np.full(n, np.nan),
        run_time=_SLOT, valid_time=_SLOT, source_label="synthetic",
        retrieved_at=_SLOT, missing=[],
    )


@pytest.mark.integration
def test_real_himawari_shanghai_sunset_retrieves_a_cloud_top():
    src = Himawari9Source()
    bbox = (29.5, 33.0, 119.5, 123.0)  # small box around Shanghai → fast resample
    field = src.fetch_brightness_temp(_SLOT, bbox=bbox)

    assert field.band == "B13"
    assert field.observation_time == _SLOT
    assert "himawari9@" in field.source_label

    tb = field.sample(*_SHANGHAI)
    # IR window brightness temperatures over land/cloud sit in this physical band.
    assert np.isfinite(tb)
    assert 180.0 < tb < 320.0

    # The real pixel drives the co-location/correction end to end. With the wide
    # synthetic column any physical Tb resolves to a finite satellite-corrected top.
    c = colocate_and_correct(tb, field.observation_time, _SLOT, 8000.0, _wide_profile())
    assert c.source == "satellite"
    assert np.isfinite(c.corrected_top_m)
    assert 0.0 <= c.confidence <= 1.0
