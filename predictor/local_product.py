"""Local fine-product renderer (#62 PR-B).

Renders a ``LocalField`` (the full single-point physics on a small grid around a
coordinate) to a zoomed PNG + JSON sidecar, in the SAME firecloud orange-red display
scheme as the national overview (colors reused, not redefined). A neutral crosshair
marks the observer. The network orchestration (``generate_local_product``) fetches one
GFS cube + per-cell snapshots; the rendering (``plot_local_product`` / ``save_local_product``)
is pure and offline-testable.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.figure import Figure
from matplotlib.patches import PathPatch
from matplotlib.ticker import FuncFormatter

from predictor.local_field import build_local_field
from predictor.national_product import (
    DISPLAY_PROBABILITY_THRESHOLD,
    DISPLAY_SMOOTH_PASSES,
    DISPLAY_UPSAMPLE_FACTOR,
    MapContext,
    PRODUCT_SCHEMA_VERSION,
    ProductArtifacts,
    _draw_admin_lines,
    _draw_polygon_boundary,
    _geom_to_path,
    _initialized_label,
    _utc,
    display_candidates,
    load_map_context,
)
from predictor.solar_event import SolarEvent, spec_for

LOCAL_CANDIDATE_ALPHA = 0.88
_LOCAL_CANDIDATE_CMAP = LinearSegmentedColormap.from_list(
    "firecloud_local_candidates",
    ["#ffd166", "#ff8a00", "#ef4444", "#991b1b"],
)
_LOCAL_CANDIDATE_CMAP.set_bad(alpha=0.0)


def _format_local_lon(value, _position) -> str:
    suffix = "E" if value >= 0 else "W"
    return f"{abs(value):.1f}°{suffix}"


def _format_local_lat(value, _position) -> str:
    suffix = "N" if value >= 0 else "S"
    return f"{abs(value):.1f}°{suffix}"


def local_display_candidates(probability) -> np.ma.MaskedArray:
    """Candidate field for local products; keeps the same >=0.50 semantics."""
    return display_candidates(
        probability,
        threshold=DISPLAY_PROBABILITY_THRESHOLD,
        passes=DISPLAY_SMOOTH_PASSES,
        upscale=DISPLAY_UPSAMPLE_FACTOR,
    )


def local_display_alpha(candidates: np.ma.MaskedArray) -> np.ndarray:
    """Stable opacity for candidate cells so color, not translucency, carries rank."""
    values = np.asarray(np.ma.filled(candidates, np.nan), dtype=float)
    return np.where(np.isfinite(values), LOCAL_CANDIDATE_ALPHA, 0.0)


def _draw_land(ax, geom, *, facecolor: str, edgecolor: str, linewidth: float, zorder: float) -> None:
    if geom.geom_type not in ("Polygon", "MultiPolygon"):
        return
    ax.add_patch(
        PathPatch(
            _geom_to_path(geom),
            transform=ax.transData,
            facecolor=facecolor,
            edgecolor=edgecolor,
            linewidth=linewidth,
            zorder=zorder,
        )
    )


def _draw_local_map_context(ax, context: MapContext | None) -> None:
    """Draw enough geographic context for a zoomed local product."""
    ax.set_facecolor("#eef6fb")  # water
    if context is None:
        return
    for geometry in context.surrounding:
        _draw_land(
            ax, geometry, facecolor="#f2efe6", edgecolor="#b5afa3",
            linewidth=0.35, zorder=0.4,
        )
    _draw_land(
        ax, context.country, facecolor="#f8f5ed", edgecolor="none",
        linewidth=0.0, zorder=0.5,
    )
    _draw_admin_lines(ax, context.admin1)
    _draw_polygon_boundary(ax, context.country, color="#151515", linewidth=0.9)


def plot_local_product(
    field,
    target_date: date,
    *,
    solar_event: SolarEvent | str = SolarEvent.SUNSET,
    generated_at: datetime | None = None,
    context: MapContext | None = None,
    figure: Figure | None = None,
) -> Figure:
    """Render the local probability field, zoomed to its own extent."""
    spec = spec_for(solar_event)
    generated = _utc(generated_at or datetime.now(timezone.utc))
    clat, clon = field.center

    fig = figure or Figure(figsize=(9.5, 9.0), facecolor="white")
    FigureCanvasAgg(fig)
    fig.patch.set_alpha(1.0)
    ax = fig.add_axes([0.08, 0.07, 0.84, 0.80])
    _draw_local_map_context(ax, context)
    ax.set_xlim(float(field.lons[0]), float(field.lons[-1]))
    ax.set_ylim(float(field.lats[0]), float(field.lats[-1]))
    ax.set_aspect("equal", adjustable="box")
    ax.xaxis.set_major_formatter(FuncFormatter(_format_local_lon))
    ax.yaxis.set_major_formatter(FuncFormatter(_format_local_lat))
    ax.grid(color="#7b8790", linewidth=0.35, alpha=0.35, zorder=1)

    quality = local_display_candidates(field.probability)
    alpha = local_display_alpha(quality)
    image = ax.imshow(
        quality,
        extent=(float(field.lons[0]), float(field.lons[-1]), float(field.lats[0]), float(field.lats[-1])),
        origin="lower",
        cmap=_LOCAL_CANDIDATE_CMAP,
        vmin=DISPLAY_PROBABILITY_THRESHOLD,
        vmax=1.0,
        interpolation="bicubic",
        alpha=alpha,
        zorder=2,
    )
    # Observer crosshair with a light halo so the map center is visible on any color.
    ax.plot(clon, clat, marker="+", markersize=15, markeredgewidth=3.4, color="white", zorder=6)
    ax.plot(clon, clat, marker="+", markersize=15, markeredgewidth=1.7, color="#111111", zorder=7)

    colorbar = fig.colorbar(
        image, ax=ax, orientation="vertical", fraction=0.04, pad=0.02,
        ticks=[DISPLAY_PROBABILITY_THRESHOLD, 0.65, 0.8, 1.0],
    )
    colorbar.ax.tick_params(labelsize=8)
    colorbar.set_label("Firecloud candidate score", fontsize=8)

    fig.text(0.08, 0.95, "Firecloud Potential — Local", ha="left", va="center", fontsize=17, color="#101010")
    fig.text(
        0.92, 0.95, f"Generated {generated:%Y-%m-%d %H:%MZ}",
        ha="right", va="center", fontsize=9, color="#404040",
    )
    fig.text(
        0.08, 0.915,
        f"{spec.label_en} · {clat:g}, {clon:g} · r={field.radius_km:g} km · {target_date:%d %b %Y}"
        f"   |   Initialized: {_initialized_label(field.source_label)}",
        ha="left", va="center", fontsize=10, color="#202020",
    )
    return fig


def _stem(center: tuple[float, float], solar_event: SolarEvent | str) -> str:
    clat, clon = center
    return f"point-{clat:g}_{clon:g}-{SolarEvent(solar_event).value}"


def _metadata(field, target_date: date, image_name: str, generated_at: datetime, solar_event) -> dict:
    prob = np.asarray(field.probability, dtype=float)
    finite = prob[np.isfinite(prob)]
    return {
        "schema_version": PRODUCT_SCHEMA_VERSION,
        "product": "china_firecloud_local",
        "solar_event": SolarEvent(solar_event).value,
        "target_date": target_date.isoformat(),
        "generated_utc": _utc(generated_at).isoformat(),
        "image": image_name,
        "center": [float(field.center[0]), float(field.center[1])],
        "radius_km": float(field.radius_km),
        "valid_time_utc": _utc(field.valid_time).isoformat(),
        "source_label": field.source_label,
        "grid_shape": [int(np.asarray(field.lats).size), int(np.asarray(field.lons).size)],
        "probability_range": {
            "min": float(finite.min()) if finite.size else None,
            "max": float(finite.max()) if finite.size else None,
        },
        "display": {
            "probability_threshold": DISPLAY_PROBABILITY_THRESHOLD,
            "colormap": "firecloud_local_candidates",
            "basemap": "local Natural Earth context",
        },
    }


def save_local_product(
    field,
    target_date: date,
    output_dir: str | Path,
    *,
    solar_event: SolarEvent | str = SolarEvent.SUNSET,
    generated_at: datetime | None = None,
    context: MapContext | None = None,
    dpi: int = 160,
) -> ProductArtifacts:
    """Atomically write ``point-{lat}_{lon}-{event}.png`` and its JSON sidecar."""
    if dpi <= 0:
        raise ValueError("dpi must be positive")
    generated = _utc(generated_at or datetime.now(timezone.utc))
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stem = _stem(field.center, solar_event)
    image_path = directory / f"{stem}.png"
    metadata_path = directory / f"{stem}.json"

    figure = plot_local_product(
        field, target_date, solar_event=solar_event,
        generated_at=generated, context=context,
    )
    image_tmp = directory / f".{stem}.png.tmp"
    figure.savefig(image_tmp, format="png", dpi=dpi, facecolor="white")
    image_tmp.replace(image_path)
    figure.clear()

    metadata = _metadata(field, target_date, image_path.name, generated, solar_event)
    metadata_tmp = directory / f".{stem}.json.tmp"
    metadata_tmp.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    metadata_tmp.replace(metadata_path)
    return ProductArtifacts(image_path=image_path, metadata_path=metadata_path)


def generate_local_product(
    target_date: date,
    output_dir: str | Path,
    lat: float,
    lon: float,
    *,
    dpi: int = 160,
    source=None,
    cube_source=None,
    predictor=None,
    solar_event: SolarEvent | str = SolarEvent.SUNSET,
    radius_km: float = 150.0,
    resolution_deg: float = 0.1,
) -> ProductArtifacts:
    """Fetch, run the full single-point physics over the local grid, render and save.

    The network half (one GFS cube + per-cell Open-Meteo snapshots). The event time
    is the center's sunrise/sunset on ``target_date`` (the small region shares it)."""
    from predictor.fetch import OpenMeteoSource
    from predictor.features import compute_event_time
    from predictor.gfs import GFSSource
    from predictor.rules import standard_predictor

    weather = source if source is not None else OpenMeteoSource(solar_event=solar_event)
    pred = predictor if predictor is not None else standard_predictor(weather)
    cubes = cube_source if cube_source is not None else GFSSource()
    context = load_map_context()

    reference = datetime(target_date.year, target_date.month, target_date.day, 12, tzinfo=timezone.utc)
    event_time = compute_event_time(lat, lon, reference, solar_event)

    field = build_local_field(
        pred, cubes, lat, lon, event_time,
        radius_km=radius_km, resolution_deg=resolution_deg,
    )
    return save_local_product(
        field, target_date, output_dir, solar_event=solar_event, dpi=dpi,
        generated_at=None, context=context,
    )
