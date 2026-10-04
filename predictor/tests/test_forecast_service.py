"""Offline checks for safe LaunchAgent preparation, never activation."""
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import plistlib
import subprocess

import pytest

from predictor import forecast_service as service


@pytest.fixture
def inputs(tmp_path):
    config = tmp_path / "viewpoint.json"
    config.write_text(json.dumps({
        "id": "example-city", "name": "Public city sample", "region": "us-nyc",
        "timezone": "America/New_York", "latitude": 40.7128, "longitude": -74.0060,
        "radius_km": 25, "resolution_deg": 0.1,
    }))
    modules = tmp_path / "pinned runtime"
    package = modules / "predictor"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "forecast_runner.py").write_text("# fixture only\n")
    working = tmp_path / "working"
    working.mkdir()
    executable = tmp_path / "venv" / "bin" / "python"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"not invoked by installer")
    executable.chmod(0o700)
    return dict(
        config_path=config, output_root=tmp_path / "private outputs", start=date(2026, 10, 4),
        python_path=executable, working_directory=working, module_path=modules,
        launch_agents_directory=tmp_path / "LaunchAgents",
    )


@pytest.fixture(autouse=True)
def no_processes(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("service preparation must not execute processes or activate jobs")
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)


def test_plan_is_read_only_and_preserves_exact_arguments(inputs):
    original = inputs["config_path"].read_bytes()
    plan = service.build_service_plan(**inputs)
    assert inputs["config_path"].read_bytes() == original
    assert not plan.plist_path.parent.exists()
    assert not inputs["output_root"].exists()
    assert plan.label == "org.firecloud.forecast.example-city"
    assert plan.properties["ProgramArguments"] == [
        str(inputs["python_path"]), "-m", "predictor.forecast_runner", "tick",
        "--config", str(inputs["config_path"]), "--output", str(inputs["output_root"]),
        "--start", "2026-10-04", "--max-attempts", "3", "--retry-minutes", "5",
    ]
    assert plan.properties["StartCalendarInterval"] == [{"Minute": m} for m in range(0, 60, 5)]
    assert plan.properties["RunAtLoad"] is True
    assert "KeepAlive" not in plan.properties
    assert plan.properties["WorkingDirectory"] == str(inputs["working_directory"])
    environment = plan.properties["EnvironmentVariables"]
    assert environment["PYTHONPATH"] == str(inputs["module_path"])
    assert environment["MPLBACKEND"] == "Agg"
    assert environment["PYTHONUNBUFFERED"] == "1"
    assert set(environment) == {"PYTHONPATH", "MPLBACKEND", "PYTHONUNBUFFERED", "MPLCONFIGDIR", "PATH"}


def test_xml_round_trip_handles_spaces_and_shell_metacharacters(inputs):
    output = inputs["output_root"].parent / "<&>$(`literal`)' archive"
    inputs["output_root"] = output
    plan = service.build_service_plan(**inputs)
    assert plistlib.loads(plan.plist_bytes()) == plan.properties
    assert str(output) in plan.properties["ProgramArguments"]
    assert b"&lt;&amp;&gt;" in plan.plist_bytes()
    assert b"/bin/sh" not in plan.plist_bytes()


def test_virtualenv_interpreter_symlink_is_not_resolved(inputs):
    base = inputs["python_path"].parent.parent.parent / "python3.11"
    base.write_bytes(b"base interpreter fixture")
    base.chmod(0o700)
    inputs["python_path"].unlink()
    inputs["python_path"].symlink_to(base)
    plan = service.build_service_plan(**inputs)
    assert plan.properties["ProgramArguments"][0] == str(inputs["python_path"])
    assert plan.properties["ProgramArguments"][0] != str(base)


@pytest.mark.parametrize("field", [
    "config_path", "output_root", "python_path", "module_path", "working_directory",
    "launch_agents_directory",
])
def test_relative_paths_are_rejected_before_writes(inputs, field):
    agents = inputs["launch_agents_directory"]
    inputs[field] = Path("relative")
    with pytest.raises(ValueError, match="absolute"):
        service.build_service_plan(**inputs)
    assert not agents.exists()


@pytest.mark.parametrize("field,value", [
    ("max_attempts", 0), ("max_attempts", True), ("max_attempts", 2.5),
    ("retry_minutes", -1), ("retry_minutes", False), ("retry_minutes", "5"), ("retry_minutes", 4),
    ("start", "2026-10-04"), ("start", datetime(2026, 10, 4, tzinfo=timezone.utc)),
])
def test_invalid_policy_rejected(inputs, field, value):
    inputs[field] = value
    with pytest.raises(ValueError):
        service.build_service_plan(**inputs)
    assert not inputs["output_root"].exists()


@pytest.mark.parametrize("change", ["missing", "not_executable", "wrong_name"])
def test_invalid_interpreter_rejected(inputs, change):
    if change == "missing":
        inputs["python_path"].unlink()
    elif change == "not_executable":
        inputs["python_path"].chmod(0o600)
    else:
        moved = inputs["python_path"].with_name("sh")
        inputs["python_path"].rename(moved)
        inputs["python_path"] = moved
    with pytest.raises(ValueError, match="Python interpreter"):
        service.build_service_plan(**inputs)


