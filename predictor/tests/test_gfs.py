"""Unit tests for GFSSource (no network — synthetic xarray + monkeypatch)."""
import re
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


def test_select_cycle_caps_future_forecast_at_latest_published_run(tmp_path):
    """A tomorrow forecast must not probe model cycles that do not exist yet."""
    src = GFSSource(
        cache_dir=tmp_path,
        as_of=datetime(2026, 7, 9, 6, 28, tzinfo=timezone.utc),
    )

    run_dt, fxx = src._select_cycle(
        datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)
    )

    # At 06:28Z, a four-hour publication lag makes 00Z the newest safe run.
    assert run_dt == datetime(2026, 7, 9, 0, 0, tzinfo=timezone.utc)
    assert fxx == 36


def test_pressure_search_matches_only_configured_levels(tmp_path):
    src = GFSSource(cache_dir=tmp_path, levels=(1000.0, 850.0, 150.0))
    search = re.compile(src._pressure_search)

    assert search.search(":TMP:1000 mb:")
    assert search.search(":ICMR:150 mb:")
    assert not search.search(":TMP:0.01 mb:")
    assert not search.search(":TMP:100 mb:")
    assert not search.search(":TMP:10 mb:")


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


class _ResumableHerbie:
    """Minimal Herbie shape for exercising prefix-resume without network IO."""

    def __init__(self, remote_path, local_path):
        self.grib = remote_path
        self.local_path = local_path

    def inventory(self, search):
        import pandas as pd

        return pd.DataFrame(
            {
                "grib_message": [1, 2, 4],
                "start_byte": [0.0, 100.0, 300.0],
                "end_byte": [99.0, 199.0, 399.0],
            }
        )

    def get_localFilePath(self, search):
        return self.local_path


def test_resumable_subset_continues_inside_a_range_group(tmp_path):
    from predictor.gfs import _download_resumable_subset

    remote = tmp_path / "global.grib2"
    remote_bytes = bytes(range(200)) + bytes(range(200))
    remote.write_bytes(remote_bytes)
    local = tmp_path / "subset.grib2"
    # Complete first group (remote 0..199), plus half of group two (300..349).
    local.write_bytes(remote_bytes[:200] + remote_bytes[300:350])
    fake = _ResumableHerbie(remote, local)

    transferred = _download_resumable_subset(fake, "pressure-search")

    assert transferred == 50
    assert local.read_bytes() == remote_bytes[:200] + remote_bytes[300:400]


def test_resumable_http_subset_keeps_prefix_after_connection_drop(
    monkeypatch, tmp_path
):
    import pandas as pd
    import requests

    from predictor import gfs as gfs_module

    local = tmp_path / "subset.grib2"

    class FakeHerbie:
        grib = "https://example.test/gfs.grib2"

        def inventory(self, search):
            return pd.DataFrame(
                {"grib_message": [1], "start_byte": [0.0], "end_byte": [99.0]}
            )

        def get_localFilePath(self, search):
            return local

    class FakeResponse:
        status_code = 206

        def __init__(self, chunks):
            self.chunks = chunks

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size):
            yield from self.chunks

    requested = []

    def first_get(url, *, headers, **kwargs):
        requested.append(headers["Range"])

        def interrupted():
            yield b"a" * 40
            raise requests.ConnectionError("connection reset by peer")

        return FakeResponse(interrupted())

    monkeypatch.setattr(gfs_module.requests, "get", first_get)
    with pytest.raises(RuntimeError, match="connection reset"):
        gfs_module._download_resumable_subset(FakeHerbie(), "pressure-search")
    assert local.stat().st_size == 40

    def second_get(url, *, headers, **kwargs):
        requested.append(headers["Range"])
        return FakeResponse([b"b" * 60])

    monkeypatch.setattr(gfs_module.requests, "get", second_get)
    transferred = gfs_module._download_resumable_subset(
        FakeHerbie(), "pressure-search"
    )

    assert requested == ["bytes=0-99", "bytes=40-99"]
    assert transferred == 60
    assert local.read_bytes() == b"a" * 40 + b"b" * 60


