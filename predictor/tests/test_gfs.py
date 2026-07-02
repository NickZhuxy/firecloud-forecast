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

    assert calls == ["pressure", "cover", "surface", "cover", "surface"]


def test_fetch_raises_gfs_unavailable_after_retries(monkeypatch):
    src = GFSSource(cache_dir="/tmp/gfs-test")

    def always_fail(run_dt, fxx):
        raise RuntimeError("down")

    monkeypatch.setattr(src, "_download_dataset", always_fail)
    with pytest.raises(GFSUnavailable):
        src.fetch_profile(30.0, 120.0, datetime(2026, 6, 23, 6, tzinfo=timezone.utc))


# ---- subset completeness verification (#59 live validation bug) ----
#
# Herbie downloads a regex subset as one HTTP range request per message group
# and, on a dropped connection, leaves the partial file on disk; every later
# call (in-process retry or a whole new run) sees the file exists and silently
# parses the stub — missing entire level blocks. Every subset download path
# (_download_dataset, _download_surface, _prefetch_surface, _download_cover)
# must verify the byte count against the idx inventory and delete-and-retry
# on mismatch.


class _SubsetHerbie:
    """Fake Herbie: inventory-priced subset download onto a real tmp file."""

    EXPECTED_BYTES = 300  # groups: msgs [1,2] → 0..199, msg [4] → 300..399

    def __init__(self, path, payload_sizes, has_inventory=True, dataset=None):
        self.path = path
        self.payload_sizes = list(payload_sizes)  # bytes written per download call
        self.has_inventory = has_inventory
        self.dataset = dataset                    # what xarray() parses into
        self.download_calls = 0
        self.xarray_calls = 0

    def inventory(self, search):
        if not self.has_inventory:
            raise AttributeError("no idx available")
        import pandas as pd

        return pd.DataFrame(
            {
                "grib_message": [1, 2, 4],
                "start_byte": [0.0, 100.0, 300.0],
                "end_byte": [99.0, 199.0, 399.0],
            }
        )

    def download(self, search):
        self.download_calls += 1
        if self.path.exists():          # mimic herbie: existing subset → skip
            return self.path
        size = self.payload_sizes.pop(0)
        self.path.write_bytes(b"\0" * size)
        return self.path

    def get_localFilePath(self, search):
        return self.path

    def xarray(self, search):
        self.xarray_calls += 1
        return self.dataset if self.dataset is not None else _synthetic_gfs_ds()


def _patched_source(monkeypatch, tmp_path, fake):
    src = GFSSource(cache_dir=tmp_path)
    src.SURFACE_RETRY_BACKOFF_S = 0.0
    monkeypatch.setattr(
        src, "_herbie", lambda run_dt, fxx, *, cache_namespace: fake
    )
    return src


def test_truncated_cached_subset_is_deleted_and_redownloaded(monkeypatch, tmp_path):
    """A stale partial file from an earlier crash must not poison the cache."""
    path = tmp_path / "subset_dead__gfs.f006"
    path.write_bytes(b"\0" * 37)                      # poisoned leftover
    fake = _SubsetHerbie(path, payload_sizes=[300])   # re-download is complete
    src = _patched_source(monkeypatch, tmp_path, fake)

    ds = src._load_dataset(datetime(2026, 6, 23, 0, tzinfo=timezone.utc), 6)

    assert "t" in ds.data_vars
    assert path.stat().st_size == _SubsetHerbie.EXPECTED_BYTES
    assert fake.download_calls == 2   # skip-existing, then real re-download
    assert fake.xarray_calls == 1     # parsed only after verification passed


