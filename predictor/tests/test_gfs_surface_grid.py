"""Unit tests for the GFS surface-grid reader (#19) — no network."""
from datetime import datetime, timezone

import numpy as np
import pandas as pd
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


def test_batch_surface_grids_use_one_common_model_run(monkeypatch, tmp_path):
    src = GFSSource(cache_dir=tmp_path)
    prefetched, parsed = [], []

    def fake_prefetch(run_dt, fxx):
        prefetched.append((run_dt, fxx))

    def fake_download(run_dt, fxx):
        parsed.append((run_dt, fxx))
        return _surface_ds()

    monkeypatch.setattr(src, "_prefetch_surface", fake_prefetch)
    monkeypatch.setattr(src, "_download_surface", fake_download)
    valid_times = (
        datetime(2026, 6, 23, 8, tzinfo=timezone.utc),
        datetime(2026, 6, 23, 10, tzinfo=timezone.utc),
    )

    grids = src.fetch_surface_grids(
        (15.0, 45.0, 117.0, 123.0), valid_times
    )

    common = datetime(2026, 6, 23, 0, tzinfo=timezone.utc)
    # Per-time selection would choose 00Z for 08Z and 06Z for 10Z. The batch pins
    # both forecast hours to 00Z. Network prefetch runs in parallel (order not
    # guaranteed); the parse is serial.
    assert sorted(prefetched) == [(common, 8), (common, 10)]
    assert sorted(parsed) == [(common, 8), (common, 10)]
    assert {grid.run_time for grid in grids} == {common}


def test_surface_download_retries_transient_then_succeeds(monkeypatch, tmp_path):
    src = GFSSource(cache_dir=tmp_path)
    src.SURFACE_RETRY_BACKOFF_S = 0.0   # no sleeping in the test
    attempts = {"n": 0}

    def flaky_download(run_dt, fxx):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("Processing failed: HTTPSConnectionPool(...): Read timed out.")
        return _surface_ds()

    monkeypatch.setattr(src, "_download_surface", flaky_download)
    grid = src.fetch_surface_grid((15.0, 45.0, 117.0, 123.0), _T6)
    assert attempts["n"] == 3                 # retried the two transient timeouts
    assert grid.cloud_low_pct.shape[0] > 0


def test_surface_download_does_not_retry_non_transient(monkeypatch, tmp_path):
    src = GFSSource(cache_dir=tmp_path)
    src.SURFACE_RETRY_BACKOFF_S = 0.0
    attempts = {"n": 0}

    def missing(run_dt, fxx):
        attempts["n"] += 1
        raise FileNotFoundError("cycle not published")

    monkeypatch.setattr(src, "_download_surface", missing)
    with pytest.raises(GFSUnavailable):       # a real 404 is not retried; falls through
        src.fetch_surface_grid((15.0, 45.0, 117.0, 123.0), _T6)
    # one attempt per cycle tried (no per-hour retry), across the fallback cycles
    assert attempts["n"] == src.MAX_CYCLE_FALLBACK + 1


def test_surface_parallel_prefetch_retries_transient(monkeypatch, tmp_path):
    src = GFSSource(cache_dir=tmp_path)
    src.SURFACE_RETRY_BACKOFF_S = 0.0
    attempts: dict[int, int] = {}

    def flaky_prefetch(run_dt, fxx):
        attempts[fxx] = attempts.get(fxx, 0) + 1
        if attempts[fxx] < 2:                 # one transient timeout per hour
            raise RuntimeError("Processing failed: HTTPSConnectionPool(...): Read timed out.")

    monkeypatch.setattr(src, "_prefetch_surface", flaky_prefetch)
    monkeypatch.setattr(src, "_download_surface", lambda run_dt, fxx: _surface_ds())
    valid_times = (
        datetime(2026, 6, 23, 8, tzinfo=timezone.utc),
        datetime(2026, 6, 23, 10, tzinfo=timezone.utc),
    )

    grids = src.fetch_surface_grids((15.0, 45.0, 117.0, 123.0), valid_times)
    assert len(grids) == 2
    assert attempts == {8: 2, 10: 2}          # each parallel hour retried once


