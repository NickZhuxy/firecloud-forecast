"""Offline scheduler contracts for real request timing and immutable delivery."""
import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from PIL import Image
import pytest

import predictor.forecast_runner as runner
import predictor.observation_pilot as pilot


@pytest.fixture
def config():
    return {
        "id": "example-city", "name": "Public city sample", "region": "us-nyc",
        "timezone": "America/New_York", "latitude": 40.7128, "longitude": -74.0060,
        "radius_km": 25, "resolution_deg": 0.1,
    }


@pytest.fixture
def environment(monkeypatch, config):
    env = SimpleNamespace(now=datetime(2026, 10, 4, tzinfo=timezone.utc),
                          seen=[], fail=False, interrupt=False, delay=3,
                          invalid_image=False, wrong_metadata=False)
    monkeypatch.setattr(runner, "_utc_now", lambda: env.now)
    monkeypatch.setattr(pilot, "_utc_now", lambda: env.now)
    monkeypatch.setattr(pilot, "_source_revision", lambda: None)
    monkeypatch.setattr(runner.shutil, "disk_usage", lambda path: SimpleNamespace(free=2_000_000_000))

    def generate(target, directory, lat, lon, **kwargs):
        env.seen.append(kwargs["now"])
        if env.interrupt:
            raise KeyboardInterrupt("simulated termination")
        env.now = kwargs["now"] + timedelta(seconds=env.delay)
        if env.fail:
            raise OSError("synthetic provider unavailable")
        directory = Path(directory)
        image = directory / "point.png"
        if env.invalid_image:
            image.write_bytes(b"invalid image content")
        else:
            Image.new("RGB", (2, 2), "white").save(image)
        event = pilot._event(pilot._validate_viewpoint(dict(config, solar_event=kwargs["solar_event"])), target)
        metadata = {
            "target_date": target.isoformat(), "region": kwargs["region"],
            "timezone": config["timezone"], "solar_event": kwargs["solar_event"].value,
            "event_time_utc": event.isoformat(),
            "event_time_local": event.astimezone(ZoneInfo(config["timezone"])).isoformat(),
            "center": [lat, lon], "image": image.name,
            "condition_index": {"center_value": 0.42, "calibrated_probability": False},
            "gfs_timing": {"initialization_time_utc": "2026-10-04T18:00:00+00:00",
                           "forecast_hour": 5, "valid_time_utc": "2026-10-04T23:00:00+00:00"},
            "provenance": {"gfs": {"selection_as_of_utc": kwargs["now"].isoformat()}},
        }
        if env.wrong_metadata:
            metadata["target_date"] = "2000-01-01"
        sidecar = directory / "point.json"
        sidecar.write_text(json.dumps(metadata), encoding="utf-8")
        return SimpleNamespace(image_path=image, metadata_path=sidecar)

    monkeypatch.setattr(pilot, "_generate_product", generate)
    return env


def schedule(config, target=date(2026, 10, 4)):
    return pilot.build_schedule(config, target, 1)[0]


def planned(config, target=date(2026, 10, 4)):
    return datetime.fromisoformat(schedule(config, target)["planned_request_utc"])


def call(config, tmp_path, environment, now, **kwargs):
    environment.now = now
    return runner.tick(config, tmp_path, now=now, **kwargs)


def state(config, tmp_path):
    return json.loads((tmp_path / config["id"] / "runner-state.json").read_text())


def slot(config, tmp_path, target=date(2026, 10, 4)):
    return state(config, tmp_path)["slots"][f"{target}/{config.get('solar_event', 'sunset')}"]


