"""Sunward cross-section helpers for detailed fire-cloud forecasts.

The manual forecasting workflow is spatial: start at the observer and inspect
the atmosphere along the sunset azimuth until the illuminated cloud deck ends.
This module keeps that geometry independent from HTTP and scoring code.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math


EARTH_RADIUS_KM = 6371.0
DEFAULT_SUNWARD_DISTANCES_KM = (0.0, 50.0, 100.0, 150.0, 250.0, 400.0, 600.0, 800.0)
# GFS 0.25° global grid: latitude 90→-90, longitude 0→359.75.
GFS_GRID_RES_DEG = 0.25


@dataclass
class SunwardProfile:
    """Weather samples from the observer outward along the sunset azimuth."""

    azimuth_deg: float
    distances_km: list[float]
    cloud_low_pct: list[float]
    cloud_mid_pct: list[float]
    cloud_high_pct: list[float]
    aerosol_optical_depth: list[float | None]
    wind_speed_850_m_s: list[float | None]
    wind_direction_850_deg: list[float | None]
    wind_speed_700_m_s: list[float | None]
    wind_direction_700_deg: list[float | None]
    wind_speed_400_m_s: list[float | None]
    wind_direction_400_deg: list[float | None]


def destination_point(
    lat: float, lon: float, bearing_deg: float, distance_km: float
) -> tuple[float, float]:
    """Return the great-circle destination from ``(lat, lon)``.

    ``bearing_deg`` is clockwise from true north. Longitude is normalised to
    [-180, 180], which keeps multi-coordinate API requests unambiguous.
    """
    if distance_km == 0:
        return lat, lon

    phi1 = math.radians(lat)
    lam1 = math.radians(lon)
    theta = math.radians(bearing_deg)
    delta = distance_km / EARTH_RADIUS_KM

    phi2 = math.asin(
        math.sin(phi1) * math.cos(delta)
        + math.cos(phi1) * math.sin(delta) * math.cos(theta)
    )
    lam2 = lam1 + math.atan2(
        math.sin(theta) * math.sin(delta) * math.cos(phi1),
        math.cos(delta) - math.sin(phi1) * math.sin(phi2),
    )
    lon2 = (math.degrees(lam2) + 540.0) % 360.0 - 180.0
    return math.degrees(phi2), lon2


def sunward_coordinates(
    lat: float,
    lon: float,
    azimuth_deg: float,
    distances_km: tuple[float, ...] | list[float] = DEFAULT_SUNWARD_DISTANCES_KM,
) -> list[tuple[float, float]]:
    """Build the observer-to-sun sampling transect."""
    return [destination_point(lat, lon, azimuth_deg, d) for d in distances_km]


# ---------------------------------------------------------------------------
# Sunward 3D sampling path (#12)
# ---------------------------------------------------------------------------


@dataclass
class SunwardSample:
    """One point along the sunward great-circle path."""

    distance_km: float
    lat: float
    lon: float
    grid_lat_idx: int     # index on the GFS 0.25° grid (lat 90→-90)
    grid_lon_idx: int     # index on the GFS 0.25° grid (lon 0→359.75)
    elevation_m: float | None  # ground elevation from the injected provider
    in_domain: bool       # within the configured data domain


@dataclass
class SunwardPath:
    """The full observer→sun sampling path used to drive vertical sampling."""

    observer: tuple[float, float]
    azimuth_deg: float
    target_time: datetime
    samples: list[SunwardSample]


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance (km) between two points on the Earth sphere."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2
    return 2.0 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def grid_index(lat: float, lon: float, res_deg: float = GFS_GRID_RES_DEG) -> tuple[int, int]:
    """Nearest (lat_idx, lon_idx) on the global GFS grid.

    Latitudes run 90→-90 (index 0 = 90 N); longitudes run 0→360 (index 0 = 0 E),
    so a negative query longitude is wrapped into 0–360 and the 360 column wraps
    back to 0 — keeping the antimeridian seam contiguous.
    """
    n_lon = int(round(360.0 / res_deg))
    lat_idx = int(round((90.0 - lat) / res_deg))
    lon_idx = int(round((lon % 360.0) / res_deg)) % n_lon
    return lat_idx, lon_idx


def even_distances(max_km: float = 800.0, count: int = 9) -> list[float]:
    """``count`` evenly-spaced sample distances from 0 to ``max_km`` (inclusive)."""
    if count < 2:
        return [0.0]
    step = max_km / (count - 1)
    return [round(i * step, 6) for i in range(count)]


def _within_domain(lat: float, lon: float, domain: tuple[float, float, float, float] | None) -> bool:
    if domain is None:
        return True
    lat_min, lat_max, lon_min, lon_max = domain
    if not (lat_min <= lat <= lat_max):
        return False
    lo = lon % 360.0
    a, b = lon_min % 360.0, lon_max % 360.0
    return a <= lo <= b if a <= b else (lo >= a or lo <= b)


def solar_azimuth(lat: float, lon: float, time: datetime) -> float:
    """Real solar azimuth (degrees clockwise from true north) at ``time``."""
    from astral import Observer
    from astral.sun import azimuth as _azimuth

    return float(_azimuth(Observer(latitude=lat, longitude=lon), time)) % 360.0


def build_sunward_path(
    lat: float,
    lon: float,
    time: datetime,
    *,
    azimuth_deg: float | None = None,
    distances_km: tuple[float, ...] | list[float] = DEFAULT_SUNWARD_DISTANCES_KM,
    elevation_fn=None,
    domain: tuple[float, float, float, float] | None = None,
    res_deg: float = GFS_GRID_RES_DEG,
) -> SunwardPath:
    """Build the deterministic observer→sun sampling path (#12).

    ``azimuth_deg`` defaults to the real solar azimuth at ``time``. Each sample
    carries its lat/lon, great-circle distance, GFS grid index, and ground
    elevation from ``elevation_fn(lat, lon)`` (injected so the geometry stays
    network-free and testable; land/sea is whatever the provider reports).
    Points outside ``domain`` are flagged ``in_domain=False`` and skip the
    elevation lookup.
    """
    az = azimuth_deg if azimuth_deg is not None else solar_azimuth(lat, lon, time)
    samples: list[SunwardSample] = []
    for d in distances_km:
        plat, plon = destination_point(lat, lon, az, d)
        gi, gj = grid_index(plat, plon, res_deg)
        in_domain = _within_domain(plat, plon, domain)
        elevation = elevation_fn(plat, plon) if (elevation_fn and in_domain) else None
        samples.append(
            SunwardSample(
                distance_km=float(d),
                lat=plat,
                lon=plon,
                grid_lat_idx=gi,
                grid_lon_idx=gj,
                elevation_m=elevation,
                in_domain=in_domain,
            )
        )
    return SunwardPath(observer=(lat, lon), azimuth_deg=az, target_time=time, samples=samples)
