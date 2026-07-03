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
class OverheadWindow:
    """Local-overhead fire-cloud timing from the fire-cloud triangle (manual §1.2.2).

    Times are minutes relative to the observer's own local sunset (positive =
    after sunset, for an evening glow).
    """
    start_min: float
    end_min: float
    duration_min: float


@dataclass
class AerosolGroundRange:
    """Equivalent-opaque-ground height swept over the aerosol scale height H.

    The manual (§1.3.3, §4.1.1) notes h_x is *non-monotonic* in H, so the column
    must be sampled across H ∈ [0.5, 4] km rather than fixed at one value; the
    span of equivalent cloud base it produces is the dominant fire-cloud
    uncertainty.
    """
    h_x_min_m: float
    h_x_max_m: float
    eff_base_min_m: float            # cloud base − h_x_max (smallest effective base)
    eff_base_max_m: float            # cloud base − h_x_min (largest effective base)
    scale_height_at_max_h_x_km: float  # the H giving the peak h_x (interior, not an edge)


@dataclass
class GeometryResult:
    cloud_base_m: float | None              # cloud base used (raw)
    equivalent_cloud_base_m: float | None   # after aerosol correction
    max_reach_km: float | None              # 2*sqrt(2*R*h_eff)
    duration_min: float | None              # characteristic illumination window
    sunset_speed_km_min: float              # terminator speed at this latitude
    # Additive single-point enrichment (#57 P0). None unless the caller supplies
    # the sunward boundary distance / raw base / AOD that each requires.
    overhead_window: "OverheadWindow | None" = None
    total_duration_min: float | None = None
    boundary_elevation_deg: float | None = None
    aerosol_ground_range: "AerosolGroundRange | None" = None


def sunset_speed_km_min(lat: float) -> float:
    """Linear speed of the sunset terminator along the sunset direction (km/min).

    Equator-near-equinox value scaled by cos(lat). This ignores season and
    azimuth and is accurate to order ~10–20%; adequate for a duration estimate.
    """
    return _SUNSET_SPEED_EQUATOR_KM_MIN * math.cos(math.radians(lat))


# Manual appendix (人工火烧云预报速成) terminator-speed values cluster in a narrow
# 18–21 km/min band across China, centred near 20 — notably below the cos-lat
# physical speed and flatter in latitude (see research/theory/fa-g4-terminator-speed.md).
_MANUAL_TERMINATOR_SPEED_KM_MIN = 20.0


def representative_terminator_speed_km_min(lat: float) -> float:
    """A statistical-midpoint terminator speed for the *duration* estimate (FA-G4).

    The manual's appendix v (~18–21, central 20) is lower than both the cos-lat
    physical speed (~18–26) and astral's dα/dt speed (~22–33), by a definition we
    can't reproduce in closed form. Since duration precision is not a priority
    (owner call 2026-06-27) and v does not enter the probability at all, we don't
    chase the manual's exact formula nor switch to astral. Instead we take the mean
    of the cos-lat physical speed and the manual's central value — a rough blend
    that pulls the low-latitude cos-lat overestimate back toward the manual while
    staying consistent at higher latitudes. Used only for the duration ballpark.
    """
    return 0.5 * (sunset_speed_km_min(lat) + _MANUAL_TERMINATOR_SPEED_KM_MIN)


def max_penetration_km(cloud_base_m: float) -> float:
    """Maximum horizontal distance a grazing ray can reach a cloud base (km).

    From the parabolic reformulation h(l) ≈ l²/(2R): |l|_max = 2·sqrt(2·R·h).
    """
    if cloud_base_m <= 0:
        return 0.0
    h_km = cloud_base_m / 1000.0
    return 2.0 * math.sqrt(2.0 * EARTH_RADIUS_KM * h_km)


def viewing_elevation_deg(distance_km: float, height_m: float) -> float:
    """Elevation angle (degrees) of a target at ``height_m`` seen ``distance_km`` away.

    From the manual's sightline expansion (§1.2.4), keeping the curvature term:
    ``θ = h/l − l/(2R)`` (radians). The second term is Earth curvature dropping
    the target below the local tangent plane, so a low, distant boundary can land
    *below* the horizon (negative angle) and be invisible. ``distance_km <= 0``
    means the target is overhead (90°).
    """
    if distance_km <= 0:
        return 90.0
    h_km = height_m / 1000.0
    theta_rad = h_km / distance_km - distance_km / (2.0 * EARTH_RADIUS_KM)
    return math.degrees(theta_rad)


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


