from datetime import date, datetime, timezone
from types import SimpleNamespace

import app.overlay as overlay


def _reset_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(overlay, "CACHE_DIR", tmp_path)
    overlay._mem_cache.clear()
    overlay._building.clear()
    overlay._build_errors.clear()


def test_exact_slot_cache_returns_ready_without_starting_build(monkeypatch, tmp_path):
    _reset_cache(monkeypatch, tmp_path)
    now = datetime(2026, 6, 22, 10, 7, tzinfo=timezone.utc)
    key = "cn-v4-2026-06-22-20260622T0900"
    overlay._mem_cache[key] = {
        "country": "China",
        "date": "2026-06-22",
        "bounds": [[17, 73], [54, 136]],
        "image": "data:image/png;base64,cmVhZHk=",
        "max_probability": 0.8,
    }
    monkeypatch.setattr(
        overlay,
        "_start_build",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected build")),
    )

    result = overlay.get_overlay(date(2026, 6, 22), object(), object(), now)

    assert result["status"] == "ready"
    assert result["image"] == "/api/overlay/image/cn-v4-2026-06-22-20260622T0900.png"
    assert (tmp_path / "cn-v4-2026-06-22-20260622T0900.png").read_bytes() == b"ready"
    assert result["generated_utc"] == "2026-06-22T09:00:00+00:00"


def test_cache_miss_returns_immediately_as_building(monkeypatch, tmp_path):
    _reset_cache(monkeypatch, tmp_path)
    started = []
    monkeypatch.setattr(
        overlay, "_start_build", lambda *args, **kwargs: started.append(args[0])
    )

    result = overlay.get_overlay(
        date(2026, 6, 22),
        object(),
        object(),
        datetime(2026, 6, 22, 10, 7, tzinfo=timezone.utc),
    )

    assert result["status"] == "building"
    assert result["image"] is None
    assert started == ["cn-v4-2026-06-22-20260622T0900"]


def test_cache_miss_serves_previous_slot_while_refreshing(monkeypatch, tmp_path):
    _reset_cache(monkeypatch, tmp_path)
    overlay._mem_cache["cn-v4-2026-06-22-20260622T0600"] = {
        "country": "China",
        "date": "2026-06-22",
        "bounds": [[17, 73], [54, 136]],
        "image": "data:image/png;base64,c3RhbGU=",
        "max_probability": 0.7,
    }
    monkeypatch.setattr(overlay, "_start_build", lambda *args, **kwargs: None)

    result = overlay.get_overlay(
        date(2026, 6, 22),
        object(),
        object(),
        datetime(2026, 6, 22, 10, 7, tzinfo=timezone.utc),
    )

    assert result["status"] == "stale"
    assert result["image"] == "/api/overlay/image/cn-v4-2026-06-22-20260622T0600.png"
    assert result["generated_utc"] == "2026-06-22T06:00:00+00:00"


def test_recent_legacy_slot_is_adopted_without_refresh(monkeypatch, tmp_path):
    _reset_cache(monkeypatch, tmp_path)
    overlay._mem_cache["cn-v4-2026-06-22-20260622T0830"] = {
        "country": "China",
        "date": "2026-06-22",
        "bounds": [[17, 73], [54, 136]],
        "image": "data:image/png;base64,cmVjZW50",
        "max_probability": 0.7,
    }
    monkeypatch.setattr(
        overlay,
        "_start_build",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected build")),
    )

    result = overlay.get_overlay(
        date(2026, 6, 22),
        object(),
        object(),
        datetime(2026, 6, 22, 9, 7, tzinfo=timezone.utc),
    )

    assert result["status"] == "ready"
    assert result["generated_utc"] == "2026-06-22T08:30:00+00:00"


