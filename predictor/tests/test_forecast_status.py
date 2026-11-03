"""Read-only status reports distinguish scheduling, usable results, and model data."""
import json
from datetime import date, timedelta
from pathlib import Path

import pytest

import predictor.forecast_runner as runner
import predictor.forecast_status as reports
import predictor.observation_pilot as pilot
from predictor.tests.test_forecast_runner import config, environment, planned, call, schedule


def files(root):
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def config_file(tmp_path, config):
    path = tmp_path / "viewpoint.json"
    path.write_text(json.dumps(config))
    return path


def test_not_initialized_report_is_read_only_and_does_not_request_weather(config, tmp_path, environment):
    text = reports.render_status(config, tmp_path, now=planned(config))
    assert "no runner record" in text
    assert "Last scheduler tick: not recorded" in text
    assert "unavailable result, not a zero" in text
    assert "Status checked:" in text
    assert not list(tmp_path.iterdir())
    assert environment.seen == []


def test_pending_report_has_due_event_and_snapshot_times_without_changing_state(config, tmp_path, environment):
    now = planned(config) - timedelta(minutes=10)
    call(config, tmp_path, environment, now)
    original = files(tmp_path)
    text = reports.render_status(config, tmp_path, now=now + timedelta(minutes=2))
    assert "**waiting for the planned request** (stored status: pending)" in text
    assert "Planned request for today's event:" in text
    assert "final permitted request:" in text
    assert "2.0 minutes" in text
    assert "does not establish live service health" in text
    assert "UTC" in text and "EDT" in text
    assert files(tmp_path) == original
    assert environment.seen == []


def test_expired_pending_record_is_described_without_reconciling_or_reforecasting(config, tmp_path, environment):
    due = planned(config)
    call(config, tmp_path, environment, due - timedelta(minutes=1))
    original = files(tmp_path)
    text = reports.render_status(config, tmp_path, now=due + timedelta(minutes=16))
    assert "stored status: pending" in text
    assert "request window has expired" in text
    assert "stored status has not been reconciled" in text
    assert files(tmp_path) == original
    assert environment.seen == []


def test_zero_is_a_valid_index_with_original_request_and_discrete_weather_time(config, tmp_path, environment, monkeypatch):
    due = planned(config)
    generate = pilot._generate_product

    def zero_product(*args, **kwargs):
        artifacts = generate(*args, **kwargs)
        path = artifacts.metadata_path
        metadata = json.loads(path.read_text())
        metadata["condition_index"]["center_value"] = 0.0
        metadata["center_diagnostics"] = {
            "stage": "model_before_nowcast", "gate_score": 0.0, "modifier_score": 0.43,
            "components": {"sunward_illumination": 0.0},
            "inputs": {"cloud_low_pct": 100, "cloud_high_pct": 100},
        }
        path.write_text(json.dumps(metadata))
        return artifacts

    monkeypatch.setattr(pilot, "_generate_product", zero_product)
    call(config, tmp_path, environment, due)
    original = files(tmp_path)
    text = reports.render_status(config, tmp_path, now=due + timedelta(minutes=1))
    assert "**0.000**" in text
    assert "unavailable result, not a zero" not in text
    assert "GFS selected weather-valid time:" in text
    assert "7:00:00 PM EDT" in text
    assert "the selected model hour, separate from the solar-event time" in text
    assert "Model diagnostics before satellite correction" in text
    assert "Sunward illumination factor: 0.00" in text
    assert "Retained model gate score: 0.00" in text
    assert "Retained model modifier score: 0.43" in text
    assert "internal scoring terms, not probabilities" in text
    assert "Modeled low-cloud cover: 100%" in text
    assert "Requested:" in text and "Completed:" in text
    assert text.index("![Forecast map]") < text.index("## Model details and source times")
    assert "not a statistical probability" in text
    assert "Terrain elevation provider: not recorded" in text
    assert files(tmp_path) == original
    assert len(environment.seen) == 1


def test_previous_result_and_failed_today_are_both_visible(config, tmp_path, environment):
    due = planned(config)
    call(config, tmp_path, environment, due)
    tomorrow = planned(config, date(2026, 10, 5))
    environment.fail = True
    call(config, tmp_path, environment, tomorrow)
    original = files(tmp_path)
    text = reports.render_status(config, tmp_path, now=tomorrow + timedelta(minutes=1))
    assert "waiting for a retry" in text
    assert "a previous event date" in text
    assert "event has already passed" in text
    assert "Next recorded retry:" in text
    assert "synthetic provider unavailable" in text
    assert files(tmp_path) == original
    assert len(environment.seen) == 2


def test_corrupted_original_produces_no_index_or_diagnostics(config, tmp_path, environment):
    due = planned(config)
    call(config, tmp_path, environment, due)
    latest = runner.status(config, tmp_path, now=due)["latest"]
    (tmp_path / config["id"] / latest["image"]).write_bytes(b"invalid original")
    original = files(tmp_path)
    text = reports.render_status(config, tmp_path, now=due)
    assert "Delivery verification failed" in text
    assert "No verified scheduled forecast" in text
    assert "Condition index:" not in text
    assert "Model diagnostics" not in text
    assert runner.status(config, tmp_path, now=due, include_details=True)["details"] is None
    assert files(tmp_path) == original


@pytest.mark.parametrize("target, abbreviation", [(date(2026, 3, 7), "EST"), (date(2026, 3, 8), "EDT"), (date(2026, 11, 1), "EST")])
def test_human_times_use_local_dst_and_keep_utc(config, tmp_path, environment, target, abbreviation):
    due = planned(config, target)
    call(config, tmp_path, environment, due, start=target)
    text = reports.render_status(config, tmp_path, now=due)
    assert abbreviation in text
    assert "UTC" in text
    assert target.strftime("%d %b %Y") in text
    assert "today's event date" in text


