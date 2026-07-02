"""Stage C end-to-end with real Himawari data (#84) — integration only.

Verifies the real pipeline shape: two live B13 frames decode, motion
estimation runs, and ``apply_nowcast`` returns a well-formed result. Numeric
outcomes depend on live weather, so only structure is asserted. Skips when
satpy (heavy optional decode dependency) or the network is unavailable.

    PYTHONPATH=. UV_CACHE_DIR=.uv-cache MPLCONFIGDIR=.uv-cache/matplotlib \
        uv run --no-sync python -m pytest -m integration -k nowcast -q
"""
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

pytest.importorskip("satpy", reason="satpy not installed (satellite decode dependency)")

from predictor.nowcast import apply_nowcast  # noqa: E402
from predictor.satellite import Himawari9Source, SatelliteUnavailable  # noqa: E402


@pytest.mark.integration
def test_apply_nowcast_runs_on_live_himawari_frames():
    now = datetime.now(timezone.utc) - timedelta(minutes=30)  # slot certainly published
    lats = np.arange(28.0, 34.01, 0.25)
    lons = np.arange(116.0, 122.01, 0.25)
    prob = np.full((lats.size, lons.size), 0.6)
    times = np.full(prob.shape, np.datetime64(int((now + timedelta(hours=1)).timestamp()), "s"))

    try:
        result = apply_nowcast(prob, lats, lons, times, Himawari9Source(), now=now)
    except SatelliteUnavailable as exc:  # pragma: no cover - network-dependent
        pytest.skip(f"live Himawari unavailable: {exc}")

    assert result.applied in (True, False)
    assert result.corrected_probability.shape == prob.shape
    assert result.corrected_mask.shape == prob.shape
    assert result.reason
    if not result.applied:
        np.testing.assert_array_equal(result.corrected_probability, prob)
    print(
        f"\n[nowcast-integration] applied={result.applied} source={result.source} "
        f"reason={result.reason!r} "
        f"cells={int(result.corrected_mask.sum())}"
    )
