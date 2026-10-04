"""Offline contracts for manual schedules and immutable forecast attempts."""
import csv
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

import predictor.observation_pilot as pilot


@pytest.fixture
def viewpoint():
    # Public city-center sample, never a private residence or observation site.
    return {
        "id": "example-city", "name": "Public city sample", "region": "us-nyc",
        "timezone": "America/New_York", "latitude": 40.7128, "longitude": -74.0060,
        "radius_km": 25, "resolution_deg": 0.1,
    }


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    revision_reader = pilot._source_revision
    def no_weather(*args, **kwargs):
        pytest.fail("offline tests must not start a weather provider")

    monkeypatch.setattr(pilot, "_generate_product", no_weather)
    monkeypatch.setattr(pilot, "_source_revision", lambda: None)
    return revision_reader


def _config_file(tmp_path, data):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _read_attempt(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _fake_product(*args, **kwargs):
    target, directory = args[:2]
    directory = Path(directory)
    image = directory / "point.png"
    sidecar = directory / "point.json"
    image.write_bytes(b"synthetic image fixture")
    metadata = {
        "target_date": target.isoformat(), "region": kwargs["region"],
        "condition_index": {"center_value": 0.42, "calibrated_probability": False},
        "center_diagnostics": {"stage": "model_before_nowcast", "gates": {"canvas": 0.8}},
        "gfs_timing": {"forecast_hour": 17, "valid_time_utc": "2026-10-04T23:00:00+00:00"},
        "provenance": {"weather": {"source": "synthetic", "selected_time_utc": "2026-10-04T23:00:00+00:00"}},
    }
    sidecar.write_text(json.dumps(metadata), encoding="utf-8")
    return SimpleNamespace(image_path=image, metadata_path=sidecar)


def test_load_viewpoint_normalizes_defaults_without_rewriting_config(tmp_path, viewpoint):
    original = dict(viewpoint, coordinate_reference="manual verification", camera={"fixed": True})
    path = _config_file(tmp_path, original)
    loaded = pilot.load_viewpoint(path)
    assert loaded["lead_minutes"] == 120
    assert loaded["lead_tolerance_minutes"] == 15
    assert loaded["solar_event"] == "sunset"
    assert json.loads(path.read_text()) == original


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", "../escape"), ("id", "/absolute"), ("id", ".."),
        ("id", "nested/site"), ("id", "site\\child"),
        ("latitude", float("nan")), ("longitude", float("inf")),
        ("latitude", True), ("latitude", 35), ("longitude", 285.994),
        ("timezone", "UTC"), ("region", "other"),
        ("radius_km", 0), ("resolution_deg", -0.1), ("resolution_deg", True),
        ("resolution_deg", 0.001), ("lead_minutes", 0), ("lead_minutes", True),
        ("lead_tolerance_minutes", -1), ("lead_tolerance_minutes", 120),
        ("solar_event", "noon"),
    ],
)
def test_invalid_config_fails_before_output_or_provider_access(tmp_path, viewpoint, field, value):
    invalid = dict(viewpoint, **{field: value})
    output = tmp_path / "output"
    with pytest.raises(ValueError):
        pilot.capture_forecast(invalid, date(2026, 10, 4), output)
    assert not output.exists()
    with pytest.raises(ValueError):
        pilot.load_viewpoint(_config_file(tmp_path, invalid))


@pytest.mark.parametrize("event", ["sunset", "sunrise"])
@pytest.mark.parametrize("start", [date(2026, 3, 7), date(2026, 10, 31)])
def test_schedule_preserves_civil_days_and_elapsed_lead_across_dst(viewpoint, start, event):
    rows = pilot.build_schedule(dict(viewpoint, solar_event=event), start, 3)
    offsets = set()
    for n, row in enumerate(rows):
        event_utc = datetime.fromisoformat(row["event_time_utc"])
        planned_utc = datetime.fromisoformat(row["planned_request_utc"])
        local_event = datetime.fromisoformat(row["event_time_local"])
        assert local_event.date() == start + timedelta(days=n)
        assert event_utc - planned_utc == timedelta(minutes=120)
        assert datetime.fromisoformat(row["planned_request_local"]).astimezone(timezone.utc) == planned_utc
        assert datetime.fromisoformat(row["window_end_utc"]) - planned_utc == timedelta(minutes=15)
        offsets.add(local_event.utcoffset())
    assert len(offsets) == 2


