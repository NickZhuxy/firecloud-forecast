"""Offline tests for the static remote-product site builder."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

from predictor.national_product import ProductArtifacts
from predictor.precompute import build_site


def test_build_site_publishes_versioned_products_and_latest_manifests(tmp_path):
    now = datetime(2026, 7, 10, 9, tzinfo=timezone.utc)
    source = object()
    seen = []

    def fake_generate(
        target_date, output_dir, *, dpi, source, solar_event, refine, satellite, now
    ):
        seen.append((target_date, solar_event.value, source, refine, satellite, now))
        directory = Path(output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        image = directory / f"national-{solar_event.value}.png"
        metadata = directory / f"national-{solar_event.value}.json"
        image.write_bytes(f"png-{solar_event.value}".encode())
        metadata.write_text(
            json.dumps({
                "generated_utc": now.isoformat(),
                "source_label": "gfs@2026-07-10T00Z+f18 | gfs@2026-07-10T00Z+f19",
            }),
            encoding="utf-8",
        )
        return ProductArtifacts(image_path=image, metadata_path=metadata)

    manifests = build_site(
        tmp_path / "site",
        start_date=date(2026, 7, 10),
        days=1,
        source=source,
        now=now,
        algorithm_version="commit/abc123",
        generate=fake_generate,
    )

    assert len(manifests) == 2
    assert {item[1] for item in seen} == {"sunrise", "sunset"}
    assert all(item[2] is source for item in seen)
    assert (tmp_path / "site" / ".nojekyll").is_file()
    index = json.loads(
        (tmp_path / "site" / "products" / "latest" / "index.json").read_text()
    )
    assert len(index["manifests"]) == 2

    for manifest_path in manifests:
        manifest = json.loads(manifest_path.read_text())
        assert manifest["schema_version"] == "v1"
        assert manifest["algorithm_version"] == "commit-abc123"
        assert manifest["model_runs"] == ["2026-07-10T00:00:00Z"]
        for artifact in manifest["artifacts"].values():
            resolved = manifest_path.parent / artifact["path"]
            assert resolved.is_file()
            assert artifact["bytes"] == resolved.stat().st_size