def test_batch_surface_fallback_moves_every_hour_together(monkeypatch, tmp_path):
    src = GFSSource(cache_dir=tmp_path)
    prefetched = []

    def fake_prefetch(run_dt, fxx):
        prefetched.append((run_dt, fxx))
        if run_dt.hour == 6:                          # cycle still publishing
            raise FileNotFoundError("cycle still publishing")

    monkeypatch.setattr(src, "_prefetch_surface", fake_prefetch)
    monkeypatch.setattr(src, "_download_surface", lambda run_dt, fxx: _surface_ds())
    valid_times = (
        datetime(2026, 6, 23, 10, tzinfo=timezone.utc),
        datetime(2026, 6, 23, 11, tzinfo=timezone.utc),
    )

    grids = src.fetch_surface_grids(
        (15.0, 45.0, 117.0, 123.0), valid_times
    )

    # The 06Z cycle is unavailable; the parallel prefetch attempts both of its
    # hours, then the whole batch falls back together to 00Z (order-insensitive).
    assert sorted(prefetched) == sorted([
        (datetime(2026, 6, 23, 6, tzinfo=timezone.utc), 4),
        (datetime(2026, 6, 23, 6, tzinfo=timezone.utc), 5),
        (datetime(2026, 6, 23, 0, tzinfo=timezone.utc), 10),
        (datetime(2026, 6, 23, 0, tzinfo=timezone.utc), 11),
    ])
    assert {grid.run_time for grid in grids} == {
        datetime(2026, 6, 23, 0, tzinfo=timezone.utc)
    }


def test_batch_surface_fallback_when_decoded_grid_lacks_cover(monkeypatch, tmp_path):
    src = GFSSource(cache_dir=tmp_path)
    calls = []

    def fake_download(run_dt, fxx):
        calls.append((run_dt, fxx))
        if run_dt.hour == 6:
            return _surface_ds(drop=("lcc", "mcc", "hcc"))
        return _surface_ds()

    # Prefetch (network) succeeds; the 06Z grid only fails at parse for lacking cover.
    monkeypatch.setattr(src, "_prefetch_surface", lambda run_dt, fxx: None)
    monkeypatch.setattr(src, "_download_surface", fake_download)
    valid_times = (
        datetime(2026, 6, 23, 10, tzinfo=timezone.utc),
        datetime(2026, 6, 23, 11, tzinfo=timezone.utc),
    )

    grids = src.fetch_surface_grids(
        (15.0, 45.0, 117.0, 123.0), valid_times
    )

    assert calls == [
        (datetime(2026, 6, 23, 6, tzinfo=timezone.utc), 4),
        (datetime(2026, 6, 23, 6, tzinfo=timezone.utc), 5),
        (datetime(2026, 6, 23, 0, tzinfo=timezone.utc), 10),
        (datetime(2026, 6, 23, 0, tzinfo=timezone.utc), 11),
    ]
    assert {grid.run_time for grid in grids} == {
        datetime(2026, 6, 23, 0, tzinfo=timezone.utc)
    }


def test_surface_grid_records_unique_grib_payload_bytes(tmp_path):
    first = tmp_path / "cloud.grib2"
    second = tmp_path / "surface.grib2"
    first.write_bytes(b"c" * 17)
    second.write_bytes(b"s" * 23)
    ds = _surface_ds()
    for short in ("lcc", "mcc", "hcc"):
        ds[short].encoding["source"] = str(first)
    for short in ("r2", "vis"):
        ds[short].encoding["source"] = str(second)

    grid = GFSSource._surface_grid_from_dataset(
        ds, bbox=(15.0, 45.0, 117.0, 123.0),
        run_time=_T0, valid_time=_T6, source_label="gfs@test",
    )

    assert grid.download_bytes == 40
    assert grid.decoded_bytes > grid.download_bytes


def test_download_surface_records_inventory_byte_ranges(monkeypatch, tmp_path):
    class FakeHerbie:
        def inventory(self, search):
            return pd.DataFrame({
                "grib_message": [1, 2, 4],
                "start_byte": [100, 200, 500],
                "end_byte": [199, 299, 599],
            })

        def xarray(self, search):
            return _surface_ds()

    src = GFSSource(cache_dir=tmp_path)
    monkeypatch.setattr(src, "_herbie", lambda *_args, **_kwargs: FakeHerbie())

    ds = src._download_surface(_T0, 6)
    grid = src._surface_grid_from_dataset(
        ds, bbox=(15.0, 45.0, 117.0, 123.0),
        run_time=_T0, valid_time=_T6, source_label="gfs@test",
    )

    # Adjacent messages 1–2 are one 200-byte range; message 4 adds 100 bytes.
    assert grid.download_bytes == 300