def test_plan_cli_writes_schedule_without_provider_or_revision_calls(
    tmp_path, viewpoint, monkeypatch, capsys
):
    def forbidden(*args, **kwargs):
        pytest.fail("planning must not call forecast or revision capture")

    monkeypatch.setattr(pilot, "_source_revision", forbidden)
    config = _config_file(tmp_path, viewpoint)
    output = tmp_path / "plans"
    assert pilot.main([
        "plan", "--config", str(config), "--start", "2026-10-04", "--days", "28",
        "--output", str(output),
    ]) == 0
    paths = list((output / viewpoint["id"]).glob("*.csv"))
    assert len(paths) == 1
    with paths[0].open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 28
    assert rows[0]["target_date"] == "2026-10-04"
    assert rows[-1]["target_date"] == "2026-10-31"
    assert "Manual capture schedule:" in capsys.readouterr().out


def test_schedule_never_overwrites_prior_schedule(tmp_path, viewpoint):
    first = pilot.write_schedule(viewpoint, date(2026, 10, 4), 1, tmp_path)
    content = first.read_bytes()
    second = pilot.write_schedule(viewpoint, date(2026, 10, 4), 1, tmp_path)
    assert second != first
    assert first.read_bytes() == content


def test_success_records_source_metadata_and_passes_request_to_existing_generator(
    tmp_path, viewpoint, monkeypatch
):
    request = datetime(2026, 10, 4, 20, 30, tzinfo=timezone.utc)
    seen = []

    def generate(*args, **kwargs):
        seen.append((args, kwargs))
        return _fake_product(*args, **kwargs)

    monkeypatch.setattr(pilot, "_generate_product", generate)
    monkeypatch.setattr(pilot, "_source_revision", lambda: "a" * 40)
    completed = request + timedelta(seconds=2.5)
    monkeypatch.setattr(pilot, "_utc_now", lambda: completed)
    ticks = iter([100.0, 102.5])
    monkeypatch.setattr(pilot.time, "monotonic", lambda: next(ticks))
    path = pilot.capture_forecast(viewpoint, date(2026, 10, 4), tmp_path, now=request)
    record = _read_attempt(path)
    assert record["status"] == "success"
    assert record["source_revision"] == "a" * 40
    assert record["working_tree_not_verified"] is True
    assert record["request_utc"] == request.isoformat()
    assert record["request_local"] == request.astimezone(ZoneInfo(viewpoint["timezone"])).isoformat()
    assert record["within_window"] is True
    assert record["record_type"] == "forecast"
    assert record["timing_status"] == "on_time"
    assert record["runtime_seconds"] == 2.5
    assert record["completion_utc"] == completed.isoformat()
    assert record["completion_time_semantics"] == "wall_clock_utc"
    assert record["product_available_before_event"] is True
    assert record["center_diagnostics"]["stage"] == "model_before_nowcast"
    assert record["source_timing"]["provenance"] == record["product_metadata"]["provenance"]
    assert record["product_metadata"]["condition_index"]["center_value"] == 0.42
    assert record["artifacts"] == {"image": "point.png", "metadata": "point.json"}
    args, kwargs = seen[0]
    assert args == (date(2026, 10, 4), path.parent, viewpoint["latitude"], viewpoint["longitude"])
    assert kwargs["region"] == "us-nyc"
    assert kwargs["now"] == request
    assert kwargs["satellite"] is False


def test_attempts_at_identical_request_time_preserve_prior_capture(tmp_path, viewpoint, monkeypatch):
    monkeypatch.setattr(pilot, "_generate_product", _fake_product)
    request = datetime(2026, 10, 4, 20, 30, tzinfo=timezone.utc)
    first = pilot.capture_forecast(viewpoint, date(2026, 10, 4), tmp_path, now=request)
    original = first.read_bytes()
    second = pilot.capture_forecast(viewpoint, date(2026, 10, 4), tmp_path, now=request)
    assert first.parent != second.parent
    assert first.read_bytes() == original
    assert _read_attempt(first)["attempt_id"] != _read_attempt(second)["attempt_id"]