def aerosol_ground_height_m(
    aerosol_optical_depth: float | None,
    scale_height_m: float = _DEFAULT_AEROSOL_SCALE_HEIGHT_M,
) -> float:
    """Equivalent opaque-ground height ``h_x`` from a column AOD (paper §5.4).

    For the manual's exponential profile ``beta(z)=beta_0*exp(-z/H)`` with column
    optical depth ``AOD=beta_0*H``, the equivalent opaque ground sits where
    extinction falls to ``beta_x = 0.02 km^-1``:

        ``h_x = H · ln(beta_0 / beta_x)``  (``beta_0 = AOD/H``).

    Below ``h_x`` the near-surface aerosol is "effectively opaque" to grazing
    sunlight. Returns 0 when AOD is unknown / non-positive, or when the surface is
    already cleaner than the threshold (``beta_0 <= beta_x``). This is the per-
    column primitive the sunward ray trace uses (FA-A2); ``equivalent_cloud_base_*``
    is just a cloud base lowered by this height.
    """
    if aerosol_optical_depth is None or aerosol_optical_depth <= 0:
        return 0.0
    scale_height_km = scale_height_m / 1000.0
    beta_0 = aerosol_optical_depth / scale_height_km
    if beta_0 <= _BETA_X_KM_INV:
        return 0.0
    return scale_height_m * math.log(beta_0 / _BETA_X_KM_INV)


def equivalent_cloud_base_from_aod_m(
    cloud_base_m: float,
    aerosol_optical_depth: float | None,
    scale_height_m: float = _DEFAULT_AEROSOL_SCALE_HEIGHT_M,
) -> float:
    """AOD-based equivalent cloud base from the manual's exponential profile.

    For ``beta(z)=beta_0*exp(-z/H)``, the column optical depth is
    ``AOD=beta_0*H``. This lets us estimate the equivalent opaque-ground height
    without treating fog-sensitive surface visibility as a column aerosol
    measurement. The base drops by ``aerosol_ground_height_m`` (floored at 0);
    unknown AOD leaves the cloud base unchanged.
    """
    return max(
        0.0, cloud_base_m - aerosol_ground_height_m(aerosol_optical_depth, scale_height_m)
    )


_DEFAULT_AEROSOL_SCALE_HEIGHTS_KM = (0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0)


def equivalent_cloud_base_range_from_aod_m(
    cloud_base_m: float,
    aerosol_optical_depth: float | None,
    scale_heights_km: tuple[float, ...] = _DEFAULT_AEROSOL_SCALE_HEIGHTS_KM,
) -> AerosolGroundRange | None:
    """Equivalent cloud base swept over the aerosol scale height H (manual §1.3.3).

    For the exponential profile ``beta(z)=beta_0·exp(-z/H)`` with ``beta_0=AOD/H``,
    the equivalent opaque-ground height is ``h_x(H)=H·ln(beta_0/beta_x)``. The
    manual stresses h_x is *non-monotonic* in H and the analyst must try several
    H ∈ [0.5, 4] km (Table 4.1) — the resulting span of effective cloud base is
    the dominant fire-cloud uncertainty, able to flip the glow/no-glow verdict.
    Returns the min/max equivalent ground and effective base over the H grid, plus
    the H at the h_x peak. ``None`` when AOD is unknown / non-positive.
    """
    if aerosol_optical_depth is None or aerosol_optical_depth <= 0:
        return None
    best_h_x = -1.0
    best_h_at_peak = scale_heights_km[0]
    min_h_x = None
    for h_km in scale_heights_km:
        beta_0 = aerosol_optical_depth / h_km  # km^-1
        h_x_m = h_km * 1000.0 * math.log(beta_0 / _BETA_X_KM_INV) if beta_0 > _BETA_X_KM_INV else 0.0
        if h_x_m > best_h_x:
            best_h_x = h_x_m
            best_h_at_peak = h_km
        if min_h_x is None or h_x_m < min_h_x:
            min_h_x = h_x_m
    return AerosolGroundRange(
        h_x_min_m=min_h_x,
        h_x_max_m=best_h_x,
        eff_base_min_m=max(0.0, cloud_base_m - best_h_x),
        eff_base_max_m=max(0.0, cloud_base_m - min_h_x),
        scale_height_at_max_h_x_km=best_h_at_peak,
    )


