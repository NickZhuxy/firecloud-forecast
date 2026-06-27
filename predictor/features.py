"""Derived features used by scoring rules."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
import math
from astral import Observer
from astral.sun import sun

from predictor.spatial import SunwardProfile
from predictor.geometry import advect_boundary_km, equivalent_cloud_base_from_aod_m
from predictor.illumination import (
    assess_layer_contributions,
    canvas_layer_from_diagnosis,
    canvas_obstruction_fraction,
)
from predictor.ray_path import RayClearance, trace_ray_clearance


# Representative base altitudes (metres) for the WMO three-tier cloud layers,
# used to estimate a cloud-base height when the data source does not report one.
_LAYER_BASE_M = {"low": 1000.0, "mid": 3500.0, "high": 7000.0}
_LAYER_PRESENCE_THRESHOLD = 10.0  # percent coverage to count a layer as "present"


@dataclass
class Features:
    cloud_low_pct: float
    cloud_mid_pct: float
    cloud_high_pct: float
    humidity_pct: float
    sunset_time: datetime
    query_time: datetime
    location: tuple[float, float]  # (lat, lon)
    visibility_m: float | None = None
    cloud_base_m: float | None = None
    canvas_layer: str | None = None
    canvas_cloud_pct: float = 0.0
    aerosol_optical_depth: float | None = None
    sun_azimuth_deg: float | None = None
    sunward_aod_mean: float | None = None
    sunward_cloud_boundary_km: float | None = None
    # FA-T1: the snapshot-time boundary before wind advection to sunset, kept for
    # transparency. ``sunward_cloud_boundary_km`` is the advected value the gate uses.
    sunward_cloud_boundary_raw_km: float | None = None
    sunward_profile_max_km: float | None = None
    sunward_boundary_gradient_pct_per_km: float | None = None
    sunward_obstruction_pct: float | None = None
    boundary_motion_m_s: float | None = None
    # Provenance of cloud_base_m and the old three-tier estimate kept for
    # new-vs-old comparison (#13). cloud_base_source ∈ {"diagnosed",
    # "source_reported", "fixed_estimate"}; the fixed-estimate fallback carries
    # lower confidence because it uses a representative height, not a real base.
    cloud_base_source: str | None = None
    cloud_base_fixed_m: float | None = None
    cloud_base_confidence: float | None = None
    # Graded obstruction of the diagnosed canvas by lower diagnosed layers
    # (0–100%), and the full per-layer breakdown (#31). None without diagnosis.
    diagnosed_obstruction_pct: float | None = None
    layer_contributions: list | None = None
    # GFS's own mid/high cloud cover (%), max(MCDC, HCDC) (#35): the same-source
    # mid/high-canvas coverage used by the presence/sweet-spot rules instead of a
    # possibly-disagreeing Open-Meteo value. Independent of which tier is the
    # canvas. None without diagnosis or GFS cover.
    diagnosed_mid_high_cover_pct: float | None = None
    # FA-G5 second cut: result of tracing the sunlight parabola across the 2-D
    # sunward cross-section (manual §4.1.2). Present only when a cross-section was
    # supplied (detailed point path); the gate then uses it over the 1-D heuristic.
    sunward_ray_clearance: RayClearance | None = None


def select_canvas_layer(
    cloud_low_pct: float, cloud_mid_pct: float, cloud_high_pct: float
) -> str | None:
    """Choose the cloud deck whose underside is the likely colour canvas.

    Typical fire-cloud forecasts prefer a mid/high deck. Low cloud is selected
    only when no mid/high layer is present; the standard predictor still treats
    that as an atypical case, but geometry can now describe it correctly.
    """
    elevated = {"mid": cloud_mid_pct, "high": cloud_high_pct}
    layer = max(elevated, key=elevated.get)
    if elevated[layer] >= _LAYER_PRESENCE_THRESHOLD:
        return layer
    if cloud_low_pct >= _LAYER_PRESENCE_THRESHOLD:
        return "low"
    return None


def estimate_cloud_base_m(
    cloud_low_pct: float, cloud_mid_pct: float, cloud_high_pct: float
) -> float | None:
    """Estimate the likely illuminated canvas base height (metres).

    Low cloud beneath a mid/high deck is an obstruction, not the canvas. The old
    "lowest present layer" estimate therefore collapsed a 7 km high-cloud deck
    to 1 km whenever even a little low cloud appeared. We now choose the
    dominant mid/high layer first and fall back to low cloud only for an
    atypical low-cloud-only sky.
    """
    layer = select_canvas_layer(cloud_low_pct, cloud_mid_pct, cloud_high_pct)
    return _LAYER_BASE_M[layer] if layer is not None else None


def tier_from_height(base_m: float) -> str:
    """Map a cloud-base height (m) to a WMO étage tier.

    Boundaries follow the standard étages: low < 2 km, mid 2–6 km, high > 6 km.
    Used to make canvas_layer follow a diagnosed canvas height (#32).
    """
    if base_m < 2000.0:
        return "low"
    if base_m < 6000.0:
        return "mid"
    return "high"


def _layer_values(profile: SunwardProfile, layer: str) -> list[float]:
    return getattr(profile, f"cloud_{layer}_pct")


def _combined_cover(*covers: float) -> float:
    """Combine potentially overlapping layer cover fractions."""
    clear_fraction = 1.0
    for cover in covers:
        clear_fraction *= 1.0 - max(0.0, min(100.0, cover)) / 100.0
    return 100.0 * (1.0 - clear_fraction)


def _projected_boundary_wind(
    profile: SunwardProfile, layer: str, indices: tuple[int, int]
) -> float | None:
    pressure = {"low": 850, "mid": 700, "high": 400}[layer]
    speeds = getattr(profile, f"wind_speed_{pressure}_m_s")
    directions = getattr(profile, f"wind_direction_{pressure}_deg")
    projections = []
    for idx in indices:
        speed, direction = speeds[idx], directions[idx]
        if speed is None or direction is None:
            continue
        # Meteorological direction is where wind comes from; convert to the
        # direction of travel before projecting onto the observer→sun axis.
        to_direction = (direction + 180.0) % 360.0
        delta = math.radians(to_direction - profile.azimuth_deg)
        projections.append(float(speed) * math.cos(delta))
    if not projections:
        return None
    # Signed projection onto the observer→sun axis: positive = cloud moving sunward
    # (outward, boundary recedes), negative = toward the observer. FA-T1 advection
    # needs the sign; the BoundaryConfidence "motion" signal takes its magnitude.
    return sum(projections) / len(projections)


def analyze_sunward_profile(
    profile: SunwardProfile,
    canvas_layer: str,
    *,
    sunset_time: datetime | None = None,
    valid_time: datetime | None = None,
) -> dict:
    """Extract cloud boundary, obstruction, AOD and motion from a transect.

    FA-T1: when ``sunset_time`` and ``valid_time`` are both given, the sunward
    boundary is advected by the cloud-height wind over ``Δt = sunset − valid`` to
    the sunset moment (manual §4.1.1/§4.2); the raw snapshot-time boundary is kept
    as ``sunward_cloud_boundary_raw_km``. Without the times (or with no boundary /
    no wind) the boundary is unmoved — the national/1-D callers are unaffected."""
    distances = profile.distances_km
    canvas = _layer_values(profile, canvas_layer)
    if len(distances) != len(canvas) or not distances:
        return {}

    threshold = 20.0
    boundary_km = None
    gradient = None
    boundary_indices = None
    for idx in range(1, len(distances)):
        near_cover, far_cover = canvas[idx - 1], canvas[idx]
        if near_cover > threshold >= far_cover:
            span = distances[idx] - distances[idx - 1]
            if span <= 0:
                continue
            fraction = (near_cover - threshold) / max(near_cover - far_cover, 1e-9)
            boundary_km = distances[idx - 1] + fraction * span
            gradient = max(0.0, near_cover - far_cover) / span
            boundary_indices = (idx - 1, idx)
            break

    path_limit = boundary_km if boundary_km is not None else distances[-1]
    path_indices = [i for i, d in enumerate(distances) if d <= path_limit]
    if boundary_indices is not None:
        path_indices.append(boundary_indices[1])
    path_indices = sorted(set(path_indices))

    obstruction_values: list[float] = []
    for idx in path_indices:
        if canvas_layer == "high":
            obstruction_values.append(
                _combined_cover(profile.cloud_low_pct[idx], profile.cloud_mid_pct[idx])
            )
        elif canvas_layer == "mid":
            obstruction_values.append(profile.cloud_low_pct[idx])
        else:
            obstruction_values.append(0.0)

    aod_values = [v for v in profile.aerosol_optical_depth if v is not None]
    signed_motion = (
        _projected_boundary_wind(profile, canvas_layer, boundary_indices)
        if boundary_indices is not None
        else None
    )
    motion = abs(signed_motion) if signed_motion is not None else None

    # FA-T1: advect the boundary to sunset by the (signed) cloud-height wind.
    advected_boundary_km = boundary_km
    if (
        boundary_km is not None
        and signed_motion is not None
        and sunset_time is not None
        and valid_time is not None
    ):
        dt_seconds = (sunset_time - valid_time).total_seconds()
        advected_boundary_km = advect_boundary_km(boundary_km, signed_motion, dt_seconds)

    return {
        "sun_azimuth_deg": profile.azimuth_deg,
        "sunward_aod_mean": sum(aod_values) / len(aod_values) if aod_values else None,
        "sunward_cloud_boundary_km": advected_boundary_km,
        "sunward_cloud_boundary_raw_km": boundary_km,
        "sunward_profile_max_km": distances[-1],
        "sunward_boundary_gradient_pct_per_km": gradient,
        "sunward_obstruction_pct": (
            max(obstruction_values) if obstruction_values else None
        ),
        "boundary_motion_m_s": motion,
    }


def compute_sunset(lat: float, lon: float, dt: datetime) -> datetime:
    """Sunset for the location on the date of ``dt`` (timezone-aware, matching dt.tzinfo).

    Used only as a fallback when the weather snapshot does not carry a
    source-reported sunset. Open-Meteo always supplies one, so the national grid
    and point lookups normally skip this astral computation entirely.
    """
    observer = Observer(latitude=lat, longitude=lon)
    return sun(observer, date=dt.date(), tzinfo=dt.tzinfo)["sunset"]


def _observer_column_aod(cross_section) -> float | None:
    """The observer's own column AOD (FA-A2): index 0 of the cross-section's
    per-column AOD, or None when no aerosol field was assembled."""
    aod = cross_section.aerosol_optical_depth_per_column
    return aod[0] if aod else None


def derive(snapshot, lat: float, lon: float, time: datetime, cloud_layers=None, cloud_cover=None, sunward_cross_section=None, valid_time=None) -> Features:
    """Build a Features instance from a WeatherSnapshot + location + query time.

    `snapshot` is duck-typed — it must expose cloud_low_pct, cloud_mid_pct,
    cloud_high_pct, humidity_pct. Optional attributes (visibility_m,
    cloud_base_m, sunset_time) are used when present and filled in otherwise:
    the sunset time falls back to an astral computation, and the cloud base to a
    layer-based estimate.

    When ``cloud_layers`` (a list of diagnosed ``CloudLayer``, #10) is supplied,
    the canvas layer's real diagnosed base replaces the three-tier representative
    height. Without it, the source-reported base or the fixed estimate is used —
    the latter at reduced confidence. The fixed estimate is always recorded in
    ``cloud_base_fixed_m`` for new-vs-old comparison (#13).
    """
    source_sunset = getattr(snapshot, "sunset_time", None)
    sunset_time = (
        source_sunset
        if source_sunset is not None
        else compute_sunset(lat, lon, time)
    )

    # #32: when a canvas is diagnosed, derive canvas_layer from its real height
    # so the field, the sunward obstruction-layer selection, and the altitude
    # modifier all stay coherent with the diagnosed cloud_base_m — instead of a
    # three-tier guess that could name a different deck.
    diagnosed_canvas = canvas_layer_from_diagnosis(cloud_layers) if cloud_layers else None
    if diagnosed_canvas is not None:
        canvas_layer = tier_from_height(diagnosed_canvas.base_m)
    else:
        canvas_layer = select_canvas_layer(
            snapshot.cloud_low_pct, snapshot.cloud_mid_pct, snapshot.cloud_high_pct
        )
    canvas_cloud_pct = (
        getattr(snapshot, f"cloud_{canvas_layer}_pct") if canvas_layer else 0.0
    )

    # #35: when the canvas is diagnosed from GFS, score it against GFS's own étage
    # cover (LCDC/MCDC/HCDC) so structure and coverage share a source. The
    # mid/high-presence signal is GFS's own max(MCDC, HCDC) — independent of which
    # tier is the canvas, so a low canvas does not wrongly erase real mid/high
    # cloud that GFS itself reports. canvas_cloud_pct shows the canvas deck's own
    # cover for the detail panel.
    diagnosed_mid_high_cover_pct = None
    if diagnosed_canvas is not None and cloud_cover is not None and canvas_layer:
        canvas_cloud_pct = cloud_cover.for_tier(canvas_layer)
        diagnosed_mid_high_cover_pct = max(cloud_cover.mid_pct, cloud_cover.high_pct)

    fixed_base = estimate_cloud_base_m(
        snapshot.cloud_low_pct, snapshot.cloud_mid_pct, snapshot.cloud_high_pct
    )
    source_base = getattr(snapshot, "cloud_base_m", None)

    if diagnosed_canvas is not None:
        cloud_base_m = diagnosed_canvas.base_m
        cloud_base_source = "diagnosed"
        cloud_base_confidence = diagnosed_canvas.confidence
    elif source_base is not None:
        cloud_base_m = source_base
        cloud_base_source = "source_reported"
        cloud_base_confidence = 0.7  # measured but not vertically diagnosed
    else:
        cloud_base_m = fixed_base
        cloud_base_source = "fixed_estimate"
        # Lowered: a representative height is a weak stand-in for a real base.
        cloud_base_confidence = 0.4 if fixed_base is not None else None

    # Diagnosed per-layer contributions + the canvas's graded obstruction by the
    # decks below it (#31). Only when layers were supplied; otherwise None.
    diagnosed_obstruction_pct = None
    layer_contributions = None
    if cloud_layers:
        obstruction = canvas_obstruction_fraction(cloud_layers)
        diagnosed_obstruction_pct = (
            obstruction * 100.0 if obstruction is not None else None
        )
        layer_contributions = assess_layer_contributions(cloud_layers, lat)

    profile = getattr(snapshot, "sunward_profile", None)
    # FA-T1: advect the sunward boundary to sunset. ``valid_time`` is the time the
    # weather fields are valid; it defaults to the query ``time`` (the Open-Meteo
    # snapshot's own valid time), so Δt = sunset − valid is 0 when scoring at sunset.
    spatial = (
        analyze_sunward_profile(
            profile, canvas_layer,
            sunset_time=sunset_time,
            valid_time=valid_time if valid_time is not None else time,
        )
        if profile is not None and canvas_layer is not None
        else {}
    )

    # FA-G5 second cut: when a 2-D cross-section is supplied (detailed point path),
    # trace the sunlight parabola across it to the (aerosol-effective) canvas base.
    # The gate prefers this faithful result over the 1-D boundary-distance heuristic.
    # FA-A2: the vertex uses the observer's *own* column AOD (the near-ground haze
    # the canvas light must clear locally); upstream path aerosol is handled per
    # column inside the trace, so the two aerosol channels don't double-count.
    # Falls back to the 1-D path-mean, then to no aerosol, when column AOD is absent.
    sunward_ray_clearance = None
    if sunward_cross_section is not None and cloud_base_m is not None:
        observer_aod = _observer_column_aod(sunward_cross_section)
        if observer_aod is None:
            observer_aod = spatial.get("sunward_aod_mean")
        effective_base = equivalent_cloud_base_from_aod_m(cloud_base_m, observer_aod)
        sunward_ray_clearance = trace_ray_clearance(sunward_cross_section, effective_base)

    return Features(
        cloud_low_pct=snapshot.cloud_low_pct,
        cloud_mid_pct=snapshot.cloud_mid_pct,
        cloud_high_pct=snapshot.cloud_high_pct,
        humidity_pct=snapshot.humidity_pct,
        sunset_time=sunset_time,
        query_time=time,
        location=(lat, lon),
        visibility_m=getattr(snapshot, "visibility_m", None),
        cloud_base_m=cloud_base_m,
        canvas_layer=canvas_layer,
        canvas_cloud_pct=canvas_cloud_pct,
        aerosol_optical_depth=getattr(snapshot, "aerosol_optical_depth", None),
        cloud_base_source=cloud_base_source,
        cloud_base_fixed_m=fixed_base,
        cloud_base_confidence=cloud_base_confidence,
        diagnosed_obstruction_pct=diagnosed_obstruction_pct,
        layer_contributions=layer_contributions,
        diagnosed_mid_high_cover_pct=diagnosed_mid_high_cover_pct,
        sunward_ray_clearance=sunward_ray_clearance,
        **spatial,
    )