def test_complete_legacy_pressure_subset_is_reused(tmp_path):
    src = GFSSource(cache_dir=tmp_path, levels=(1000.0, 850.0))
    legacy_path = tmp_path / "legacy-subset"
    exact_path = tmp_path / "exact-subset"

    class FakeHerbie(_ResumableHerbie):
        def get_localFilePath(self, search):
            if search == src._LEGACY_PRESSURE_SEARCH:
                return legacy_path
            return exact_path

    fake = FakeHerbie(tmp_path / "global.grib2", exact_path)
    legacy_path.write_bytes(b"\0" * _SubsetHerbie.EXPECTED_BYTES)

    assert src._select_pressure_search(fake) == src._LEGACY_PRESSURE_SEARCH

    exact_path.write_bytes(b"\0" * _SubsetHerbie.EXPECTED_BYTES)
    assert src._select_pressure_search(fake) == src._pressure_search


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
    # Parse recognizes the verified file directly; no redundant Herbie call.
    assert fakes[6].download_calls == 2  # truncated prefetch + complete retry
    assert fakes[9].download_calls == 1  # clean prefetch only


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
    assert captured["priority"] == ["aws", "nomads", "google", "azure"]
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


# ---- download progress logging (big transfers only) ----
#
# A default pressure cube is a ~130 MB download that takes minutes; with herbie's
# chatter silenced the CLI would look hung. _verified_subset_download logs
# meaningful progress at INFO — but only for payloads over the announce
# threshold, so the six ~0.6 MB surface hours of a national run stay quiet.


def test_progress_line_reports_rate_eta_and_stall():
    from predictor.gfs import _progress_line

    moving = _progress_line("pressure", 19, 50_000_000, 100_000_000, 2_000_000, False)
    stalled = _progress_line("pressure", 19, 50_000_000, 100_000_000, 0.0, True)

    assert "50/100 MB" in moving
    assert "2.0 MB/s" in moving
    assert "25 s left" in moving
    assert "no progress" in stalled


def test_big_subset_download_logs_progress(monkeypatch, tmp_path, caplog):
    import logging

    from predictor import gfs as gfs_module

    monkeypatch.setattr(gfs_module, "_PROGRESS_ANNOUNCE_BYTES", 100)
    path = tmp_path / "subset_big__gfs.f006"
    fake = _SubsetHerbie(path, payload_sizes=[300])
    src = _patched_source(monkeypatch, tmp_path, fake)

    with caplog.at_level(logging.INFO, logger="predictor.gfs"):
        src._load_dataset(datetime(2026, 6, 23, 0, tzinfo=timezone.utc), 6)

    messages = [r.message for r in caplog.records]
    assert any("downloading" in m for m in messages)
    assert any("ready" in m for m in messages)


def test_small_subset_download_stays_quiet(monkeypatch, tmp_path, caplog):
    import logging

    path = tmp_path / "subset_small__gfs.f006"
    fake = _SubsetHerbie(path, payload_sizes=[300])   # 300 B << threshold
    src = _patched_source(monkeypatch, tmp_path, fake)

    with caplog.at_level(logging.INFO, logger="predictor.gfs"):
        src._load_dataset(datetime(2026, 6, 23, 0, tzinfo=timezone.utc), 6)

    assert caplog.records == []


def test_cached_big_subset_logs_cache_hit_not_download(
    monkeypatch, tmp_path, caplog
):
    import logging

    from predictor import gfs as gfs_module

    monkeypatch.setattr(gfs_module, "_PROGRESS_ANNOUNCE_BYTES", 100)
    path = tmp_path / "subset_big__gfs.f006"
    path.write_bytes(b"\0" * _SubsetHerbie.EXPECTED_BYTES)   # complete on disk
    fake = _SubsetHerbie(path, payload_sizes=[])
    src = _patched_source(monkeypatch, tmp_path, fake)

    with caplog.at_level(logging.INFO, logger="predictor.gfs"):
        src._load_dataset(datetime(2026, 6, 23, 0, tzinfo=timezone.utc), 6)

    messages = [r.message for r in caplog.records]
    assert any("cached" in m for m in messages)
    assert not any("downloading" in m for m in messages)


# ---- network-bytes accounting ----
#
# The refine metadata reports real cube download cost. Only bytes that were
# actually transferred count — a disk-cache hit re-parses a retained subset
# and must not inflate the number.


