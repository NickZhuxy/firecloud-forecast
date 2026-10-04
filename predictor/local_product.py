"""Local fine-product renderer (#62 PR-B).

Renders a ``LocalField`` (the full single-point physics on a small grid around a
coordinate) to a zoomed PNG + JSON sidecar using the same raw-cell condition-index
scale, typography, and uncertainty language as the national product. A
neutral crosshair marks the observer. The network orchestration
(``generate_local_product``) fetches one GFS cube + per-cell snapshots; rendering is
pure and offline-testable.
"""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.patches import PathPatch
from matplotlib.ticker import FuncFormatter, MaxNLocator

from predictor.local_field import _gfs_timing, build_local_field, local_grid
from predictor.map_style import raw_grid_mesh, horizontal_scale, sampling_text, display_metadata
from predictor.local_map_context import load_local_map_context
from predictor.nowcast import NowcastStageResult, apply_nowcast, stage_block
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
from predictor.regions import get_region

def _format_local_lon(value, _position, *, precision: int = 1) -> str:
    suffix = "E" if value >= 0 else "W"
    return f"{abs(value):.{precision}f}°{suffix}"


def _format_local_lat(value, _position, *, precision: int = 1) -> str:
    suffix = "N" if value >= 0 else "S"
    return f"{abs(value):.{precision}f}°{suffix}"


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
    region: str = "china",
) -> Figure:
    """Render the original scored cells with an approximate local geographic aspect."""
    spec = spec_for(solar_event)
    generated = _utc(generated_at or datetime.now(timezone.utc))
    profile = get_region(region)
    event_local = _utc(field.valid_time).astimezone(ZoneInfo(profile.timezone_name))
    model_timing = _model_timing(field)
    clat, clon = field.center
    cos_lat = max(float(np.cos(np.deg2rad(clat))), 1e-6)
    fig = figure or Figure(figsize=(8.2, 8.4), facecolor="white")
    FigureCanvasAgg(fig)
    fig.patch.set_alpha(1.0)
    ax = fig.add_axes([0.095, 0.22, 0.83, 0.62])
    _draw_local_map_context(ax, context)
    mesh, lat_edges, lon_edges = raw_grid_mesh(
        ax, field, DISPLAY_INDEX_BOUNDS,
        singleton_steps=(2 * field.radius_km / 111.0,
                         2 * field.radius_km / (111.0 * cos_lat)),
    )
    ax.set_xlim(float(lon_edges[0]), float(lon_edges[-1]))
    ax.set_ylim(float(lat_edges[0]), float(lat_edges[-1]))
    ax.set_aspect(1.0 / cos_lat, adjustable="box")
    lon_precision = 2 if lon_edges[-1] - lon_edges[0] < 1.0 else 1
    lat_precision = 2 if lat_edges[-1] - lat_edges[0] < 1.0 else 1
    ax.xaxis.set_major_formatter(FuncFormatter(
        lambda value, position: _format_local_lon(value, position, precision=lon_precision)))
    ax.yaxis.set_major_formatter(FuncFormatter(
        lambda value, position: _format_local_lat(value, position, precision=lat_precision)))
    ax.xaxis.set_major_locator(MaxNLocator(nbins=4))
    ax.yaxis.set_major_locator(MaxNLocator(nbins=4))
    ax.tick_params(labelsize=8, length=0, pad=7, colors="#766e68")
    for spine in ax.spines.values():
        spine.set_edgecolor("#ded9d4")
        spine.set_linewidth(0.7)
    for label in [*ax.get_xticklabels(), *ax.get_yticklabels()]:
        label.set_fontfamily(SCIENTIFIC_FONT_FAMILY)
    ax.grid(color="#8d8d8d", linewidth=0.35, alpha=0.25, zorder=1)
    if context is not None:
        _draw_admin_lines(ax, context.admin1)
        _draw_polygon_boundary(ax, context.country, color="#444444", linewidth=0.7)
    ax.plot(clon, clat, marker="+", markersize=13, markeredgewidth=3.2, color="white", zorder=6)
    ax.plot(clon, clat, marker="+", markersize=13, markeredgewidth=1.5, color="#111111", zorder=7)
    horizontal_scale(fig, mesh, DISPLAY_INDEX_BOUNDS)
    center_j = int(np.argmin(np.abs(np.asarray(field.lats) - clat)))
    center_i = int(np.argmin(np.abs(np.asarray(field.lons) - clon)))
    center_raw = float(np.ma.filled(np.ma.asarray(field.probability, dtype=float), np.nan)[center_j, center_i])
    center_value = f"{center_raw:.2f}" if np.isfinite(center_raw) else "No data"
    texts = (
        (0.075, 0.947, f"{spec.label_en} condition index", 17, "left", "bold"),
        (0.075, 0.902, f"{event_local:%d %b %Y %H:%M %Z} · "
         f"event {_utc(field.valid_time):%d %b %H:%M UTC}", 9, "left", "normal"),
        (0.925, 0.947, f"Center index  {center_value}", 11, "right", "semibold"),
        (0.075, 0.867, f"Observer {abs(clat):.2f}°{'N' if clat >= 0 else 'S'}, "
         f"{abs(clon):.2f}°{'E' if clon >= 0 else 'W'} · {profile.name} · radius {field.radius_km:g} km", 8, "left", "normal"),
        (0.075, 0.065, f"GFS 0.25° initialized {_initialized_label(field.source_label)} · "
         f"weather valid {_model_time_label(model_timing['valid_time_utc'])}", 8, "left", "normal"),
        (0.075, 0.035, f"{np.asarray(field.probability).size:,} evaluated cells · {sampling_text(field)} · "
         f"raw values, no spatial interpolation · product timestamp {generated:%Y-%m-%d %H:%M UTC}", 7.5, "left", "normal"),
    )
    for x, y, text, size, align, weight in texts:
        fig.text(x, y, text, ha=align, va="center", fontsize=size,
                 fontfamily=SCIENTIFIC_FONT_FAMILY, fontweight=weight,
                 color="#312824" if weight != "normal" else "#766e68")
    nowcast = getattr(field, "nowcast", None)
    note = "Uncalibrated diagnostic; not a calibrated occurrence probability"
    if nowcast and nowcast.get("applied"):
        note += f" · {nowcast.get('cells_corrected', 0):,} cells satellite-nudged"
    fig.text(0.075, 0.095, note, fontsize=8, fontfamily=SCIENTIFIC_FONT_FAMILY, color="#766e68")
    return fig


