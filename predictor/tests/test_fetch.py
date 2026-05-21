from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
import xarray as xr

from predictor.fetch import FakeSource, HRRRSource, WeatherSnapshot


def _fake_hrrr_clouds_dataset(lat_target=42.36, lon_target=-71.06):
    """Build a tiny 3x3 xarray Dataset shaped like a HRRR cloud-cover slice.

    cfgrib uses shortnames: hcc (high), mcc (middle), lcc (low).
    """
    # Build a 3x3 grid centered on target with ~0.05 deg spacing
    lats = np.array([[lat_target + dy for _ in range(3)] for dy in [-0.05, 0.0, 0.05]])
    lons = np.array([[lon_target + dx for dx in [-0.05, 0.0, 0.05]] for _ in range(3)])
    hcc = np.array([[10, 20, 30], [40, 55, 60], [50, 50, 50]], dtype=float)
    mcc = np.array([[20, 30, 40], [50, 65, 70], [60, 60, 60]], dtype=float)
    lcc = np.array([[5, 8, 10], [12, 15, 20], [18, 22, 25]], dtype=float)
    return xr.Dataset(
        data_vars={
            "hcc": (("y", "x"), hcc),
            "mcc": (("y", "x"), mcc),
            "lcc": (("y", "x"), lcc),
        },
        coords={
            "latitude": (("y", "x"), lats),
            "longitude": (("y", "x"), lons),
        },
    )


def _fake_hrrr_rh_dataset(lat_target=42.36, lon_target=-71.06):
    lats = np.array([[lat_target + dy for _ in range(3)] for dy in [-0.05, 0.0, 0.05]])
    lons = np.array([[lon_target + dx for dx in [-0.05, 0.0, 0.05]] for _ in range(3)])
    rh = np.array([[50, 55, 60], [55, 62, 65], [60, 65, 70]], dtype=float)
    return xr.Dataset(
        data_vars={"r2": (("y", "x"), rh)},  # cfgrib often names 2m RH 'r2'
        coords={
            "latitude": (("y", "x"), lats),
            "longitude": (("y", "x"), lons),
        },
    )


def test_snapshot_from_datasets_picks_nearest_grid_point():
    clouds = _fake_hrrr_clouds_dataset()
    rh = _fake_hrrr_rh_dataset()
    snap = HRRRSource._snapshot_from_datasets(
        ds_clouds=clouds,
        ds_rh=rh,
        lat=42.36, lon=-71.06,
        run_label="hrrr@2026-05-20T18:00Z+f06",
        retrieved_at=datetime(2026, 5, 20, 18, 30, tzinfo=timezone.utc),
    )
    # Center grid point is the nearest; values should match the [1,1] cells.
    assert snap.cloud_high_pct == 55.0
    assert snap.cloud_mid_pct == 65.0
    assert snap.cloud_low_pct == 15.0
    assert snap.humidity_pct == 62.0
    assert snap.source_label == "hrrr@2026-05-20T18:00Z+f06"


def test_weather_snapshot_fields():
    s = WeatherSnapshot(
        cloud_low_pct=20.0, cloud_mid_pct=40.0, cloud_high_pct=30.0,
        humidity_pct=55.0, source_label="fake", retrieved_at=datetime(2026, 5, 20, tzinfo=timezone.utc),
    )
    assert s.cloud_low_pct == 20.0
    d = s.to_dict()
    assert d["cloud_mid_pct"] == 40.0
    assert d["source_label"] == "fake"


def test_fake_source_returns_canned_snapshot():
    canned = WeatherSnapshot(
        cloud_low_pct=10, cloud_mid_pct=50, cloud_high_pct=40,
        humidity_pct=60, source_label="fake",
        retrieved_at=datetime(2026, 5, 20, tzinfo=timezone.utc),
    )
    src = FakeSource(canned)
    got = src.fetch(lat=42.36, lon=-71.06, time=datetime(2026, 5, 20, 23, 0, tzinfo=timezone.utc))
    assert got is canned


@pytest.mark.integration
def test_hrrr_source_real_fetch_for_boston(tmp_path):
    """Hits the network (AWS S3). Run manually with: pytest -m integration."""
    src = HRRRSource(cache_dir=tmp_path)
    # Pick a recent past time (HRRR keeps several days online).
    t = datetime.now(timezone.utc) - timedelta(hours=3)
    snap = src.fetch(lat=42.36, lon=-71.06, time=t)
    assert 0 <= snap.cloud_low_pct <= 100
    assert 0 <= snap.cloud_mid_pct <= 100
    assert 0 <= snap.cloud_high_pct <= 100
    assert 0 <= snap.humidity_pct <= 100
    assert snap.source_label.startswith("hrrr@")
