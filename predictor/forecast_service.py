"""Prepare a macOS LaunchAgent for deterministic local forecast delivery.

Preparation does not load or activate a job. A user agent requires a logged-in
user, an awake computer, and access to the configured files and weather sources.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime
import os
from pathlib import Path
import plistlib
import re
import shlex
import sys
from uuid import uuid4

from predictor.observation_pilot import load_viewpoint
from predictor.forecast_runner import validate_runner_config


LABEL_PREFIX = "org.firecloud.forecast."
_PYTHON_NAME = re.compile(r"python(?:\d+(?:\.\d+)*)?\Z")


@dataclass(frozen=True)
class ServicePlan:
    """Validated arguments and paths; the plan itself has no write side effects."""

    label: str
    plist_path: Path
    output_root: Path
    log_directory: Path
    mpl_directory: Path
    properties: dict

    def plist_bytes(self) -> bytes:
        return plistlib.dumps(self.properties, fmt=plistlib.FMT_XML, sort_keys=False)


def _absolute(path: str | Path, field: str) -> Path:
    # Do not resolve the interpreter symlink: virtualenv discovery depends on
    # invoking its bin/python path, not the underlying managed base interpreter.
    value = Path(path).expanduser()
    if not value.is_absolute() or any(ord(c) < 32 for c in str(value)):
        raise ValueError(f"{field} must be an absolute path without control characters")
    return value.absolute()


def _positive_integer(value: int, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _check_directory(path: Path, field: str, *, required: bool = False) -> None:
    if path.is_symlink():
        raise ValueError(f"{field} must not be a symbolic link")
    if path.exists() and not path.is_dir():
        raise ValueError(f"{field} must be a directory")
    if required and not path.is_dir():
        raise ValueError(f"{field} must be an existing directory")


def build_service_plan(
    config_path: str | Path,
    output_root: str | Path,
    start: date,
    *,
    python_path: str | Path | None = None,
    working_directory: str | Path | None = None,
    module_path: str | Path | None = None,
    launch_agents_directory: str | Path | None = None,
    max_attempts: int = 3,
    retry_minutes: int = 5,
    cache_root: str | Path | None = None,
    cache_retention_days: int = 14,
) -> ServicePlan:
    """Validate the service without creating files or contacting providers.

    module_path is the import root of a checked-out or separately installed
    predictor package. Set it to a pinned wheel installation for stable service
    code when the development checkout can change branches.
    """
    if isinstance(start, datetime) or not isinstance(start, date):
        raise ValueError("start must be a calendar date")
    attempts = _positive_integer(max_attempts, "max_attempts")
    retry = _positive_integer(retry_minutes, "retry_minutes")
    if retry < 5:
        raise ValueError("retry_minutes must be at least 5 for the five-minute service schedule")
    config = _absolute(config_path, "config")
    if not config.is_file() or not os.access(config, os.R_OK):
        raise ValueError("config must be a readable file")
    site = validate_runner_config(load_viewpoint(config))
    if site["lead_tolerance_minutes"] < 5:
        raise ValueError("lead_tolerance_minutes must be at least 5 for the five-minute service schedule")
    executable = _absolute(python_path or sys.executable, "python")
    if (_PYTHON_NAME.fullmatch(executable.name) is None
            or not executable.is_file() or not os.access(executable, os.X_OK)):
        raise ValueError("python must identify an existing executable Python interpreter")
    modules = _absolute(module_path or Path(__file__).absolute().parent.parent, "module_path")
    _check_directory(modules, "module_path", required=True)
    _check_directory(modules / "predictor", "predictor_package", required=True)
    if not all((modules / "predictor" / name).is_file()
               for name in ("__init__.py", "forecast_runner.py")):
        raise ValueError("module_path must contain the predictor forecast runner package")
    working = _absolute(working_directory or modules, "working_directory")
    _check_directory(working, "working_directory", required=True)
    # Python searches the working directory before PYTHONPATH. Reject a second
    # predictor package which would silently replace the pinned installation.
    if ((working / "predictor").exists() or (working / "predictor").is_symlink()) and working != modules:
        raise ValueError("working_directory would shadow module_path with another predictor package")
    cache_arguments = []
    if cache_root is not None:
        cache = _absolute(cache_root, "cache_root")
        if cache != working / "research" / "data" / "cache" / "gfs":
            raise ValueError("cache_root must match the default GFS cache under working_directory")
        retention = _positive_integer(cache_retention_days, "cache_retention_days")
        current = working
        for component in ("research", "data", "cache", "gfs"):
            current = current / component
            _check_directory(current, "cache_directory")
        cache_arguments = ["--cache-root", str(cache), "--cache-retention-days", str(retention)]
    output = _absolute(output_root, "output")
    _check_directory(output, "output")
    agents = _absolute(
        launch_agents_directory or Path.home() / "Library" / "LaunchAgents",
        "launch_agents_directory",
    )
    _check_directory(agents, "launch_agents_directory")
    log_directory = output / site["id"] / "service" / "logs"
    mpl_directory = output / site["id"] / "service" / "matplotlib"
    for directory in (output / site["id"], log_directory.parent, log_directory, mpl_directory):
        _check_directory(directory, "service_directory")
    stdout = log_directory / "launchd.stdout.log"
    stderr = log_directory / "launchd.stderr.log"
    for path in (stdout, stderr):
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError("log paths must be ordinary files or absent")
    label = LABEL_PREFIX + site["id"]
    properties = {
        "Label": label,
        "ProgramArguments": [
            str(executable), "-m", "predictor.forecast_runner", "tick",
            "--config", str(config), "--output", str(output),
            "--start", start.isoformat(), "--max-attempts", str(attempts),
            "--retry-minutes", str(retry),
        ] + cache_arguments,
        "WorkingDirectory": str(working),
        "EnvironmentVariables": {
            "MPLBACKEND": "Agg", "PYTHONUNBUFFERED": "1",
            "PYTHONPATH": str(modules), "MPLCONFIGDIR": str(mpl_directory),
            "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        },
        "StartCalendarInterval": [{"Minute": minute} for minute in range(0, 60, 5)],
        "RunAtLoad": True,
        "ProcessType": "Background",
        "Umask": "077",
        "StandardOutPath": str(stdout), "StandardErrorPath": str(stderr),
    }
    return ServicePlan(label, agents / f"{label}.plist", output, log_directory, mpl_directory, properties)


def _mkdir_private(path: Path) -> None:
    """Create new private directories without changing existing directory modes."""
    if path.exists():
        _check_directory(path, "service_directory", required=True)
        return
    if path.is_symlink():
        raise ValueError("service_directory must not be a symbolic link")
    _mkdir_private(path.parent)
    path.mkdir(mode=0o700)


def write_service_plan(plan: ServicePlan) -> Path:
    """Create the plist without activating it or overwriting a different job.

    An identical existing job is preserved. A changed or unrelated existing job
    requires explicit removal after it is unloaded; preparation never replaces it.
    """
    path = plan.plist_path
    _check_directory(path.parent, "launch_agents_directory")
    for directory in (plan.output_root, plan.log_directory.parent.parent,
                      plan.log_directory.parent, plan.log_directory, plan.mpl_directory):
        _check_directory(directory, "service_directory")
    for key in ("StandardOutPath", "StandardErrorPath"):
        log = Path(plan.properties[key])
        if log.is_symlink() or (log.exists() and not log.is_file()):
            raise ValueError("log paths must be ordinary files or absent")
    if path.is_symlink():
        raise ValueError("refusing to replace a symbolic-link LaunchAgent")
    if path.exists():
        if not path.is_file():
            raise ValueError("LaunchAgent path must be an ordinary file")
        try:
            existing = plistlib.loads(path.read_bytes())
        except (OSError, plistlib.InvalidFileException, ValueError) as exc:
            raise ValueError("existing LaunchAgent cannot be verified; refusing to replace it") from exc
        if existing != plan.properties:
            raise ValueError("a different LaunchAgent already exists; unload and remove it explicitly")
    _mkdir_private(path.parent)
    _mkdir_private(plan.log_directory)
    _mkdir_private(plan.mpl_directory)
    if path.exists():
        return path
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            os.chmod(temporary, 0o600)
            handle.write(plan.plist_bytes())
        # Hard-link creation is atomic and cannot replace a concurrent writer.
        # Unlike replace(), this leaves an existing job untouched on collision.
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def service_commands(plan: ServicePlan, uid: int | None = None) -> dict[str, list[str]]:
    """Return reviewable launchctl commands; never execute them."""
    user_id = os.getuid() if uid is None else uid
    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id < 0:
        raise ValueError("uid must be a nonnegative integer")
    domain = f"gui/{user_id}"
    target = f"{domain}/{plan.label}"
    return {
        "activate": ["launchctl", "bootstrap", domain, str(plan.plist_path)],
        "run_now": ["launchctl", "kickstart", target],
        "status": ["launchctl", "print", target],
        "deactivate": ["launchctl", "bootout", target],
        "remove_after_deactivation": ["rm", "--", str(plan.plist_path)],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare a macOS forecast LaunchAgent; activation is separate.")
    parser.add_argument("command", choices=("install", "commands"))
    parser.add_argument("--config", type=Path, required=True, help="absolute forecast config path")
    parser.add_argument("--output", type=Path, required=True, help="absolute private output root")
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--working-directory", type=Path)
    parser.add_argument("--module-path", type=Path, help="absolute checked-out or pinned package import root")
    parser.add_argument("--launch-agents-directory", type=Path)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--retry-minutes", type=int, default=5)
    parser.add_argument("--cache-root", type=Path, help="opt in to pruning the default service-owned GFS cache")
    parser.add_argument("--cache-retention-days", type=int, default=14)
    parser.add_argument("--dry-run", action="store_true", help="show the plist without creating files")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        plan = build_service_plan(
            args.config, args.output, args.start, python_path=args.python,
            working_directory=args.working_directory, module_path=args.module_path,
            launch_agents_directory=args.launch_agents_directory,
            max_attempts=args.max_attempts, retry_minutes=args.retry_minutes,
            cache_root=args.cache_root, cache_retention_days=args.cache_retention_days,
        )
        if args.command == "install":
            if args.dry_run:
                print(plan.plist_bytes().decode("utf-8"), end="")
            else:
                print(f"Prepared LaunchAgent (not activated): {write_service_plan(plan)}")
        for action, command in service_commands(plan).items():
            stream = sys.stderr if args.command == "install" and args.dry_run else sys.stdout
            print(f"{action}: {shlex.join(command)}", file=stream)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
