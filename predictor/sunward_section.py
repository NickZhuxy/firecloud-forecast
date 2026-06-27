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
    aod_fn=None,
) -> SunwardCrossSection:
    """Build the cross-section by extracting one column per path sample.

    Each in-domain sample's nearest cube column is normalized and cloud-diagnosed;
    out-of-domain samples get a ``None`` profile and empty layers, which
    ``build_cross_section`` masks out. Pure — no network.

    ``aod_fn(lat, lon) -> float | None`` (FA-A2), when supplied, gives the column
    AOD at each in-domain sample for the per-column path-extinction trace (injected
    so the assembly stays network-free, mirroring ``elevation_fn``); out-of-domain
    columns get ``None``. Without it, the cross-section carries no aerosol field.
    """
    profiles: list = []
    layers_per_point: list = []
    aod_per_column: list | None = [] if aod_fn is not None else None
    for sample in path.samples:
        if not sample.in_domain:
            profiles.append(None)
            layers_per_point.append([])
            if aod_per_column is not None:
                aod_per_column.append(None)
            continue
        normalized = normalize(cube.profile_at(sample.lat, sample.lon))
        profiles.append(normalized)
        layers_per_point.append(diagnose_clouds(normalized, config))
        if aod_per_column is not None:
            aod_per_column.append(aod_fn(sample.lat, sample.lon))
    return build_cross_section(
        path, profiles, layers_per_point, heights_m=heights_m, aod_per_column=aod_per_column
    )


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
    aod_fn=None,
) -> SunwardCrossSection:
    """Fetch one GFS cube over the sunward path's bbox and assemble the cross-section.

    The network half: builds the observer→sun path, fetches a single cube spanning
    it (so per-column extraction is in-memory), then delegates to the pure
    ``assemble_sunward_cross_section``. ``aod_fn(lat, lon)`` (FA-A2) supplies the
    per-column AOD for path extinction; production wires it to the Open-Meteo
    air-quality endpoint.
    """
    path = build_sunward_path(
        lat, lon, time,
        azimuth_deg=azimuth_deg,
        distances_km=distances_km,
        elevation_fn=elevation_fn,
        domain=domain,
    )
    cube = source.fetch_cube(_path_bbox(path, margin_deg), time)
    return assemble_sunward_cross_section(
        path, cube, heights_m=heights_m, config=config, aod_fn=aod_fn
    )


# A denser column set for the detailed point trace than the 1-D sampling, so the
# parabola can't leap an opaque deck between columns near the (low) vertex region.
DETAIL_SUNWARD_DISTANCES_KM = tuple(float(d) for d in range(0, 801, 25))


def score_point_with_sunward_section(
    predictor,
    cube_source,
    lat: float,
    lon: float,
    time: datetime,
    *,
    distances_km: tuple[float, ...] | list[float] = DETAIL_SUNWARD_DISTANCES_KM,
    azimuth_deg: float | None = None,
    margin_deg: float = 0.5,
    elevation_fn=None,
    domain: tuple[float, float, float, float] | None = None,
    config: CloudDiagnosisConfig = DEFAULT_CLOUD_CONFIG,
    aod_fn=None,
):
    """Score one point with the 2-D sunward ray trace wired in (activates FA-G5).

    Ties the pieces together: the snapshot from ``predictor.source``; one GFS cube
    from ``cube_source`` over the sunward path (reused for both the observer's own
    cloud-layer diagnosis and the cross-section); then ``predictor.score_snapshot``
    with the diagnosed canvas and the cross-section, so ``SunwardIlluminationGate``
    can veto when an opaque deck obstructs the light path. ``aod_fn(lat, lon)``
    (FA-A2) supplies the per-column AOD so dense path aerosol also vetoes. Returns a
    ``Forecast``.
    """
    snapshot = predictor.source.fetch(lat, lon, time)
    path = build_sunward_path(
        lat, lon, time,
        azimuth_deg=azimuth_deg,
        distances_km=distances_km,
        elevation_fn=elevation_fn,
        domain=domain,
    )
    cube = cube_source.fetch_cube(_path_bbox(path, margin_deg), time)
    observer = normalize(cube.profile_at(lat, lon))
    cloud_layers = diagnose_clouds(observer, config)
    cross_section = assemble_sunward_cross_section(path, cube, config=config, aod_fn=aod_fn)
    return predictor.score_snapshot(
        snapshot, lat, lon, time,
        cloud_layers=cloud_layers, sunward_cross_section=cross_section,
    )
