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
    key = "cn-v3-2026-06-22-20260622T0900"
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
    assert result["image"] == "/api/overlay/image/cn-v3-2026-06-22-20260622T0900.png"
    assert (tmp_path / "cn-v3-2026-06-22-20260622T0900.png").read_bytes() == b"ready"
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
    assert started == ["cn-v3-2026-06-22-20260622T0900"]


def test_cache_miss_serves_previous_slot_while_refreshing(monkeypatch, tmp_path):
    _reset_cache(monkeypatch, tmp_path)
    overlay._mem_cache["cn-v3-2026-06-22-20260622T0600"] = {
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
    assert result["image"] == "/api/overlay/image/cn-v3-2026-06-22-20260622T0600.png"
    assert result["generated_utc"] == "2026-06-22T06:00:00+00:00"


def test_recent_legacy_slot_is_adopted_without_refresh(monkeypatch, tmp_path):
    _reset_cache(monkeypatch, tmp_path)
    overlay._mem_cache["cn-v3-2026-06-22-20260622T0830"] = {
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


def test_build_selects_each_grid_points_sunset_window(monkeypatch):
    monkeypatch.setattr(overlay, "CN_BBOX", (30.0, 120.0, 30.0, 121.0))
    monkeypatch.setattr(overlay, "CN_STEP", 1.0)
    monkeypatch.setattr(overlay, "_render_clipped_png", lambda *args: "image")
    calls = []

    class Source:
        def fetch_many_for_sunset(
            self, coords, evening_hint, score_offset, *, window_days
        ):
            calls.append((coords, evening_hint, score_offset, window_days))
            return [
                SimpleNamespace(
                    sunset_time=datetime(2026, 6, 22, 10 + i, tzinfo=timezone.utc)
                )
                for i, _ in enumerate(coords)
            ]

    class Predictor:
        def score_snapshot(self, snapshot, lat, lon, time):
            expected = snapshot.sunset_time - overlay.SCORE_OFFSET
            assert time == expected
            return SimpleNamespace(probability=0.5)

    result = overlay._build(date(2026, 6, 22), Source(), Predictor(), object())

    assert len(calls) == 1
    assert calls[0][0] == [(30.0, 120.0), (30.0, 121.0)]
    assert calls[0][3] == 0
    assert result["image"] == "image"


def test_previous_schema_cache_is_ignored(monkeypatch, tmp_path):
    _reset_cache(monkeypatch, tmp_path)
    overlay._mem_cache["cn-v1-2026-06-22-20260622T0900"] = {
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
    assert started == ["cn-v3-2026-06-22-20260622T0900"]


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
    key = "cn-v3-2026-06-22-20260622T0900"
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
