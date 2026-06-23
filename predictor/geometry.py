"""Fire-cloud spatiotemporal geometry (paper §3).

Closed-form geometric quantities derived from the parabolic flat-coordinate
reformulation and the fire-cloud spatiotemporal triangle:

- maximum horizontal reach of a fire cloud for a given cloud base,
- an aerosol-corrected "equivalent" cloud base height,
- a characteristic illumination duration.

These are deliberately simple analytic estimates, not a radiative-transfer or
ray-tracing model. They enrich the rule-based probability with "when / how long
/ how far" context. All inputs are SI-ish (metres, degrees); outputs are km/min.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

EARTH_RADIUS_KM = 6371.0

# Visibility-to-extinction convention: an object is at the visibility limit when
# its contrast falls to 2%, giving Vis = -ln(0.02) / beta. We treat beta_x =
# 0.02 km^-1 as the extinction threshold above which sunlight is "blocked" for
# the equivalent-ground model (paper §5.4).
_CONTRAST_THRESHOLD = 0.02
_BETA_X_KM_INV = 0.02
_DEFAULT_AEROSOL_SCALE_HEIGHT_M = 2000.0

# Sunset terminator linear speed at the equator near equinox: v = R * dα/dt with
# dα/dt ≈ 15°/hr = 0.25°/min. v_eq = R * 0.25 * π/180 ≈ 27.8 km/min. Mid/high
# latitudes scale by cos(lat) (the sun tracks more obliquely to the horizon).
_SUNSET_SPEED_EQUATOR_KM_MIN = EARTH_RADIUS_KM * math.radians(0.25)


@dataclass
class GeometryResult:
    cloud_base_m: float | None              # cloud base used (raw)
    equivalent_cloud_base_m: float | None   # after aerosol correction
    max_reach_km: float | None              # 2*sqrt(2*R*h_eff)
    duration_min: float | None              # characteristic illumination window
    sunset_speed_km_min: float              # terminator speed at this latitude


def sunset_speed_km_min(lat: float) -> float:
    """Linear speed of the sunset terminator along the sunset direction (km/min).

    Equator-near-equinox value scaled by cos(lat). This ignores season and
    azimuth and is accurate to order ~10–20%; adequate for a duration estimate.
    """
    return _SUNSET_SPEED_EQUATOR_KM_MIN * math.cos(math.radians(lat))


def max_penetration_km(cloud_base_m: float) -> float:
    """Maximum horizontal distance a grazing ray can reach a cloud base (km).

    From the parabolic reformulation h(l) ≈ l²/(2R): |l|_max = 2·sqrt(2·R·h).
    """
    if cloud_base_m <= 0:
        return 0.0
    h_km = cloud_base_m / 1000.0
    return 2.0 * math.sqrt(2.0 * EARTH_RADIUS_KM * h_km)


def equivalent_cloud_base_m(
    cloud_base_m: float,
    visibility_m: float | None,
    scale_height_m: float = _DEFAULT_AEROSOL_SCALE_HEIGHT_M,
) -> float:
    """Cloud base reduced by the aerosol "equivalent opaque ground" height (paper §5.4).

    Surface extinction is inferred from visibility (beta_0 = -ln(0.02)/Vis_km).
    The equivalent ground sits where extinction falls to beta_x = 0.02 km^-1:
    h_x = h_a · ln(beta_0 / beta_x). The effective base is cloud_base - h_x,
    floored at 0. With unknown visibility, returns the cloud base unchanged.
    """
    if visibility_m is None or visibility_m <= 0:
        return cloud_base_m
    vis_km = visibility_m / 1000.0
    beta_0 = -math.log(_CONTRAST_THRESHOLD) / vis_km  # km^-1
    if beta_0 <= _BETA_X_KM_INV:
        return cloud_base_m  # already cleaner than threshold at the surface
    h_x_m = scale_height_m * math.log(beta_0 / _BETA_X_KM_INV)
    return max(0.0, cloud_base_m - h_x_m)


def equivalent_cloud_base_from_aod_m(
    cloud_base_m: float,
    aerosol_optical_depth: float | None,
    scale_height_m: float = _DEFAULT_AEROSOL_SCALE_HEIGHT_M,
) -> float:
    """AOD-based equivalent cloud base from the manual's exponential profile.

    For ``beta(z)=beta_0*exp(-z/H)``, the column optical depth is
    ``AOD=beta_0*H``. This lets us estimate the equivalent opaque-ground height
    without treating fog-sensitive surface visibility as a column aerosol
    measurement. Unknown AOD leaves the cloud base unchanged.
    """
    if aerosol_optical_depth is None or aerosol_optical_depth <= 0:
        return cloud_base_m
    scale_height_km = scale_height_m / 1000.0
    beta_0 = aerosol_optical_depth / scale_height_km
    if beta_0 <= _BETA_X_KM_INV:
        return cloud_base_m
    h_x_m = scale_height_m * math.log(beta_0 / _BETA_X_KM_INV)
    return max(0.0, cloud_base_m - h_x_m)


def characteristic_duration_min(cloud_base_eff_m: float, lat: float) -> float:
    """Characteristic fire-cloud illumination window (minutes).

    The spatiotemporal triangle spans t ∈ [-L/v, L/v] with L = sqrt(2·R·h_eff);
    its full width 2L/v is the time over which the terminator sweeps the
    illuminated zone — a proxy for "how long the show lasts". Scales as
    sqrt(h_eff), matching the high-cloud-lasts-longer intuition.
    """
    if cloud_base_eff_m <= 0:
        return 0.0
    v = sunset_speed_km_min(lat)
    if v <= 0:
        return 0.0
    L_km = math.sqrt(2.0 * EARTH_RADIUS_KM * (cloud_base_eff_m / 1000.0))
    return 2.0 * L_km / v


def compute_geometry(
    cloud_base_m: float | None,
    visibility_m: float | None,
    lat: float,
    scale_height_m: float = _DEFAULT_AEROSOL_SCALE_HEIGHT_M,
    *,
    aerosol_optical_depth: float | None = None,
) -> GeometryResult:
    """Assemble the geometric enrichment for one location.

    Returns a GeometryResult with reach and duration computed from the
    aerosol-corrected equivalent cloud base. When there is no cloud base
    (clear sky), reach/duration are None.
    """
    v = sunset_speed_km_min(lat)
    if cloud_base_m is None:
        return GeometryResult(None, None, None, None, v)

    eff = (
        equivalent_cloud_base_from_aod_m(
            cloud_base_m, aerosol_optical_depth, scale_height_m
        )
        if aerosol_optical_depth is not None
        else equivalent_cloud_base_m(cloud_base_m, visibility_m, scale_height_m)
    )
    return GeometryResult(
        cloud_base_m=cloud_base_m,
        equivalent_cloud_base_m=eff,
        max_reach_km=max_penetration_km(eff),
        duration_min=characteristic_duration_min(eff, lat),
        sunset_speed_km_min=v,
    )