def test_build_scores_covering_gfs_hours_per_cell(monkeypatch):
    # The overview reads a handful of GFS hours and still scores one vectorized
    # national field — no per-point weather requests (#43).
    import numpy as np

    from predictor.gfs import SurfaceGrid

    calls = []

    class FakeGFS:
        def fetch_surface_grid(self, bbox, valid_time):
            calls.append((bbox, valid_time))
            lats = np.array([34.0, 32.0, 30.0])   # north→south, like GFS
            lons = np.array([120.0, 121.0])
            shape = (3, 2)
            return SurfaceGrid(
                lats=lats, lons=lons,
                cloud_low_pct=np.full(shape, 5.0),
                cloud_mid_pct=np.full(shape, 55.0),
                cloud_high_pct=np.full(shape, 40.0),
                humidity_pct=np.full(shape, 60.0),
                visibility_m=np.full(shape, 25000.0),
                run_time=datetime(2026, 6, 22, 0, tzinfo=timezone.utc),
                valid_time=valid_time,
                source_label=f"gfs@test+f{valid_time.hour:02d}", missing=[],
            )

    monkeypatch.setattr(overlay, "_GFS", FakeGFS())
    monkeypatch.setattr(
        overlay,
        "_geometry_mask",
        lambda _geom, lats, lons: np.ones((len(lats), len(lons)), dtype=bool),
    )
    monkeypatch.setattr(overlay, "_render_clipped_png", lambda *a, **k: "image")

    result = overlay._build(date(2026, 6, 22), object(), object(), object())

    assert len(calls) >= 3
    # CN_BBOX is (south, west, north, east); fetch_surface_grid takes
    # (lat_min, lat_max, lon_min, lon_max), so the build must reorder it.
    south, west, north, east = overlay.CN_BBOX
    assert all(call[0] == (south, north, west, east) for call in calls)
    assert all(call[1].minute == 0 and call[1].tzinfo == timezone.utc for call in calls)
    assert all(
        later - earlier == overlay.timedelta(hours=1)
        for (_bbox, earlier), (_bbox2, later) in zip(calls, calls[1:])
    )
    assert result["image"] == "image"
    assert result["n_points"] == 6
    assert result["valid_times_utc"] == [call[1].isoformat() for call in calls]
    assert len(result["sunset_range_utc"]) == 2
    assert result["surface_fetches"] == len(calls)
    assert result["additional_surface_fetches"] == len(calls) - 1
    assert result["decoded_input_bytes"] > 0
    assert "valid_utc" not in result
    assert 0.0 <= result["max_probability"] <= 1.0


def test_previous_schema_cache_is_ignored(monkeypatch, tmp_path):
    _reset_cache(monkeypatch, tmp_path)
    overlay._mem_cache["cn-v3-2026-06-22-20260622T0900"] = {
        "country": "China",
        "date": "2026-06-22",
        "bounds": [[17, 73], [54, 136]],
        "image": "data:image/png;base64,b2xk",
        "max_probability": 0.9,
    }
    started = []
    monkeypatch.setattr(
        overlay, "_start_build", lambda *args, **kwargs: started.append(args[0])
    )

    result = overlay.get_overlay(
        date(2026, 6, 22),
        object(),
        object(),
        datetime(2026, 6, 22, 10, 7, tzinfo=timezone.utc),
    )

    assert result["status"] == "building"
    assert result["image"] is None
    assert started == ["cn-v4-2026-06-22-20260622T0900"]


def test_axis_values_always_include_country_bounds():
    values = overlay._axis_values(17.0, 54.0, 4.0)

    assert values[0] == 17.0
    assert values[-1] == 54.0


def test_refresh_slots_are_three_hourly():
    now = datetime(2026, 6, 22, 10, 47, tzinfo=timezone.utc)
    slot = overlay._refresh_slot(now)

    assert slot == datetime(2026, 6, 22, 9, 0, tzinfo=timezone.utc)
    assert overlay._next_refresh(now, slot) == datetime(
        2026, 6, 22, 12, 0, tzinfo=timezone.utc
    )


def test_failed_build_observes_retry_cooldown(monkeypatch):
    key = "cn-v4-2026-06-22-20260622T0900"
    overlay._building.clear()
    overlay._build_errors.clear()
    overlay._build_errors[key] = ("rate limited", overlay.time.monotonic() + 60)
    monkeypatch.setattr(
        overlay.threading,
        "Thread",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected retry")),
    )

    started = overlay._start_build(key, date(2026, 6, 22), object(), object())

    assert started is False
