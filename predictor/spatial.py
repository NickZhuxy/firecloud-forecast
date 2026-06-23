"""Sunward cross-section helpers for detailed fire-cloud forecasts.

The manual forecasting workflow is spatial: start at the observer and inspect
the atmosphere along the sunset azimuth until the illuminated cloud deck ends.
This module keeps that geometry independent from HTTP and scoring code.
"""
from __future__ import annotations

from dataclasses import dataclass
import math


EARTH_RADIUS_KM = 6371.0
DEFAULT_SUNWARD_DISTANCES_KM = (0.0, 50.0, 100.0, 150.0, 250.0, 400.0, 600.0, 800.0)


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
