"""Check the bounded pilot snapshot offline; this does not replay weather data."""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify(directory: Path):
    capture = json.loads((directory / "capture.json").read_text())
    for name, spec in capture["files"].items():
        require(Path(name).name == name, "Expected local artifact basenames")
        data = (directory / name).read_bytes()
        require(len(data) == spec["bytes"], f"{name}: size mismatch")
        require(hashlib.sha256(data).hexdigest() == spec["sha256"], f"{name}: checksum mismatch")
        print(f"Verified {name}: {len(data):,} bytes")
    metadata = json.loads((directory / "metadata.json").read_text())
    require(metadata["region"] == "us-nyc", "Unexpected region")
    require(metadata["product"] == "us_nyc_firecloud_local", "Unexpected product")
    require(metadata["timezone"] == "America/New_York", "Unexpected timezone")
    event = datetime.fromisoformat(metadata["event_time_utc"])
    local = event.astimezone(ZoneInfo(metadata["timezone"]))
    require(local.date().isoformat() == metadata["target_date"], "Wrong civil event day")
    require(local.isoformat() == metadata["event_time_local"], "Local/UTC event mismatch")
    timing = metadata["gfs_timing"]
    initialized = datetime.fromisoformat(timing["initialization_time_utc"])
    valid = initialized + timedelta(hours=timing["forecast_hour"])
    require(valid.isoformat() == timing["valid_time_utc"], "Wrong discrete GFS time")
    require(metadata["grid_shape"] == [5, 5], "Unexpected evaluation grid")
    require(metadata["nowcast"]["applied"] is False, "Unsupported satellite correction")
    require(capture["observational_validation"] is False, "Unexpected skill claim")
    require(capture["raw_weather_inputs_archived"] is False, "Unexpected weather replay claim")
    index = metadata["condition_index"]
    require(index["calibrated_probability"] is False, "Unexpected calibration claim")
    require(0 <= index["range"]["min"] <= index["center_value"] <= index["range"]["max"] <= 1,
            "Invalid index range")
    print(f"Event: {local.isoformat()} / {event.isoformat()}")
    print(f"GFS forecast: {valid.isoformat()} ({(valid-event).total_seconds()/60:.2f} minutes from event)")
    print(f"Center index: {index['center_value']:.2f}; uncalibrated, no observed validation")


if __name__ == "__main__":
    try:
        verify(Path(__file__).resolve().parent)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Example verification failed: {exc}", file=sys.stderr)
        sys.exit(1)
