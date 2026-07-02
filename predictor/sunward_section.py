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
from predictor.geometry import convective_duration_min
from predictor.normalize import normalize
from predictor.profiles import AtmosphericCube
from predictor.spatial import (
    DEFAULT_SUNWARD_DISTANCES_KM,
    SunwardPath,
    build_sunward_path,
)
from predictor.stability import (
    DEFAULT_STABILITY_CONFIG,
    StabilityConfig,
    StabilityDiagnosis,
    diagnose_stability,
)

# FA-C4 (#86), manual §4.1.2: a congestus-grade convective situation is an
# independent cloud regime the numerical model cannot forecast effectively.
# The honest treatment is to LABEL it, estimate its own §1.2.3 duration, and
# shrink the probability toward the uninformative 0.5 rather than pretend the
# stratiform reasoning still carries full weight.
CONVECTIVE_REGIME_DAMPING = 0.5


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
    return score_point_with_cube(
        predictor, cube, snapshot, lat, lon, time,
        distances_km=distances_km, azimuth_deg=azimuth_deg,
        elevation_fn=elevation_fn, domain=domain, config=config, aod_fn=aod_fn,
    )


def score_point_with_cube(
    predictor,
    cube: AtmosphericCube,
    snapshot,
    lat: float,
    lon: float,
    time: datetime,
    *,
    distances_km: tuple[float, ...] | list[float] = DETAIL_SUNWARD_DISTANCES_KM,
    azimuth_deg: float | None = None,
    elevation_fn=None,
    domain: tuple[float, float, float, float] | None = None,
    config: CloudDiagnosisConfig = DEFAULT_CLOUD_CONFIG,
    aod_fn=None,
    stability_config: StabilityConfig = DEFAULT_STABILITY_CONFIG,
):
    """Score one point against an ALREADY-FETCHED cube + snapshot.

    The shared-cube core of the detailed point path (#62): diagnoses the observer's
    canvas and assembles the sunward cross-section from ``cube`` (no fetch), then
    scores. ``score_point_with_sunward_section`` is this plus a per-point cube fetch;
    a local grid (``local_field``) reuses ONE cube across every observer instead.
    """
    observer = normalize(cube.profile_at(lat, lon))
    cloud_layers = diagnose_clouds(observer, config)
    stability = diagnose_stability(observer, stability_config)
    path = build_sunward_path(
        lat, lon, time,
        azimuth_deg=azimuth_deg,
        distances_km=distances_km,
        elevation_fn=elevation_fn,
        domain=domain,
    )
    cross_section = assemble_sunward_cross_section(path, cube, config=config, aod_fn=aod_fn)
    forecast = predictor.score_snapshot(
        snapshot, lat, lon, time,
        cloud_layers=cloud_layers, sunward_cross_section=cross_section,
    )
    return _with_convective_regime(forecast, stability, lat)


def _with_convective_regime(forecast, stability: StabilityDiagnosis, lat: float):
    """Attach the FA-C4 diagnosis; damp congestus cases per manual §4.1.2.

    Every forecast carries the regime label (explainability); only a clear
    congestus (past the marginal band) switches to the §1.2.3 vertical-line
    duration AND shrinks the probability toward 0.5 — the manual treats that
    regime as unsupported by model-based forecasting, so confidence in either
    direction must drop. Marginal cases are labeled but not damped.
    """
    geometry = dict(forecast.geometry or {})
    geometry.update(
        cloud_regime=stability.regime,
        lcl_m=stability.lcl_m,
        unstable_depth_m=stability.unstable_depth_m,
        regime_marginal=stability.marginal,
    )
    if stability.regime == "cumulus_congestus":
        geometry["convective_duration_min"] = convective_duration_min(
            stability.unstable_top_m or 0.0, lat
        )
        if not stability.marginal:
            forecast.probability = (
                0.5 + (forecast.probability - 0.5) * CONVECTIVE_REGIME_DAMPING
            )
            forecast.components["convective_regime_damping"] = CONVECTIVE_REGIME_DAMPING
            forecast.explanation += (
                ";浓积云对流云况(手册§4.1.2:模式支持度低,建议临近实况)"
            )
    forecast.geometry = geometry
    return forecast