def test_persistently_truncated_subset_fails_loud_and_leaves_no_stub(
    monkeypatch, tmp_path
):
    """Every attempt truncates → loud GFSUnavailable, no poisoned file left."""
    path = tmp_path / "subset_dead__gfs.f006"
    fake = _SubsetHerbie(path, payload_sizes=[37, 37, 37])
    src = _patched_source(monkeypatch, tmp_path, fake)

    with pytest.raises(GFSUnavailable, match="truncated"):
        src._load_dataset(datetime(2026, 6, 23, 0, tzinfo=timezone.utc), 6)

    assert not path.exists()          # never left behind to poison later runs
    assert fake.download_calls == src.SURFACE_DOWNLOAD_ATTEMPTS
    assert fake.xarray_calls == 0     # a truncated file is never parsed


def test_truncation_error_is_classified_transient():
    from predictor.gfs import _is_transient_network_error

    exc = GFSUnavailable("GFS pressure subset f06 truncated (37/300 bytes)")
    assert _is_transient_network_error(exc)


def test_subset_without_inventory_skips_verification(monkeypatch, tmp_path):
    """No idx (e.g. a stub source) → parse as before, no crash."""
    path = tmp_path / "subset_dead__gfs.f006"
    fake = _SubsetHerbie(path, payload_sizes=[37], has_inventory=False)
    src = _patched_source(monkeypatch, tmp_path, fake)

    ds = src._load_dataset(datetime(2026, 6, 23, 0, tzinfo=timezone.utc), 6)

    assert "t" in ds.data_vars
    assert fake.xarray_calls == 1


def _synthetic_surface_ds() -> xr.Dataset:
    """Cover-bearing surface dataset — keeps _download_surface off the cover path."""
    dims = ("latitude", "longitude")
    data = {
        s: (dims, np.full((2, 2), 42.0)) for s in ("lcc", "mcc", "hcc", "r2", "vis")
    }
    return xr.Dataset(
        data, coords={"latitude": [40.0, 30.0], "longitude": [118.0, 120.0]}
    )


def test_truncated_surface_subset_is_deleted_and_redownloaded(monkeypatch, tmp_path):
    """A poisoned surface stub must be caught before parse, like the pressure path."""
    path = tmp_path / "surface_dead__gfs.f006"
    path.write_bytes(b"\0" * 37)                      # poisoned leftover
    fake = _SubsetHerbie(path, payload_sizes=[300], dataset=_synthetic_surface_ds())
    src = _patched_source(monkeypatch, tmp_path, fake)

    ds = src._load_surface(datetime(2026, 6, 23, 0, tzinfo=timezone.utc), 6)

    assert "lcc" in ds.data_vars
    assert path.stat().st_size == _SubsetHerbie.EXPECTED_BYTES
    assert fake.download_calls == 2   # skip-existing, then real re-download
    assert fake.xarray_calls == 1     # parsed only after verification passed


def test_persistently_truncated_surface_fails_loud_and_leaves_no_stub(
    monkeypatch, tmp_path
):
    path = tmp_path / "surface_dead__gfs.f006"
    fake = _SubsetHerbie(
        path, payload_sizes=[37, 37, 37], dataset=_synthetic_surface_ds()
    )
    src = _patched_source(monkeypatch, tmp_path, fake)

    with pytest.raises(GFSUnavailable, match="surface subset f06 truncated"):
        src._load_surface(datetime(2026, 6, 23, 0, tzinfo=timezone.utc), 6)

    assert not path.exists()          # never left behind to poison later runs
    assert fake.download_calls == src.SURFACE_DOWNLOAD_ATTEMPTS
    assert fake.xarray_calls == 0     # a truncated file is never parsed


