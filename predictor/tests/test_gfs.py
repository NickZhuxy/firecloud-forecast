"""Unit tests for GFSSource (no network — synthetic xarray + monkeypatch)."""
from datetime import datetime, timezone

import numpy as np
import pytest
import xarray as xr

from predictor.gfs import GFSUnavailable, GFSSource


def _synthetic_gfs_ds(drop: tuple[str, ...] = ()) -> xr.Dataset:
    """Mimic a merged GFS pressure-level dataset (isobaricInhPa, lat, lon)."""
    levels = [850.0, 700.0, 500.0]
    lats = [40.0, 30.0, 20.0]   # descending, like GFS global grids
    lons = [118.0, 120.0, 122.0]
    dims = ("isobaricInhPa", "latitude", "longitude")
    shape = (len(levels), len(lats), len(lons))
    shorts = ["t", "r", "q", "gh", "u", "v", "w", "clwmr", "icmr"]
    data = {
        s: (dims, np.arange(np.prod(shape)).reshape(shape).astype(float))
        for s in shorts
        if s not in drop
    }
    return xr.Dataset(
        data,
        coords={"isobaricInhPa": levels, "latitude": lats, "longitude": lons},
    )


def test_select_cycle_picks_recent_6h_cycle_and_nearest_fxx():
    src = GFSSource(cache_dir="/tmp/gfs-test")
    run_dt, fxx = src._select_cycle(datetime(2026, 6, 23, 6, 0, tzinfo=timezone.utc))
    # valid 06:00Z, 4h lag → available cycles end at 02:00 → latest is 00Z, fxx=6.
    assert run_dt == datetime(2026, 6, 23, 0, 0, tzinfo=timezone.utc)
    assert fxx == 6


def test_select_cycle_uses_06z_when_lagged_window_allows():
    src = GFSSource(cache_dir="/tmp/gfs-test")
    run_dt, fxx = src._select_cycle(datetime(2026, 6, 23, 10, 30, tzinfo=timezone.utc))
    assert run_dt == datetime(2026, 6, 23, 6, 0, tzinfo=timezone.utc)
    assert fxx in (4, 5)


def test_cube_from_datasets_crops_bbox_and_maps_vars():
    src = GFSSource(cache_dir="/tmp/gfs-test")
    ds = _synthetic_gfs_ds()
    cube = src._cube_from_datasets(
        ds, bbox=(25.0, 35.0, 119.0, 121.0), levels=GFSSource.DEFAULT_LEVELS_HPA,
        run_time=datetime(2026, 6, 23, 0, tzinfo=timezone.utc),
        valid_time=datetime(2026, 6, 23, 6, tzinfo=timezone.utc),
        source_label="gfs@2026-06-23T00Z+f06",
        retrieved_at=datetime(2026, 6, 23, 5, tzinfo=timezone.utc),
    )
    # bbox keeps lat 30 (idx 1) and lon 120 (idx 1) only.
    assert cube.lats.tolist() == [30.0]
    assert cube.lons.tolist() == [120.0]
    # Only the 3 requested-and-present levels survive, ordered descending.
    assert cube.levels_hpa.tolist() == [850.0, 700.0, 500.0]
    assert cube.temperature_k.shape == (3, 1, 1)
    assert cube.missing == []


def test_cube_from_datasets_records_missing_variable_as_nan():
    src = GFSSource(cache_dir="/tmp/gfs-test")
    ds = _synthetic_gfs_ds(drop=("icmr",))
    cube = src._cube_from_datasets(
        ds, bbox=(15.0, 45.0, 117.0, 123.0), levels=GFSSource.DEFAULT_LEVELS_HPA,
        run_time=datetime(2026, 6, 23, 0, tzinfo=timezone.utc),
        valid_time=datetime(2026, 6, 23, 6, tzinfo=timezone.utc),
        source_label="gfs@2026-06-23T00Z+f06",
        retrieved_at=datetime(2026, 6, 23, 5, tzinfo=timezone.utc),
    )
    assert "cloud_ice_kg_kg" in cube.missing
    assert np.isnan(cube.cloud_ice_kg_kg).all()
    # A present variable is untouched.
    assert not np.isnan(cube.temperature_k).any()


def test_cube_from_datasets_treats_sparse_field_levels_as_missing():
    src = GFSSource(cache_dir="/tmp/gfs-test")
    base = _synthetic_gfs_ds(drop=("icmr",))
    dims = ("isobaricInhPa", "latitude", "longitude")
    sparse_ice = xr.Dataset(
        {"icmr": (dims, np.ones((1, 3, 3), dtype=float))},
        coords={
            "isobaricInhPa": [50.0],
            "latitude": [40.0, 30.0, 20.0],
            "longitude": [118.0, 120.0, 122.0],
        },
    )
    ds = xr.merge([base, sparse_ice], compat="override", join="outer")

    cube = src._cube_from_datasets(
        ds, bbox=(15.0, 45.0, 117.0, 123.0), levels=GFSSource.DEFAULT_LEVELS_HPA,
        run_time=datetime(2026, 6, 23, 0, tzinfo=timezone.utc),
        valid_time=datetime(2026, 6, 23, 6, tzinfo=timezone.utc),
        source_label="gfs@2026-06-23T00Z+f06",
        retrieved_at=datetime(2026, 6, 23, 5, tzinfo=timezone.utc),
    )

    assert cube.levels_hpa.tolist() == [850.0, 700.0, 500.0]
    assert np.isnan(cube.cloud_ice_kg_kg).all()
    assert "cloud_ice_kg_kg" in cube.missing
    assert not np.isnan(cube.temperature_k).any()