def test_due_boundary_immutable_capture_delivery_and_dedup(config, tmp_path, environment):
    due = planned(config)
    assert call(config, tmp_path, environment, due - timedelta(microseconds=1))["action"] == "idle"
    result = call(config, tmp_path, environment, due)
    assert result["status"] == "success"
    path = tmp_path / config["id"] / result["attempt"]
    original = path.read_bytes()
    captured = json.loads(original)
    assert captured["request_utc"] == due.isoformat()
    assert captured["completion_utc"] != captured["request_utc"]
    assert captured["source_timing"]["provenance"]["gfs"]["selection_as_of_utc"] == due.isoformat()
    assert len(slot(config, tmp_path)["attempts"]) == 1
    for delta in (1, 5, 15, 20):
        assert call(config, tmp_path, environment, due + timedelta(minutes=delta))["action"] == "idle"
    assert len(environment.seen) == 1
    assert path.read_bytes() == original
    delivery = runner.status(config, tmp_path, now=due)
    assert delivery["latest"]["condition_index"] == 0.42
    assert delivery["latest"]["is_current_date"] is True
    text = (tmp_path / config["id"] / "latest.md").read_text()
    assert str(path.resolve()) in text
    assert "2026-10-04T18:00:00+00:00" in text
    assert "uncalibrated heuristic" in text
    assert "Local completion:" in text


@pytest.mark.parametrize("delta", [15, 15.0001])
def test_deadline_boundary(config, tmp_path, environment, delta):
    end = planned(config) + timedelta(minutes=delta)
    result = call(config, tmp_path, environment, end)
    if delta == 15:
        assert result["action"] == "forecast"
    else:
        assert result["action"] == "idle"
        assert slot(config, tmp_path)["status"] == "missed"
        assert environment.seen == []


def test_retries_use_actual_current_time_completion_backoff_and_three_attempt_limit(config, tmp_path, environment):
    due = planned(config)
    environment.fail = True
    assert call(config, tmp_path, environment, due)["status"] == "retry_wait"
    assert call(config, tmp_path, environment, due + timedelta(minutes=5))["action"] == "idle"
    second = due + timedelta(minutes=5, seconds=3)
    assert call(config, tmp_path, environment, second)["status"] == "retry_wait"
    third = second + timedelta(minutes=5, seconds=3)
    assert call(config, tmp_path, environment, third)["status"] == "exhausted"
    call(config, tmp_path, environment, due + timedelta(minutes=14))
    record = slot(config, tmp_path)
    assert environment.seen == [due, second, third]
    assert len(record["attempts"]) == 3
    assert record["exhaustion_reason"] == "maximum_attempts_reached"
    paths = [tmp_path / config["id"] / entry["attempt_path"] for entry in record["attempts"]]
    assert len(set(paths)) == 3
    assert all(json.loads(path.read_text())["status"] == "failed" for path in paths)


def test_failed_attempt_deadline_is_exhausted_not_no_attempt_missed(config, tmp_path, environment):
    due = planned(config)
    environment.fail = True
    call(config, tmp_path, environment, due)
    call(config, tmp_path, environment, due + timedelta(minutes=16))
    value = slot(config, tmp_path)
    assert value["status"] == "exhausted"
    assert value["generation_status"] == "failed"
    assert value["exhaustion_reason"] == "request_window_expired"


@pytest.mark.parametrize("target", [date(2026, 3, 8), date(2026, 11, 1), date(2027, 1, 1)])
def test_resume_backfills_all_expected_local_dates_across_dst_and_year(config, tmp_path, environment, target):
    start = target - timedelta(days=2)
    now = planned(config, target) - timedelta(minutes=1)
    call(config, tmp_path, environment, now, start=start)
    values = state(config, tmp_path)["slots"]
    assert list(values) == [f"{start}/sunset", f"{start + timedelta(days=1)}/sunset", f"{target}/sunset"]
    assert [value["status"] for value in values.values()] == ["missed", "missed", "pending"]
    assert environment.seen == []
    assert call(config, tmp_path, environment, planned(config, target), start=start)["status"] == "success"


def test_utc_midnight_does_not_create_next_local_date(config, tmp_path, environment):
    now = datetime(2026, 10, 5, 1, tzinfo=timezone.utc)  # Still October 4 in NYC.
    call(config, tmp_path, environment, now, start=date(2026, 10, 4))
    assert list(state(config, tmp_path)["slots"]) == ["2026-10-04/sunset"]
    assert slot(config, tmp_path)["status"] == "missed"


