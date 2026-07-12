"""Build the static national and configured local-product feed for GitHub Pages."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import posixpath
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from predictor.gfs import GFSSource
from predictor.local_product import generate_local_product
from predictor.national_product import ProductArtifacts, generate_product
from predictor.remote_product import REMOTE_SCHEMA_VERSION, point_key
from predictor.solar_event import SolarEvent

_PUBLISH_VALID_HOURS = 18
_MODEL_RUN_RE = re.compile(r"gfs@(\d{4}-\d{2}-\d{2})T(\d{2})Z")


@dataclass(frozen=True)
class PrecomputeLocation:
    name: str
    lat: float
    lon: float
    radius_km: float = 150.0
    resolution_deg: float = 0.1

    @property
    def slug(self) -> str:
        return _safe_version(self.name).lower()


def _iso_z(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_version(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")
    return cleaned or "dev"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _model_runs(metadata: dict) -> list[str]:
    found = sorted(set(_MODEL_RUN_RE.findall(str(metadata.get("source_label", "")))))
    return [f"{day}T{hour}:00:00Z" for day, hour in found]


def _model_run_slug(model_runs: list[str]) -> str:
    if not model_runs:
        return "gfs-unknown"
    parsed = datetime.fromisoformat(model_runs[-1].replace("Z", "+00:00"))
    return f"gfs-{parsed:%Y%m%dT%HZ}"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _artifact_entry(path: Path, manifest_path: Path) -> dict:
    relative = posixpath.relpath(path.as_posix(), manifest_path.parent.as_posix())
    return {
        "path": relative,
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def parse_location(
    value: str,
    *,
    radius_km: float = 150.0,
    resolution_deg: float = 0.1,
) -> PrecomputeLocation:
    """Parse ``NAME:LAT:LON`` used by repeatable CLI/workflow inputs."""
    try:
        name, lat_text, lon_text = value.split(":", 2)
        lat = float(lat_text)
        lon = float(lon_text)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError(
            "location must be NAME:LAT:LON, for example shanghai:31.23:121.47"
        ) from exc
    if not name.strip():
        raise argparse.ArgumentTypeError("location name must not be empty")
    if not -90.0 <= lat <= 90.0 or not -180.0 <= lon <= 180.0:
        raise argparse.ArgumentTypeError("location coordinates are out of range")
    if radius_km <= 0 or resolution_deg <= 0:
        raise argparse.ArgumentTypeError("local radius and resolution must be positive")
    return PrecomputeLocation(
        name=name.strip(),
        lat=lat,
        lon=lon,
        radius_km=float(radius_km),
        resolution_deg=float(resolution_deg),
    )


def build_site(
    output_dir: str | Path,
    *,
    start_date: date,
    days: int = 2,
    source=None,
    now: datetime | None = None,
    algorithm_version: str = "dev",
    dpi: int = 160,
    refine: bool = True,
    satellite: bool = True,
    events: tuple[SolarEvent, ...] = (SolarEvent.SUNRISE, SolarEvent.SUNSET),
    locations: tuple[PrecomputeLocation, ...] = (),
    generate=generate_product,
    local_generate=generate_local_product,
) -> list[Path]:
    """Generate a complete static Pages snapshot and return latest manifests."""
    if days <= 0:
        raise ValueError("days must be positive")
    generated_at = now or datetime.now(timezone.utc)
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=timezone.utc)
    generated_at = generated_at.astimezone(timezone.utc)
    version = _safe_version(algorithm_version)
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / ".nojekyll").write_text("", encoding="utf-8")
    shared_source = source or GFSSource(as_of=generated_at)
    manifests: list[Path] = []

    with tempfile.TemporaryDirectory(prefix="firecloud-precompute-") as temporary:
        work_root = Path(temporary)
        for offset in range(days):
            target_date = start_date + timedelta(days=offset)
            for event in events:
                artifacts: ProductArtifacts = generate(
                    target_date,
                    work_root / target_date.isoformat(),
                    dpi=dpi,
                    source=shared_source,
                    solar_event=event,
                    refine=refine,
                    satellite=satellite,
                    now=generated_at,
                )
                metadata = json.loads(
                    artifacts.metadata_path.read_text(encoding="utf-8")
                )
                model_runs = _model_runs(metadata)
                run_slug = _model_run_slug(model_runs)
                publish_dir = (
                    root
                    / "products"
                    / "runs"
                    / version
                    / run_slug
                    / target_date.isoformat()
                    / event.value
                )
                publish_dir.mkdir(parents=True, exist_ok=True)
                image_path = publish_dir / "national.png"
                metadata_path = publish_dir / "national.json"
                shutil.copyfile(artifacts.image_path, image_path)
                shutil.copyfile(artifacts.metadata_path, metadata_path)

                manifest_path = (
                    root
                    / "products"
                    / "latest"
                    / target_date.isoformat()
                    / f"{event.value}.json"
                )
                manifest = {
                    "schema_version": REMOTE_SCHEMA_VERSION,
                    "scope": "national",
                    "algorithm_version": version,
                    "model_runs": model_runs,
                    "target_date": target_date.isoformat(),
                    "event": event.value,
                    "generated_at": _iso_z(generated_at),
                    "valid_until": _iso_z(
                        generated_at + timedelta(hours=_PUBLISH_VALID_HOURS)
                    ),
                    "artifacts": {
                        "image": _artifact_entry(image_path, manifest_path),
                        "metadata": _artifact_entry(metadata_path, manifest_path),
                    },
                }
                _write_json(manifest_path, manifest)
                manifests.append(manifest_path)

                for location in locations:
                    local_artifacts: ProductArtifacts = local_generate(
                        target_date,
                        work_root / target_date.isoformat(),
                        location.lat,
                        location.lon,
                        dpi=dpi,
                        cube_source=shared_source,
                        solar_event=event,
                        radius_km=location.radius_km,
                        resolution_deg=location.resolution_deg,
                        satellite=satellite,
                        now=generated_at,
                    )
                    local_metadata = json.loads(
                        local_artifacts.metadata_path.read_text(encoding="utf-8")
                    )
                    local_model_runs = _model_runs(local_metadata)
                    local_run_slug = _model_run_slug(local_model_runs)
                    key = point_key(location.lat, location.lon)
                    local_publish_dir = (
                        root
                        / "products"
                        / "runs"
                        / version
                        / local_run_slug
                        / target_date.isoformat()
                        / event.value
                        / "points"
                        / key
                    )
                    local_publish_dir.mkdir(parents=True, exist_ok=True)
                    local_image_path = local_publish_dir / "point.png"
                    local_metadata_path = local_publish_dir / "point.json"
                    shutil.copyfile(local_artifacts.image_path, local_image_path)
                    shutil.copyfile(local_artifacts.metadata_path, local_metadata_path)

                    local_manifest_path = (
                        root
                        / "products"
                        / "latest"
                        / target_date.isoformat()
                        / event.value
                        / "points"
                        / f"{key}.json"
                    )
                    local_manifest = {
                        "schema_version": REMOTE_SCHEMA_VERSION,
                        "scope": "point",
                        "algorithm_version": version,
                        "model_runs": local_model_runs,
                        "target_date": target_date.isoformat(),
                        "event": event.value,
                        "generated_at": _iso_z(generated_at),
                        "valid_until": _iso_z(
                            generated_at + timedelta(hours=_PUBLISH_VALID_HOURS)
                        ),
                        "location_name": location.name,
                        "location_slug": location.slug,
                        "center": [location.lat, location.lon],
                        "radius_km": location.radius_km,
                        "resolution_deg": location.resolution_deg,
                        "artifacts": {
                            "image": _artifact_entry(
                                local_image_path, local_manifest_path
                            ),
                            "metadata": _artifact_entry(
                                local_metadata_path, local_manifest_path
                            ),
                        },
                    }
                    _write_json(local_manifest_path, local_manifest)
                    manifests.append(local_manifest_path)

    latest_root = root / "products" / "latest"
    _write_json(
        latest_root / "index.json",
        {
            "schema_version": REMOTE_SCHEMA_VERSION,
            "generated_at": _iso_z(generated_at),
            "manifests": [
                path.relative_to(latest_root).as_posix() for path in manifests
            ],
        },
    )
    return manifests


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the Firecloud Pages feed")
    parser.add_argument("--start-date", type=date.fromisoformat, default=None)
    parser.add_argument("--days", type=int, default=2)
    parser.add_argument("--output", type=Path, default=Path("_site"))
    parser.add_argument("--dpi", type=int, default=160)
    parser.add_argument(
        "--event", choices=["sunrise", "sunset", "both"], default="both"
    )
    parser.add_argument("--no-refine", action="store_true")
    parser.add_argument("--no-satellite", action="store_true")
    parser.add_argument("--algorithm-version", default=None)
    parser.add_argument(
        "--location",
        action="append",
        default=[],
        metavar="NAME:LAT:LON",
        help="precompute an exact local point; repeat for multiple locations",
    )
    parser.add_argument("--local-radius", type=float, default=150.0)
    parser.add_argument("--local-resolution", type=float, default=0.1)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    now = datetime.now(timezone.utc)
    start_date = args.start_date or datetime.now(ZoneInfo("Asia/Shanghai")).date()
    version = args.algorithm_version or os.environ.get(
        "FIRECLOUD_ALGORITHM_VERSION", os.environ.get("GITHUB_SHA", "dev")[:12]
    )
    events = (
        (SolarEvent.SUNRISE, SolarEvent.SUNSET)
        if args.event == "both"
        else (SolarEvent(args.event),)
    )
    locations = tuple(
        parse_location(
            value,
            radius_km=args.local_radius,
            resolution_deg=args.local_resolution,
        )
        for value in args.location
    )
    manifests = build_site(
        args.output,
        start_date=start_date,
        days=args.days,
        now=now,
        algorithm_version=version,
        dpi=args.dpi,
        refine=not args.no_refine,
        satellite=not args.no_satellite,
        events=events,
        locations=locations,
    )
    for manifest in manifests:
        print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
