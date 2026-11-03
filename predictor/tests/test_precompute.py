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
        source,
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


def test_build_site_shares_one_open_meteo_cache_across_local_products(tmp_path):
    from predictor.fetch import OpenMeteoSource

    weather_sources = []

    def fake_national(target_date, output_dir, *, solar_event, **_):
        directory = Path(output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        image = directory / f"national-{solar_event.value}.png"
        metadata = directory / f"national-{solar_event.value}.json"
        image.write_bytes(b"national")
        metadata.write_text(json.dumps({"source_label": "gfs@2026-07-10T00Z+f18"}), encoding="utf-8")
        return ProductArtifacts(image_path=image, metadata_path=metadata)

    def fake_local(target_date, output_dir, lat, lon, *, source, solar_event, **_):
        weather_sources.append((target_date, solar_event, source))
        directory = Path(output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        stem = f"point-{lat:g}_{lon:g}-{solar_event.value}"
        image, metadata = directory / f"{stem}.png", directory / f"{stem}.json"
        image.write_bytes(b"point")
        metadata.write_text(json.dumps({"source_label": "gfs@2026-07-10T00Z+f19"}), encoding="utf-8")
        return ProductArtifacts(image_path=image, metadata_path=metadata)

    build_site(
        tmp_path / "site",
        start_date=date(2026, 7, 10),
        days=2,
        source=object(),
        now=datetime(2026, 7, 10, 9, tzinfo=timezone.utc),
        locations=(
            PrecomputeLocation("Shanghai", 31.23, 121.47),
            PrecomputeLocation("Hangzhou", 30.27, 120.15),
        ),
        generate=fake_national,
        local_generate=fake_local,
    )

    assert len(weather_sources) == 2 * 2 * 2
    caches = {id(source._run_cache) for _, _, source in weather_sources}
    assert len(caches) == 1
    cache = weather_sources[0][2]._run_cache
    assert (cache.start, cache.end) == (date(2026, 7, 8), date(2026, 7, 13))
    for _, event, source in weather_sources:
        assert isinstance(source, OpenMeteoSource)
        assert source._solar_event is event


def _artifacts(directory, stem, label):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    image, metadata = directory / f"{stem}.png", directory / f"{stem}.json"
    grid = directory / f"{stem}.grid.json"
    image.write_bytes(b"png")
    metadata.write_text(json.dumps({"source_label": label}), encoding="utf-8")
    grid.write_text('{"schema":"firecloud-grid/1"}', encoding="utf-8")
    return ProductArtifacts(image_path=image, metadata_path=metadata, grid_path=grid)


def _national_with_grid(target_date, output_dir, *, solar_event, **_):
    return _artifacts(output_dir, f"national-{solar_event.value}", "gfs@2026-11-03T00Z+f09")


def test_manifests_include_grid_artifact(tmp_path):
    def fake_local(target_date, output_dir, lat, lon, *, solar_event, **_):
        return _artifacts(output_dir, f"point-{solar_event.value}", "gfs@2026-11-03T00Z+f10")

    manifests = build_site(
        tmp_path / "site", start_date=date(2026, 11, 3), days=1, source=object(),
        now=datetime(2026, 11, 3, 3, tzinfo=timezone.utc), events=(SolarEvent.SUNSET,),
        locations=(PrecomputeLocation("Shanghai", 31.23, 121.47),),
        generate=_national_with_grid, local_generate=fake_local,
    )
    names = {}
    for path in manifests:
        manifest = json.loads(path.read_text())
        grid = manifest["artifacts"]["grid"]
        resolved = path.parent / grid["path"]
        assert resolved.is_file() and grid["bytes"] == resolved.stat().st_size
        names[manifest["scope"]] = resolved.name
        assert set(manifest["artifacts"]) == {"image", "metadata", "grid"}
    assert names == {"national": "national.grid.json", "point": "point.grid.json"}


def test_regional_location_uses_region_dates_and_paths(tmp_path):
    calls = []

    def fake_local(target_date, output_dir, lat, lon, *, solar_event, **kwargs):
        calls.append((target_date, solar_event, kwargs))
        return _artifacts(output_dir, f"point-{solar_event.value}", "gfs@2026-11-03T00Z+f22")

    # 03:00Z is still 2 Nov in New York and already 3 Nov in Shanghai.
    manifests = build_site(
        tmp_path / "site", start_date=date(2026, 11, 3), days=2, source=object(),
        now=datetime(2026, 11, 3, 3, tzinfo=timezone.utc),
        locations=(PrecomputeLocation("new-york", 40.7128, -74.006, region="us-nyc"),),
        generate=_national_with_grid, local_generate=fake_local,
    )
    assert sorted({c[0] for c in calls}) == [date(2026, 11, 2), date(2026, 11, 3)]
    assert len(calls) == 4
    for _, event, kwargs in calls:
        assert kwargs["region"] == "us-nyc"
        assert kwargs["satellite"] is False
        assert kwargs["source"]._solar_event is event
    regional = [p for p in manifests if "regions" in p.parts]
    assert len(regional) == 4
    first = json.loads(regional[0].read_text())
    assert first["region"] == "us-nyc"
    assert "regions/us-nyc/2026-11-02/sunrise/points/" in regional[0].as_posix()
    assert "/regions/us-nyc/" in (regional[0].parent / first["artifacts"]["image"]["path"]).resolve().as_posix()
    index = json.loads((tmp_path / "site" / "products" / "latest" / "index.json").read_text())
    assert not any("regions/" in item for item in index["manifests"])
    assert len(index["manifests"]) == 4
    assert sorted(index["regional"]["us-nyc"]) == sorted(
        p.relative_to(tmp_path / "site" / "products" / "latest").as_posix() for p in regional
    )


def test_parse_location_accepts_optional_region():
    import argparse

    import pytest

    assert parse_location("shanghai:31.23:121.47").region == "china"
    nyc = parse_location("new-york:40.7128:-74.0060:us-nyc")
    assert (nyc.name, nyc.lat, nyc.lon, nyc.region) == ("new-york", 40.7128, -74.006, "us-nyc")
    with pytest.raises(argparse.ArgumentTypeError):
        parse_location("paris:48.85:2.35:eu-paris")
    with pytest.raises(argparse.ArgumentTypeError):
        parse_location("far:30.0:-74.0:us-nyc")   # outside the pilot's centre box


def test_regional_failure_does_not_block_the_china_feed(tmp_path, caplog):
    def fake_local(target_date, output_dir, lat, lon, *, solar_event, **kwargs):
        if kwargs.get("region") == "us-nyc":
            raise RuntimeError("HTTP Error 429: Too Many Requests")
        return _artifacts(output_dir, f"point-{solar_event.value}", "gfs@2026-11-03T00Z+f10")

    manifests = build_site(
        tmp_path / "site", start_date=date(2026, 11, 3), days=1, source=object(),
        now=datetime(2026, 11, 3, 3, tzinfo=timezone.utc), events=(SolarEvent.SUNSET,),
        locations=(
            PrecomputeLocation("Shanghai", 31.23, 121.47),
            PrecomputeLocation("new-york", 40.7128, -74.006, region="us-nyc"),
        ),
        generate=_national_with_grid, local_generate=fake_local,
    )
    assert len(manifests) == 2
    index = json.loads((tmp_path / "site" / "products" / "latest" / "index.json").read_text())
    assert len(index["manifests"]) == 2
    assert index["regional"] == {}
    assert "new-york" in caplog.text and "429" in caplog.text