def test_source_failure_is_saved_as_an_attempt(tmp_path, viewpoint, monkeypatch):
    def unavailable(*args, **kwargs):
        raise RuntimeError("synthetic source unavailable")

    monkeypatch.setattr(pilot, "_generate_product", unavailable)
    path = pilot.capture_forecast(
        viewpoint, date(2026, 10, 4), tmp_path,
        now=datetime(2026, 10, 4, 20, 30, tzinfo=timezone.utc),
    )
    record = _read_attempt(path)
    assert record["status"] == "failed"
    assert record["error"] == {"type": "RuntimeError", "message": "synthetic source unavailable"}
    assert record["artifacts"] == {}
    assert record["source_revision"] is None
    assert record["runtime_seconds"] >= 0
    assert record["product_available_before_event"] is False


def test_nonfinite_product_metadata_is_saved_as_failed_attempt(tmp_path, viewpoint, monkeypatch):
    def malformed(*args, **kwargs):
        artifacts = _fake_product(*args, **kwargs)
        artifacts.metadata_path.write_text('{"center_value": NaN}', encoding="utf-8")
        return artifacts

    monkeypatch.setattr(pilot, "_generate_product", malformed)
    path = pilot.capture_forecast(viewpoint, date(2026, 10, 4), tmp_path)
    record = _read_attempt(path)
    assert record["status"] == "failed"
    assert record["error"]["type"] == "ValueError"
    assert record["product_metadata"] is None


