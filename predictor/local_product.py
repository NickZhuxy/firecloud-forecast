"""Local fine-product renderer (#62 PR-B).

Renders a ``LocalField`` (the full single-point physics on a small grid around a
coordinate) to a zoomed PNG + JSON sidecar using the same classified condition-index
scale, isolines, typography, and uncertainty language as the national product. A
neutral crosshair marks the observer. The network orchestration
(``generate_local_product``) fetches one GFS cube + per-cell snapshots; rendering is
pure and offline-testable.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.patches import PathPatch
from matplotlib.ticker import FuncFormatter

from predictor.local_field import build_local_field
from predictor.nowcast import apply_nowcast, stage_block
from predictor.national_product import (
    DISPLAY_CONTOUR_LEVELS,
    DISPLAY_FIELD_ALPHA,
    DISPLAY_INDEX_BOUNDS,
    DISPLAY_PROBABILITY_THRESHOLD,
    DISPLAY_SMOOTH_PASSES,
    DISPLAY_UPSAMPLE_FACTOR,
    MapContext,
    PRODUCT_SCHEMA_VERSION,
    ProductArtifacts,
    SCIENTIFIC_FONT_FAMILY,
    SCIENTIFIC_MONO_FONT_FAMILY,
    _QUALITY_CMAP,
    _QUALITY_NORM,
    _draw_admin_lines,
    _draw_polygon_boundary,
    _geom_to_path,
    _initialized_label,
    _utc,
    display_index_field,
    load_map_context,
)
from predictor.solar_event import SolarEvent, spec_for

def _format_local_lon(value, _position) -> str:
    suffix = "E" if value >= 0 else "W"
    return f"{abs(value):.1f}°{suffix}"


def _format_local_lat(value, _position) -> str:
    suffix = "N" if value >= 0 else "S"
    return f"{abs(value):.1f}°{suffix}"


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
    ax.set_facecolor("white")
    if context is None:
        return
    for geometry in context.surrounding:
        _draw_land(
            ax, geometry, facecolor="white", edgecolor="#adb5bd",
            linewidth=0.35, zorder=0.4,
        )
    _draw_land(
        ax, context.country, facecolor="white", edgecolor="none",
        linewidth=0.0, zorder=0.5,
    )


def plot_local_product(
    field,
    target_date: date,
    *,
    solar_event: SolarEvent | str = SolarEvent.SUNSET,
    generated_at: datetime | None = None,
    context: MapContext | None = None,
    figure: Figure | None = None,
) -> Figure:
    """Render a publication-style local condition-index analysis."""
    spec = spec_for(solar_event)
    generated = _utc(generated_at or datetime.now(timezone.utc))
    clat, clon = field.center

    fig = figure or Figure(figsize=(11.5, 8.6), facecolor="white")
    FigureCanvasAgg(fig)
    fig.patch.set_alpha(1.0)
    ax = fig.add_axes([0.065, 0.15, 0.69, 0.68])
    _draw_local_map_context(ax, context)
    ax.set_xlim(float(field.lons[0]), float(field.lons[-1]))
    ax.set_ylim(float(field.lats[0]), float(field.lats[-1]))
    ax.set_aspect("equal", adjustable="box")
    ax.xaxis.set_major_formatter(FuncFormatter(_format_local_lon))
    ax.yaxis.set_major_formatter(FuncFormatter(_format_local_lat))
    ax.tick_params(labelsize=8.5)
    for label in [*ax.get_xticklabels(), *ax.get_yticklabels()]:
        label.set_fontfamily(SCIENTIFIC_FONT_FAMILY)
    ax.grid(color="#8d8d8d", linewidth=0.35, alpha=0.35, zorder=1)

    index_field = display_index_field(field.probability)
    image = ax.imshow(
        index_field,
        extent=(float(field.lons[0]), float(field.lons[-1]), float(field.lats[0]), float(field.lats[-1])),
        origin="lower",
        cmap=_QUALITY_CMAP,
        norm=_QUALITY_NORM,
        interpolation="nearest",
        alpha=DISPLAY_FIELD_ALPHA,
        zorder=2,
    )

    display_lats = np.linspace(field.lats[0], field.lats[-1], index_field.shape[0])
    display_lons = np.linspace(field.lons[0], field.lons[-1], index_field.shape[1])
    finite = index_field.compressed()
    contour_levels = [
        level
        for level in DISPLAY_CONTOUR_LEVELS
        if finite.size and float(finite.min()) < level < float(finite.max())
    ]
    if contour_levels:
        contours = ax.contour(
            display_lons,
            display_lats,
            index_field,
            levels=contour_levels,
            colors="#343a40",
            linewidths=[
                1.6 if level == DISPLAY_PROBABILITY_THRESHOLD else 0.75
                for level in contour_levels
            ],
            linestyles=[
                "solid" if level >= DISPLAY_PROBABILITY_THRESHOLD else "dashed"
                for level in contour_levels
            ],
            zorder=3,
        )
        contour_labels = ax.clabel(
            contours,
            fmt="%.1f",
            fontsize=6.5,
            inline=True,
            inline_spacing=2,
        )
        for label in contour_labels:
            label.set_fontfamily(SCIENTIFIC_FONT_FAMILY)

    # Repaint administrative lines above the field so high-index colors cannot hide them.
    if context is not None:
        _draw_admin_lines(ax, context.admin1)
        _draw_polygon_boundary(ax, context.country, color="#151515", linewidth=0.9)

    # Observer crosshair with a light halo so the map center is visible on any color.
    ax.plot(clon, clat, marker="+", markersize=15, markeredgewidth=3.4, color="white", zorder=6)
    ax.plot(clon, clat, marker="+", markersize=15, markeredgewidth=1.7, color="#111111", zorder=7)

    colorbar_ax = fig.add_axes([0.80, 0.55, 0.028, 0.25])
    colorbar = fig.colorbar(
        image,
        cax=colorbar_ax,
        orientation="vertical",
        boundaries=DISPLAY_INDEX_BOUNDS,
        ticks=DISPLAY_INDEX_BOUNDS,
        spacing="proportional",
    )
    colorbar.ax.tick_params(labelsize=7.5, length=3)
    colorbar.ax.set_yticklabels(["0", "0.2", "0.4", "0.5", "0.7", "0.85", "1.0"])
    for label in colorbar.ax.get_yticklabels():
        label.set_fontfamily(SCIENTIFIC_FONT_FAMILY)
    colorbar.set_label(
        "Condition index", fontsize=9, fontfamily=SCIENTIFIC_FONT_FAMILY
    )

    fig.text(
        0.065,
        0.93,
        "Firecloud Condition Index — Local Detail",
        ha="left",
        va="center",
        fontsize=19,
        fontfamily=SCIENTIFIC_FONT_FAMILY,
        fontweight="semibold",
        color="#101010",
    )
    fig.text(
        0.95,
        0.93,
        "UNCALIBRATED DIAGNOSTIC  |  FAVORABLE ≥ 0.50",
        ha="right",
        va="center",
        fontsize=8.5,
        fontfamily=SCIENTIFIC_FONT_FAMILY,
        color="#444444",
    )
    nowcast = getattr(field, "nowcast", None)
    nowcast_note = ""
    if nowcast and nowcast.get("applied") and nowcast.get("cells_corrected"):
        nowcast_note = (
            f" · {nowcast['cells_corrected']:,} cells satellite-nudged "
            f"({nowcast['regime']}, conf {nowcast['confidence']:.1f})"
        )
    fig.text(
        0.065,
        0.875,
        f"GFS initialized {_initialized_label(field.source_label)}  →  "
        f"{spec.label_en.lower()} {target_date:%d %b %Y} | {field.valid_time:%H:%M UTC}",
        ha="left",
        va="center",
        fontsize=9.5,
        fontfamily=SCIENTIFIC_FONT_FAMILY,
        color="#202020",
    )
    center_j = int(np.argmin(np.abs(np.asarray(field.lats) - clat)))
    center_i = int(np.argmin(np.abs(np.asarray(field.lons) - clon)))
    center_raw = float(np.asarray(field.probability)[center_j, center_i])
    center_value = f"{center_raw:.2f}" if np.isfinite(center_raw) else "—"
    grid_spacing = (
        float(np.median(np.diff(np.asarray(field.lats))))
        if np.asarray(field.lats).size > 1
        else 0.0
    )
    fig.text(
        0.80,
        0.815,
        "CLASSIFIED SCALE",
        ha="left",
        va="bottom",
        fontsize=8,
        fontweight="bold",
        fontfamily=SCIENTIFIC_FONT_FAMILY,
        color="#303030",
    )
    fig.text(
        0.80,
        0.49,
        "LOCAL ANALYSIS",
        ha="left",
        va="bottom",
        fontsize=8,
        fontweight="bold",
        fontfamily=SCIENTIFIC_FONT_FAMILY,
        color="#303030",
    )
    details = (
        ("Center", f"{clat:.2f}°N, {clon:.2f}°E"),
        ("Radius", f"{field.radius_km:g} km"),
        ("Grid", f"{grid_spacing:g}° evaluation"),
        ("Valid", f"{field.valid_time:%H:%M UTC}"),
        ("Center index", center_value),
    )
    for row, (label, value) in enumerate(details):
        y = 0.455 - row * 0.035
        fig.text(
            0.80,
            y,
            label,
            ha="left",
            va="center",
            fontsize=7.5,
            fontfamily=SCIENTIFIC_FONT_FAMILY,
            color="#555555",
        )
        fig.text(
            0.95,
            y,
            value,
            ha="right",
            va="center",
            fontsize=7.5,
            fontfamily=SCIENTIFIC_MONO_FONT_FAMILY,
            color="#111111",
        )
    fig.text(
        0.80,
        0.25,
        "Isolines  0.3 · 0.5 · 0.7 · 0.9\nBold 0.5 = favorable threshold",
        ha="left",
        va="top",
        fontsize=7,
        fontfamily=SCIENTIFIC_FONT_FAMILY,
        color="#555555",
        linespacing=1.35,
    )
    fig.text(
        0.065,
        0.072,
        f"{np.asarray(field.probability).size:,} full-physics grid cells · "
        f"display-only smoothing/interpolation{nowcast_note}",
        ha="left",
        va="center",
        fontsize=7.8,
        fontfamily=SCIENTIFIC_FONT_FAMILY,
        color="#555555",
    )
    fig.text(
        0.065,
        0.04,
        "Relative diagnostic index, not a calibrated occurrence probability · "
        f"generated {generated.isoformat()}",
        ha="left",
        va="center",
        fontsize=7.3,
        fontfamily=SCIENTIFIC_FONT_FAMILY,
        color="#666666",
    )
    return fig


def _stem(center: tuple[float, float], solar_event: SolarEvent | str) -> str:
    clat, clon = center
    return f"point-{clat:g}_{clon:g}-{SolarEvent(solar_event).value}"


def _metadata(field, target_date: date, image_name: str, generated_at: datetime, solar_event) -> dict:
    prob = np.asarray(field.probability, dtype=float)
    finite = prob[np.isfinite(prob)]
    lats = np.asarray(field.lats, dtype=float)
    lons = np.asarray(field.lons, dtype=float)
    center_j = int(np.argmin(np.abs(lats - float(field.center[0]))))
    center_i = int(np.argmin(np.abs(lons - float(field.center[1]))))
    center_raw = float(prob[center_j, center_i])
    center_value = center_raw if np.isfinite(center_raw) else None
    resolution_deg = float(np.median(np.diff(lats))) if lats.size > 1 else None
    metadata = {
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
        "condition_index": {
            "calibrated_probability": False,
            "range": {
                "min": float(finite.min()) if finite.size else None,
                "max": float(finite.max()) if finite.size else None,
            },
            "favorable_threshold": DISPLAY_PROBABILITY_THRESHOLD,
            "center_value": center_value,
        },
        "display": {
            "metric": "uncalibrated_condition_index",
            "favorable_threshold": DISPLAY_PROBABILITY_THRESHOLD,
            "class_bounds": list(DISPLAY_INDEX_BOUNDS),
            "contour_levels": list(DISPLAY_CONTOUR_LEVELS),
            "field_alpha": DISPLAY_FIELD_ALPHA,
            "colormap": "firecloud_scientific_classes",
            "font_family": SCIENTIFIC_FONT_FAMILY,
            "basemap": "white Natural Earth context",
            "upsample_factor": DISPLAY_UPSAMPLE_FACTOR,
            "smoothing_passes": DISPLAY_SMOOTH_PASSES,
            "evaluation_resolution_deg": resolution_deg,
        },
    }
    nowcast = getattr(field, "nowcast", None)
    if nowcast is not None:
        metadata["nowcast"] = nowcast
    return metadata


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
    metadata_tmp.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
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
    satellite: bool = True,
    satellite_source=None,
    now: datetime | None = None,
) -> ProductArtifacts:
    """Fetch, run the full single-point physics over the local grid, render and save.

    The network half (one GFS cube + per-cell Open-Meteo snapshots). The event time
    is the center's sunrise/sunset on ``target_date`` (the small region shares it).
    Stage C (#84): within ~2 h of the event, two Himawari B13 frames nudge the
    field toward the observed cloud motion; failures keep the field as-is and
    ``satellite=False`` skips the stage entirely."""
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
    if satellite:
        field = _with_nowcast(field, event_time, satellite_source, now)
    return save_local_product(
        field, target_date, output_dir, solar_event=solar_event, dpi=dpi,
        generated_at=now, context=context,
    )


def _with_nowcast(field, event_time: datetime, satellite_source, now: datetime | None):
    """Run Stage C on the local grid; the small region shares one event time."""
    from dataclasses import replace

    if satellite_source is None:
        from predictor.satellite import Himawari9Source

        satellite_source = Himawari9Source()
    event_times = np.full(
        np.asarray(field.probability).shape,
        np.datetime64(int(event_time.timestamp()), "s"),
    )
    result = apply_nowcast(
        field.probability, field.lats, field.lons, event_times,
        satellite_source, now=now or datetime.now(timezone.utc),
    )
    block = stage_block(result, field.probability)
    if result.applied:
        return replace(field, probability=result.corrected_probability, nowcast=block)
    return replace(field, nowcast=block)