def test_setup_preview_is_never_a_scheduled_result(config, tmp_path, environment):
    due = planned(config)
    environment.now = due - timedelta(hours=1)
    runner.preview(config, tmp_path, target=date(2026, 10, 4))
    call(config, tmp_path, environment, due - timedelta(minutes=1))
    text = reports.render_status(config, tmp_path, now=due - timedelta(minutes=1))
    assert "No verified scheduled forecast" in text
    assert "Setup previews are extra requests" in text
    assert "Condition index:" not in text
    assert len(environment.seen) == 1


def test_default_status_json_is_unchanged_and_text_cli_writes_nothing(config, tmp_path, environment, capsys):
    config_path = config_file(tmp_path, config)
    output = tmp_path / "output"
    environment.now = planned(config) - timedelta(minutes=1)
    call(config, output, environment, environment.now)
    original = files(tmp_path)
    argv = ["status", "--config", str(config_path), "--output", str(output)]
    assert runner.main(argv) == 0
    payload = json.loads(capsys.readouterr().out)
    assert "details" not in payload
    assert payload == runner.status(config, output, now=environment.now)
    assert runner.main(argv + ["--format", "text"]) == 0
    assert "Status checked:" in capsys.readouterr().out
    assert files(tmp_path) == original
    assert environment.seen == []


def test_cli_tick_writes_separate_snapshot_without_changing_canonical_latest(config, tmp_path, environment, capsys):
    config_path = config_file(tmp_path, config)
    output = tmp_path / "output"
    environment.now = planned(config)
    argv = ["tick", "--config", str(config_path), "--output", str(output)]
    assert runner.main(argv) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "success"
    directory = output / config["id"]
    assert (directory / "status.md").exists()
    canonical = {path.name: path.read_bytes() for path in (directory / "latest.json", directory / "latest.md")}
    environment.now += timedelta(minutes=5)
    assert runner.main(argv) == 0
    assert json.loads(capsys.readouterr().out)["action"] == "idle"
    assert canonical == {path.name: path.read_bytes() for path in (directory / "latest.json", directory / "latest.md")}
    assert len(environment.seen) == 1


def test_cli_locked_tick_skips_status_snapshot(config, tmp_path, environment, capsys):
    config_path = config_file(tmp_path, config)
    output = tmp_path / "output"
    with runner._site_lock(output / config["id"]):
        assert runner.main(["tick", "--config", str(config_path), "--output", str(output)]) == 0
    assert json.loads(capsys.readouterr().out)["action"] == "locked"
    assert not (output / config["id"] / "status.md").exists()
    assert environment.seen == []


def test_report_write_failure_preserves_success_and_next_tick_retries(config, tmp_path, environment, monkeypatch, capsys):
    config_path = config_file(tmp_path, config)
    output = tmp_path / "output"
    environment.now = planned(config)
    writer = reports.write_status_report
    monkeypatch.setattr(reports, "write_status_report", lambda *args: (_ for _ in ()).throw(OSError("synthetic report disk error")))
    argv = ["tick", "--config", str(config_path), "--output", str(output)]
    assert runner.main(argv) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["status"] == "success"
    assert "Forecast status report could not be saved" in captured.err
    directory = output / config["id"]
    original_latest = (directory / "latest.json").read_bytes()
    monkeypatch.setattr(reports, "write_status_report", writer)
    environment.now += timedelta(minutes=5)
    assert runner.main(argv) == 0
    assert (directory / "status.md").exists()
    assert (directory / "latest.json").read_bytes() == original_latest
    assert len(environment.seen) == 1


def test_missing_model_metadata_is_unknown_not_false(config, tmp_path, environment):
    due = planned(config)
    call(config, tmp_path, environment, due)
    text = reports.render_status(config, tmp_path, now=due)
    assert "Model diagnostics: not recorded" in text
    assert "Terrain elevation provider: not recorded" in text
    assert "Per-column aerosol provider: not recorded" in text
    assert "Weather model identity: not recorded" in text


def test_satellite_adjusted_result_is_separate_from_model_diagnostics(config, tmp_path, environment, monkeypatch):
    generate = pilot._generate_product

    def corrected_product(*args, **kwargs):
        artifacts = generate(*args, **kwargs)
        path = artifacts.metadata_path
        metadata = json.loads(path.read_text())
        metadata["condition_index"]["center_value"] = 0.7
        metadata["center_diagnostics"] = {
            "stage": "model_before_nowcast", "condition_index": 0.0,
            "components": {"sunward_illumination": 0.0},
        }
        metadata["nowcast"] = {"applied": True}
        path.write_text(json.dumps(metadata))
        return artifacts

    monkeypatch.setattr(pilot, "_generate_product", corrected_product)
    due = planned(config)
    call(config, tmp_path, environment, due)
    text = reports.render_status(config, tmp_path, now=due)
    assert "**0.700**" in text
    assert "Sunward illumination factor: 0.00" in text
    assert "Satellite correction was applied to the delivered field" in text
    assert "diagnostics describe the model before that correction" in text


def test_report_render_failure_preserves_primary_outcome(config, tmp_path, environment, monkeypatch, capsys):
    config_path = config_file(tmp_path, config)
    output = tmp_path / "output"
    environment.now = planned(config)
    monkeypatch.setattr(reports, "render_status", lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("synthetic rendering failure")))
    assert runner.main(["tick", "--config", str(config_path), "--output", str(output)]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["status"] == "success"
    assert "synthetic rendering failure" in captured.err
    assert runner.status(config, output, now=environment.now)["latest"] is not None
    assert len(environment.seen) == 1
