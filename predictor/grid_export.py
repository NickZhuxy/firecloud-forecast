"""Per-cell grid sidecars (``{stem}.grid.json``) for the static web map.

The page draws these values directly, so a clicked cell shows exactly the index
the PNG colours: same grid, same class bounds, same colours, same Natural Earth
outlines (simplified). Non-finite values become ``null`` so the file is strict
JSON.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Iterable

import numpy as np
from matplotlib.colors import BoundaryNorm, to_hex

from predictor.map_style import INDEX_CMAP, NO_DATA_COLOR
from predictor.national_product import DISPLAY_INDEX_BOUNDS, MapContext, geometry_mask
from predictor.rules import limiting_gate  # noqa: F401  (re-exported for callers)

if TYPE_CHECKING:
    from predictor.local_field import LocalField
    from predictor.national_field import NationalField

GRID_SCHEMA = "firecloud-grid/1"


def color_stops() -> list[list]:
    """``[[lower_bound, "#rrggbb"], ...]``: the class colours the PNG uses."""
    norm = BoundaryNorm(DISPLAY_INDEX_BOUNDS, INDEX_CMAP.N, clip=True)
    return [[float(bound), to_hex(INDEX_CMAP(norm(bound)))] for bound in DISPLAY_INDEX_BOUNDS[:-1]]


def _rounded(values, digits: int = 3) -> list:
    array = np.asarray(values, dtype=float)
    out = np.round(array, digits).astype(object)
    out[~np.isfinite(array)] = None
    return out.tolist()


def _flags(mask) -> list:
    return np.asarray(mask, dtype=bool).tolist()


def _lines_of(geometry) -> Iterable:
    kind = geometry.geom_type
    if kind in ("Polygon", "MultiPolygon"):
        yield from _lines_of(geometry.boundary)
    elif kind == "LineString":
        yield geometry
    elif kind in ("MultiLineString", "GeometryCollection"):
        for part in geometry.geoms:
            yield from _lines_of(part)


def context_polylines(
    context: MapContext | None,
    *,
    bbox: tuple[float, float, float, float] | None = None,
    tolerance_deg: float = 0.02,
) -> list[list[list[float]]]:
    """Outlines the PNG draws, as ``[lon, lat]`` lines clipped to ``bbox``.

    ``bbox`` is ``(south, north, west, east)``; without it nothing is clipped.
    """
    if context is None:
        return []
    from shapely.geometry import box

    window = None if bbox is None else box(bbox[2], bbox[0], bbox[3], bbox[1])
    geometries = [context.country, *context.surrounding, *context.admin1]
    lines: list[list[list[float]]] = []
    for geometry in geometries:
        if geometry is None:
            continue
        for line in _lines_of(geometry):
            if window is not None:
                if not line.intersects(window):
                    continue
                line = line.intersection(window)
            for part in _lines_of(line.simplify(tolerance_deg, preserve_topology=False)):
                points = [[round(x, 3), round(y, 3)] for x, y in part.coords]
                if len(points) >= 2:
                    lines.append(points)
    return lines


def _bbox(field) -> tuple[float, float, float, float]:
    lats, lons = np.asarray(field.lats, dtype=float), np.asarray(field.lons, dtype=float)
    pad_lat = float(np.diff(lats).mean()) if lats.size > 1 else 0.25
    pad_lon = float(np.diff(lons).mean()) if lons.size > 1 else 0.25
    return (lats[0] - pad_lat, lats[-1] + pad_lat, lons[0] - pad_lon, lons[-1] + pad_lon)


def _base(field, *, scope: str, event: str, context, tolerance_deg: float) -> dict:
    return {
        "schema": GRID_SCHEMA,
        "scope": scope,
        "event": event,
        "lats": [round(float(v), 4) for v in field.lats],
        "lons": [round(float(v), 4) for v in field.lons],
        "index": _rounded(field.probability),
        "colors": color_stops(),
        "no_data_color": NO_DATA_COLOR,
        "lines": context_polylines(context, bbox=_bbox(field), tolerance_deg=tolerance_deg),
    }


def local_grid_payload(
    field: LocalField, *, event: str, event_time_utc: str, context: MapContext | None,
) -> dict:
    payload = _base(field, scope="point", event=event, context=context, tolerance_deg=0.02)
    payload["center"] = [float(field.center[0]), float(field.center[1])]
    payload["event_time_utc"] = event_time_utc
    payload["source_label"] = field.source_label
    if field.gate_score is not None:
        payload["gate"] = _rounded(field.gate_score)
    if field.limiting_gate is not None:
        payload["limiting"] = np.asarray(field.limiting_gate, dtype=object).tolist()
    if field.nowcast_mask is not None:
        payload["nowcast_adjusted"] = _flags(field.nowcast_mask)
    return payload


def national_grid_payload(field: NationalField, *, event: str, context: MapContext) -> dict:
    payload = _base(field, scope="national", event=event, context=context, tolerance_deg=0.05)
    payload["label"] = "national screening"
    payload["source_label"] = field.source_label
    # The PNG clips the field to China; cells outside it are not part of the product.
    payload["in_domain"] = _flags(geometry_mask(context.country, field.lats, field.lons))
    if field.refined_mask is not None:
        payload["refined"] = _flags(field.refined_mask)
    return payload
