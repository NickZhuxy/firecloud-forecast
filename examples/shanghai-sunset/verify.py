"""Verify the archived published example offline using the standard library."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def verify(directory: Path) -> None:
    manifest = json.loads((directory / "manifest.json").read_text())
    capture = json.loads((directory / "capture.json").read_text())
    for kind in ("image", "metadata"):
        filename = capture["files"][kind]
        require(Path(filename).name == filename, "Capture filenames must be local basenames")
        data = (directory / filename).read_bytes()
        spec = manifest["artifacts"][kind]
        require(len(data) == spec["bytes"], f"{filename}: byte count mismatch")
        require(hashlib.sha256(data).hexdigest() == spec["sha256"],
                f"{filename}: SHA-256 mismatch")
        print(f"Verified {filename}: {len(data):,} bytes, SHA-256 matches")

    metadata = json.loads((directory / capture["files"]["metadata"]).read_text())
    require(manifest["scope"] == "point", "Expected a point manifest")
    require(metadata["product"] == "china_firecloud_local", "Unexpected product identity")
    for key in ("target_date", "center", "radius_km"):
        require(metadata[key] == manifest[key], f"Product/manifest {key} mismatch")
    require(metadata["solar_event"] == manifest["event"], "Solar-event mismatch")
    require(datetime.fromisoformat(metadata["generated_utc"]) ==
            datetime.fromisoformat(manifest["generated_at"]), "Generation-time mismatch")
    require(abs(metadata["display"]["evaluation_resolution_deg"] -
                manifest["resolution_deg"]) < 1e-9, "Grid resolution mismatch")

    source = re.fullmatch(r"gfs@(\d{4}-\d{2}-\d{2}T\d{2})Z\+f(\d+)",
                          metadata["source_label"])
    require(source is not None, "Cannot derive forecast time from source_label")
    run = datetime.fromisoformat(source[1] + ":00:00+00:00")
    require(run in [datetime.fromisoformat(value) for value in manifest["model_runs"]],
            "Source initialization missing from manifest model_runs")
    forecast_time = run + timedelta(hours=int(source[2]))
    event_time = datetime.fromisoformat(metadata["valid_time_utc"])
    index = metadata["condition_index"]
    require(index["calibrated_probability"] is False, "Expected an uncalibrated index")
    require(0 <= index["range"]["min"] <= index["center_value"] <=
            index["range"]["max"] <= 1, "Invalid condition-index range")

    print(f"Source revision: {manifest['algorithm_version']}")
    print(f"Event at center (UTC): {event_time.isoformat()}")
    print(f"GFS forecast time (UTC): {forecast_time.isoformat()}")
    print(f"Forecast minus event: {(forecast_time - event_time).total_seconds() / 60:.2f} minutes")
    print(f"Center condition index: {index['center_value']:.5f} (uncalibrated)")
    print("Archived delivery evidence; no observations or accuracy validation included.")


if __name__ == "__main__":
    try:
        verify(Path(__file__).resolve().parent)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Example verification failed: {exc}", file=sys.stderr)
        sys.exit(1)
