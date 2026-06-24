"""Unit tests for the GFS surface-grid reader (#19) — no network."""
from datetime import datetime, timezone

import numpy as np
import pytest
import xarray as xr

from predictor.gfs import GFSSource, GFSUnavailable, SurfaceGrid

_T0 = datetime(2026, 6, 23, 0, tzinfo=timezone.utc)
_T6 = datetime(2026, 6, 23, 6, tzinfo=timezone.utc)


def _surface_ds(drop: tuple[str, ...] = ()) -> xr.Dataset:
    lats = [40.0, 30.0, 20.0]
    lons = [118.0, 120.0, 122.0]
    dims = ("latitude", "longitude")
    base = np.arange(9).reshape(3, 3).astype(float)
    fields = {
        "lcc": base + 10, "mcc": base + 20, "hcc": base + 30,
        "r2": base + 50, "vis": (base + 1) * 5000,
    }
    data = {k: (dims, v) for k, v in fields.items() if k not in drop}
    return xr.Dataset(data, coords={"latitude": lats, "longitude": lons})


def test_surface_grid_crops_bbox_and_maps_fields():
    grid = GFSSource._surface_grid_from_dataset(
        _surface_ds(), bbox=(25.0, 35.0, 119.0, 121.0),
        run_time=_T0, valid_time=_T6, source_label="gfs@test",
    )
    assert isinstance(grid, SurfaceGrid)
    assert grid.lats.tolist() == [30.0]            # only the 30 N row
    assert grid.lons.tolist() == [120.0]           # only the 120 E column
    assert grid.cloud_low_pct.shape == (1, 1)
    assert grid.n_points == 1
    # 30 N / 120 E is row 1, col 1 → base value 4 → lcc 14, mcc 24, hcc 34, r2 54.
    assert grid.cloud_low_pct[0, 0] == 14.0
    assert grid.cloud_high_pct[0, 0] == 34.0
    assert grid.humidity_pct[0, 0] == 54.0
    assert grid.missing == []


def test_surface_grid_full_region_shape():
    grid = GFSSource._surface_grid_from_dataset(
        _surface_ds(), bbox=(15.0, 45.0, 117.0, 123.0),
        run_time=_T0, valid_time=_T6, source_label="gfs@test",
    )
    assert grid.cloud_mid_pct.shape == (3, 3)
    assert grid.visibility_m.shape == (3, 3)


def test_missing_field_defaults_and_recorded():
    grid = GFSSource._surface_grid_from_dataset(
        _surface_ds(drop=("vis", "r2")), bbox=(15.0, 45.0, 117.0, 123.0),
        run_time=_T0, valid_time=_T6, source_label="gfs@test",
    )
    assert "vis" in grid.missing and "r2" in grid.missing
    assert np.isnan(grid.visibility_m).all()
    assert np.isnan(grid.humidity_pct).all()
    # Cover present → real values, not defaults.
    assert not np.isnan(grid.cloud_low_pct).any()


def test_all_cover_absent_raises():
    # A cover shortname mismatch must degrade loudly, not render a blank map.
    with pytest.raises(GFSUnavailable):
        GFSSource._surface_grid_from_dataset(
            _surface_ds(drop=("lcc", "mcc", "hcc")), bbox=(15.0, 45.0, 117.0, 123.0),
            run_time=_T0, valid_time=_T6, source_label="gfs@test",
        )


def test_empty_crop_raises():
    with pytest.raises(GFSUnavailable):
        GFSSource._surface_grid_from_dataset(
            _surface_ds(), bbox=(60.0, 70.0, 117.0, 123.0),  # no rows in 60–70 N
            run_time=_T0, valid_time=_T6, source_label="gfs@test",
        )


def test_residual_level_dim_is_collapsed():
    # cfgrib may keep a size-1 level dim (e.g. heightAboveGround on RH); the
    # crop must still yield a 2-D (lat, lon) field.
    ds = _surface_ds()
    r2 = ds["r2"].expand_dims({"heightAboveGround": [2.0]})
    ds = ds.drop_vars("r2").assign(r2=r2)
    grid = GFSSource._surface_grid_from_dataset(
        ds, bbox=(15.0, 45.0, 117.0, 123.0),
        run_time=_T0, valid_time=_T6, source_label="gfs@test",
    )
    assert grid.humidity_pct.shape == (3, 3)


def test_fetch_surface_grid_uses_cache(monkeypatch):
    src = GFSSource(cache_dir="/tmp/gfs-surface-test")
    calls = {"n": 0}

    def fake_download(run_dt, fxx):
        calls["n"] += 1
        return _surface_ds()

    monkeypatch.setattr(src, "_download_surface", fake_download)
    bbox = (15.0, 45.0, 117.0, 123.0)
    a = src.fetch_surface_grid(bbox, _T6)
    b = src.fetch_surface_grid(bbox, _T6)
    assert calls["n"] == 1
    assert a.cloud_mid_pct.shape == b.cloud_mid_pct.shape