def test_truncated_batch_prefetch_is_deleted_and_redownloaded(monkeypatch, tmp_path):
    """_load_surface_batch heals a truncated prefetch instead of parsing the stub."""
    fakes = {
        6: _SubsetHerbie(
            tmp_path / "surface__gfs.f006",
            payload_sizes=[37, 300],              # truncated once, then complete
            dataset=_synthetic_surface_ds(),
        ),
        9: _SubsetHerbie(
            tmp_path / "surface__gfs.f009",
            payload_sizes=[300],
            dataset=_synthetic_surface_ds(),
        ),
    }
    src = GFSSource(cache_dir=tmp_path)
    src.SURFACE_RETRY_BACKOFF_S = 0.0
    monkeypatch.setattr(
        src, "_herbie", lambda run_dt, fxx, *, cache_namespace: fakes[fxx]
    )

    datasets = src._load_surface_batch(
        datetime(2026, 6, 23, 0, tzinfo=timezone.utc), [6, 9]
    )

    assert len(datasets) == 2
    for fake in fakes.values():
        assert fake.path.stat().st_size == _SubsetHerbie.EXPECTED_BYTES
        assert fake.xarray_calls == 1
    # f06: truncated prefetch + verified re-download + skip-existing at parse.
    assert fakes[6].download_calls == 3
    # f09: clean prefetch + skip-existing at parse.
    assert fakes[9].download_calls == 2


def test_truncated_cover_subset_is_deleted_and_redownloaded(monkeypatch, tmp_path):
    """The cover path must verify, delete and retry like every other subset."""
    path = tmp_path / "cover_dead__gfs.f006"
    path.write_bytes(b"\0" * 37)                      # poisoned leftover
    fake = _SubsetHerbie(path, payload_sizes=[300])
    src = _patched_source(monkeypatch, tmp_path, fake)

    ds = src._load_cover(datetime(2026, 6, 23, 0, tzinfo=timezone.utc), 6)

    assert "t" in ds.data_vars
    assert path.stat().st_size == _SubsetHerbie.EXPECTED_BYTES
    assert fake.download_calls == 2   # skip-existing, then real re-download
    assert fake.xarray_calls == 1     # parsed only after verification passed


# ---- download chatter suppression (CLI noise) ----
#
# A firecloud CLI run used to spray herbie's verbose prints ("✅ Found …",
# per-message subset download rows, "Note: Returning a list of …") plus two
# recurring third-party warnings (herbie's "Will not remove GRIB file…",
# cfgrib's xr.merge FutureWarning) over the product output. The Herbie handle
# must be constructed quiet, and GFSSource must install *targeted* warning
# filters — everything else keeps warning normally.


def test_herbie_handle_is_quiet_and_predates_date_dir(monkeypatch, tmp_path):
    captured = {}

    class StubHerbie:
        def __init__(self, date, **kwargs):
            captured.update(kwargs, date=date)

    import herbie

    monkeypatch.setattr(herbie, "Herbie", StubHerbie)
    src = GFSSource(cache_dir=tmp_path)
    src._herbie(datetime(2026, 6, 23, 0, tzinfo=timezone.utc), 6,
                cache_namespace="pressure")

    assert captured["verbose"] is False
    # The dated subdir herbie would otherwise create (with an ungated
    # "Created directory" print) must already exist.
    assert (tmp_path / "pressure" / "gfs" / "20260623").is_dir()


def test_grib_chatter_filters_are_targeted():
    import warnings

    from predictor import gfs as gfs_module

    with warnings.catch_warnings(record=True) as rec:
        warnings.simplefilter("always")
        gfs_module._silence_grib_chatter()
        warnings.warn("Will not remove GRIB file because it previously existed.")
        warnings.warn(
            "In a future version of xarray the default value for compat will "
            "change from compat='no_conflicts' to compat='override'.",
            FutureWarning,
        )
        warnings.warn("unrelated warning stays visible")

    assert [str(w.message) for w in rec] == ["unrelated warning stays visible"]


def test_gfssource_init_installs_chatter_filters(tmp_path):
    import warnings

    from predictor import gfs as gfs_module

    with warnings.catch_warnings(record=True) as rec:
        warnings.simplefilter("always")
        gfs_module._GRIB_CHATTER_SILENCED = False   # fresh process state
        GFSSource(cache_dir=tmp_path)
        warnings.warn("Will not remove GRIB file because it previously existed.")

    assert rec == []