def _stem(center: tuple[float, float], solar_event: SolarEvent | str) -> str:
    clat, clon = center
    return f"point-{clat:g}_{clon:g}-{SolarEvent(solar_event).value}"


def _model_timing(field) -> dict:
    provenance = getattr(field, "provenance", None) or {}
    return provenance.get("gfs") or _gfs_timing(field.source_label)


def _model_time_label(value: str | None) -> str:
    if value is None:
        return "unknown"
    return f"{_utc(datetime.fromisoformat(value)):%d %b %H:%M UTC}"


def _json_value(value):
    """Keep optional diagnostic data compatible with strict JSON."""
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [_json_value(item) for item in value]
    if isinstance(value, datetime):
        return _utc(value).isoformat()
    if isinstance(value, (float, np.floating)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def _metadata(
    field, target_date: date, image_name: str, generated_at: datetime, solar_event,
    *, region: str = "china",
) -> dict:
    prob = np.ma.filled(np.ma.asarray(field.probability, dtype=float), np.nan)
    finite = prob[np.isfinite(prob)]
    lats = np.asarray(field.lats, dtype=float)
    lons = np.asarray(field.lons, dtype=float)
    center_j = int(np.argmin(np.abs(lats - float(field.center[0]))))
    center_i = int(np.argmin(np.abs(lons - float(field.center[1]))))
    center_raw = float(prob[center_j, center_i])
    center_value = center_raw if np.isfinite(center_raw) else None
    resolution_deg = float(np.median(np.diff(lats))) if lats.size > 1 else None
    profile = get_region(region)
    event_utc = _utc(field.valid_time)
    event_local = event_utc.astimezone(ZoneInfo(profile.timezone_name))
    metadata = {
        "schema_version": PRODUCT_SCHEMA_VERSION,
        "product": profile.local_product_name,
        "region": profile.key,
        "region_name": profile.name,
        "timezone": profile.timezone_name,
        "solar_event": SolarEvent(solar_event).value,
        "target_date": target_date.isoformat(),
        "generated_utc": _utc(generated_at).isoformat(),
        "image": image_name,
        "center": [float(field.center[0]), float(field.center[1])],
        "radius_km": float(field.radius_km),
        "valid_time_utc": _utc(field.valid_time).isoformat(),
        "valid_time_semantics": "requested_solar_event",
        "event_time_utc": event_utc.isoformat(),
        "event_time_local": event_local.isoformat(),
        "event_timezone_abbreviation": event_local.tzname(),
        "gfs_timing": _model_timing(field),
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
            **display_metadata(field, DISPLAY_INDEX_BOUNDS, projection={
                "name": "local_equirectangular_approximation",
                "aspect": float(1.0 / max(np.cos(np.deg2rad(field.center[0])), 1e-6)),
                "reference_latitude_deg": float(field.center[0]),
            }),
            "favorable_threshold": DISPLAY_PROBABILITY_THRESHOLD,
            "threshold_semantics": "legacy_display_reference_only",
            "basemap": "white Natural Earth context",
            "evaluation_resolution_deg": resolution_deg,
            "singleton_axis_footprint": "requested_radius",
        },
    }
    nowcast = getattr(field, "nowcast", None)
    if nowcast is not None:
        metadata["nowcast"] = nowcast
    for name in ("provenance", "center_diagnostics"):
        value = getattr(field, name, None)
        if value is not None:
            metadata[name] = _json_value(value)
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
    region: str = "china",
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
        generated_at=generated, context=context, region=region,
    )
    image_tmp = directory / f".{stem}.png.tmp"
    figure.savefig(image_tmp, format="png", dpi=dpi, facecolor="white")
    image_tmp.replace(image_path)
    figure.clear()

    metadata = _metadata(
        field, target_date, image_path.name, generated, solar_event, region=region,
    )
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
    region: str = "china",
) -> ProductArtifacts:
    """Fetch, run the full single-point physics over the local grid, render and save.

    The network half (one GFS cube + per-cell Open-Meteo snapshots). The event time
    is the center's sunrise/sunset on ``target_date`` (the small region shares it).
    Stage C (#84): within ~2 h of the event, two Himawari B13 frames nudge the
    field toward the observed cloud motion; failures keep the field as-is and
    ``satellite=False`` skips the stage entirely."""
    from predictor.fetch import OpenMeteoSource
    from predictor.solar_event import event_time_utc
    from predictor.gfs import GFSSource
    from predictor.rules import standard_predictor

    profile = get_region(region)
    profile.validate_center(lat, lon)
    weather = source if source is not None else OpenMeteoSource(solar_event=solar_event)
    pred = predictor if predictor is not None else standard_predictor(weather)
    cubes = cube_source if cube_source is not None else GFSSource(as_of=now)
    if region == "china":
        context = load_map_context()
    else:
        lats, lons = local_grid(lat, lon, radius_km=radius_km, resolution_deg=resolution_deg)
        context = load_local_map_context(
            profile.country_code,
            (float(lats[0]), float(lats[-1]), float(lons[0]), float(lons[-1])),
        )

    event_time = event_time_utc(
        target_date, lat, lon, solar_event,
        timezone_name=profile.timezone_name if region != "china" else None,
    )

    field = build_local_field(
        pred, cubes, lat, lon, event_time,
        radius_km=radius_km, resolution_deg=resolution_deg,
    )
    if not profile.satellite_enabled:
        probability = np.asarray(field.probability, dtype=float)
        skipped = NowcastStageResult(
            corrected_probability=probability,
            corrected_mask=np.zeros(probability.shape, dtype=bool),
            motion=None, applied=False, source="model",
            reason=f"unsupported satellite coverage for region {profile.key}",
            lead_hr_range=None,
        )
        field = replace(field, nowcast=stage_block(skipped, probability))
    elif satellite:
        field = _with_nowcast(field, event_time, satellite_source, now)
    return save_local_product(
        field, target_date, output_dir, solar_event=solar_event, dpi=dpi,
        generated_at=now, context=context, region=region,
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