def test_network_bytes_counts_downloads_not_cache_hits(monkeypatch, tmp_path):
    path = tmp_path / "subset_acct__gfs.f006"
    fake = _SubsetHerbie(path, payload_sizes=[300])
    src = _patched_source(monkeypatch, tmp_path, fake)

    src._load_dataset(datetime(2026, 6, 23, 0, tzinfo=timezone.utc), 6)
    assert src.network_bytes["pressure"] == _SubsetHerbie.EXPECTED_BYTES

    src._ds_cache.clear()   # force a re-parse; the complete file is on disk
    src._load_dataset(datetime(2026, 6, 23, 0, tzinfo=timezone.utc), 6)
    assert src.network_bytes["pressure"] == _SubsetHerbie.EXPECTED_BYTES


def test_release_cube_pops_matching_datasets(monkeypatch, tmp_path):
    src = GFSSource(cache_dir=tmp_path)
    run = datetime(2026, 6, 23, 0, tzinfo=timezone.utc)
    older = datetime(2026, 6, 22, 18, tzinfo=timezone.utc)
    ds = _synthetic_gfs_ds()
    src._ds_cache[(run, 6)] = ds        # valid 06Z via 00Z+f06
    src._ds_cache[(older, 12)] = ds     # same valid hour via fallback cycle
    src._ds_cache[(run, 9)] = ds        # a different valid hour — must survive

    released = src.release_cube(datetime(2026, 6, 23, 6, tzinfo=timezone.utc))

    assert released == 2
    assert list(src._ds_cache) == [(run, 9)]


# ---------------------------------------------------------------------------
# #103: download heartbeat — a multi-minute blocking download must not be silent
# ---------------------------------------------------------------------------


def test_progress_line_reports_rate_and_eta():
    from predictor.gfs import _progress_line

    line = _progress_line(
        "pressure", 19, size=34_000_000, expected=89_000_000,
        rate_bytes_s=2_266_667, stalled=False,
    )
    assert "f19" in line
    assert "34/89 MB" in line
    assert "2.3 MB/s" in line
    assert "s left" in line


def test_progress_line_flags_stall_explicitly():
    from predictor.gfs import _progress_line

    line = _progress_line(
        "pressure", 19, size=34_000_000, expected=89_000_000,
        rate_bytes_s=0.0, stalled=True,
    )
    assert "no progress" in line


class _SlowHerbie(_SubsetHerbie):
    """Subset download that trickles onto disk across several heartbeat ticks."""

    def __init__(self, path, *, chunks, pause_s, write_bytes=True):
        super().__init__(path, payload_sizes=[])
        self.chunks = chunks
        self.pause_s = pause_s
        self.write_bytes = write_bytes

    def download(self, search):
        self.download_calls += 1
        import time as _time

        for i in range(1, self.chunks + 1):
            _time.sleep(self.pause_s)
            if self.write_bytes:
                self.path.write_bytes(b"\0" * (100 * i))
        if not self.write_bytes:
            self.path.write_bytes(b"\0" * _SubsetHerbie.EXPECTED_BYTES)
        return self.path


def test_slow_subset_download_emits_heartbeat(monkeypatch, tmp_path, caplog):
    import logging as _logging

    import predictor.gfs as gfs_mod

    monkeypatch.setattr(gfs_mod, "_PROGRESS_ANNOUNCE_BYTES", 100)
    monkeypatch.setattr(gfs_mod, "_PROGRESS_HEARTBEAT_S", 0.03)
    # 3 chunks of 100·i bytes end exactly at the 300-byte inventory total.
    fake = _SlowHerbie(tmp_path / "subset", chunks=3, pause_s=0.05)
    src = _patched_source(monkeypatch, tmp_path, fake)
    with caplog.at_level(_logging.INFO, logger="predictor.gfs"):
        src._verified_subset_download(fake, "search", 19, "pressure")
    beats = [r.message for r in caplog.records if "f19" in r.message and "MB" in r.message]
    # start line + at least one mid-download heartbeat + ready line
    assert len(beats) >= 3


