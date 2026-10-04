"""Plan a manual observation pilot and preserve each local forecast attempt.

This workflow records forecasts and their timing; it does not classify observations
or establish observed forecast skill. Viewpoint settings and capture output are local.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import subprocess
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from predictor.regions import get_region
from predictor.solar_event import SolarEvent, event_time_utc

DEFAULT_CONFIG = Path(".local/observation-pilot/viewpoint.json")
DEFAULT_OUTPUT = Path("output/pilot")
_SITE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")


def _number(data: dict, key: str, default=None) -> float:
    value = data.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be a finite number")
    if not math.isfinite(value):
        raise ValueError(f"{key} must be a finite number")
    return float(value)


def _validate_viewpoint(data: dict) -> dict:
    if not isinstance(data, dict):
        raise ValueError("viewpoint config must be a JSON object")
    site_id = data.get("id")
    if not isinstance(site_id, str) or _SITE_ID.fullmatch(site_id) is None:
        raise ValueError("id must be a safe basename of 1–64 letters, digits, underscores, or hyphens")
    name = data.get("name")
    if not isinstance(name, str) or not name.strip() or any(ord(c) < 32 for c in name):
        raise ValueError("name must be nonempty text without control characters")
    region_key = data.get("region")
    if not isinstance(region_key, str):
        raise ValueError("region must identify a supported coverage profile")
    region = get_region(region_key)
    if data.get("timezone") != region.timezone_name:
        raise ValueError(f"timezone must match the region: {region.timezone_name}")
    lat, lon = _number(data, "latitude"), _number(data, "longitude")
    region.validate_center(lat, lon)
    radius = _number(data, "radius_km")
    resolution = _number(data, "resolution_deg")
    # Reuse the existing grid contract before any provider or output access.
    from predictor.local_field import local_grid

    lats, lons = local_grid(lat, lon, radius_km=radius, resolution_deg=resolution)
    if min(lats) < -90 or max(lats) > 90 or min(lons) < -180 or max(lons) > 180:
        raise ValueError("local grid must remain within signed geographic coordinates")
    lead = _number(data, "lead_minutes", 120)
    tolerance = _number(data, "lead_tolerance_minutes", 15)
    if lead <= 0 or not 0 <= tolerance < lead:
        raise ValueError("lead_minutes must be positive and tolerance must be nonnegative and smaller than lead")
    solar_event = SolarEvent(data.get("solar_event", "sunset"))
    return {
        "id": site_id, "name": name.strip(), "region": region.key,
        "timezone": region.timezone_name, "latitude": lat, "longitude": lon,
        "radius_km": radius, "resolution_deg": resolution,
        "lead_minutes": lead, "lead_tolerance_minutes": tolerance,
        "solar_event": solar_event.value,
    }


def load_viewpoint(path: str | Path = DEFAULT_CONFIG) -> dict:
    """Load and normalize a local config without accessing weather providers."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("viewpoint config must contain valid JSON") from exc
    return _validate_viewpoint(data)


def _event(config: dict, target_date: date) -> datetime:
    return event_time_utc(
        target_date, config["latitude"], config["longitude"], config["solar_event"],
        timezone_name=config["timezone"],
    )


def build_schedule(config: dict, start: date, days: int = 28) -> list[dict]:
    """Plan elapsed lead times in UTC and present the region's civil times."""
    config = _validate_viewpoint(config)
    if isinstance(start, datetime) or not isinstance(start, date):
        raise ValueError("start must be a calendar date")
    if isinstance(days, bool) or not isinstance(days, int) or days <= 0:
        raise ValueError("days must be a positive integer")
    tz = ZoneInfo(config["timezone"])
    tolerance = timedelta(minutes=config["lead_tolerance_minutes"])
    rows = []
    for offset in range(days):
        target = start + timedelta(days=offset)
        event = _event(config, target)
        planned = event - timedelta(minutes=config["lead_minutes"])
        rows.append({
            "site_id": config["id"], "target_date": target.isoformat(),
            "region": config["region"], "timezone": config["timezone"],
            "solar_event": config["solar_event"],
            "event_time_utc": event.isoformat(),
            "event_time_local": event.astimezone(tz).isoformat(),
            "planned_request_utc": planned.isoformat(),
            "planned_request_local": planned.astimezone(tz).isoformat(),
            "window_start_utc": (planned - tolerance).isoformat(),
            "window_end_utc": (planned + tolerance).isoformat(),
            "lead_minutes": config["lead_minutes"],
            "lead_tolerance_minutes": config["lead_tolerance_minutes"],
        })
    return rows


def write_schedule(
    config: dict, start: date, days: int = 28, output_root: str | Path = DEFAULT_OUTPUT,
) -> Path:
    """Write a uniquely named schedule; repeated planning preserves prior CSVs."""
    rows = build_schedule(config, start, days)
    directory = Path(output_root) / rows[0]["site_id"]
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (
        f"schedule-{rows[0]['target_date']}-{rows[-1]['target_date']}-{uuid4().hex}.csv"
    )
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return path


def _source_revision() -> str | None:
    """Record available Git HEAD, without asserting an unchanged working tree."""
    source = Path(__file__).resolve()
    source_root = source.parent.parent
    if source != (source_root / "predictor" / "observation_pilot.py").resolve():
        return None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel", "--verify", "HEAD"],
            cwd=source_root, capture_output=True, text=True,
            check=True, timeout=1,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    lines = result.stdout.strip().splitlines()
    if len(lines) != 2 or Path(lines[0]).resolve() != source_root:
        return None
    return lines[1] if re.fullmatch(r"[0-9a-f]{40,64}", lines[1]) else None


