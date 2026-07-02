"""Affordable national physics approximations for #59.

This module implements the first #58 recommendation that is cheap enough for
the national product: a 1-D sunward physics screen built from already-fetched
surface fields. It does not fetch pressure cubes or run the heavier 2-D ray
trace; that refinement is represented in metadata/config and can be layered on
after the screen.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np

from predictor.features import analyze_sunward_profile
from predictor.spatial import DEFAULT_SUNWARD_DISTANCES_KM, SunwardProfile, solar_azimuth, sunward_coordinates

_MID_BASE_M = 3500.0
_HIGH_BASE_M = 7000.0
_PRESENCE_THRESHOLD_PCT = 10.0


@dataclass(frozen=True)
class NationalPhysicsConfig:
    enabled: bool = True
    screen_distances_km: tuple[float, ...] = DEFAULT_SUNWARD_DISTANCES_KM
    refine: bool = False
    refine_threshold: float = 0.50
    refine_distances_km: tuple[float, ...] = tuple(float(d) for d in range(0, 801, 50))
    # Cost cap for the national product: at most this many candidates run the
    # full ray trace per field (highest screen probability first; the rest keep
    # their screen value and are counted in metadata). Live validation (#59 §7)
    # saw 1419 candidates nationally at threshold 0.50 — 4000 is ~3× headroom.
    max_refine_cells: int | None = 4000


@dataclass
class SunwardScreen:
    cloud_base_m: np.ndarray
    sunward_cloud_boundary_km: np.ndarray
    sunward_profile_max_km: np.ndarray
    sunward_aod_mean: np.ndarray
    sampled_points: int
    distances_km: tuple[float, ...]


def build_sunward_screen(
    lats: np.ndarray,
    lons: np.ndarray,
    cloud_low_pct: np.ndarray,
    cloud_mid_pct: np.ndarray,
    cloud_high_pct: np.ndarray,
    event_times: np.ndarray,
    *,
    aerosol_optical_depth: np.ndarray | None = None,
    distances_km: tuple[float, ...] | list[float] = DEFAULT_SUNWARD_DISTANCES_KM,
    azimuth_deg: float | None = None,
) -> SunwardScreen:
    """Approximate each grid cell's sunward boundary from surface cloud fields.

    The arrays must already be mosaiced to the cell's own event-valid GFS hour.
    Sampling stops when the sunward path leaves the available rectangular field;
    the downstream gate treats a too-short path as neutral rather than a failure.
    """
    lats = np.asarray(lats, dtype=float)
    lons = np.asarray(lons, dtype=float)
    low = np.asarray(cloud_low_pct, dtype=float)
    mid = np.asarray(cloud_mid_pct, dtype=float)
    high = np.asarray(cloud_high_pct, dtype=float)
    aod = None if aerosol_optical_depth is None else np.asarray(aerosol_optical_depth, dtype=float)
    distances = tuple(float(d) for d in distances_km)
    shape = low.shape

    cloud_base = np.full(shape, np.nan, dtype=float)
    boundary = np.full(shape, np.nan, dtype=float)
    profile_max = np.zeros(shape, dtype=float)
    aod_mean = np.full(shape, np.nan, dtype=float)
    sampled_points = 0

    for j, lat in enumerate(lats):
        for i, lon in enumerate(lons):
            canvas = _canvas_layer(mid[j, i], high[j, i])
            if canvas is None:
                continue
            cloud_base[j, i] = _HIGH_BASE_M if canvas == "high" else _MID_BASE_M
            event_time = _event_datetime(event_times[j, i])
            az = azimuth_deg if azimuth_deg is not None else solar_azimuth(float(lat), float(lon), event_time)
            samples = _sample_profile(
                lats, lons, low, mid, high, aod, float(lat), float(lon), event_time, az, distances
            )
            if samples is None:
                continue
            profile, sample_aod = samples
            sampled_points += len(profile.distances_km)
            profile_max[j, i] = profile.distances_km[-1] if profile.distances_km else 0.0
            if sample_aod:
                finite_aod = [v for v in sample_aod if v is not None and np.isfinite(v)]
                if finite_aod:
                    aod_mean[j, i] = float(np.mean(finite_aod))
            metrics = analyze_sunward_profile(profile, canvas, sunset_time=event_time, valid_time=event_time)
            if metrics.get("sunward_cloud_boundary_km") is not None:
                boundary[j, i] = float(metrics["sunward_cloud_boundary_km"])

    return SunwardScreen(
        cloud_base_m=cloud_base,
        sunward_cloud_boundary_km=boundary,
        sunward_profile_max_km=profile_max,
        sunward_aod_mean=aod_mean,
        sampled_points=sampled_points,
        distances_km=distances,
    )


def _canvas_layer(mid: float, high: float) -> str | None:
    if high >= _PRESENCE_THRESHOLD_PCT and high >= mid:
        return "high"
    if mid >= _PRESENCE_THRESHOLD_PCT:
        return "mid"
    if high >= _PRESENCE_THRESHOLD_PCT:
        return "high"
    return None


def _event_datetime(value) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromtimestamp(
        int(np.datetime64(value, "s").astype("datetime64[s]").astype("int64")),
        tz=timezone.utc,
    )


def _sample_profile(
    lats: np.ndarray,
    lons: np.ndarray,
    low: np.ndarray,
    mid: np.ndarray,
    high: np.ndarray,
    aod: np.ndarray | None,
    lat: float,
    lon: float,
    event_time: datetime,
    azimuth_deg: float,
    distances_km: tuple[float, ...],
) -> tuple[SunwardProfile, list[float | None]] | None:
    sample_distances: list[float] = []
    sample_low: list[float] = []
    sample_mid: list[float] = []
    sample_high: list[float] = []
    sample_aod: list[float | None] = []
    for distance, (plat, plon) in zip(
        distances_km, sunward_coordinates(lat, lon, azimuth_deg, distances_km)
    ):
        if not _inside(lats, lons, plat, plon):
            break
        y = int(np.argmin(np.abs(lats - plat)))
        x = int(np.argmin(np.abs(lons - plon)))
        sample_distances.append(float(distance))
        sample_low.append(float(low[y, x]))
        sample_mid.append(float(mid[y, x]))
        sample_high.append(float(high[y, x]))
        sample_aod.append(float(aod[y, x]) if aod is not None and np.isfinite(aod[y, x]) else None)

    if not sample_distances:
        return None
    profile = SunwardProfile(
        azimuth_deg=float(azimuth_deg) % 360.0,
        distances_km=sample_distances,
        cloud_low_pct=sample_low,
        cloud_mid_pct=sample_mid,
        cloud_high_pct=sample_high,
        aerosol_optical_depth=sample_aod,
        wind_speed_850_m_s=[None] * len(sample_distances),
        wind_direction_850_deg=[None] * len(sample_distances),
        wind_speed_700_m_s=[None] * len(sample_distances),
        wind_direction_700_deg=[None] * len(sample_distances),
        wind_speed_400_m_s=[None] * len(sample_distances),
        wind_direction_400_deg=[None] * len(sample_distances),
    )
    return profile, sample_aod


def _inside(lats: np.ndarray, lons: np.ndarray, lat: float, lon: float) -> bool:
    return (
        float(lats.min()) <= lat <= float(lats.max())
        and float(lons.min()) <= lon <= float(lons.max())
    )