def test_missing_config_and_runner_package_rejected(inputs):
    inputs["config_path"].unlink()
    with pytest.raises(ValueError, match="readable file"):
        service.build_service_plan(**inputs)


def test_package_must_include_runner(inputs):
    (inputs["module_path"] / "predictor" / "forecast_runner.py").unlink()
    with pytest.raises(ValueError, match="forecast runner package"):
        service.build_service_plan(**inputs)


def test_foreign_cwd_package_cannot_shadow_pinned_runtime(inputs):
    (inputs["working_directory"] / "predictor").mkdir()
    with pytest.raises(ValueError, match="shadow"):
        service.build_service_plan(**inputs)
    inputs["working_directory"] = inputs["module_path"]
    service.build_service_plan(**inputs)


@pytest.mark.parametrize("field", ["output_root", "module_path", "working_directory", "launch_agents_directory"])
def test_directory_symlinks_rejected(inputs, field, tmp_path):
    link = tmp_path / f"{field}-link"
    target = inputs[field]
    target.mkdir(exist_ok=True)
    link.symlink_to(target, target_is_directory=True)
    inputs[field] = link
    with pytest.raises(ValueError, match="symbolic link"):
        service.build_service_plan(**inputs)


def test_install_is_idempotent_and_preserves_config(inputs):
    original = inputs["config_path"].read_bytes()
    plan = service.build_service_plan(**inputs)
    path = service.write_service_plan(plan)
    assert plistlib.loads(path.read_bytes()) == plan.properties
    assert path.stat().st_mode & 0o777 == 0o600
    stat = path.stat()
    assert service.write_service_plan(plan) == path
    assert path.stat().st_mtime_ns == stat.st_mtime_ns
    assert path.stat().st_ino == stat.st_ino
    assert inputs["config_path"].read_bytes() == original
    assert plan.log_directory.is_dir()
    assert plan.mpl_directory.is_dir()
    for directory in (inputs["output_root"], inputs["output_root"] / "example-city",
                      plan.log_directory.parent, plan.log_directory, plan.mpl_directory):
        assert directory.stat().st_mode & 0o777 == 0o700
    assert not list(path.parent.glob("*.tmp"))


@pytest.mark.parametrize("existing", [b"not plist", plistlib.dumps({"Label": "foreign"})])
def test_foreign_or_malformed_existing_job_never_overwritten(inputs, existing):
    plan = service.build_service_plan(**inputs)
    plan.plist_path.parent.mkdir()
    plan.plist_path.write_bytes(existing)
    with pytest.raises(ValueError):
        service.write_service_plan(plan)
    assert plan.plist_path.read_bytes() == existing
    assert not inputs["output_root"].exists()


def test_plist_symlink_is_not_followed(inputs, tmp_path):
    plan = service.build_service_plan(**inputs)
    plan.plist_path.parent.mkdir()
    original = tmp_path / "untouched"
    original.write_bytes(b"private file")
    plan.plist_path.symlink_to(original)
    with pytest.raises(ValueError, match="symbolic-link LaunchAgent"):
        service.write_service_plan(plan)
    assert original.read_bytes() == b"private file"


def test_atomic_collision_leaves_other_writer_untouched(inputs, monkeypatch):
    plan = service.build_service_plan(**inputs)
    real_link = os.link
    def collide(source, destination):
        Path(destination).write_bytes(b"concurrent writer")
        return real_link(source, destination)
    monkeypatch.setattr(os, "link", collide)
    with pytest.raises(FileExistsError):
        service.write_service_plan(plan)
    assert plan.plist_path.read_bytes() == b"concurrent writer"
    assert not list(plan.plist_path.parent.glob(".*.tmp"))


def test_control_characters_and_unsafe_id_fail_before_writes(inputs):
    data = json.loads(inputs["config_path"].read_text())
    data["id"] = "../../foreign"
    inputs["config_path"].write_text(json.dumps(data))
    with pytest.raises(ValueError, match="safe basename"):
        service.build_service_plan(**inputs)
    assert not inputs["output_root"].exists()


def test_installer_rejects_lead_outside_runner_horizon_before_writes(inputs):
    config = json.loads(inputs["config_path"].read_text())
    config["lead_minutes"] = 7 * 24 * 60 + 1
    inputs["config_path"].write_text(json.dumps(config))
    with pytest.raises(ValueError, match="at most 7 days"):
        service.build_service_plan(**inputs)
    assert not inputs["output_root"].exists()
    assert not inputs["launch_agents_directory"].exists()
    config["lead_minutes"] = 7 * 24 * 60
    inputs["config_path"].write_text(json.dumps(config))
    service.build_service_plan(**inputs)


