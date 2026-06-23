"""Unit tests for GFS étage cloud cover (#35) — no network."""
from datetime import datetime, timezone

import numpy as np
import pytest
import xarray as xr

from predictor.gfs import EtageCloudCover, GFSSource, GFSUnavailable


def _cover_ds(drop: tuple[str, ...] = ()) -> xr.Dataset:
    lats = [40.0, 30.0, 20.0]
    lons = [118.0, 120.0, 122.0]
    dims = ("latitude", "longitude")
    fields = {"lcc": 10.0, "mcc": 50.0, "hcc": 80.0}
    data = {
        s: (dims, np.full((3, 3), v)) for s, v in fields.items() if s not in drop
    }
    return xr.Dataset(data, coords={"latitude": lats, "longitude": lons})


def test_cover_from_dataset_reads_three_tiers():
    cover = GFSSource._cover_from_dataset(_cover_ds(), lat=30.0, lon=120.0)
    assert isinstance(cover, EtageCloudCover)
    assert (cover.low_pct, cover.mid_pct, cover.high_pct) == (10.0, 50.0, 80.0)


def test_cover_missing_tier_defaults_to_zero():
    cover = GFSSource._cover_from_dataset(_cover_ds(drop=("hcc",)), lat=30.0, lon=120.0)
    assert cover.high_pct == 0.0
    assert cover.mid_pct == 50.0


def test_all_tiers_absent_raises_for_safe_fallback():
    # A shortname/parse mismatch (no lcc/mcc/hcc) must raise, not silently 0% —
    # the caller then falls back to Open-Meteo instead of wrongly zeroing gates.
    empty = xr.Dataset(coords={"latitude": [30.0], "longitude": [120.0]})
    with pytest.raises(GFSUnavailable):
        GFSSource._cover_from_dataset(empty, lat=30.0, lon=120.0)


def test_for_tier_maps_names():
    cover = EtageCloudCover(low_pct=10.0, mid_pct=50.0, high_pct=80.0)
    assert cover.for_tier("low") == 10.0
    assert cover.for_tier("mid") == 50.0
    assert cover.for_tier("high") == 80.0


def test_fetch_cloud_cover_uses_cache(monkeypatch):
    src = GFSSource(cache_dir="/tmp/gfs-cover-test")
    calls = {"n": 0}

    def fake_download(run_dt, fxx):
        calls["n"] += 1
        return _cover_ds()

    monkeypatch.setattr(src, "_download_cover", fake_download)
    vt = datetime(2026, 6, 23, 6, tzinfo=timezone.utc)
    a = src.fetch_cloud_cover(30.0, 120.0, vt)
    b = src.fetch_cloud_cover(30.5, 120.5, vt)  # same cycle, nearby point
    assert calls["n"] == 1
    assert a.high_pct == b.high_pct == 80.0