def test_cube_from_datasets_accepts_clmr_cloud_water_alias():
    src = GFSSource(cache_dir="/tmp/gfs-test")
    ds = _synthetic_gfs_ds(drop=("clwmr",)).assign(
        clmr=_synthetic_gfs_ds()["clwmr"] + 1000.0
    )

    cube = src._cube_from_datasets(
        ds, bbox=(15.0, 45.0, 117.0, 123.0), levels=GFSSource.DEFAULT_LEVELS_HPA,
        run_time=datetime(2026, 6, 23, 0, tzinfo=timezone.utc),
        valid_time=datetime(2026, 6, 23, 6, tzinfo=timezone.utc),
        source_label="gfs@2026-06-23T00Z+f06",
        retrieved_at=datetime(2026, 6, 23, 5, tzinfo=timezone.utc),
    )

    assert "cloud_water_kg_kg" not in cube.missing
    assert np.nanmin(cube.cloud_water_kg_kg) >= 1000.0


def test_fetch_profile_uses_dataset_cache(monkeypatch):
    src = GFSSource(cache_dir="/tmp/gfs-test")
    calls = {"n": 0}

    def fake_download(run_dt, fxx):
        calls["n"] += 1
        return _synthetic_gfs_ds()

    monkeypatch.setattr(src, "_download_dataset", fake_download)
    vt = datetime(2026, 6, 23, 6, tzinfo=timezone.utc)
    p1 = src.fetch_profile(30.0, 120.0, vt)
    p2 = src.fetch_profile(30.0, 120.0, vt)
    assert calls["n"] == 1            # same cycle → downloaded/parsed once
    assert p1.lat == p2.lat == 30.0
    assert p1.temperature_k.shape == (3,)


def test_fetch_cube_falls_back_to_previous_cycle(monkeypatch):
    src = GFSSource(cache_dir="/tmp/gfs-test")
    first_run, _ = src._select_cycle(datetime(2026, 6, 23, 6, tzinfo=timezone.utc))

    def fake_download(run_dt, fxx):
        if run_dt == first_run:
            raise RuntimeError("cycle not published yet")
        return _synthetic_gfs_ds()

    monkeypatch.setattr(src, "_download_dataset", fake_download)
    cube = src.fetch_cube(
        (15.0, 45.0, 117.0, 123.0), datetime(2026, 6, 23, 6, tzinfo=timezone.utc)
    )
    # Fell back one cycle (6h earlier) and bumped the forecast hour by 6.
    assert cube.run_time < first_run
    assert "+f12" in cube.source_label


def test_fetch_cube_retries_transient_download_then_succeeds(monkeypatch, tmp_path):
    src = GFSSource(cache_dir=tmp_path)
    src.SURFACE_RETRY_BACKOFF_S = 0.0
    attempts = {"n": 0}

    def flaky_download(run_dt, fxx):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError(
                "Processing failed: ('Connection aborted.', "
                "ConnectionResetError(54, 'Connection reset by peer'))"
            )
        return _synthetic_gfs_ds()

    monkeypatch.setattr(src, "_download_dataset", flaky_download)
    cube = src.fetch_cube(
        (15.0, 45.0, 117.0, 123.0),
        datetime(2026, 6, 23, 6, tzinfo=timezone.utc),
    )
    assert attempts["n"] == 3
    assert cube.temperature_k.shape == (3, 3, 3)


def test_download_paths_use_distinct_herbie_cache_namespaces(monkeypatch, tmp_path):
    src = GFSSource(cache_dir=tmp_path)
    calls = []

    class FakeHerbie:
        def xarray(self, search):
            return _synthetic_gfs_ds()

        def download(self, search):
            return None

    def fake_herbie(run_dt, fxx, *, cache_namespace):
        calls.append(cache_namespace)
        return FakeHerbie()

    monkeypatch.setattr(src, "_herbie", fake_herbie)
    run_dt = datetime(2026, 6, 23, 0, tzinfo=timezone.utc)
    src._download_dataset(run_dt, 6)
    src._download_cover(run_dt, 6)
    src._download_surface(run_dt, 6)
    src._prefetch_surface(run_dt, 6)

    assert calls == ["pressure", "cover", "surface", "surface"]


def test_fetch_raises_gfs_unavailable_after_retries(monkeypatch):
    src = GFSSource(cache_dir="/tmp/gfs-test")

    def always_fail(run_dt, fxx):
        raise RuntimeError("down")

    monkeypatch.setattr(src, "_download_dataset", always_fail)
    with pytest.raises(GFSUnavailable):
        src.fetch_profile(30.0, 120.0, datetime(2026, 6, 23, 6, tzinfo=timezone.utc))