def advect_boundary_km(
    boundary_km: float, signed_wind_m_s: float, dt_seconds: float
) -> float:
    """Advect the sunward cloud boundary by the cloud-height wind (FA-T1).

    Frozen-boundary kinematic extrapolation to sunset (manual §4.1.1/§4.2): the
    edge moves ``signed_wind_m_s · dt`` along the observer→sun axis, where
    ``signed_wind_m_s`` is the boundary-normal wind projected onto that axis
    (positive = cloud moving sunward / outward, increasing the boundary distance;
    negative = toward the observer). ``dt_seconds = sunset − valid_time``. Floored
    at 0 (the edge cannot cross the observer). ``dt=0`` is the identity.
    """
    return max(0.0, boundary_km + signed_wind_m_s * dt_seconds / 1000.0)


def characteristic_duration_min(cloud_base_eff_m: float, lat: float) -> float:
    """Characteristic fire-cloud illumination window (minutes).

    The spatiotemporal triangle spans t ∈ [-L/v, L/v] with L = sqrt(2·R·h_eff);
    its full width 2L/v is the time over which the terminator sweeps the
    illuminated zone — a proxy for "how long the show lasts". Scales as
    sqrt(h_eff), matching the high-cloud-lasts-longer intuition.

    FA-G4: uses the representative (blended) terminator speed for a rough,
    both-definitions ballpark rather than the bare cos-lat speed. Duration is a
    secondary, informational output and never enters the probability.
    """
    if cloud_base_eff_m <= 0:
        return 0.0
    v = representative_terminator_speed_km_min(lat)
    if v <= 0:
        return 0.0
    L_km = math.sqrt(2.0 * EARTH_RADIUS_KM * (cloud_base_eff_m / 1000.0))
    return 2.0 * L_km / v


def convective_duration_min(cloud_top_m: float, lat: float) -> float:
    """Convective fire-cloud window (minutes) — vertical-line model (FA-C4).

    Manual §1.2.3(1): a cumulus tower is a vertical line at the origin; after
    local sunset the earth-shadow height climbs as h_S(t) = (t·v)²/(2R) and the
    tower stays lit while h_S < h_CT, i.e. for 0 ≤ t ≤ √(2R·h_CT)/v. Note the
    height is the cloud TOP (not the base) and the window is HALF the
    stratiform characteristic 2L/v — the tower has no horizontal extent for
    the terminator to sweep. Sunrise mirrors the time axis; the window length
    is identical. Informational output only; never enters the probability.
    """
    if cloud_top_m <= 0:
        return 0.0
    v = representative_terminator_speed_km_min(lat)
    if v <= 0:
        return 0.0
    return math.sqrt(2.0 * EARTH_RADIUS_KM * (cloud_top_m / 1000.0)) / v


def overhead_firecloud_window(
    boundary_km: float,
    cloud_base_eff_m: float,
    sunset_speed_km_min: float,
) -> OverheadWindow | None:
    """Local-overhead fire-cloud timing from the fire-cloud triangle (manual §1.2.2).

    An observer sits a horizontal distance ``boundary_km`` (= D) from the sunward
    cloud edge, under a deck whose (aerosol-)effective base is ``cloud_base_eff_m``.
    Solving the triangle for the lit interval over the observer's own column and
    referencing it to the observer's local sunset gives

        start    = D / (2v)
        end      = √(2R·h_eff) / v
        duration = end − start = (2√(2R·h_eff) − D) / (2v)

    The deck is lit overhead only while ``D < 2√(2R·h_eff)`` (= ``max_penetration_km``);
    beyond that the sunward edge is too far for any grazing ray to reach, so this
    returns ``None``. Times are minutes after the observer's local sunset.
    """
    if cloud_base_eff_m <= 0 or sunset_speed_km_min <= 0 or boundary_km < 0:
        return None
    L_km = math.sqrt(2.0 * EARTH_RADIUS_KM * (cloud_base_eff_m / 1000.0))
    v = sunset_speed_km_min
    start_min = boundary_km / (2.0 * v)
    end_min = L_km / v
    duration_min = end_min - start_min
    if duration_min <= 0:
        return None
    return OverheadWindow(start_min=start_min, end_min=end_min, duration_min=duration_min)


def viewing_extension_min(
    cloud_base_m: float,
    sunset_speed_km_min: float,
    min_elev_deg: float = 5.0,
) -> float:
    """Extra minutes the glow stays visible down to ``min_elev_deg`` in the sky.

    The overhead window ends when the observer's own column goes dark, but the
    glow is still visible toward the sun until the deck there drops below a
    minimum viewing elevation. The manual (§1.2.4 / §4.1.1) takes the horizontal
    distance to that point as ``h / tan(min_elev)`` (curvature neglected, matching
    its worked examples) and divides by the terminator speed. Uses the *raw*
    cloud base — this is about where the real cloud sits in the sky.
    """
    if cloud_base_m <= 0 or sunset_speed_km_min <= 0:
        return 0.0
    h_km = cloud_base_m / 1000.0
    ext_distance_km = h_km / math.tan(math.radians(min_elev_deg))
    return ext_distance_km / sunset_speed_km_min