def _cli(inputs, *, dry_run=False, command="install"):
    arguments = [
        command, "--config", str(inputs["config_path"]), "--output", str(inputs["output_root"]),
        "--start", inputs["start"].isoformat(), "--python", str(inputs["python_path"]),
        "--module-path", str(inputs["module_path"]),
        "--working-directory", str(inputs["working_directory"]),
        "--launch-agents-directory", str(inputs["launch_agents_directory"]),
    ]
    if dry_run:
        arguments.append("--dry-run")
    return arguments


def test_cli_dry_run_and_commands_have_no_filesystem_effect(inputs, capsys):
    assert service.main(_cli(inputs, dry_run=True)) == 0
    output = capsys.readouterr()
    assert plistlib.loads(output.out.encode())["Label"] == "org.firecloud.forecast.example-city"
    assert "activate: launchctl bootstrap gui/" in output.err
    assert "not activated" not in output.out  # No installation claim for a dry run.
    assert not inputs["output_root"].exists()
    assert not inputs["launch_agents_directory"].exists()
    assert service.main(_cli(inputs, command="commands")) == 0
    assert "status: launchctl print gui/" in capsys.readouterr().out
    assert not inputs["launch_agents_directory"].exists()


def test_cli_install_explicitly_reports_not_activated(inputs, capsys):
    assert service.main(_cli(inputs)) == 0
    assert "Prepared LaunchAgent (not activated)" in capsys.readouterr().out
    assert service.build_service_plan(**inputs).plist_path.exists()


def test_reviewable_launchctl_arguments(inputs):
    plan = service.build_service_plan(**inputs)
    commands = service.service_commands(plan, uid=501)
    assert commands["activate"] == ["launchctl", "bootstrap", "gui/501", str(plan.plist_path)]
    assert commands["run_now"] == ["launchctl", "kickstart", f"gui/501/{plan.label}"]
    assert commands["deactivate"] == ["launchctl", "bootout", f"gui/501/{plan.label}"]
    assert commands["remove_after_deactivation"] == ["rm", "--", str(plan.plist_path)]
    with pytest.raises(ValueError, match="uid"):
        service.service_commands(plan, uid=-1)


def test_cache_pruning_requires_explicit_owned_cache_root(inputs):
    plan = service.build_service_plan(**inputs)
    assert "--cache-root" not in plan.properties["ProgramArguments"]
    inputs["cache_root"] = inputs["working_directory"] / "research" / "data" / "cache" / "gfs"
    inputs["cache_retention_days"] = 14
    plan = service.build_service_plan(**inputs)
    assert plan.properties["ProgramArguments"][-4:] == [
        "--cache-root", str(inputs["cache_root"]), "--cache-retention-days", "14",
    ]
    assert not inputs["cache_root"].exists()


@pytest.mark.parametrize("value", [0, -1, True, 2.5])
def test_invalid_cache_retention_rejected(inputs, value):
    inputs["cache_root"] = inputs["working_directory"] / "research" / "data" / "cache" / "gfs"
    inputs["cache_retention_days"] = value
    with pytest.raises(ValueError, match="cache_retention_days"):
        service.build_service_plan(**inputs)
    assert not inputs["output_root"].exists()


def test_cache_root_cannot_select_project_or_forecast_archive(inputs):
    inputs["cache_root"] = inputs["output_root"]
    with pytest.raises(ValueError, match="default GFS cache"):
        service.build_service_plan(**inputs)


def test_owned_cache_ancestor_symlink_rejected(inputs, tmp_path):
    target = tmp_path / "foreign archive"
    target.mkdir()
    (inputs["working_directory"] / "research").symlink_to(target, target_is_directory=True)
    inputs["cache_root"] = inputs["working_directory"] / "research" / "data" / "cache" / "gfs"
    with pytest.raises(ValueError, match="symbolic link"):
        service.build_service_plan(**inputs)


def test_owned_service_ancestor_symlink_rejected(inputs, tmp_path):
    target = tmp_path / "foreign private folder"
    target.mkdir()
    inputs["output_root"].mkdir()
    (inputs["output_root"] / "example-city").symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match="symbolic link"):
        service.build_service_plan(**inputs)
    assert list(target.iterdir()) == []


def test_parent_changed_to_symlink_after_plan_rejected_on_write(inputs, tmp_path):
    plan = service.build_service_plan(**inputs)
    target = tmp_path / "foreign private folder"
    target.mkdir()
    inputs["launch_agents_directory"].symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match="symbolic link"):
        service.write_service_plan(plan)
    assert list(target.iterdir()) == []


def test_log_changed_to_symlink_after_plan_rejected_on_write(inputs, tmp_path):
    plan = service.build_service_plan(**inputs)
    plan.log_directory.mkdir(parents=True)
    original = tmp_path / "original private file"
    original.write_bytes(b"untouched")
    (plan.log_directory / "launchd.stdout.log").symlink_to(original)
    with pytest.raises(ValueError, match="ordinary files"):
        service.write_service_plan(plan)
    assert original.read_bytes() == b"untouched"
    assert not plan.plist_path.exists()
