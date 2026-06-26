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

Wiring this into ``SunwardIlluminationGate`` (upgrade when a cross-section is
available, scalar fallback otherwise) and per-column aerosol extinction (FA-A2)
are deliberate follow-ups. Aerosol enters correctly through the *effective base*
(P0's ``equivalent_cloud_base_*`` lowers ``h_eff``, raising the graze and pulling
the vertex inward); FA-A2 will vary that per column. A flat opaque-ground floor is
deliberately NOT used here — since the parabola dips to 0 at the vertex, clipping
it at a fixed height would block essentially any ray, which is the wrong physics.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from predictor.clouds import CloudLayer
from predictor.cross_section import SunwardCrossSection
from predictor.geometry import EARTH_RADIUS_KM
from predictor.illumination import _layer_opacity


@dataclass
class RayClearance:
    clear: bool
    blocked_at_km: float | None      # distance of the first obstruction (None if clear)
    blocked_height_m: float | None   # ray height there
    blocked_layer: CloudLayer | None  # the obstructing layer (None for a ground/aerosol block)
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
) -> RayClearance:
    """Trace the grazing ray to ``observer_cloud_base_eff_m`` and report obstruction.

    Walks the cross-section columns from the observer outward; at each column the
    ray height is ``ray_height_m(distance, vertex)``. A column blocks the ray when
    a diagnosed cloud layer there spans that height with
    ``_layer_opacity(layer) >= opacity_threshold``. The observer's own column
    (``distance < min_path_distance_km``) is skipped so the canvas deck does not
    count as self-obstruction. Returns the first blockage, or ``clear=True`` when
    none is found. ``columns_checked == 0`` flags a path with no usable columns.

    Assumes ``cross_section.cloud_layers`` is aligned with ``distances_km`` (as
    ``build_cross_section`` emits it). A non-finite or non-positive effective base
    means light cannot reach it → ``clear=False``.
    """
    if not math.isfinite(observer_cloud_base_eff_m) or observer_cloud_base_eff_m <= 0:
        return RayClearance(False, 0.0, 0.0, None, 0)

    vertex_km = math.sqrt(2.0 * EARTH_RADIUS_KM * (observer_cloud_base_eff_m / 1000.0))
    checked = 0
    for distance_km, layers in zip(cross_section.distances_km, cross_section.cloud_layers):
        if distance_km < min_path_distance_km:
            continue
        height_m = ray_height_m(distance_km, vertex_km)
        checked += 1
        if not layers:
            continue
        for layer in layers:
            if layer.base_m <= height_m <= layer.top_m and _layer_opacity(layer) >= opacity_threshold:
                return RayClearance(False, float(distance_km), height_m, layer, checked)
    return RayClearance(True, None, None, None, checked)
