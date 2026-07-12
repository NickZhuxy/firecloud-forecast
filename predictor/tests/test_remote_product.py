"""Offline tests for remote-first national product delivery."""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone

import pytest
import requests

from predictor.remote_product import RemoteProductClient, RemoteProductUnavailable


class _Response:
    def __init__(self, *, content=b"", payload=None, status=200):
        self.content = content
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        if self._payload is None:
            return json.loads(self.content)
        return self._payload


class _Session:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        response = self.responses[url]
        if isinstance(response, Exception):
            raise response
        return response


def _manifest(now, image, metadata, *, expires_delta=timedelta(hours=6)):
    return {
        "schema_version": "v1",
        "algorithm_version": "abc123",
        "model_runs": ["2026-07-10T00:00:00Z"],
        "target_date": "2026-07-10",
        "event": "sunrise",
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "valid_until": (now + expires_delta).isoformat().replace("+00:00", "Z"),
        "artifacts": {
            "image": {
                "path": "../../runs/abc123/gfs-20260710T00Z/2026-07-10/sunrise/national.png",
                "bytes": len(image),
                "sha256": hashlib.sha256(image).hexdigest(),
            },
            "metadata": {
                "path": "../../runs/abc123/gfs-20260710T00Z/2026-07-10/sunrise/national.json",
                "bytes": len(metadata),
                "sha256": hashlib.sha256(metadata).hexdigest(),
            },
        },
    }


def _point_manifest(now, image, metadata):
    manifest = _manifest(now, image, metadata)
    manifest.update({
        "scope": "point",
        "center": [31.23, 121.47],
        "radius_km": 150.0,
        "resolution_deg": 0.1,
        "location_name": "Shanghai",
    })
    root = "../../../../runs/abc123/gfs-20260710T00Z/2026-07-10/sunrise/points/31.2300_121.4700"
    manifest["artifacts"]["image"]["path"] = f"{root}/point.png"
    manifest["artifacts"]["metadata"]["path"] = f"{root}/point.json"
    return manifest


def test_remote_fetch_validates_and_materializes_product(tmp_path):
    now = datetime(2026, 7, 10, 9, tzinfo=timezone.utc)
    base = "https://example.test/firecloud/"
    manifest_url = base + "products/latest/2026-07-10/sunrise.json"
    image_url = base + "products/runs/abc123/gfs-20260710T00Z/2026-07-10/sunrise/national.png"
    metadata_url = base + "products/runs/abc123/gfs-20260710T00Z/2026-07-10/sunrise/national.json"
    image = b"png-payload"
    metadata = b'{"product":"china_firecloud_potential"}\n'
    manifest = _manifest(now, image, metadata)
    session = _Session({
        manifest_url: _Response(payload=manifest),
        image_url: _Response(content=image),
        metadata_url: _Response(content=metadata),
    })
    client = RemoteProductClient(base_url=base, session=session, now_fn=lambda: now)

    result = client.fetch(date(2026, 7, 10), "sunrise", tmp_path)

    assert result.cached is False
    assert result.model_runs == ("2026-07-10T00:00:00Z",)
    assert result.artifacts.image_path.read_bytes() == image
    assert result.artifacts.metadata_path.read_bytes() == metadata
    assert (tmp_path / ".remote-manifest-sunrise.json").is_file()


def test_remote_fetch_uses_valid_cached_copy_when_network_is_down(tmp_path):
    now = datetime(2026, 7, 10, 9, tzinfo=timezone.utc)
    base = "https://example.test/firecloud/"
    manifest_url = base + "products/latest/2026-07-10/sunrise.json"
    image_url = base + "products/runs/abc123/gfs-20260710T00Z/2026-07-10/sunrise/national.png"
    metadata_url = base + "products/runs/abc123/gfs-20260710T00Z/2026-07-10/sunrise/national.json"
    image = b"png-payload"
    metadata = b"{}\n"
    manifest = _manifest(now, image, metadata)
    warm = _Session({
        manifest_url: _Response(payload=manifest),
        image_url: _Response(content=image),
        metadata_url: _Response(content=metadata),
    })
    RemoteProductClient(base_url=base, session=warm, now_fn=lambda: now).fetch(
        date(2026, 7, 10), "sunrise", tmp_path
    )
    offline = _Session({manifest_url: requests.ConnectionError("offline")})

    result = RemoteProductClient(
        base_url=base,
        session=offline,
        now_fn=lambda: now + timedelta(hours=1),
    ).fetch(date(2026, 7, 10), "sunrise", tmp_path)

    assert result.cached is True
    assert result.artifacts.image_path.read_bytes() == image