def _generate_product(*args, **kwargs):
    # Planning requires no map assets, weather sources, or renderer initialization.
    from predictor.local_product import generate_local_product

    return generate_local_product(*args, **kwargs)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _write_attempt(path: Path, attempt: dict) -> None:
    """Replace this attempt's state atomically; distinct attempts never share paths."""
    temporary = path.with_name(f".attempt-{uuid4().hex}.json.tmp")
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump(attempt, handle, indent=2, allow_nan=False)
        handle.write("\n")
    temporary.replace(path)


def capture_forecast(
    config: dict, target_date: date | None = None,
    output_root: str | Path = DEFAULT_OUTPUT, *, now: datetime | None = None,
) -> Path:
    """Save a unique attempt; interruptions can leave an incomplete started record.

    Completion uses the actual wall clock, independently of any injected request
    time. Atomic state replacement does not guarantee crash-safe disk persistence.
    """
    config = _validate_viewpoint(config)
    request = now or _utc_now()
    if request.tzinfo is None or request.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    request = request.astimezone(timezone.utc)
    started = time.monotonic()
    tz = ZoneInfo(config["timezone"])
    target = target_date if target_date is not None else request.astimezone(tz).date()
    if isinstance(target, datetime) or not isinstance(target, date):
        raise ValueError("target_date must be a calendar date")
    event = _event(config, target)
    lead = (event - request).total_seconds() / 60
    record_type = "forecast" if request < event else "after_event"
    delta = lead - config["lead_minutes"]
    within = record_type == "forecast" and abs(delta) <= config["lead_tolerance_minutes"]
    timing = (
        "after_event" if record_type == "after_event" else "on_time" if within
        else "early" if delta > 0 else "late"
    )
    attempt_id = f"{request:%Y%m%dT%H%M%S.%fZ}-{uuid4().hex}"
    directory = Path(output_root) / config["id"] / target.isoformat() / attempt_id
    directory.mkdir(parents=True, exist_ok=False)
    attempt = {
        "schema_version": "v1", "attempt_id": attempt_id, "site": config,
        "target_date": target.isoformat(), "solar_event": config["solar_event"],
        "source_revision": _source_revision(), "working_tree_not_verified": True,
        "request_utc": request.isoformat(), "request_local": request.astimezone(tz).isoformat(),
        "event_time_utc": event.isoformat(), "event_time_local": event.astimezone(tz).isoformat(),
        "intended_lead_minutes": config["lead_minutes"], "actual_lead_minutes": lead,
        "lead_tolerance_minutes": config["lead_tolerance_minutes"],
        "within_window": within, "record_type": record_type, "timing_status": timing,
        "status": "started", "error": None, "artifacts": {},
        "product_metadata": None, "center_diagnostics": None, "source_timing": None,
        "runtime_seconds": None, "completion_utc": None, "completion_local": None,
        "completion_time_semantics": "wall_clock_utc",
        "product_available_before_event": None,
    }
    path = directory / "attempt.json"
    _write_attempt(path, attempt)
    try:
        artifacts = _generate_product(
            target, directory, config["latitude"], config["longitude"],
            solar_event=SolarEvent(config["solar_event"]), radius_km=config["radius_km"],
            resolution_deg=config["resolution_deg"], satellite=False, now=request,
            region=config["region"],
        )
        image = Path(artifacts.image_path)
        metadata_path = Path(artifacts.metadata_path)
        # Artifacts belong to this attempt, rather than an unrelated cached run.
        image_name = image.resolve().relative_to(directory.resolve()).as_posix()
        metadata_name = metadata_path.resolve().relative_to(directory.resolve()).as_posix()
        if not image.is_file():
            raise ValueError("forecast image was not saved")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if not isinstance(metadata, dict):
            raise ValueError("forecast metadata must be an object")
        # Malformed or nonfinite metadata is itself a saved failed attempt.
        json.dumps(metadata, allow_nan=False)
        attempt.update({
            "status": "success",
            "artifacts": {"image": image_name, "metadata": metadata_name},
            "product_metadata": metadata,
            "center_diagnostics": metadata.get("center_diagnostics"),
            "source_timing": {
                "gfs_timing": metadata.get("gfs_timing"),
                "provenance": metadata.get("provenance"),
            },
        })
    except Exception as exc:
        attempt["status"] = "failed"
        attempt["error"] = {"type": type(exc).__name__, "message": str(exc)}
    elapsed = time.monotonic() - started
    completed = _utc_now()
    attempt.update({
        "runtime_seconds": elapsed,
        "completion_utc": completed.isoformat(),
        "completion_local": completed.astimezone(tz).isoformat(),
        "product_available_before_event": attempt["status"] == "success" and completed < event,
    })
    _write_attempt(path, attempt)
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Plan and capture a manual observation pilot.")
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("plan", "forecast"):
        child = commands.add_parser(command)
        child.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
        child.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="local output root")
        if command == "plan":
            child.add_argument("--start", type=date.fromisoformat, required=True)
            child.add_argument("--days", type=int, default=28)
        else:
            child.add_argument("--date", type=date.fromisoformat, default=None,
                               help="local event date (default: today at the viewpoint)")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config = load_viewpoint(args.config)
        if args.command == "plan":
            path = write_schedule(config, args.start, args.days, args.output)
            print(f"Manual capture schedule: {path}")
            return 0
        path = capture_forecast(config, args.date, args.output)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    attempt = json.loads(path.read_text(encoding="utf-8"))
    print(f"Forecast attempt ({attempt['status']}, {attempt['timing_status']}): {path}")
    if attempt["error"] is not None:
        print(f"  {attempt['error']['type']}: {attempt['error']['message']}")
    return 0 if attempt["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