def test_long_lead_schedules_event_more_than_one_local_day_ahead(config, tmp_path, environment):
    config["lead_minutes"] = 3000
    target = date(2026, 10, 6)
    due = planned(config, target)
    result = call(config, tmp_path, environment, due, start=date(2026, 10, 4))
    assert result["target_date"] == target.isoformat()
    assert result["status"] == "success"
    assert environment.seen == [due]


def test_config_policy_and_activation_changes_never_reset_slot(config, tmp_path, environment):
    due = planned(config)
    call(config, tmp_path, environment, due)
    original = state(config, tmp_path)
    for kwargs in ({"max_attempts": 4}, {"retry_minutes": 6}, {"start": date(2026, 10, 3)}):
        with pytest.raises(ValueError):
            call(config, tmp_path, environment, due, **kwargs)
    with pytest.raises(ValueError, match="configuration changed"):
        call(dict(config, longitude=-74.01), tmp_path, environment, due)
    assert state(config, tmp_path) == original
    assert len(environment.seen) == 1


@pytest.mark.parametrize("kwargs", [{"retry_minutes": 1}, {"max_attempts": 0}, {"max_attempts": True}, {"retry_minutes": float("nan")}])
def test_invalid_policy_fails_before_output(config, tmp_path, environment, kwargs):
    with pytest.raises(ValueError):
        call(config, tmp_path, environment, planned(config), **kwargs)
    assert not list(tmp_path.iterdir())


def test_excessive_lead_fails_before_output(config, tmp_path, environment):
    with pytest.raises(ValueError, match="at most 7 days"):
        call(dict(config, lead_minutes=10081), tmp_path, environment, datetime(2026, 10, 4, tzinfo=timezone.utc))
    assert not list(tmp_path.iterdir())


def test_lock_held_worker_prevents_duplicate_provider_call(config, tmp_path, environment):
    directory = tmp_path / config["id"]
    with runner._site_lock(directory) as acquired:
        assert acquired
        assert call(config, tmp_path, environment, planned(config))["action"] == "locked"
    assert environment.seen == []
    assert call(config, tmp_path, environment, planned(config))["status"] == "success"


def test_interrupted_worker_preserves_started_attempt_and_bounded_retry(config, tmp_path, environment):
    due = planned(config)
    environment.interrupt = True
    with pytest.raises(KeyboardInterrupt):
        call(config, tmp_path, environment, due)
    entry = slot(config, tmp_path)["attempts"][0]
    path = tmp_path / config["id"] / entry["attempt_path"]
    assert json.loads(path.read_text())["status"] == "started"
    original = path.read_bytes()
    environment.interrupt = False
    assert call(config, tmp_path, environment, due + timedelta(minutes=1))["action"] == "idle"
    assert slot(config, tmp_path)["attempts"][0]["status"] == "interrupted"
    assert call(config, tmp_path, environment, due + timedelta(minutes=5))["status"] == "success"
    assert len(slot(config, tmp_path)["attempts"]) == 2
    assert path.read_bytes() == original


