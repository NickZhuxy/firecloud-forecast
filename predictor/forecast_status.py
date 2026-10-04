"""Render a dated local forecast status without requesting weather.

The report describes persisted scheduling records and verified forecast artifacts.
A recent scheduler tick is evidence of a check, not a guarantee of host uptime.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
from pathlib import Path
from zoneinfo import ZoneInfo


def _time(value: str | None, tz: ZoneInfo) -> str:
    if value is None:
        return "not recorded"
    instant = datetime.fromisoformat(value)
    if instant.tzinfo is None or instant.utcoffset() is None:
        return "not recorded (timestamp has no time zone)"
    local = instant.astimezone(tz)
    clock = local.strftime("%I:%M:%S %p").lstrip("0")
    return f"{local:%d %b %Y} at {clock} {local.tzname()}"


def _both_times(value: str | None, tz: ZoneInfo) -> str:
    return f"{_time(value, tz)} / {_time(value, ZoneInfo('UTC'))}"


def _number(value, *, digits: int = 2) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return "not recorded"
    return f"{value:.{digits}f}"


def _elapsed(seconds: float) -> str:
    if seconds < 0:
        return "recorded time is in the future relative to this check"
    if seconds < 60:
        return f"{seconds:.0f} seconds"
    if seconds < 3600:
        return f"{seconds / 60:.1f} minutes"
    return f"{seconds / 3600:.1f} hours"


def _availability(value) -> str:
    if value is True:
        return "available in this forecast"
    if value is False:
        return "not used in this forecast"
    return "not recorded"


def _slot_text(payload: dict, config: dict, current: datetime, schedule: dict) -> list[str]:
    slot = payload.get("current_slot")
    lines = []
    if payload["status"] == "not_initialized":
        lines.append("Today's forecast: **no runner record**.")
    elif slot is None:
        lines.append("Today's forecast: **no recorded slot**. The scheduler has not saved an entry for this local date.")
    else:
        saved = slot["status"]
        labels = {
            "pending": "pending", "running": "last recorded as running", "retry_wait": "waiting for a retry",
            "success": "delivered", "missed": "missed", "exhausted": "no usable delivery",
            "delivery_failed": "delivery failed", "late_completion": "completed after the event",
            "late_delivery": "delivered after the event", "archived_success": "an archived successful request",
        }
        if saved == "pending":
            planned = datetime.fromisoformat(slot["planned_request_utc"])
            end = datetime.fromisoformat(slot["window_end_utc"])
            labels["pending"] = (
                "waiting for the planned request" if current < planned
                else "waiting for a request within the window" if current <= end
                else "request window expired"
            )
        if saved in ("success", "late_delivery") and (
            payload.get("latest") is None or payload["latest"]["target_date"] != slot["target_date"]
        ):
            labels[saved] = "delivery recorded; no verified result for today's event in this report"
        lines.append(f"Today's forecast: **{labels.get(saved, saved)}** (stored status: {saved}).")
        end = datetime.fromisoformat(slot["window_end_utc"])
        if saved in ("pending", "running", "retry_wait") and current > end:
            lines.append("The request window has expired at this check. The stored status has not been reconciled; this report does not change it.")
        if slot.get("attempts"):
            lines.append(f"Requests recorded for this event: {len(slot['attempts'])}.")
        if slot.get("next_retry_utc"):
            lines.append(f"Next recorded retry: {_time(slot['next_retry_utc'], ZoneInfo(config['timezone']))}.")
        if slot.get("error"):
            lines.append(f"Last recorded error: {slot['error'].get('type', 'Error')}: {slot['error'].get('message', 'not recorded')}.")
    tz = ZoneInfo(config["timezone"])
    timing = slot or schedule
    planned = timing["planned_request_utc"]
    end = timing["window_end_utc"]
    lines.extend([
        f"Target date: **{timing['target_date']}** ({config['timezone']}).",
        f"Planned request for today's event: {_time(planned, tz)}; final permitted request: {_time(end, tz)}.",
        f"Intended lead: {str(config['lead_minutes']).removesuffix('.0')} minutes.",
        f"Event: {config['solar_event']} at {_time(timing['event_time_utc'], tz)}.",
    ])
    return lines


def _model_text(record: dict) -> list[str]:
    metadata = record.get("product_metadata") or {}
    diagnostics = record.get("center_diagnostics") or metadata.get("center_diagnostics")
    if not isinstance(diagnostics, dict):
        diagnostics = {}
        lines = ["Model diagnostics: not recorded."]
    else:
        stage = diagnostics.get("stage")
        lines = [
            "Model diagnostics before satellite correction:" if stage == "model_before_nowcast"
            else f"Model diagnostics (stage: {stage or 'not recorded'}):"
        ]
    components = diagnostics.get("components") or {}
    inputs = diagnostics.get("inputs") or {}
    stage = diagnostics.get("stage")
    for key, label in (("gate_score", "Retained model gate score"), ("modifier_score", "Retained model modifier score")):
        if key in diagnostics:
            lines.append(f"{label}: {_number(diagnostics[key])}.")
    if components:
        lines.append("Factors use a scale from 0 to 1. They are internal scoring terms, not probabilities. Lower factor values contribute less favorable modeled conditions.")
    for key, label in (
        ("sunward_illumination", "Sunward illumination factor"),
        ("mid_high_cloud_presence", "Mid/high cloud presence factor"),
        ("low_cloud_obstruction", "Low-cloud factor"),
    ):
        if key in components:
            lines.append(f"- {label}: {_number(components[key])}.")
    for key, label in (
        ("cloud_low_pct", "Modeled low-cloud cover"),
        ("cloud_mid_pct", "Modeled mid-cloud cover"),
        ("cloud_high_pct", "Modeled high-cloud cover"),
    ):
        if key in inputs:
            lines.append(f"- {label}: {_number(inputs[key], digits=0)}%." if _number(inputs[key]) != "not recorded" else f"- {label}: not recorded.")
    lines.append("These are model results. They do not establish observed sky conditions or an exact sky color.")
    nowcast = metadata.get("nowcast") or {}
    if nowcast.get("applied") is True:
        lines.append("Satellite correction was applied to the delivered field.")
        if stage == "model_before_nowcast":
            lines.append("These diagnostics describe the model before that correction.")
    elif nowcast.get("applied") is False:
        lines.append(f"Satellite correction was not applied: {nowcast.get('reason') or 'reason not recorded'}.")
    provenance = metadata.get("provenance") or {}
    availability = provenance.get("input_availability") or {}
    lines.extend([
        f"Terrain elevation provider: {_availability(availability.get('terrain_elevation_provider'))}.",
        f"Per-column aerosol provider: {_availability(availability.get('per_column_aerosol_provider'))}.",
    ])
    weather = provenance.get("weather_snapshots") or {}
    identity = weather.get("model_identity")
    if identity == "provider_default_unspecified":
        lines.append("Open-Meteo model identity: provider default; the specific model was not recorded.")
    else:
        lines.append(f"Weather model identity: {identity or 'not recorded'}.")
    return lines


def render_status(config: dict, output_root: str | Path, *, now: datetime | None = None) -> str:
    """Read verified evidence and return a Markdown status snapshot; write nothing."""
    # Lazy imports keep the CLI renderer separate from runner initialization.
    from predictor import forecast_runner as runner
    from predictor.observation_pilot import build_schedule

    config = runner.validate_runner_config(config)
    current = runner._instant(now)
    tz = ZoneInfo(config["timezone"])
    payload = runner.status(config, output_root, now=current, include_details=True)
    today = current.astimezone(tz).date()
    schedule = build_schedule(config, today, 1)[0]
    lines = [
        f"# {config['name']} forecast status", "",
        f"Status checked: **{_both_times(current.isoformat(), tz)}**.", "",
        "This dated snapshot does not establish live service health or future delivery; a tick records only a scheduler check.", "",
    ]
    lines.extend(_slot_text(payload, config, current, schedule))
    last_tick = payload.get("last_tick_utc")
    if last_tick:
        age = (current - datetime.fromisoformat(last_tick)).total_seconds()
        lines.append(f"Last scheduler tick: {_time(last_tick, tz)} ({_elapsed(age)} before this check).")
    else:
        lines.append("Last scheduler tick: not recorded.")
    lines.extend(["", "## Last verified scheduled forecast", ""])
    latest = payload.get("latest")
    record = payload.get("details")
    if latest is None:
        lines.append("No verified scheduled forecast is available. This is an unavailable result, not a zero condition index.")
        if payload.get("latest_error"):
            error = payload["latest_error"]
            lines.append(f"Delivery verification failed: {error.get('type', 'Error')}: {error.get('message', 'not recorded')}.")
    else:
        target = latest["target_date"]
        position = "today's event date" if target == today.isoformat() else "a previous event date" if target < today.isoformat() else "a future event date"
        lines.append(f"Target date: **{target}** ({position}).")
        if latest["event_has_passed"]:
            lines.append("This forecast's event has already passed at the status-check time.")
        age = (current - datetime.fromisoformat(latest["completion_utc"])).total_seconds()
        lines.append(f"Condition index: **{_number(latest.get('condition_index'), digits=3)}** (uncalibrated heuristic; it is not a statistical probability).")
        directory = Path(output_root) / config["id"]
        image_path = (directory / latest["image"]).resolve()
        lines.extend(["", f"[Forecast map](<{image_path}>)", "", f"![Forecast map](<{image_path}>)", "",
                      f"Age since completion: {_elapsed(age)} at this check.", "",
                      "## Model details and source times", "",
            f"Requested: {_both_times(latest['request_utc'], tz)}.",
            f"Completed: {_both_times(latest['completion_utc'], tz)}.",
            f"Event: {_both_times(latest['event_time_utc'], tz)}.",
            f"Delivered before the event: {'yes' if latest['delivered_before_event'] else 'no'}.",
        ])
        timing = (latest.get("source_timing") or {}).get("gfs_timing") or {}
        lines.extend([
            f"GFS initialization: {_both_times(timing.get('initialization_time_utc'), tz)}.",
            f"GFS selected weather-valid time: {_both_times(timing.get('valid_time_utc'), tz)}.",
        ])
        if timing.get("valid_time_utc"):
            difference = (datetime.fromisoformat(timing["valid_time_utc"]) - datetime.fromisoformat(latest["event_time_utc"])).total_seconds() / 60
            lines.append(f"Selected weather time is {abs(difference):.1f} minutes {'after' if difference >= 0 else 'before'} the exact event. This is the selected model hour, separate from the solar-event time.")
        lines.extend(["", *_model_text(record), ""])
        for key, label in (("metadata", "Product metadata"), ("attempt", "Original request")):
            lines.append(f"[{label}](<{(directory / latest[key]).resolve()}>)")
    lines.extend(["", "Setup previews are extra requests. They do not satisfy a scheduled event slot.", ""])
    return "\n\n".join(line for line in lines if line) + "\n"


def write_status_report(config: dict, output_root: str | Path, *, now: datetime | None = None) -> Path:
    """Atomically replace only the mutable status card; retain all forecast evidence."""
    from predictor import forecast_runner as runner

    text = render_status(config, output_root, now=now)
    normalized = runner.validate_runner_config(config)
    path = Path(output_root) / normalized["id"] / "status.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    runner._atomic_text(path, text)
    return path