def total_observed_duration_min(
    boundary_km: float,
    cloud_base_eff_m: float,
    cloud_base_raw_m: float,
    sunset_speed_km_min: float,
    min_elev_deg: float = 5.0,
) -> float | None:
    """Total visible fire-cloud time: overhead window + the sky-viewing extension.

    Overhead duration uses the aerosol-effective base (where light can reach the
    underside); the viewing extension uses the raw base (the cloud's true height
    in the sky). ``None`` when there is no overhead window. (manual §4.1.1)
    """
    window = overhead_firecloud_window(boundary_km, cloud_base_eff_m, sunset_speed_km_min)
    if window is None:
        return None
    return window.duration_min + viewing_extension_min(
        cloud_base_raw_m, sunset_speed_km_min, min_elev_deg
    )


# Module-level alias so compute_geometry can still reach the latitude-based speed
# helper even though it now also accepts a ``sunset_speed_km_min`` parameter (the
# parameter name would otherwise shadow the function inside the body).
_speed_for_lat = sunset_speed_km_min


def compute_geometry(
    cloud_base_m: float | None,
    visibility_m: float | None,
    lat: float,
    scale_height_m: float = _DEFAULT_AEROSOL_SCALE_HEIGHT_M,
    *,
    aerosol_optical_depth: float | None = None,
    boundary_km: float | None = None,
    cloud_base_raw_m: float | None = None,
    sunset_speed_km_min: float | None = None,
) -> GeometryResult:
    """Assemble the geometric enrichment for one location.

    Returns a GeometryResult with reach and duration computed from the
    aerosol-corrected equivalent cloud base. When there is no cloud base
    (clear sky), reach/duration are None.

    #57 P0 (all optional, additive): when ``boundary_km`` (distance to the sunward
    cloud edge) is supplied, the fire-cloud-triangle overhead window, the total
    visible duration (with the 5° sky extension), and the boundary's viewing
    elevation are filled in; when ``aerosol_optical_depth`` is supplied, the
    equivalent-base range over the aerosol scale-height sweep is filled in.
    ``sunset_speed_km_min`` overrides the (cos-lat) terminator speed; ``cloud_base_raw_m``
    overrides the raw cloud base used for the sky extension and boundary angle.

    Note: the legacy ``duration_min`` (the old ``2L/v`` triangle-width proxy) always
    uses the cos-lat speed for backward compatibility, so it can disagree with the
    reported ``sunset_speed_km_min`` when an override is passed; the new
    ``overhead_window``/``total_duration_min`` honour the override. FA-G4 (P1) will
    replace the cos-lat speed model and reconcile them.
    """
    v = sunset_speed_km_min if sunset_speed_km_min is not None else _speed_for_lat(lat)
    aerosol_range = (
        equivalent_cloud_base_range_from_aod_m(cloud_base_m, aerosol_optical_depth)
        if cloud_base_m is not None
        else None
    )
    if cloud_base_m is None:
        return GeometryResult(None, None, None, None, v)

    eff = (
        equivalent_cloud_base_from_aod_m(
            cloud_base_m, aerosol_optical_depth, scale_height_m
        )
        if aerosol_optical_depth is not None
        else equivalent_cloud_base_m(cloud_base_m, visibility_m, scale_height_m)
    )
    raw = cloud_base_raw_m if cloud_base_raw_m is not None else cloud_base_m

    overhead_window = None
    total_duration = None
    boundary_elev = None
    if boundary_km is not None:
        overhead_window = overhead_firecloud_window(boundary_km, eff, v)
        if overhead_window is not None:
            total_duration = overhead_window.duration_min + viewing_extension_min(raw, v)
        boundary_elev = viewing_elevation_deg(boundary_km, raw)

    return GeometryResult(
        cloud_base_m=cloud_base_m,
        equivalent_cloud_base_m=eff,
        max_reach_km=max_penetration_km(eff),
        duration_min=characteristic_duration_min(eff, lat),
        sunset_speed_km_min=v,
        overhead_window=overhead_window,
        total_duration_min=total_duration,
        boundary_elevation_deg=boundary_elev,
        aerosol_ground_range=aerosol_range,
    )