def test_finished_capture_recovers_after_crash_without_new_request(config, tmp_path, environment, monkeypatch):
    due = planned(config)
    finish = runner._finish_entry
    monkeypatch.setattr(runner, "_finish_entry", lambda *args: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        call(config, tmp_path, environment, due)
    monkeypatch.setattr(runner, "_finish_entry", finish)
    assert call(config, tmp_path, environment, due + timedelta(minutes=1))["action"] == "idle"
    assert slot(config, tmp_path)["status"] == "success"
    assert len(environment.seen) == 1


def test_recovered_forecast_delivery_after_event_is_explicit(config, tmp_path, environment, monkeypatch):
    due = planned(config)
    finish = runner._finish_entry
    monkeypatch.setattr(runner, "_finish_entry", lambda *args: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        call(config, tmp_path, environment, due)
    monkeypatch.setattr(runner, "_finish_entry", finish)
    after = datetime.fromisoformat(schedule(config)["event_time_utc"]) + timedelta(minutes=1)
    call(config, tmp_path, environment, after)
    assert slot(config, tmp_path)["status"] == "late_delivery"
    assert runner.status(config, tmp_path, now=after)["latest"]["delivered_before_event"] is False
    assert len(environment.seen) == 1


def test_generation_completing_after_event_is_never_delivered(config, tmp_path, environment):
    environment.delay = 3 * 60 * 60
    assert call(config, tmp_path, environment, planned(config))["status"] == "late_completion"
    assert not (tmp_path / config["id"] / "latest.json").exists()
    assert runner.status(config, tmp_path, now=environment.now)["latest"] is None


@pytest.mark.parametrize("artifact", ["image", "metadata", "attempt"])
def test_artifact_tampering_revokes_delivery_without_overwriting_archive(config, tmp_path, environment, artifact):
    due = planned(config)
    result = call(config, tmp_path, environment, due)
    directory = tmp_path / config["id"]
    pointer = json.loads((directory / "latest.json").read_text())
    path = directory / pointer[artifact]
    path.write_bytes(b"corrupted archive")
    assert runner.status(config, tmp_path, now=due)["latest"] is None
    call(config, tmp_path, environment, due + timedelta(minutes=1))
    assert slot(config, tmp_path)["delivery_status"] == "failed"
    assert not (directory / "latest.json").exists()
    assert path.read_bytes() == b"corrupted archive"
    assert len(environment.seen) == 1


@pytest.mark.parametrize("field", ["condition_index", "image", "event_time_utc", "delivered_utc"])
def test_pointer_tampering_is_detected(config, tmp_path, environment, field):
    due = planned(config)
    call(config, tmp_path, environment, due)
    path = tmp_path / config["id"] / "latest.json"
    pointer = json.loads(path.read_text())
    pointer[field] = 0.99 if field == "condition_index" else "untrusted"
    path.write_text(json.dumps(pointer))
    assert runner.status(config, tmp_path, now=due)["latest"] is None
    call(config, tmp_path, environment, due + timedelta(minutes=1))
    assert not path.exists()


@pytest.mark.parametrize("invalid", ["image", "metadata"])
def test_invalid_product_never_delivered(config, tmp_path, environment, invalid):
    environment.invalid_image = invalid == "image"
    environment.wrong_metadata = invalid == "metadata"
    call(config, tmp_path, environment, planned(config))
    assert slot(config, tmp_path)["generation_status"] == "integrity_failed"
    assert not (tmp_path / config["id"] / "latest.json").exists()


def test_yesterdays_valid_forecast_is_marked_stale(config, tmp_path, environment):
    due = planned(config)
    call(config, tmp_path, environment, due)
    tomorrow = due + timedelta(days=1)
    result = runner.status(config, tmp_path, now=tomorrow)
    assert result["latest"]["is_current_date"] is False
    assert result["latest"]["event_has_passed"] is True
    assert result["current_slot"] is None


def test_preview_is_separate_from_primary_schedule_and_has_own_delivery(config, tmp_path, environment):
    due = planned(config)
    environment.now = due - timedelta(hours=1)
    preview_path = runner.preview(config, tmp_path, target=date(2026, 10, 4))
    directory = tmp_path / "previews" / config["id"]
    assert (directory / "preview_latest.json").exists()
    assert (directory / "preview_latest.md").exists()
    assert "preview" in (directory / "preview_latest.md").read_text()
    assert not (tmp_path / config["id"] / "runner-state.json").exists()
    assert call(config, tmp_path, environment, due)["status"] == "success"
    assert len(environment.seen) == 2
    assert preview_path.exists()


def test_free_space_guard_blocks_provider_and_preserves_failure(config, tmp_path, environment, monkeypatch):
    monkeypatch.setattr(runner.shutil, "disk_usage", lambda path: SimpleNamespace(free=999_999_999))
    call(config, tmp_path, environment, planned(config))
    value = slot(config, tmp_path)
    assert value["generation_status"] == "failed"
    assert "less than 1 GB" in value["error"]["message"]
    assert environment.seen == []


def test_cache_cleanup_is_opt_in_bounded_and_preserves_forecasts(config, tmp_path, environment, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "research/data/cache/gfs"
    root.mkdir(parents=True)
    old = root / "old.grib2"
    current = root / "current.grib2"
    old.write_bytes(b"old")
    current.write_bytes(b"current")
    due = planned(config)
    os.utime(old, (due.timestamp() - 15 * 86400,) * 2)
    os.utime(current, (due.timestamp(),) * 2)
    output = tmp_path / "forecasts"
    call(config, output, environment, due, cache_root=root)
    assert not old.exists()
    assert current.read_bytes() == b"current"
    assert slot(config, output)["status"] == "success"
    assert list((output / config["id"] / "2026-10-04").rglob("point.png"))


def test_cache_symlink_fails_closed_without_deletion(config, tmp_path, environment, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "research/data/cache/gfs"
    root.mkdir(parents=True)
    external = tmp_path / "keep.grib2"
    external.write_bytes(b"keep")
    (root / "link").symlink_to(external)
    call(config, tmp_path / "forecasts", environment, planned(config), cache_root=root)
    assert external.read_bytes() == b"keep"
    assert slot(config, tmp_path / "forecasts")["generation_status"] == "failed"
    assert environment.seen == []


def test_unrelated_cache_root_is_rejected_before_output(config, tmp_path, environment):
    with pytest.raises(ValueError, match="current working directory"):
        call(config, tmp_path, environment, planned(config), cache_root=tmp_path / "unrelated")
    assert not list(tmp_path.iterdir())


def test_retry_crossing_local_midnight_keeps_original_event_slot(config, tmp_path, environment):
    target = date(2026, 10, 5)
    event = pilot._event(pilot._validate_viewpoint(config), target)
    due = datetime(2026, 10, 4, 23, 58, tzinfo=ZoneInfo(config["timezone"])).astimezone(timezone.utc)
    config["lead_minutes"] = (event - due).total_seconds() / 60
    environment.fail = True
    assert call(config, tmp_path, environment, due, start=date(2026, 10, 4))["status"] == "retry_wait"
    environment.fail = False
    retry = due + timedelta(minutes=5, seconds=3)
    result = call(config, tmp_path, environment, retry, start=date(2026, 10, 4))
    assert result["target_date"] == "2026-10-05"
    assert result["status"] == "success"
    assert environment.seen == [due, retry]
    assert len(slot(config, tmp_path, target)["attempts"]) == 2
    assert slot(config, tmp_path, date(2026, 10, 4))["status"] == "missed"


def test_delivery_failure_retries_delivery_without_new_forecast(config, tmp_path, environment, monkeypatch):
    due = planned(config)
    write = runner._atomic_text
    monkeypatch.setattr(runner, "_atomic_text", lambda *args: (_ for _ in ()).throw(OSError("synthetic delivery error")))
    assert call(config, tmp_path, environment, due)["status"] == "delivery_failed"
    assert slot(config, tmp_path)["generation_status"] == "success"
    monkeypatch.setattr(runner, "_atomic_text", write)
    assert call(config, tmp_path, environment, due + timedelta(minutes=1))["action"] == "idle"
    assert slot(config, tmp_path)["status"] == "success"
    assert len(environment.seen) == 1


def test_preview_verification_failure_does_not_report_delivery_success(config, tmp_path, environment):
    environment.now = planned(config)
    environment.invalid_image = True
    with pytest.raises(ValueError, match="preview delivery failed"):
        runner.preview(config, tmp_path, target=date(2026, 10, 4))
    assert not list(tmp_path.rglob("preview_latest.json"))
    assert list(tmp_path.rglob("attempt.json"))


def test_spaces_in_output_have_valid_absolute_markdown_targets(config, tmp_path, environment):
    output = tmp_path / "Application Support" / "forecast data"
    call(config, output, environment, planned(config))
    text = (output / config["id"] / "latest.md").read_text()
    pointer = json.loads((output / config["id"] / "latest.json").read_text())
    image = (output / config["id"] / pointer["image"]).resolve()
    assert f"![Forecast map](<{image}>)" in text


def test_runner_cli_defaults_do_not_depend_on_observation_workflow():
    args = runner.build_parser().parse_args(["status"])
    assert args.config == Path(".local/forecast-service/viewpoint.json")
    assert args.output == Path("output/forecasts")
