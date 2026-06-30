"""Local fine-product field: full single-point physics over a small grid (#62).

The national overview (``grid_score``) omits the highest-weight sunward illumination
gate, the multi-layer cloud diagnosis, and AOD — too costly at country scale. For a
coordinate the user actually cares about, we instead run the *complete* detailed
single-point physics (FA-G5 cross-section ray trace + cloud diagnosis + AOD) on every
cell of a small local grid around it.

The cost trap is the GFS cube: the detailed point path fetches one cube per point,
which is unaffordable for hundreds of cells. So this module fetches **one** cube
covering the whole local region *and* every cell's sunward path, then scores each
cell against that shared cube (``sunward_section.score_point_with_cube``). A cell's
score is therefore identical to the standalone single-point score for that
coordinate — the whole point of "local fidelity, not interpolation".
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from predictor.clouds import CloudDiagnosisConfig, DEFAULT_CLOUD_CONFIG
from predictor.spatial import build_sunward_path
from predictor.sunward_section import (
    DETAIL_SUNWARD_DISTANCES_KM,
    score_point_with_cube,
)

_KM_PER_DEG_LAT = 111.0
logger = logging.getLogger(__name__)


@dataclass
class LocalField:
    lats: np.ndarray          # 1-D ascending
    lons: np.ndarray          # 1-D ascending
    probability: np.ndarray   # (ny, nx)
    center: tuple[float, float]
    radius_km: float
    valid_time: datetime
    source_label: str | None = None


# The default cap must admit the default radius/resolution across the WHOLE China
# domain. Cell count grows toward the poles (the east-west degree span widens by
# ÷cos lat), peaking at ~1215 cells for 150 km / 0.1° near 53.5°N (northern border);
# 1500 leaves headroom so a default call never crashes, while still rejecting
# genuinely oversized custom requests.
_DEFAULT_MAX_POINTS = 1500


def local_grid(
    center_lat: float,
    center_lon: float,
    *,
    radius_km: float = 150.0,
    resolution_deg: float = 0.1,
    max_points: int = _DEFAULT_MAX_POINTS,
) -> tuple[np.ndarray, np.ndarray]:
    """Build the local lat/lon grid centred on ``(center_lat, center_lon)``.

    Extends ~``radius_km`` each way (latitude in degrees = km/111; longitude divided
    by ``cos(lat)`` so the east-west span is geographically symmetric), stepped by
    ``resolution_deg`` with the centre cell included. Raises if the cell count would
    exceed ``max_points`` — a deliberate latency cap (#62), since every cell runs the
    full single-point physics. The default cap admits the default radius/resolution at
    every latitude in the China domain (cell count rises with latitude, ~1215 at the
    northern border).
    """
    if radius_km <= 0 or resolution_deg <= 0:
        raise ValueError("radius_km and resolution_deg must be positive")
    half_lat_deg = radius_km / _KM_PER_DEG_LAT
    cos_lat = max(math.cos(math.radians(center_lat)), 1e-6)
    half_lon_deg = radius_km / (_KM_PER_DEG_LAT * cos_lat)

    n_lat = int(half_lat_deg / resolution_deg)
    n_lon = int(half_lon_deg / resolution_deg)
    n_points = (2 * n_lat + 1) * (2 * n_lon + 1)
    if n_points > max_points:
        raise ValueError(
            f"local grid is {n_points} cells (> max_points={max_points}); "
            f"reduce radius_km or coarsen resolution_deg to control latency"
        )

    offsets_lat = np.arange(-n_lat, n_lat + 1) * resolution_deg
    offsets_lon = np.arange(-n_lon, n_lon + 1) * resolution_deg
    return center_lat + offsets_lat, center_lon + offsets_lon


def _shared_cube_bbox(
    lats, lons, time, *, distances_km, azimuth_deg, elevation_fn, domain, margin_deg
) -> tuple[float, float, float, float]:
    """``(lat_min, lat_max, lon_min, lon_max)`` covering every cell's sunward path."""
    lat_min = lon_min = math.inf
    lat_max = lon_max = -math.inf
    for la in lats:
        for lo in lons:
            path = build_sunward_path(
                float(la), float(lo), time, azimuth_deg=azimuth_deg,
                distances_km=distances_km, elevation_fn=elevation_fn, domain=domain,
            )
            for s in path.samples:
                lat_min = min(lat_min, s.lat)
                lat_max = max(lat_max, s.lat)
                lon_min = min(lon_min, s.lon)
                lon_max = max(lon_max, s.lon)
    return (lat_min - margin_deg, lat_max + margin_deg, lon_min - margin_deg, lon_max + margin_deg)


def build_local_field(
    predictor,
    cube_source,
    center_lat: float,
    center_lon: float,
    time: datetime,
    *,
    radius_km: float = 150.0,
    resolution_deg: float = 0.1,
    max_points: int = _DEFAULT_MAX_POINTS,
    distances_km: tuple[float, ...] | list[float] = DETAIL_SUNWARD_DISTANCES_KM,
    azimuth_deg: float | None = None,
    margin_deg: float = 0.5,
    elevation_fn=None,
    domain: tuple[float, float, float, float] | None = None,
    config: CloudDiagnosisConfig = DEFAULT_CLOUD_CONFIG,
    aod_fn=None,
) -> LocalField:
    """Run the full detailed single-point physics on every cell of a local grid.

    Fetches ONE GFS cube covering the grid and all cells' sunward paths, then scores
    each cell against it (``score_point_with_cube``). The per-cell snapshot comes from
    ``predictor.source`` (sunrise/sunset follows from ``time``'s event, like the point
    path). Returns the probability field; a cell's value equals the standalone
    detailed single-point score for that coordinate.
    """
    lats, lons = local_grid(
        center_lat, center_lon,
        radius_km=radius_km, resolution_deg=resolution_deg, max_points=max_points,
    )
    n_points = int(lats.size * lons.size)
    logger.info(
        "Local product grid: %d cells (%d x %d), radius %.0f km, resolution %.3f deg",
        n_points, lats.size, lons.size, radius_km, resolution_deg,
    )
    bbox = _shared_cube_bbox(
        lats, lons, time, distances_km=distances_km, azimuth_deg=azimuth_deg,
        elevation_fn=elevation_fn, domain=domain, margin_deg=margin_deg,
    )
    logger.info(
        "Local product GFS cube: fetching bbox %.2f..%.2f N, %.2f..%.2f E",
        bbox[0], bbox[1], bbox[2], bbox[3],
    )
    cube = cube_source.fetch_cube(bbox, time)
    logger.info("Local product GFS cube: loaded %s", getattr(cube, "source_label", "unknown"))

    # Snapshots: one batched Open-Meteo request set (fetch_many, 280 coords/request)
    # instead of N sequential calls, so a several-hundred-cell grid stays seconds, not
    # minutes. Falls back to per-cell fetch for sources without batching (e.g. tests).
    coords = [(float(la), float(lo)) for la in lats for lo in lons]
    source = predictor.source
    if hasattr(source, "fetch_many"):
        logger.info("Local product weather: fetching %d batched snapshots", len(coords))
        snapshots = source.fetch_many(coords, time)
    else:
        logger.info("Local product weather: fetching %d snapshots sequentially", len(coords))
        snapshots = [source.fetch(la, lo, time) for la, lo in coords]
    logger.info("Local product weather: loaded %d snapshots", len(snapshots))

    probability = np.empty((lats.size, lons.size), dtype=float)
    logger.info("Local product scoring: scoring %d cells", n_points)
    for k, (la, lo) in enumerate(coords):
        forecast = score_point_with_cube(
            predictor, cube, snapshots[k], la, lo, time,
            distances_km=distances_km, azimuth_deg=azimuth_deg,
            elevation_fn=elevation_fn, domain=domain, config=config, aod_fn=aod_fn,
        )
        probability[k // lons.size, k % lons.size] = forecast.probability
    finite = probability[np.isfinite(probability)]
    if finite.size:
        logger.info(
            "Local product scoring: scored %d cells (probability %.3f..%.3f)",
            n_points, float(finite.min()), float(finite.max()),
        )
    else:
        logger.info("Local product scoring: scored %d cells (all probabilities non-finite)", n_points)

    return LocalField(
        lats=lats, lons=lons, probability=probability,
        center=(center_lat, center_lon), radius_km=radius_km,
        valid_time=time, source_label=getattr(cube, "source_label", None),
    )
