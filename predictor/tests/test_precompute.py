"""Offline tests for the static remote-product site builder."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

from predictor.national_product import ProductArtifacts
from predictor.precompute import PrecomputeLocation, build_site, parse_location
from predictor.solar_event import SolarEvent


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
        assert manifest["scope"] == "national"
        assert manifest["algorithm_version"] == "commit-abc123"
        assert manifest["model_runs"] == ["2026-07-10T00:00:00Z"]
        for artifact in manifest["artifacts"].values():
            resolved = manifest_path.parent / artifact["path"]
            assert resolved.is_file()
            assert artifact["bytes"] == resolved.stat().st_size


def test_build_site_publishes_configured_local_point_manifests(tmp_path):
    now = datetime(2026, 7, 10, 9, tzinfo=timezone.utc)
    source = object()
    local_calls = []

    def fake_national(
        target_date, output_dir, *, dpi, source, solar_event, refine, satellite, now
    ):
        directory = Path(output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        image = directory / f"national-{solar_event.value}.png"
        metadata = directory / f"national-{solar_event.value}.json"
        image.write_bytes(b"national")
        metadata.write_text(
            json.dumps({"source_label": "gfs@2026-07-10T00Z+f18"}),
            encoding="utf-8",
        )
        return ProductArtifacts(image_path=image, metadata_path=metadata)

    def fake_local(
        target_date,
        output_dir,
        lat,
        lon,
        *,
        dpi,
        cube_source,
        solar_event,
        radius_km,
        resolution_deg,
        satellite,
        now,
    ):
        local_calls.append(
            (lat, lon, radius_km, resolution_deg, cube_source, solar_event.value)
        )
        directory = Path(output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        image = directory / f"point-{lat:g}_{lon:g}-{solar_event.value}.png"
        metadata = directory / f"point-{lat:g}_{lon:g}-{solar_event.value}.json"
        image.write_bytes(b"point")
        metadata.write_text(
            json.dumps({"source_label": "gfs@2026-07-10T00Z+f19"}),
            encoding="utf-8",
        )
        return ProductArtifacts(image_path=image, metadata_path=metadata)

    manifests = build_site(
        tmp_path / "site",
        start_date=date(2026, 7, 10),
        days=1,
        source=source,
        now=now,
        algorithm_version="abc123",
        events=(SolarEvent.SUNSET,),
        locations=(PrecomputeLocation("Shanghai", 31.23, 121.47),),
        generate=fake_national,
        local_generate=fake_local,
    )

    assert len(manifests) == 2
    assert local_calls == [(31.23, 121.47, 150.0, 0.1, source, "sunset")]
    point_manifest_path = next(path for path in manifests if "points" in path.parts)
    manifest = json.loads(point_manifest_path.read_text())
    assert manifest["scope"] == "point"
    assert manifest["location_name"] == "Shanghai"
    assert manifest["location_slug"] == "shanghai"
    assert manifest["center"] == [31.23, 121.47]
    assert manifest["radius_km"] == 150.0
    assert manifest["resolution_deg"] == 0.1
    assert point_manifest_path.name == "31.2300_121.4700.json"
    for artifact in manifest["artifacts"].values():
        assert (point_manifest_path.parent / artifact["path"]).is_file()


def test_parse_location_uses_shared_grid_settings():
    location = parse_location(
        "shanghai:31.23:121.47", radius_km=80.0, resolution_deg=0.05
    )

    assert location == PrecomputeLocation("shanghai", 31.23, 121.47, 80.0, 0.05)