def test_before_event_request_finishing_late_is_not_available_for_prospective_comparison(
    tmp_path, viewpoint, monkeypatch
):
    monkeypatch.setattr(pilot, "_generate_product", _fake_product)
    event = datetime.fromisoformat(pilot.build_schedule(viewpoint, date(2026, 10, 4), 1)[0]["event_time_utc"])
    ticks = iter([0.0, 180.0])
    monkeypatch.setattr(pilot.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(pilot, "_utc_now", lambda: event + timedelta(minutes=2))
    path = pilot.capture_forecast(
        viewpoint, date(2026, 10, 4), tmp_path, now=event - timedelta(minutes=1),
    )
    record = _read_attempt(path)
    assert record["status"] == "success"
    assert record["record_type"] == "forecast"
    assert record["product_available_before_event"] is False
    assert datetime.fromisoformat(record["completion_utc"]) == event + timedelta(minutes=2)


def test_provider_sees_started_evidence_and_interrupt_leaves_incomplete_record(
    tmp_path, viewpoint, monkeypatch
):
    paths = []

    def interrupted(*args, **kwargs):
        path = Path(args[1]) / "attempt.json"
        paths.append(path)
        initial = _read_attempt(path)
        assert initial["status"] == "started"
        assert initial["completion_utc"] is None
        assert initial["product_available_before_event"] is None
        raise KeyboardInterrupt

    monkeypatch.setattr(pilot, "_generate_product", interrupted)
    with pytest.raises(KeyboardInterrupt):
        pilot.capture_forecast(viewpoint, date(2026, 10, 4), tmp_path)
    assert len(paths) == 1
    assert _read_attempt(paths[0])["status"] == "started"
    assert not list(paths[0].parent.glob("*.tmp"))


def test_injected_request_does_not_fabricate_wall_clock_completion(
    tmp_path, viewpoint, monkeypatch
):
    monkeypatch.setattr(pilot, "_generate_product", _fake_product)
    request = datetime(2026, 10, 4, 20, tzinfo=timezone.utc)
    actual_completion = request + timedelta(minutes=3)
    monkeypatch.setattr(pilot, "_utc_now", lambda: actual_completion)
    ticks = iter([0.0, 1.5])
    monkeypatch.setattr(pilot.time, "monotonic", lambda: next(ticks))
    path = pilot.capture_forecast(viewpoint, date(2026, 10, 4), tmp_path, now=request)
    record = _read_attempt(path)
    assert record["completion_utc"] == actual_completion.isoformat()
    assert record["runtime_seconds"] == 1.5
    assert record["completion_utc"] != (request + timedelta(seconds=1.5)).isoformat()


@pytest.mark.parametrize("matching_root", [True, False])
def test_revision_uses_only_the_source_checkout_root(monkeypatch, offline, matching_root):
    source_root = Path(pilot.__file__).resolve().parent.parent
    actual_root = source_root if matching_root else source_root.parent
    seen = []

    def git_probe(command, **kwargs):
        seen.append(kwargs["cwd"])
        return SimpleNamespace(stdout=f"{actual_root}\n{'a' * 40}\n")

    monkeypatch.setattr(pilot.subprocess, "run", git_probe)
    assert offline() == ("a" * 40 if matching_root else None)
    assert seen == [source_root]


def test_revision_is_unavailable_outside_matching_source_layout(monkeypatch, tmp_path, offline):
    monkeypatch.setattr(pilot, "__file__", str(tmp_path / "installed" / "observation_pilot.py"))

    def forbidden_probe(*args, **kwargs):
        pytest.fail("unrelated source layouts must not probe their surrounding Git repo")

    monkeypatch.setattr(pilot.subprocess, "run", forbidden_probe)
    assert offline() is None


@pytest.mark.parametrize(
    ("lead", "timing", "record_type", "within"),
    [(180, "early", "forecast", False), (120, "on_time", "forecast", True),
     (90, "late", "forecast", False), (-5, "after_event", "after_event", False)],
)
def test_early_late_and_after_event_records_are_distinguished(
    tmp_path, viewpoint, monkeypatch, lead, timing, record_type, within
):
    monkeypatch.setattr(pilot, "_generate_product", _fake_product)
    event = datetime.fromisoformat(pilot.build_schedule(viewpoint, date(2026, 10, 4), 1)[0]["event_time_utc"])
    path = pilot.capture_forecast(
        viewpoint, date(2026, 10, 4), tmp_path, now=event - timedelta(minutes=lead),
    )
    record = _read_attempt(path)
    assert record["actual_lead_minutes"] == pytest.approx(lead)
    assert record["record_type"] == record_type
    assert record["timing_status"] == timing
    assert record["within_window"] is within


def test_default_target_date_uses_viewpoint_day_at_utc_midnight(tmp_path, viewpoint, monkeypatch):
    monkeypatch.setattr(pilot, "_generate_product", _fake_product)
    path = pilot.capture_forecast(
        viewpoint, output_root=tmp_path,
        now=datetime(2026, 6, 22, 0, 15, tzinfo=timezone.utc),
    )
    record = _read_attempt(path)
    assert record["target_date"] == "2026-06-21"
    assert datetime.fromisoformat(record["event_time_utc"]).date() == date(2026, 6, 22)
    assert path.parent.parent.name == "2026-06-21"


def test_naive_request_is_rejected_before_output(tmp_path, viewpoint):
    with pytest.raises(ValueError, match="timezone-aware"):
        pilot.capture_forecast(viewpoint, output_root=tmp_path / "output", now=datetime(2026, 10, 4, 16))
    assert not (tmp_path / "output").exists()


def test_forecast_cli_defaults_use_local_config_and_failure_exit_status(
    tmp_path, viewpoint, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    config = tmp_path / pilot.DEFAULT_CONFIG
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps(viewpoint), encoding="utf-8")

    def unavailable(*args, **kwargs):
        raise RuntimeError("synthetic source unavailable")

    monkeypatch.setattr(pilot, "_generate_product", unavailable)
    assert pilot.main(["forecast"]) == 1
    paths = list((tmp_path / pilot.DEFAULT_OUTPUT / viewpoint["id"]).glob("*/*/attempt.json"))
    assert len(paths) == 1
    assert "Forecast attempt (failed," in capsys.readouterr().out


@pytest.mark.parametrize("days", [0, -1, True, 1.5])
def test_invalid_schedule_length_creates_no_output(tmp_path, viewpoint, days):
    with pytest.raises(ValueError, match="positive integer"):
        pilot.write_schedule(viewpoint, date(2026, 10, 4), days, tmp_path / "output")
    assert not (tmp_path / "output").exists()
