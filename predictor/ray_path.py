"""Parabolic sunward ray trace through the cross-section (#57 P1, FA-G5).

The current `SunwardIlluminationGate` only compares a scalar boundary distance to
the maximum reach. The manual's operational method (§4.1.2) is richer: draw the
parabola that represents the sunlight ray reaching the observer's cloud base and
make sure it does not cross an opaque region — cloud or heavy aerosol — on its way
in ("保证抛物线不穿过不透光的大气区域，比如有云的区域或者气溶胶消光严重的区域").

This module is the pure algorithm (no I/O, no scoring): given an assembled
``SunwardCrossSection`` (which carries the diagnosed cloud layers per column) and
the observer's aerosol-effective cloud base, it traces that parabola and reports
whether the ray is clear, and where it is first blocked.

Geometry (same parabolic flat coordinates as ``geometry.py``): the ray reaching a
cloud base ``h_eff`` grazes the equivalent ground at the vertex
``l_v = √(2R·h_eff)``; its height a horizontal distance ``l`` from the observer is
``h_ray(l) = (l − l_v)² / (2R)``. So the ray is near the ground around the vertex
(where low cloud blocks it) and rises to ``h_eff`` at the observer's own column —
which is the canvas itself and is therefore excluded from obstruction.

FA-A2 (per-column aerosol path extinction) is now live, but as an UPSTREAM-EXCESS
test, not an absolute floor. Each column's AOD gives an equivalent opaque-ground
height ``h_x`` (``geometry.aerosol_ground_height_m``). A fixed floor would be wrong:
the parabola dips to 0 at the vertex, so comparing the ray to an absolute ``h_x``
would veto on any turbid near-vertex column — including a uniformly hazy path that
is firecloud-viable. Instead, the observer's OWN ``h_x`` is the grazing datum (it
already lowered the effective base / pulled the vertex in, P0's
``equivalent_cloud_base_*``), and an upstream column obstructs only when its ``h_x``
rises ABOVE that datum by more than the ray height — i.e. its EXCESS over the
observer. So uniform haze never self-vetoes (it is in the effective base), and only a
genuinely denser upstream plume — the grazing ray's longest near-ground segment,
often hundreds of km upstream, where the manual warns extinction is higher than
expected (§1.3.4) — intercepts the low ray. The observer column is skipped for
obstruction, so the local and upstream aerosol channels never double-count.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from predictor.clouds import CloudLayer
from predictor.cross_section import SunwardCrossSection
from predictor.geometry import (
    _DEFAULT_AEROSOL_SCALE_HEIGHT_M,
    EARTH_RADIUS_KM,
    aerosol_ground_height_m,
)
from predictor.illumination import _layer_opacity


@dataclass
class RayClearance:
    clear: bool
    blocked_at_km: float | None      # distance of the first obstruction (None if clear)
    blocked_height_m: float | None   # ray height there
    blocked_layer: CloudLayer | None  # the obstructing layer (None for a terrain/aerosol block)
    columns_checked: int


def ray_height_m(distance_km: float, vertex_km: float) -> float:
    """Height (m) of the grazing ray at horizontal distance ``distance_km``.

    ``h_ray(l) = (l − l_v)² / (2R)`` with ``l_v = vertex_km``; 0 at the vertex,
    rising on both sides.
    """
    dl = distance_km - vertex_km
    return (dl * dl) / (2.0 * EARTH_RADIUS_KM) * 1000.0


def trace_ray_clearance(
    cross_section: SunwardCrossSection,
    observer_cloud_base_eff_m: float,
    *,
    opacity_threshold: float = 0.5,
    min_path_distance_km: float = 1.0,
    aerosol_scale_height_m: float = _DEFAULT_AEROSOL_SCALE_HEIGHT_M,
) -> RayClearance:
    """Trace the grazing ray to ``observer_cloud_base_eff_m`` and report obstruction.

    Walks the cross-section columns from the observer outward; at each column the
    ray height is ``ray_height_m(distance, vertex)``. A column blocks the ray when
    either (a) a diagnosed cloud layer there spans that height with
    ``_layer_opacity(layer) >= opacity_threshold``, (b) terrain (FA-G6): the
    column's ground elevation exceeds the observer-column elevation datum and
    the ray dips into that excess (a uniform plateau is a shifted datum and
    never self-vetoes; no datum → no terrain checks), or (c) per-column aerosol
    (FA-A2, RH-amplified per FA-A4): the column's AOD — swollen by its own
    near-ground humidity via ``hygroscopic_growth_factor`` — gives an equivalent
    opaque-ground height ``h_x`` and the ray dips to/below it
    (``height <= h_x``, ``h_x > 0``). Clouds are checked before aerosol within a
    column, so a real deck is reported in preference to the aerosol floor it shares
    the column with. The observer's own column (``distance < min_path_distance_km``)
    is skipped — its near-ground aerosol enters through the effective base, not here.
    Returns the first (nearest) blockage, or ``clear=True`` when none is found.
    ``columns_checked == 0`` flags a path with no usable columns.

    Assumes ``cross_section.cloud_layers`` (and ``aerosol_optical_depth_per_column``
    when present) is aligned with ``distances_km`` (as ``build_cross_section`` emits
    it); a None aerosol attribute means no per-column aerosol data → cloud-only
    behaviour. A non-finite or non-positive effective base means light cannot reach
    it → ``clear=False``.
    """
    if not math.isfinite(observer_cloud_base_eff_m) or observer_cloud_base_eff_m <= 0:
        return RayClearance(False, 0.0, 0.0, None, 0)

    n_columns = len(cross_section.distances_km)
    aod_per_column = cross_section.aerosol_optical_depth_per_column
    if aod_per_column is None:
        aod_per_column = [None] * n_columns
    rh_per_column = _near_ground_rh_per_column(cross_section)
    terrain_per_column = cross_section.terrain_elevation_m_per_column
    if terrain_per_column is None:
        terrain_per_column = [None] * n_columns

    # The observer's own equivalent aerosol ground is the grazing datum: it already
    # lowered the effective base (vertex), so the ray height here is measured *above*
    # it. An upstream column only obstructs when its equivalent ground rises ABOVE
    # that datum — i.e. by its EXCESS over the observer — so uniform haze (already in
    # the effective base) never self-vetoes and only a genuinely denser upstream
    # plume (manual §1.3.4) intercepts the low ray. FA-A4: each column's AOD is
    # amplified by its own near-ground humidity (manual §2.4.3 雾霾), so a humid
    # upstream pocket can veto at uniform AOD while uniform humidity cancels out.
    observer_ground_m = 0.0
    observer_terrain_m = None
    for distance_km, aod, rh, terrain in zip(
        cross_section.distances_km, aod_per_column, rh_per_column, terrain_per_column
    ):
        if distance_km < min_path_distance_km:
            observer_ground_m = aerosol_ground_height_m(
                aod, aerosol_scale_height_m, rh_pct=rh
            )
            observer_terrain_m = terrain
            break

    vertex_km = math.sqrt(2.0 * EARTH_RADIUS_KM * (observer_cloud_base_eff_m / 1000.0))
    checked = 0
    for distance_km, layers, aod, rh, terrain in zip(
        cross_section.distances_km, cross_section.cloud_layers, aod_per_column,
        rh_per_column, terrain_per_column,
    ):
        if distance_km < min_path_distance_km:
            continue
        height_m = ray_height_m(distance_km, vertex_km)
        checked += 1
        for layer in layers or []:
            if layer.base_m <= height_m <= layer.top_m and _layer_opacity(layer) >= opacity_threshold:
                return RayClearance(False, float(distance_km), height_m, layer, checked)
        # FA-G6 terrain horizon: a ridge obstructs only by its EXCESS over the
        # observer-column elevation datum — a uniform plateau is a shifted
        # datum (never self-vetoes), an elevated observer sees over lower
        # ridges (horizon depression), and with no datum we don't guess (an
        # absolute floor would wrongly veto every elevated plain).
        if observer_terrain_m is not None and terrain is not None:
            terrain_excess_m = terrain - observer_terrain_m
            if terrain_excess_m > 0.0 and height_m <= terrain_excess_m:
                return RayClearance(False, float(distance_km), height_m, None, checked)
        aerosol_excess_m = (
            aerosol_ground_height_m(aod, aerosol_scale_height_m, rh_pct=rh)
            - observer_ground_m
        )
        if aerosol_excess_m > 0.0 and height_m <= aerosol_excess_m:
            return RayClearance(False, float(distance_km), height_m, None, checked)
    return RayClearance(True, None, None, None, checked)


_NEAR_GROUND_MAX_HEIGHT_M = 1500.0


def _near_ground_rh_per_column(
    cross_section: SunwardCrossSection,
    max_height_m: float = _NEAR_GROUND_MAX_HEIGHT_M,
) -> list[float | None]:
    """Lowest-level (≤ ~boundary-layer top) finite RH per column, for FA-A4.

    Returns None for columns with no finite RH below ``max_height_m`` — those
    columns get no hygroscopic amplification (bit-exact dry behaviour).
    """
    n = len(cross_section.distances_km)
    rh_grid = cross_section.relative_humidity_pct
    if rh_grid is None:
        return [None] * n
    low_rows = [
        k for k, h in enumerate(cross_section.heights_m) if h <= max_height_m
    ]
    out: list[float | None] = [None] * n
    for i in range(n):
        for k in low_rows:  # heights ascend → first finite value is the lowest
            value = rh_grid[k, i]
            if value is not None and math.isfinite(value):
                out[i] = float(value)
                break
    return out
