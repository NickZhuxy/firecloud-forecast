from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
import xarray as xr

from predictor.fetch import FakeSource, HRRRSource, WeatherSnapshot, _nearest_grid_index


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


def test_nearest_grid_index_applies_cos_lat_correction():
    """At mid-to-high latitudes, longitudinal distance shrinks by cos(lat).

    Without the correction, naive Euclidean-in-degrees picks the
    latitudinally-closer point; with it, the longitudinally-closer point wins
    because 0.7 deg of longitude at 60 deg N is geographically shorter than
    0.5 deg of latitude.
    """
    # Two candidate grid points relative to query (60.0, 0.0):
    #   A = (60.5, 0.0)  -> Δlat=0.5,  Δlon=0   (d² = 0.25 either way)
    #   B = (60.0, 0.7)  -> Δlat=0,    Δlon=0.7 (d² = 0.49 plain; 0.1225 with cos(60°)=0.5)
    lat_arr = np.array([[60.5, 60.0]])
    lon_arr = np.array([[0.0, 0.7]])

    yi, xi = _nearest_grid_index(lat_arr, lon_arr, lat=60.0, lon=0.0)
    assert (yi, xi) == (0, 1)


def test_nearest_grid_index_at_equator_unchanged():
    """At the equator, cos(0°)=1, so behavior matches the original Euclidean rule."""
    lat_arr = np.array([[0.5, 0.0]])
    lon_arr = np.array([[0.0, 0.7]])

    yi, xi = _nearest_grid_index(lat_arr, lon_arr, lat=0.0, lon=0.0)
    # A=(0.5, 0): d²=0.25 (winner); B=(0, 0.7): d²=0.49
    assert (yi, xi) == (0, 0)


def test_hrrr_source_caches_parsed_datasets_per_run(monkeypatch, tmp_path):
    """Repeated fetches with the same (run_dt, fxx) reuse the parsed datasets.

    Without caching, every fetch() recomputes Herbie.xarray(...), which is the
    slow path the map notebook hammers. The cache key is (run_dt, fxx); query
    lat/lon vary freely between calls.
    """
    cloud_ds = _fake_hrrr_clouds_dataset()
    rh_ds = _fake_hrrr_rh_dataset()
    counts = {"init": 0, "xarray": 0}

    class FakeHerbie:
        def __init__(self, *args, **kwargs):
            counts["init"] += 1

        def xarray(self, search):
            counts["xarray"] += 1
            if "CDC" in search:
                return [cloud_ds]
            return rh_ds

    import herbie
    monkeypatch.setattr(herbie, "Herbie", FakeHerbie)

    src = HRRRSource(cache_dir=tmp_path)
    t = datetime(2026, 5, 20, 18, 0, tzinfo=timezone.utc)

    snap1 = src.fetch(lat=42.36, lon=-71.06, time=t)
    snap2 = src.fetch(lat=44.0, lon=-72.0, time=t)  # different point, same run_dt

    # First call parses (1 cloud search + 1 RH search). Second is a pure cache hit.
    assert counts["init"] == 1
    assert counts["xarray"] == 2
    # Sanity: both calls returned a real snapshot.
    assert isinstance(snap1, WeatherSnapshot)
    assert isinstance(snap2, WeatherSnapshot)


def test_hrrr_source_cache_misses_on_different_run(monkeypatch, tmp_path):
    """A fetch landing on a different run cycle parses afresh."""
    cloud_ds = _fake_hrrr_clouds_dataset()
    rh_ds = _fake_hrrr_rh_dataset()
    counts = {"init": 0, "xarray": 0}

    class FakeHerbie:
        def __init__(self, *args, **kwargs):
            counts["init"] += 1

        def xarray(self, search):
            counts["xarray"] += 1
            if "CDC" in search:
                return [cloud_ds]
            return rh_ds

    import herbie
    monkeypatch.setattr(herbie, "Herbie", FakeHerbie)

    src = HRRRSource(cache_dir=tmp_path)
    t1 = datetime(2026, 5, 20, 18, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 5, 20, 19, 0, tzinfo=timezone.utc)  # different hour -> different run_dt

    src.fetch(lat=42.36, lon=-71.06, time=t1)
    src.fetch(lat=42.36, lon=-71.06, time=t2)

    assert counts["init"] == 2
    assert counts["xarray"] == 4  # 2 clouds + 2 RH


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