def test_stalled_download_says_so(monkeypatch, tmp_path, caplog):
    import logging as _logging

    import predictor.gfs as gfs_mod

    monkeypatch.setattr(gfs_mod, "_PROGRESS_ANNOUNCE_BYTES", 100)
    monkeypatch.setattr(gfs_mod, "_PROGRESS_HEARTBEAT_S", 0.03)
    fake = _SlowHerbie(tmp_path / "subset", chunks=4, pause_s=0.05, write_bytes=False)
    src = _patched_source(monkeypatch, tmp_path, fake)
    with caplog.at_level(_logging.INFO, logger="predictor.gfs"):
        src._verified_subset_download(fake, "search", 19, "pressure")
    assert any("no progress" in r.message for r in caplog.records)


def test_transient_retry_log_is_human_and_hides_exception_repr(monkeypatch, caplog):
    import logging as _logging

    src = GFSSource(cache_dir="/tmp/gfs-test")
    src.SURFACE_RETRY_BACKOFF_S = 0.0
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 2:
            raise RuntimeError(
                "HTTPSConnectionPool(host='noaa'): Read timed out"
            )
        return "ok"

    with caplog.at_level(_logging.INFO, logger="predictor.gfs"):
        assert src._retry_transient(flaky, 19, "pressure") == "ok"
    warnings = [r for r in caplog.records if r.levelno == _logging.WARNING]
    assert warnings, "a retry should log at WARNING"
    line = warnings[0].message
    assert "重试" in line and "1/3" in line          # human: which attempt
    assert "HTTPSConnectionPool" not in line          # raw repr not in the headline


# ---------------------------------------------------------------------------
# #108 Story B: parallel pressure-cube prefetch (download parallel, parse serial)
# ---------------------------------------------------------------------------


def test_prefetch_cubes_downloads_each_distinct_hour_once(monkeypatch):
    src = GFSSource(cache_dir="/tmp/gfs-test")
    calls = []
    monkeypatch.setattr(src, "_prefetch_dataset", lambda run, fxx: calls.append((run, fxx)))
    vt = datetime(2026, 6, 23, 6, tzinfo=timezone.utc)
    src.prefetch_cubes([vt, vt, vt])          # same hour requested three times
    assert len(calls) == 1                     # deduped to one (run, fxx)


def test_prefetch_cubes_retries_but_remains_best_effort(monkeypatch):
    src = GFSSource(cache_dir="/tmp/gfs-test")
    src.SURFACE_RETRY_BACKOFF_S = 0.0
    calls = []

    def boom(run, fxx):
        calls.append((run, fxx))
        raise RuntimeError("Connection reset by peer")

    monkeypatch.setattr(src, "_prefetch_dataset", boom)
    # Two distinct hours → the parallel path; failures must be swallowed.
    src.prefetch_cubes([
        datetime(2026, 6, 23, 6, tzinfo=timezone.utc),
        datetime(2026, 6, 24, 6, tzinfo=timezone.utc),
    ])
    assert len(calls) == 2 * src.SURFACE_DOWNLOAD_ATTEMPTS


def test_prefetch_cubes_skips_already_decoded_hours(monkeypatch):
    src = GFSSource(cache_dir="/tmp/gfs-test")
    calls = []
    monkeypatch.setattr(src, "_prefetch_dataset", lambda run, fxx: calls.append((run, fxx)))
    vt = datetime(2026, 6, 23, 6, tzinfo=timezone.utc)
    run, fxx = src._select_cycle(vt)
    src._ds_cache[(run, fxx)] = object()       # pretend this hour is already decoded
    src.prefetch_cubes([vt])
    assert calls == []                          # nothing left to download


def test_prefetch_cubes_bounds_concurrent_downloads(monkeypatch):
    import predictor.gfs as gfs_mod

    src = GFSSource(cache_dir="/tmp/gfs-test")
    src.MAX_CUBE_WORKERS = 2
    monkeypatch.setattr(src, "_prefetch_dataset", lambda run, fxx: None)
    captured = {}
    real_pool = gfs_mod.ThreadPoolExecutor

    def spy(max_workers):
        captured["workers"] = max_workers
        return real_pool(max_workers=max_workers)

    monkeypatch.setattr(gfs_mod, "ThreadPoolExecutor", spy)
    vts = [datetime(2026, 6, d, 6, tzinfo=timezone.utc) for d in (23, 24, 25, 26)]
    src.prefetch_cubes(vts)
    assert captured["workers"] == 2             # min(distinct hours, cap) honoured


def test_default_cube_worker_cap_is_four():
    assert GFSSource.MAX_CUBE_WORKERS == 4
