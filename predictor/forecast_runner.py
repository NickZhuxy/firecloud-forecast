"""Run scheduled local forecasts without observations or external delivery services.

A scheduler calls ``tick`` repeatedly. Local civil dates identify the expected
solar events; UTC instants control due times and retries. Each forecast retains
its original attempt, product metadata, and source timing.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys
from uuid import uuid4
from zoneinfo import ZoneInfo

from predictor.observation_pilot import (
    _validate_viewpoint, build_schedule, capture_forecast, load_viewpoint,
)

DEFAULT_CONFIG = Path(".local/forecast-service/viewpoint.json")
DEFAULT_OUTPUT = Path("output/forecasts")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _instant(now: datetime | None = None) -> datetime:
    value = now or _utc_now()
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return value.astimezone(timezone.utc)


def _load_json(path: Path) -> dict:
    def invalid(value):
        raise ValueError(f"nonfinite JSON value: {value}")

    value = json.loads(path.read_text(encoding="utf-8"), parse_constant=invalid)
    if not isinstance(value, dict):
        raise ValueError(f"JSON must be an object: {path.name}")
    return value


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}-{uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, allow_nan=False)
            handle.write("\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_text(path: Path, value: str) -> None:
    temporary = path.with_name(f".{path.name}-{uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            handle.write(value)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _fingerprint(config: dict) -> str:
    payload = json.dumps(config, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _settings(max_attempts: int, retry_minutes: float) -> dict:
    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts < 1:
        raise ValueError("max_attempts must be a positive integer")
    if (isinstance(retry_minutes, bool) or not isinstance(retry_minutes, (int, float))
            or not math.isfinite(retry_minutes) or retry_minutes < 5):
        raise ValueError("retry_minutes must be a finite number of at least 5")
    return {"max_attempts": max_attempts, "retry_minutes": float(retry_minutes)}


def _runner_config(config: dict) -> dict:
    normalized = _validate_viewpoint(config)
    if normalized["lead_minutes"] > 7 * 24 * 60:
        raise ValueError("the unattended runner supports forecast leads of at most 7 days")
    return normalized


def validate_runner_config(config: dict) -> dict:
    """Normalize viewpoint settings and check the unattended scheduling horizon."""
    return _runner_config(config)


def _cache_policy(cache_root: str | Path | None, retention_days: int) -> dict | None:
    if cache_root is None:
        return None
    if isinstance(retention_days, bool) or not isinstance(retention_days, int) or retention_days < 1:
        raise ValueError("cache_retention_days must be a positive integer")
    root = Path(cache_root)
    expected = Path.cwd() / "research/data/cache/gfs"
    if not root.is_absolute() or root.resolve() != expected.resolve():
        raise ValueError("cache_root must be the current working directory's research/data/cache/gfs")
    for path in (root, *root.parents):
        if path.is_symlink():
            raise ValueError("cache_root and its parents must not be symlinks")
    return {"root": str(root), "retention_days": retention_days}


def _prune_cache(policy: dict, now: datetime) -> dict:
    root = Path(policy["root"])
    root.mkdir(parents=True, exist_ok=True)
    paths = list(root.rglob("*"))
    if any(path.is_symlink() for path in paths):
        raise ValueError("cache cleanup refused: a cache entry is a symlink")
    cutoff = now.timestamp() - policy["retention_days"] * 24 * 60 * 60
    removed = 0
    for path in paths:
        if path.is_file() and path.stat().st_mtime < cutoff:
            path.resolve().relative_to(root.resolve())
            path.unlink()
            removed += 1
    return {"checked_utc": now.isoformat(), "removed_files": removed, **policy}


@contextmanager
def _site_lock(directory: Path):
    # POSIX locks release when a process exits, including a terminated worker.
    try:
        import fcntl
    except ImportError as exc:
        raise RuntimeError("the unattended runner requires POSIX file locking") from exc
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".runner.lock").open("a", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _state_path(directory: Path) -> Path:
    return directory / "runner-state.json"


def _relative(path: Path, directory: Path) -> str:
    return path.resolve().relative_to(directory.resolve()).as_posix()


def _safe_path(directory: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError("artifact path must be relative to the site directory")
    path = directory / relative
    _relative(path, directory)
    return path


def _hash(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _initial_state(config: dict, start: date, now: datetime, settings: dict) -> dict:
    return {
        "schema_version": "v1", "site_id": config["id"], "site": config,
        "config_fingerprint": _fingerprint(config), "start_date": start.isoformat(),
        "created_utc": now.isoformat(), "settings": settings, "slots": {},
        "last_tick_utc": None,
    }


def _open_state(directory: Path, config: dict, start: date | None,
                now: datetime, settings: dict) -> dict:
    path = _state_path(directory)
    if not path.exists():
        chosen = start or now.astimezone(ZoneInfo(config["timezone"])).date()
        return _initial_state(config, chosen, now, settings)
    state = _load_json(path)
    if state.get("schema_version") != "v1" or state.get("site_id") != config["id"]:
        raise ValueError("runner state has an unsupported schema or site identity")
    if state.get("config_fingerprint") != _fingerprint(config):
        raise ValueError("forecast configuration changed; use a new site id or output directory")
    if start is not None and state.get("start_date") != start.isoformat():
        raise ValueError("start date differs from the recorded activation date")
    if state.get("settings") != settings:
        raise ValueError("retry settings differ from the recorded runner policy")
    if not isinstance(state.get("slots"), dict):
        raise ValueError("runner slots must be an object")
    return state


def _slot(config: dict, target: date) -> dict:
    schedule = build_schedule(config, target, 1)[0]
    return {
        **schedule, "config_fingerprint": _fingerprint(config), "status": "pending",
        "generation_status": "pending", "delivery_status": "pending",
        "attempts": [], "next_retry_utc": None, "error": None,
        "delivered_utc": None,
    }


def _key(target: date, config: dict) -> str:
    return f"{target.isoformat()}/{config['solar_event']}"


def _ensure_slots(state: dict, config: dict, now: datetime) -> None:
    start = date.fromisoformat(state["start_date"])
    today = now.astimezone(ZoneInfo(config["timezone"])).date()
    target = start
    while target <= today:
        key = _key(target, config)
        if key not in state["slots"]:
            state["slots"][key] = _slot(config, target)
        target += timedelta(days=1)
    # Future event dates can be due today when the configured lead spans midnight.
    lookahead = math.ceil(config["lead_minutes"] / (24 * 60)) + 1
    for offset in range(1, lookahead + 1):
        upcoming = today + timedelta(days=offset)
        if upcoming < start:
            continue
        candidate = _slot(config, upcoming)
        if datetime.fromisoformat(candidate["planned_request_utc"]) <= now:
            state["slots"].setdefault(_key(upcoming, config), candidate)


def _verify_attempt(directory: Path, slot: dict, entry: dict) -> tuple[dict, dict]:
    path = _safe_path(directory, entry["attempt_path"])
    record = _load_json(path)
    if (record.get("target_date") != slot["target_date"]
            or record.get("solar_event") != slot["solar_event"]
            or record.get("request_utc") != entry["request_utc"]
            or _fingerprint(record.get("site", {})) != slot["config_fingerprint"]):
        raise ValueError("forecast attempt does not match its scheduled slot")
    if record.get("status") != "success":
        return record, {}
    metadata = record.get("product_metadata")
    if not isinstance(metadata, dict):
        raise ValueError("successful attempt has no product metadata")
    artifacts = record.get("artifacts") or {}
    site = record["site"]
    expected = {
        "target_date": slot["target_date"], "region": site["region"],
        "timezone": site["timezone"], "solar_event": site["solar_event"],
        "event_time_utc": slot["event_time_utc"], "event_time_local": slot["event_time_local"],
        "center": [site["latitude"], site["longitude"]],
        "image": artifacts.get("image"),
    }
    if any(metadata.get(key) != value for key, value in expected.items()):
        raise ValueError("forecast product metadata does not match its scheduled location and event")
    paths = {"attempt": path}
    for key in ("image", "metadata"):
        name = artifacts.get(key)
        if not isinstance(name, str) or not name or Path(name).is_absolute():
            raise ValueError("successful attempt has an invalid artifact path")
        item = path.parent / name
        item.resolve().relative_to(path.parent.resolve())
        if not item.is_file() or item.stat().st_size == 0:
            raise ValueError(f"forecast {key} artifact is missing or empty")
        paths[key] = item
    if _load_json(paths["metadata"]) != metadata:
        raise ValueError("forecast sidecar differs from the captured metadata")
    from PIL import Image

    with Image.open(paths["image"]) as image:
        image.verify()
    hashes = {key: _hash(item) for key, item in paths.items()}
    if entry.get("artifact_sha256") is not None and hashes != entry["artifact_sha256"]:
        raise ValueError("forecast artifacts changed after completion")
    return record, hashes


def _finish_entry(directory: Path, slot: dict, entry: dict) -> None:
    try:
        record, hashes = _verify_attempt(directory, slot, entry)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        entry.update(status="integrity_failed", error={"type": type(exc).__name__, "message": str(exc)})
        return
    status = record.get("status")
    entry.update(status=status, completion_utc=record.get("completion_utc"),
                 error=record.get("error"), artifact_sha256=hashes or None)
    if status == "started":
        entry["status"] = "interrupted"
        entry["error"] = {"type": "InterruptedAttempt", "message": "previous worker ended before finalization"}
    elif status not in ("success", "failed"):
        entry["status"] = "integrity_failed"
        entry["error"] = {"type": "InvalidAttempt", "message": "unsupported forecast attempt status"}
    if status == "success":
        try:
            completed = _instant(datetime.fromisoformat(record["completion_utc"]))
            event = datetime.fromisoformat(slot["event_time_utc"])
            entry["available_before_event"] = (
                completed < event and record.get("product_available_before_event") is True
                and record.get("record_type") == "forecast" and record.get("within_window") is True
            )
        except (KeyError, ValueError, TypeError):
            entry["status"] = "integrity_failed"
            entry["error"] = {"type": "InvalidAttempt", "message": "invalid forecast completion timing"}


def _latest_summary(directory: Path, slot: dict, entry: dict, now: datetime) -> dict:
    record, _hashes = _verify_attempt(directory, slot, entry)
    attempt = _safe_path(directory, entry["attempt_path"])
    metadata = record["product_metadata"]
    condition = metadata.get("condition_index") or {}
    return {
        "schema_version": "v1", "site_id": record["site"]["id"],
        "site_name": record["site"]["name"], "region": record["site"]["region"],
        "timezone": record["site"]["timezone"], "target_date": slot["target_date"],
        "solar_event": slot["solar_event"], "request_utc": record["request_utc"],
        "request_local": record["request_local"], "completion_utc": record["completion_utc"],
        "completion_local": record["completion_local"],
        "event_time_utc": slot["event_time_utc"], "event_time_local": slot["event_time_local"],
        "condition_index": condition.get("center_value"), "calibrated_probability": False,
        "source_timing": record.get("source_timing"), "source_revision": record.get("source_revision"),
        "working_tree_not_verified": record.get("working_tree_not_verified", True),
        "attempt": entry["attempt_path"],
        "image": _relative(attempt.parent / record["artifacts"]["image"], directory),
        "metadata": _relative(attempt.parent / record["artifacts"]["metadata"], directory),
        "artifact_sha256": entry["artifact_sha256"], "delivered_utc": now.isoformat(),
        "product_available_before_event": True,
        "delivered_before_event": now < datetime.fromisoformat(slot["event_time_utc"]),
    }


def _publish_latest(directory: Path, slot: dict, entry: dict, now: datetime) -> bool:
    summary = _latest_summary(directory, slot, entry, now)
    json_path = directory / "latest.json"
    if json_path.exists():
        previous = _load_json(json_path)
        if (previous.get("target_date", ""), previous.get("request_utc", "")) > (
            summary["target_date"], summary["request_utc"]
        ):
            return False
    text = _summary_text(directory, summary)
    # Each file is replaced atomically. A failed pair is retried on the next tick.
    _atomic_json(json_path, summary)
    _atomic_text(directory / "latest.md", text)
    return True


def _summary_text(directory: Path, summary: dict, *, is_preview: bool = False) -> str:
    value = summary["condition_index"]
    formatted = "unavailable" if value is None else f"{value:.3f}"
    timing = (summary.get("source_timing") or {}).get("gfs_timing") or {}
    return (
        f"# {summary['site_name']} {'preview' if is_preview else 'forecast'}\n\n"
        f"Event: {summary['solar_event']} on {summary['target_date']}.\n\n"
        f"Event time: {summary['event_time_local']}.\n\n"
        f"Forecast requested: {summary['request_local']}.\n\n"
        f"Forecast completed: {summary['completion_utc']} UTC.\n\n"
        f"Local completion: {summary['completion_local']}.\n\n"
        f"GFS model initialized: {timing.get('initialization_time_utc') or 'unknown'}; "
        f"valid time: {timing.get('valid_time_utc', 'unknown')}.\n\n"
        f"Delivery completed before the event: {summary['delivered_before_event']}.\n\n"
        f"Condition index: **{formatted}** (uncalibrated heuristic).\n\n"
        f"This index does not establish real-world forecast skill or predict exact sky colors.\n\n"
        f"[Forecast image](<{(directory / summary['image']).resolve()}>) · "
        f"[Product metadata](<{(directory / summary['metadata']).resolve()}>) · "
        f"[Original attempt](<{(directory / summary['attempt']).resolve()}>)\n"
        f"\n![Forecast map](<{(directory / summary['image']).resolve()}>)\n"
    )


def _revoke_latest(directory: Path, entry: dict | None = None) -> None:
    path = directory / "latest.json"
    try:
        previous = _load_json(path) if path.exists() else {}
    except (OSError, ValueError):
        previous = {}
    if entry is None or not previous or previous.get("attempt") == entry.get("attempt_path"):
        # Only mutable delivery pointers are revoked; original artifacts are retained.
        try:
            path.unlink(missing_ok=True)
            _atomic_text(directory / "latest.md", "# Forecast unavailable\n\nThe previous delivery failed its integrity check. See runner-state.json.\n")
        except OSError:
            # The persisted delivery failure remains authoritative if disk IO fails.
            pass


def _update_slot(directory: Path, slot: dict, now: datetime, settings: dict) -> None:
    attempts = slot["attempts"]
    last = attempts[-1] if attempts else None
    if last is not None and last["status"] == "success":
        slot["generation_status"] = "success"
        slot["next_retry_utc"] = None
        if not last.get("available_before_event"):
            slot.update(status="late_completion", delivery_status="expired", error=None)
            return
        try:
            published = _publish_latest(directory, slot, last, now)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            _revoke_latest(directory, last)
            slot.update(status="delivery_failed", delivery_status="failed",
                        error={"type": type(exc).__name__, "message": str(exc)})
        else:
            if published:
                before = now < datetime.fromisoformat(slot["event_time_utc"])
                slot.update(status="success" if before else "late_delivery",
                            delivery_status="delivered" if before else "delivered_late",
                            error=None, delivered_utc=now.isoformat(), delivered_before_event=before)
            else:
                slot.update(status="archived_success", delivery_status="superseded", error=None)
        return
    end = datetime.fromisoformat(slot["window_end_utc"])
    if now > end:
        slot.update(status="missed" if not attempts else "exhausted",
                    generation_status="missed" if not attempts else last["status"],
                    delivery_status="unavailable", next_retry_utc=None,
                    exhaustion_reason="request_window_expired")
    elif last is None:
        slot.update(status="pending", generation_status="pending")
    elif len(attempts) >= settings["max_attempts"]:
        slot.update(status="exhausted", generation_status=last["status"],
                    delivery_status="unavailable", next_retry_utc=None, error=last.get("error"),
                    exhaustion_reason="maximum_attempts_reached")
    else:
        # A failed or interrupted request consumes its attempt and respects backoff.
        anchor = last.get("completion_utc") or last["request_utc"]
        retry = datetime.fromisoformat(anchor) + timedelta(minutes=settings["retry_minutes"])
        slot.update(status="retry_wait", generation_status=last["status"],
                    next_retry_utc=retry.isoformat(), error=last.get("error"))


def tick(config: dict, output_root: str | Path = DEFAULT_OUTPUT, *,
         start: date | None = None, max_attempts: int = 3, retry_minutes: float = 5,
         cache_root: str | Path | None = None, cache_retention_days: int = 14,
         now: datetime | None = None) -> dict:
    """Perform at most one due request, with a lock spanning request and delivery."""
    config = _runner_config(config)
    request = _instant(now)
    if start is not None and (isinstance(start, datetime) or not isinstance(start, date)):
        raise ValueError("start must be a calendar date")
    settings = _settings(max_attempts, retry_minutes)
    policy = _cache_policy(cache_root, cache_retention_days)
    settings["cache_policy"] = policy
    directory = Path(output_root) / config["id"]
    with _site_lock(directory) as acquired:
        if not acquired:
            return {"action": "locked", "site_id": config["id"]}
        state = _open_state(directory, config, start, request, settings)
        _ensure_slots(state, config, request)
        for slot in state["slots"].values():
            if slot["attempts"] and slot["attempts"][-1]["status"] in ("starting", "started"):
                entry = slot["attempts"][-1]
                if entry.get("attempt_path"):
                    _finish_entry(directory, slot, entry)
                else:
                    entry.update(status="interrupted", error={"type": "InterruptedAttempt", "message": "worker ended before attempt binding"})
            if slot["status"] not in ("success", "late_delivery", "archived_success"):
                _update_slot(directory, slot, request, settings)
        if (directory / "latest.json").exists():
            try:
                _checked_latest(directory, state)
            except (OSError, ValueError, KeyError, TypeError, StopIteration) as exc:
                try:
                    pointer = _load_json(directory / "latest.json")
                    affected = state["slots"][_key(date.fromisoformat(pointer["target_date"]), config)]
                    affected.update(status="delivery_failed", delivery_status="failed",
                                    error={"type": type(exc).__name__, "message": str(exc)})
                except (OSError, ValueError, KeyError, TypeError):
                    pass
                _revoke_latest(directory)
        state["last_tick_utc"] = request.isoformat()
        _atomic_json(_state_path(directory), state)
        due = [slot for slot in state["slots"].values()
               if slot["status"] in ("pending", "retry_wait")
               and datetime.fromisoformat(slot["planned_request_utc"]) <= request
               <= datetime.fromisoformat(slot["window_end_utc"])
               and (slot["next_retry_utc"] is None
                    or datetime.fromisoformat(slot["next_retry_utc"]) <= request)]
        if not due:
            return {"action": "idle", "site_id": config["id"], "state": str(_state_path(directory))}
        slot = min(due, key=lambda item: item["planned_request_utc"])
        entry = {"number": len(slot["attempts"]) + 1, "status": "starting",
                 "request_utc": request.isoformat(), "completion_utc": None,
                 "attempt_path": None, "artifact_sha256": None, "error": None}
        slot["attempts"].append(entry)
        slot.update(status="running", generation_status="running", next_retry_utc=None)
        _atomic_json(_state_path(directory), state)

        def started(path: Path) -> None:
            entry.update(attempt_path=_relative(path, directory), status="started")
            _atomic_json(_state_path(directory), state)

        try:
            if policy is not None:
                state["cache_maintenance"] = _prune_cache(policy, request)
            if shutil.disk_usage(directory).free < 1_000_000_000:
                raise OSError("forecast skipped: less than 1 GB of free disk space")
            if policy is not None and shutil.disk_usage(policy["root"]).free < 1_000_000_000:
                raise OSError("forecast skipped: less than 1 GB of free cache disk space")
            path = capture_forecast(config, date.fromisoformat(slot["target_date"]),
                                    output_root, now=request, on_started=started)
            entry["attempt_path"] = _relative(path, directory)
            _finish_entry(directory, slot, entry)
        except Exception as exc:
            entry.update(status="failed", completion_utc=_utc_now().isoformat(),
                         error={"type": type(exc).__name__, "message": str(exc)})
        completed = _instant()
        _update_slot(directory, slot, completed, settings)
        _atomic_json(_state_path(directory), state)
        return {"action": "forecast", "site_id": config["id"], "target_date": slot["target_date"],
                "status": slot["status"], "attempt": entry["attempt_path"],
                "state": str(_state_path(directory))}


def _checked_latest(directory: Path, state: dict, *, include_record: bool = False):
    candidate = _load_json(directory / "latest.json")
    selected = state["slots"][_key(date.fromisoformat(candidate["target_date"]), state["site"])]
    entry = next(item for item in selected["attempts"] if item["attempt_path"] == candidate["attempt"])
    record, _hashes = _verify_attempt(directory, selected, entry)
    if (record.get("status") != "success" or not entry.get("available_before_event")
            or selected.get("delivery_status") not in ("delivered", "delivered_late")):
        raise ValueError("latest pointer has no eligible delivered forecast")
    expected = _latest_summary(directory, selected, entry, datetime.fromisoformat(selected["delivered_utc"]))
    if candidate != expected:
        raise ValueError("latest pointer differs from the original forecast and delivery record")
    if (directory / "latest.md").read_text(encoding="utf-8") != _summary_text(directory, expected):
        raise ValueError("latest Markdown delivery is missing or differs from its forecast")
    return (candidate, record) if include_record else candidate


def status(config: dict, output_root: str | Path = DEFAULT_OUTPUT, *,
           now: datetime | None = None, include_details: bool = False) -> dict:
    """Read scheduling and delivery status without requesting weather."""
    config = _runner_config(config)
    current = _instant(now)
    directory = Path(output_root) / config["id"]
    path = _state_path(directory)
    if not path.exists():
        result = {"site_id": config["id"], "status": "not_initialized", "latest": None}
        if include_details:
            result["details"] = None
        return result
    state = _load_json(path)
    if state.get("config_fingerprint") != _fingerprint(config):
        raise ValueError("forecast configuration differs from runner state")
    today = current.astimezone(ZoneInfo(config["timezone"])).date()
    key = _key(today, config)
    latest = None
    latest_error = None
    details = None
    if (directory / "latest.json").exists():
        try:
            if include_details:
                candidate, details = _checked_latest(directory, state, include_record=True)
            else:
                candidate = _checked_latest(directory, state)
            latest = {**candidate, "is_current_date": candidate["target_date"] == today.isoformat(),
                      "event_has_passed": current >= datetime.fromisoformat(candidate["event_time_utc"])}
        except (OSError, ValueError, KeyError, TypeError, StopIteration) as exc:
            latest_error = {"type": type(exc).__name__, "message": str(exc)}
            details = None
    result = {"site_id": config["id"], "status": "initialized", "start_date": state["start_date"],
            "last_tick_utc": state["last_tick_utc"], "current_date": today.isoformat(),
            "current_slot": state["slots"].get(key), "latest": latest, "latest_error": latest_error,
            "expected_dates": len(state["slots"])}
    if include_details:
        result["details"] = details
    return result


def preview(config: dict, output_root: str | Path = DEFAULT_OUTPUT, *, target: date | None = None) -> Path:
    """Save an extra forecast outside the primary runner state and delivery pointer."""
    config = _runner_config(config)
    path = capture_forecast(config, target, Path(output_root) / "previews")
    record = _load_json(path)
    if record.get("status") == "success":
        directory = Path(output_root) / "previews" / config["id"]
        slot = _slot(config, date.fromisoformat(record["target_date"]))
        entry = {"attempt_path": _relative(path, directory), "request_utc": record["request_utc"]}
        _finish_entry(directory, slot, entry)
        if entry["status"] != "success":
            raise ValueError("preview delivery failed its product integrity check")
        summary = _latest_summary(directory, slot, entry, _instant())
        summary.update(product_available_before_event=record["product_available_before_event"], preview=True)
        _atomic_json(directory / "preview_latest.json", summary)
        _atomic_text(directory / "preview_latest.md", _summary_text(directory, summary, is_preview=True))
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run unattended local forecasts and preserve original evidence.")
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("tick", "plan", "status", "preview"):
        child = commands.add_parser(command)
        child.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
        child.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
        if command in ("tick", "plan"):
            child.add_argument("--start", type=date.fromisoformat)
        if command == "tick":
            child.add_argument("--max-attempts", type=int, default=3)
            child.add_argument("--retry-minutes", type=float, default=5)
            child.add_argument("--cache-root", type=Path)
            child.add_argument("--cache-retention-days", type=int, default=14)
        if command == "plan":
            child.add_argument("--days", type=int, default=7)
        if command == "preview":
            child.add_argument("--date", type=date.fromisoformat)
        if command == "status":
            child.add_argument("--format", choices=("json", "text"), default="json")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config = validate_runner_config(load_viewpoint(args.config))
        if args.command == "tick":
            result = tick(config, args.output, start=args.start,
                          max_attempts=args.max_attempts, retry_minutes=args.retry_minutes,
                          cache_root=args.cache_root, cache_retention_days=args.cache_retention_days)
        elif args.command == "status":
            if args.format == "text":
                from predictor.forecast_status import render_status

                print(render_status(config, args.output), end="")
                return 0
            result = status(config, args.output)
        elif args.command == "plan":
            start = args.start or _utc_now().astimezone(ZoneInfo(config["timezone"])).date()
            result = {"site_id": config["id"], "schedule": build_schedule(config, start, args.days)}
        else:
            path = preview(config, args.output, target=args.date)
            record = _load_json(path)
            result = {"action": "preview", "status": record["status"], "attempt": str(path)}
    except (OSError, ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    if args.command == "tick" and result.get("action") != "locked":
        try:
            from predictor.forecast_status import write_status_report

            write_status_report(config, args.output)
        except Exception as exc:
            print(f"Forecast status report could not be saved: {type(exc).__name__}: {exc}", file=sys.stderr)
    print(json.dumps(result, indent=2, allow_nan=False))
    if result.get("status") in ("exhausted", "delivery_failed", "late_completion", "failed"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