def test_remote_fetch_rejects_expired_manifest(tmp_path):
    now = datetime(2026, 7, 10, 9, tzinfo=timezone.utc)
    base = "https://example.test/firecloud/"
    manifest_url = base + "products/latest/2026-07-10/sunrise.json"
    image = b"png"
    metadata = b"{}"
    manifest = _manifest(now, image, metadata, expires_delta=timedelta(seconds=-1))
    session = _Session({manifest_url: _Response(payload=manifest)})

    with pytest.raises(RemoteProductUnavailable, match="expired"):
        RemoteProductClient(base_url=base, session=session, now_fn=lambda: now).fetch(
            date(2026, 7, 10), "sunrise", tmp_path
        )


def test_remote_fetch_rejects_checksum_mismatch_without_writing(tmp_path):
    now = datetime(2026, 7, 10, 9, tzinfo=timezone.utc)
    base = "https://example.test/firecloud/"
    manifest_url = base + "products/latest/2026-07-10/sunrise.json"
    image_url = base + "products/runs/abc123/gfs-20260710T00Z/2026-07-10/sunrise/national.png"
    metadata_url = base + "products/runs/abc123/gfs-20260710T00Z/2026-07-10/sunrise/national.json"
    manifest = _manifest(now, b"expected", b"{}")
    session = _Session({
        manifest_url: _Response(payload=manifest),
        image_url: _Response(content=b"corrupt!"),
        metadata_url: _Response(content=b"{}"),
    })

    with pytest.raises(RemoteProductUnavailable, match="checksum"):
        RemoteProductClient(base_url=base, session=session, now_fn=lambda: now).fetch(
            date(2026, 7, 10), "sunrise", tmp_path
        )
    assert not (tmp_path / "national-sunrise.png").exists()


def test_remote_point_fetch_validates_grid_and_materializes_local_filename(tmp_path):
    now = datetime(2026, 7, 10, 9, tzinfo=timezone.utc)
    base = "https://example.test/firecloud/"
    key = "31.2300_121.4700"
    manifest_url = base + f"products/latest/2026-07-10/sunrise/points/{key}.json"
    artifact_root = (
        base
        + f"products/runs/abc123/gfs-20260710T00Z/2026-07-10/sunrise/points/{key}"
    )
    image = b"point-png"
    metadata = b'{"product":"china_firecloud_local"}\n'
    manifest = _point_manifest(now, image, metadata)
    session = _Session({
        manifest_url: _Response(payload=manifest),
        f"{artifact_root}/point.png": _Response(content=image),
        f"{artifact_root}/point.json": _Response(content=metadata),
    })

    result = RemoteProductClient(
        base_url=base, session=session, now_fn=lambda: now
    ).fetch_point(
        date(2026, 7, 10),
        "sunrise",
        tmp_path,
        31.23,
        121.47,
        radius_km=150.0,
        resolution_deg=0.1,
    )

    assert result.cached is False
    assert result.artifacts.image_path.name == "point-31.23_121.47-sunrise.png"
    assert result.artifacts.image_path.read_bytes() == image
    assert (
        tmp_path / ".remote-manifest-point-31.2300_121.4700-sunrise.json"
    ).is_file()


def test_remote_point_fetch_rejects_a_different_requested_grid(tmp_path):
    now = datetime(2026, 7, 10, 9, tzinfo=timezone.utc)
    base = "https://example.test/firecloud/"
    manifest_url = (
        base
        + "products/latest/2026-07-10/sunrise/points/31.2300_121.4700.json"
    )
    manifest = _point_manifest(now, b"point-png", b"{}")
    session = _Session({manifest_url: _Response(payload=manifest)})

    with pytest.raises(RemoteProductUnavailable, match="resolution mismatch"):
        RemoteProductClient(
            base_url=base, session=session, now_fn=lambda: now
        ).fetch_point(
            date(2026, 7, 10),
            "sunrise",
            tmp_path,
            31.23,
            121.47,
            radius_km=150.0,
            resolution_deg=0.05,
        )
    assert not (tmp_path / "point-31.23_121.47-sunrise.png").exists()
