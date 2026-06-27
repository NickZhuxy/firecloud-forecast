"""Assemble the 2-D sunward cross-section for single-point scoring (#62 plumbing).

The detailed single-point method (manual §4.1.1-2) reads the atmosphere on a
*cross-section* — distance × height of cloud along the sunset azimuth — and traces
the sunlight ray across it. The pieces already exist (``build_sunward_path``,
``GFSSource.fetch_cube``/``profile_at``, ``normalize``, ``diagnose_clouds``,
``build_cross_section``, ``ray_path.trace_ray_clearance``); this module is the
missing glue that ties them into one cross-section the scorer can consume.

``assemble_sunward_cross_section`` is pure (takes an already-fetched cube, no
network) so it is offline-testable; ``sunward_cross_section_for_point`` is the thin
network orchestrator that fetches one cube over the path's bounding box first.
"""
from __future__ import annotations

from datetime import datetime

from predictor.clouds import CloudDiagnosisConfig, DEFAULT_CLOUD_CONFIG, diagnose_clouds
from predictor.cross_section import SunwardCrossSection, build_cross_section
from predictor.normalize import normalize
from predictor.profiles import AtmosphericCube
from predictor.spatial import (
    DEFAULT_SUNWARD_DISTANCES_KM,
    SunwardPath,
    build_sunward_path,
)


def assemble_sunward_cross_section(
    path: SunwardPath,
    cube: AtmosphericCube,
    *,
    heights_m: list[float] | None = None,
    config: CloudDiagnosisConfig = DEFAULT_CLOUD_CONFIG,
) -> SunwardCrossSection:
    """Build the cross-section by extracting one column per path sample.

    Each in-domain sample's nearest cube column is normalized and cloud-diagnosed;
    out-of-domain samples get a ``None`` profile and empty layers, which
    ``build_cross_section`` masks out. Pure — no network.
    """
    profiles: list = []
    layers_per_point: list = []
    for sample in path.samples:
        if not sample.in_domain:
            profiles.append(None)
            layers_per_point.append([])
            continue
        normalized = normalize(cube.profile_at(sample.lat, sample.lon))
        profiles.append(normalized)
        layers_per_point.append(diagnose_clouds(normalized, config))
    return build_cross_section(path, profiles, layers_per_point, heights_m=heights_m)


def _path_bbox(
    path: SunwardPath, margin_deg: float
) -> tuple[float, float, float, float]:
    """``(lat_min, lat_max, lon_min, lon_max)`` covering the path, padded by ``margin_deg``.

    Matches ``fetch_cube``'s bbox order (NOT the (south, west, north, east) of
    ``overlay.CN_BBOX``). Assumes the path does not straddle the antimeridian — true
    for the China domain; a wrapping path would need seam handling.
    """
    lats = [s.lat for s in path.samples]
    lons = [s.lon for s in path.samples]
    return (
        min(lats) - margin_deg,
        max(lats) + margin_deg,
        min(lons) - margin_deg,
        max(lons) + margin_deg,
    )


def sunward_cross_section_for_point(
    source,
    lat: float,
    lon: float,
    time: datetime,
    *,
    distances_km: tuple[float, ...] | list[float] = DEFAULT_SUNWARD_DISTANCES_KM,
    azimuth_deg: float | None = None,
    heights_m: list[float] | None = None,
    margin_deg: float = 0.5,
    elevation_fn=None,
    domain: tuple[float, float, float, float] | None = None,
    config: CloudDiagnosisConfig = DEFAULT_CLOUD_CONFIG,
) -> SunwardCrossSection:
    """Fetch one GFS cube over the sunward path's bbox and assemble the cross-section.

    The network half: builds the observer→sun path, fetches a single cube spanning
    it (so per-column extraction is in-memory), then delegates to the pure
    ``assemble_sunward_cross_section``.
    """
    path = build_sunward_path(
        lat, lon, time,
        azimuth_deg=azimuth_deg,
        distances_km=distances_km,
        elevation_fn=elevation_fn,
        domain=domain,
    )
    cube = source.fetch_cube(_path_bbox(path, margin_deg), time)
    return assemble_sunward_cross_section(path, cube, heights_m=heights_m, config=config)
