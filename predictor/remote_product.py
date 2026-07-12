"""Fetch precomputed national and exact-center local products from Pages."""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

from predictor.national_product import ProductArtifacts
from predictor.solar_event import SolarEvent

logger = logging.getLogger(__name__)

REMOTE_SCHEMA_VERSION = "v1"
DEFAULT_REMOTE_BASE_URL = "https://nickzhuxy.github.io/firecloud-forecast/"
_REMOTE_MANIFEST_STEM = ".remote-manifest"
POINT_COORDINATE_PRECISION = 4


class RemoteProductUnavailable(RuntimeError):
    """No fresh, valid remote or locally cached remote product is available."""


@dataclass(frozen=True)
class RemoteProductResult:
    artifacts: ProductArtifacts
    model_runs: tuple[str, ...]
    generated_at: datetime
    cached: bool


def _parse_utc(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise RemoteProductUnavailable(f"invalid remote {field}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


def point_key(lat: float, lon: float) -> str:
    """Stable path key for an exact precomputed local-product center."""
    return (
        f"{float(lat):.{POINT_COORDINATE_PRECISION}f}_"
        f"{float(lon):.{POINT_COORDINATE_PRECISION}f}"
    )


def point_stem(lat: float, lon: float, event: SolarEvent | str) -> str:
    """Local filename matching the locally generated point product."""
    return f"point-{float(lat):g}_{float(lon):g}-{SolarEvent(event).value}"


class RemoteProductClient:
    """Download checksum-pinned PNG/JSON products with a fresh-cache fallback."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        session=None,
        now_fn=None,
        timeout: tuple[float, float] = (3.0, 20.0),
    ):
        configured = base_url or os.environ.get(
            "FIRECLOUD_REMOTE_BASE_URL", DEFAULT_REMOTE_BASE_URL
        )
        self.base_url = configured.rstrip("/") + "/"
        self.session = session or requests
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self.timeout = timeout

    def fetch(
        self,
        target_date: date,
        event: SolarEvent | str,
        output_dir: str | Path,
    ) -> RemoteProductResult:
        event_value = SolarEvent(event).value
        directory = Path(output_dir)
        manifest_url = urljoin(
            self.base_url,
            f"products/latest/{target_date.isoformat()}/{event_value}.json",
        )
        remote_error: Exception | None = None
        try:
            return self._fetch_remote(
                manifest_url, target_date, event_value, directory
            )
        except Exception as exc:  # noqa: BLE001 - cached copy is the resilience path
            remote_error = exc
            logger.warning("remote product fetch failed: %s", exc)

        try:
            return self._load_cached(target_date, event_value, directory)
        except Exception:
            if isinstance(remote_error, RemoteProductUnavailable):
                raise remote_error
            raise RemoteProductUnavailable(
                f"remote product unavailable: {remote_error}"
            ) from remote_error

    def fetch_point(
        self,
        target_date: date,
        event: SolarEvent | str,
        output_dir: str | Path,
        lat: float,
        lon: float,
        *,
        radius_km: float,
        resolution_deg: float,
    ) -> RemoteProductResult:
        """Fetch one exact precomputed local product, with a verified cache fallback."""
        event_value = SolarEvent(event).value
        key = point_key(lat, lon)
        directory = Path(output_dir)
        manifest_url = urljoin(
            self.base_url,
            f"products/latest/{target_date.isoformat()}/{event_value}/points/{key}.json",
        )
        remote_error: Exception | None = None
        try:
            return self._fetch_remote_point(
                manifest_url,
                target_date,
                event_value,
                directory,
                lat,
                lon,
                radius_km,
                resolution_deg,
            )
        except Exception as exc:  # noqa: BLE001 - cache fallback is intentional
            remote_error = exc
            logger.warning("remote point product fetch failed: %s", exc)

        try:
            return self._load_cached_point(
                target_date,
                event_value,
                directory,
                lat,
                lon,
                radius_km,
                resolution_deg,
            )
        except Exception:
            if isinstance(remote_error, RemoteProductUnavailable):
                raise remote_error
            raise RemoteProductUnavailable(
                f"remote point product unavailable: {remote_error}"
            ) from remote_error

    def _fetch_remote(
        self,
        manifest_url: str,
        target_date: date,
        event: str,
        output_dir: Path,
    ) -> RemoteProductResult:
        response = self.session.get(
            manifest_url,
            timeout=self.timeout,
            headers={"User-Agent": "firecloud-forecast/remote-product-v1"},
        )
        response.raise_for_status()
        try:
            manifest = response.json()
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RemoteProductUnavailable("invalid remote manifest JSON") from exc
        validated = self._validate_manifest(manifest, target_date, event)

        image = self._download_artifact(
            manifest_url, validated["artifacts"]["image"]
        )
        metadata = self._download_artifact(
            manifest_url, validated["artifacts"]["metadata"]
        )
        try:
            json.loads(metadata)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RemoteProductUnavailable("invalid remote product metadata") from exc

        image_path = output_dir / f"national-{event}.png"
        metadata_path = output_dir / f"national-{event}.json"
        _atomic_write(image_path, image)
        _atomic_write(metadata_path, metadata)
        _atomic_write(
            self._cache_manifest_path(output_dir, event),
            (json.dumps(validated, ensure_ascii=False, indent=2) + "\n").encode(),
        )
        return self._result(validated, image_path, metadata_path, cached=False)

    def _load_cached(
        self, target_date: date, event: str, output_dir: Path
    ) -> RemoteProductResult:
        cache_path = self._cache_manifest_path(output_dir, event)
        try:
            manifest = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RemoteProductUnavailable("no cached remote product") from exc
        validated = self._validate_manifest(manifest, target_date, event)
        image_path = output_dir / f"national-{event}.png"
        metadata_path = output_dir / f"national-{event}.json"
        self._verify_file(image_path, validated["artifacts"]["image"])
        self._verify_file(metadata_path, validated["artifacts"]["metadata"])
        return self._result(validated, image_path, metadata_path, cached=True)

    def _fetch_remote_point(
        self,
        manifest_url: str,
        target_date: date,
        event: str,
        output_dir: Path,
        lat: float,
        lon: float,
        radius_km: float,
        resolution_deg: float,
    ) -> RemoteProductResult:
        response = self.session.get(
            manifest_url,
            timeout=self.timeout,
            headers={"User-Agent": "firecloud-forecast/remote-product-v1"},
        )
        response.raise_for_status()
        try:
            manifest = response.json()
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RemoteProductUnavailable("invalid remote point manifest JSON") from exc
        validated = self._validate_point_manifest(
            manifest,
            target_date,
            event,
            lat,
            lon,
            radius_km,
            resolution_deg,
        )

        image = self._download_artifact(
            manifest_url, validated["artifacts"]["image"]
        )
        metadata = self._download_artifact(
            manifest_url, validated["artifacts"]["metadata"]
        )
        try:
            json.loads(metadata)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RemoteProductUnavailable("invalid remote point metadata") from exc

        stem = point_stem(lat, lon, event)
        image_path = output_dir / f"{stem}.png"
        metadata_path = output_dir / f"{stem}.json"
        _atomic_write(image_path, image)
        _atomic_write(metadata_path, metadata)
        _atomic_write(
            self._cache_point_manifest_path(output_dir, event, lat, lon),
            (json.dumps(validated, ensure_ascii=False, indent=2) + "\n").encode(),
        )
        return self._result(validated, image_path, metadata_path, cached=False)

    def _load_cached_point(
        self,
        target_date: date,
        event: str,
        output_dir: Path,
        lat: float,
        lon: float,
        radius_km: float,
        resolution_deg: float,
    ) -> RemoteProductResult:
        cache_path = self._cache_point_manifest_path(output_dir, event, lat, lon)
        try:
            manifest = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RemoteProductUnavailable("no cached remote point product") from exc
        validated = self._validate_point_manifest(
            manifest,
            target_date,
            event,
            lat,
            lon,
            radius_km,
            resolution_deg,
        )
        stem = point_stem(lat, lon, event)
        image_path = output_dir / f"{stem}.png"
        metadata_path = output_dir / f"{stem}.json"
        self._verify_file(image_path, validated["artifacts"]["image"])
        self._verify_file(metadata_path, validated["artifacts"]["metadata"])
        return self._result(validated, image_path, metadata_path, cached=True)

    def _validate_manifest(self, manifest, target_date: date, event: str) -> dict:
        if not isinstance(manifest, dict):
            raise RemoteProductUnavailable("invalid remote manifest")
        if manifest.get("schema_version") != REMOTE_SCHEMA_VERSION:
            raise RemoteProductUnavailable("unsupported remote manifest schema")
        if manifest.get("target_date") != target_date.isoformat():
            raise RemoteProductUnavailable("remote product date mismatch")
        if manifest.get("event") != event:
            raise RemoteProductUnavailable("remote product event mismatch")
        generated = _parse_utc(manifest.get("generated_at"), "generated_at")
        valid_until = _parse_utc(manifest.get("valid_until"), "valid_until")
        now = self.now_fn().astimezone(timezone.utc)
        if valid_until <= now:
            raise RemoteProductUnavailable("remote product manifest expired")
        model_runs = manifest.get("model_runs")
        if not isinstance(model_runs, list) or not all(
            isinstance(value, str) for value in model_runs
        ):
            raise RemoteProductUnavailable("invalid remote model_runs")
        artifacts = manifest.get("artifacts")
        if not isinstance(artifacts, dict):
            raise RemoteProductUnavailable("invalid remote artifacts")
        for name in ("image", "metadata"):
            self._validate_artifact_spec(artifacts.get(name), name)
        validated = dict(manifest)
        validated["generated_at"] = generated.isoformat().replace("+00:00", "Z")
        validated["valid_until"] = valid_until.isoformat().replace("+00:00", "Z")
        return validated

    def _validate_point_manifest(
        self,
        manifest,
        target_date: date,
        event: str,
        lat: float,
        lon: float,
        radius_km: float,
        resolution_deg: float,
    ) -> dict:
        validated = self._validate_manifest(manifest, target_date, event)
        if validated.get("scope") != "point":
            raise RemoteProductUnavailable("remote product scope mismatch")
        center = validated.get("center")
        if not (
            isinstance(center, list)
            and len(center) == 2
            and all(isinstance(value, (int, float)) for value in center)
        ):
            raise RemoteProductUnavailable("invalid remote point center")
        tolerance = 10 ** (-POINT_COORDINATE_PRECISION)
        if not (
            math.isclose(float(center[0]), float(lat), abs_tol=tolerance)
            and math.isclose(float(center[1]), float(lon), abs_tol=tolerance)
        ):
            raise RemoteProductUnavailable("remote point center mismatch")
        try:
            remote_radius = float(validated["radius_km"])
            remote_resolution = float(validated["resolution_deg"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RemoteProductUnavailable("invalid remote point grid") from exc
        if not math.isclose(remote_radius, float(radius_km), abs_tol=1e-9):
            raise RemoteProductUnavailable("remote point radius mismatch")
        if not math.isclose(remote_resolution, float(resolution_deg), abs_tol=1e-9):
            raise RemoteProductUnavailable("remote point resolution mismatch")
        return validated

    @staticmethod
    def _validate_artifact_spec(spec, name: str) -> None:
        if not isinstance(spec, dict):
            raise RemoteProductUnavailable(f"invalid remote {name} artifact")
        path = spec.get("path")
        if not isinstance(path, str) or not path or path.startswith("/"):
            raise RemoteProductUnavailable(f"invalid remote {name} path")
        parsed = urlparse(path)
        if parsed.scheme or parsed.netloc:
            raise RemoteProductUnavailable(f"remote {name} path must be relative")
        if not isinstance(spec.get("bytes"), int) or spec["bytes"] < 0:
            raise RemoteProductUnavailable(f"invalid remote {name} size")
        digest = spec.get("sha256")
        if not isinstance(digest, str) or len(digest) != 64:
            raise RemoteProductUnavailable(f"invalid remote {name} checksum")

    def _download_artifact(self, manifest_url: str, spec: dict) -> bytes:
        url = urljoin(manifest_url, spec["path"])
        if urlparse(url).netloc != urlparse(self.base_url).netloc:
            raise RemoteProductUnavailable("remote artifact crossed origin")
        response = self.session.get(
            url,
            timeout=self.timeout,
            headers={"User-Agent": "firecloud-forecast/remote-product-v1"},
        )
        response.raise_for_status()
        payload = bytes(response.content)
        self._verify_payload(payload, spec)
        return payload

    @staticmethod
    def _verify_payload(payload: bytes, spec: dict) -> None:
        if len(payload) != spec["bytes"]:
            raise RemoteProductUnavailable("remote artifact size mismatch")
        if _sha256(payload) != spec["sha256"]:
            raise RemoteProductUnavailable("remote artifact checksum mismatch")

    @classmethod
    def _verify_file(cls, path: Path, spec: dict) -> None:
        try:
            payload = path.read_bytes()
        except OSError as exc:
            raise RemoteProductUnavailable("cached remote artifact missing") from exc
        cls._verify_payload(payload, spec)

    @staticmethod
    def _cache_manifest_path(output_dir: Path, event: str) -> Path:
        return output_dir / f"{_REMOTE_MANIFEST_STEM}-{event}.json"

    @staticmethod
    def _cache_point_manifest_path(
        output_dir: Path, event: str, lat: float, lon: float
    ) -> Path:
        return output_dir / f"{_REMOTE_MANIFEST_STEM}-point-{point_key(lat, lon)}-{event}.json"

    @staticmethod
    def _result(
        manifest: dict,
        image_path: Path,
        metadata_path: Path,
        *,
        cached: bool,
    ) -> RemoteProductResult:
        return RemoteProductResult(
            artifacts=ProductArtifacts(image_path=image_path, metadata_path=metadata_path),
            model_runs=tuple(manifest["model_runs"]),
            generated_at=_parse_utc(manifest["generated_at"], "generated_at"),
            cached=cached,
        )
