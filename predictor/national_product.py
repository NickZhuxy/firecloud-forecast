"""Local SunsetWx-style national forecast product generator (#45).

This is deliberately a batch artifact workflow, not a web application.  The
renderer consumes an already-scored ``NationalField`` and writes one canonical,
complete scientific PNG plus machine-readable metadata for local review/sharing.
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.figure import Figure
from matplotlib.patches import PathPatch
from matplotlib.path import Path as MplPath
from matplotlib.ticker import FuncFormatter

from predictor.gfs import GFSSource
from predictor.national_field import NationalField, build_national_field

PRODUCT_SCHEMA_VERSION = "v1"
CN_BBOX = (17.0, 73.0, 54.0, 136.0)  # south, west, north, east
_QUALITY_CMAP = LinearSegmentedColormap.from_list(
    "firecloud_turbo",
    matplotlib.colormaps["turbo"](np.linspace(0.10, 1.0, 256)),
)
_QUALITY_CMAP.set_bad(alpha=0.0)
# Rendering-only smoothing: the scored 0.25° grid can be speckled because many
# gates are intentionally local. The product should read as a coherent weather
# field, so the figure uses a tiny nan-aware binomial blur while metadata and
# downstream algorithm values keep the original unsmoothed probabilities.
DISPLAY_SMOOTH_PASSES = 2


@dataclass(frozen=True)
class MapContext:
    """Injected map geometry; tests use synthetic shapes, production Natural Earth."""

    country: object
    surrounding: tuple[object, ...]
    admin1: tuple[object, ...]


@dataclass(frozen=True)
class ProductArtifacts:
    image_path: Path
    metadata_path: Path


def _geom_to_path(geom) -> MplPath:
    # NOTE: interior rings are appended as additional closed subpaths but are not
    # oriented to cut holes, so lakes/holes are filled rather than excluded. The
    # production 110 m China outline has no interior rings, so this is currently
    # latent; revisit if a higher-resolution outline with lakes is adopted.
    polygons = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
    vertices: list[tuple[float, float]] = []
    codes: list[int] = []
    for polygon in polygons:
        for ring in [polygon.exterior, *polygon.interiors]:
            points = list(ring.coords)
            if len(points) < 3:
                continue
            vertices.extend(points)
            codes.append(MplPath.MOVETO)
            codes.extend([MplPath.LINETO] * (len(points) - 2))
            codes.append(MplPath.CLOSEPOLY)
    if not vertices:
        raise ValueError("country geometry contains no polygon rings")
    return MplPath(vertices, codes)


def _draw_polygon_boundary(ax, geom, *, color: str, linewidth: float) -> None:
    if geom.geom_type not in ("Polygon", "MultiPolygon"):
        return
    ax.add_patch(
        PathPatch(
            _geom_to_path(geom),
            transform=ax.transData,
            facecolor="none",
            edgecolor=color,
            linewidth=linewidth,
            zorder=4,
        )
    )


def _line_parts(geom):
    if geom.geom_type == "LineString":
        yield geom
    elif geom.geom_type in ("MultiLineString", "GeometryCollection"):
        for part in geom.geoms:
            yield from _line_parts(part)


def _draw_admin_lines(ax, geometries: tuple[object, ...]) -> None:
    for geometry in geometries:
        for line in _line_parts(geometry):
            xy = np.asarray(line.coords, dtype=float)
            if xy.size:
                ax.plot(
                    xy[:, 0],
                    xy[:, 1],
                    color="#5a5a5a",
                    linewidth=0.35,
                    alpha=0.75,
                    zorder=4,
                )


def geometry_mask(geom, lats, lons) -> np.ndarray:
    """Boolean grid mask for the country geometry."""
    lon_grid, lat_grid = np.meshgrid(lons, lats)
    points = np.column_stack((lon_grid.ravel(), lat_grid.ravel()))
    return _geom_to_path(geom).contains_points(points, radius=1e-9).reshape(
        lat_grid.shape
    )


def _format_lon(value, _position) -> str:
    suffix = "E" if value >= 0 else "W"
    return f"{abs(value):.0f}°{suffix}"


def _format_lat(value, _position) -> str:
    suffix = "N" if value >= 0 else "S"
    return f"{abs(value):.0f}°{suffix}"


def _initialized_label(source_label: str) -> str:
    matches = dict.fromkeys(
        re.findall(r"gfs@(\d{4}-\d{2}-\d{2}T\d{2}Z)\+f\d+", source_label)
    )
    if not matches:
        return "unknown"
    labels = []
    for value in matches:
        run = datetime.strptime(value, "%Y-%m-%dT%HZ")
        labels.append(run.strftime("%d %b %Y %HZ").upper())
    return ", ".join(labels)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _smooth_axis(values: np.ndarray, axis: int) -> np.ndarray:
    before = [(0, 0)] * values.ndim
    before[axis] = (1, 1)
    padded = np.pad(values, before, mode="edge")
    return (
        np.take(padded, range(0, values.shape[axis]), axis=axis)
        + 2.0 * np.take(padded, range(1, values.shape[axis] + 1), axis=axis)
        + np.take(padded, range(2, values.shape[axis] + 2), axis=axis)
    ) / 4.0


def display_quality(probability, passes: int = DISPLAY_SMOOTH_PASSES) -> np.ndarray:
    """Display-only, nan-aware smoothing for the local PNG product."""
    raw = np.asarray(probability, dtype=float)
    finite = np.isfinite(raw)
    values = np.where(finite, raw, 0.0)
    weights = finite.astype(float)
    for _ in range(max(0, int(passes))):
        values = _smooth_axis(_smooth_axis(values, 0), 1)
        weights = _smooth_axis(_smooth_axis(weights, 0), 1)
    smoothed = np.divide(
        values,
        weights,
        out=np.full_like(raw, np.nan, dtype=float),
        where=weights > 0,
    )
    return np.clip(smoothed, 0.0, 1.0)


def plot_sunsetwx_product(
    field: NationalField,
    target_date: date,
    context: MapContext,
    *,
    generated_at: datetime | None = None,
    figure: Figure | None = None,
) -> Figure:
    """Build one complete, opaque SunsetWx-style scientific forecast figure."""
    generated = _utc(generated_at or datetime.now(timezone.utc))
    fig = figure or Figure(figsize=(14, 10.8), facecolor="white")
    FigureCanvasAgg(fig)
    fig.patch.set_alpha(1.0)

    ax = fig.add_axes([0.045, 0.14, 0.875, 0.66])
    ax.set_facecolor("white")
    ax.set_xlim(float(field.lons[0]), float(field.lons[-1]))
    ax.set_ylim(float(field.lats[0]), float(field.lats[-1]))
    ax.set_aspect("equal", adjustable="box")
    ax.xaxis.set_major_formatter(FuncFormatter(_format_lon))
    ax.yaxis.set_major_formatter(FuncFormatter(_format_lat))
    ax.set_xticks(np.arange(np.ceil(field.lons[0] / 10) * 10, field.lons[-1] + 1, 10))
    ax.set_yticks(np.arange(np.ceil(field.lats[0] / 5) * 5, field.lats[-1] + 1, 5))
    ax.tick_params(labelsize=9)
    ax.grid(color="#8d8d8d", linewidth=0.35, alpha=0.35, zorder=1)

    for geometry in context.surrounding:
        _draw_polygon_boundary(ax, geometry, color="#777777", linewidth=0.45)

    probability = np.ma.masked_invalid(display_quality(field.probability))
    image = ax.imshow(
        probability,
        extent=(
            float(field.lons[0]),
            float(field.lons[-1]),
            float(field.lats[0]),
            float(field.lats[-1]),
        ),
        origin="lower",
        cmap=_QUALITY_CMAP,
        vmin=0.0,
        vmax=1.0,
        interpolation="bilinear",
        zorder=2,
    )
    country_path = PathPatch(
        _geom_to_path(context.country),
        transform=ax.transData,
        facecolor="none",
        edgecolor="none",
    )
    ax.add_patch(country_path)
    image.set_clip_path(country_path)
    _draw_admin_lines(ax, context.admin1)
    _draw_polygon_boundary(ax, context.country, color="#151515", linewidth=1.0)

    colorbar = fig.colorbar(
        image,
        ax=ax,
        orientation="vertical",
        fraction=0.026,
        pad=0.012,
        ticks=np.linspace(0.0, 1.0, 6),
    )
    colorbar.ax.tick_params(labelsize=8)
    colorbar.set_label("Sunset quality index", fontsize=9)

    # The caption reflects the true per-cell sunset window, not the (wider)
    # snapped GFS hourly bracket in field.valid_times.
    sunset_start, sunset_end = field.sunset_range_utc
    valid_label = f"{sunset_start:%H:%M}–{sunset_end:%H:%M} UTC"
    fig.text(
        0.045,
        0.91,
        "Sunset Quality — China GFS 0.25°",
        ha="left",
        va="center",
        fontsize=19,
        color="#101010",
    )
    fig.text(
        0.955,
        0.91,
        "Warmer Colors = Better Sunset | firecloud-forecast",
        ha="right",
        va="center",
        fontsize=10,
        color="#202020",
    )
    fig.text(
        0.045,
        0.865,
        f"Initialized: {_initialized_label(field.source_label)}  →  "
        f"Per-cell Sunset Valid: {target_date:%d %b %Y} | {valid_label}",
        ha="left",
        va="center",
        fontsize=10,
        color="#202020",
    )
    fig.text(
        0.045,
        0.07,
        f"{field.n_points:,} grid cells · gate × modifier algorithm · "
        f"generated {generated.isoformat()}",
        ha="left",
        va="center",
        fontsize=8,
        color="#555555",
    )
    return fig


def _metadata(
    field: NationalField,
    target_date: date,
    image_name: str,
    generated_at: datetime,
) -> dict:
    probability = np.asarray(field.probability, dtype=float)
    finite = probability[np.isfinite(probability)]
    # An all-NaN grid would make nanmin/nanmax return NaN, which json.dumps emits
    # as a bare `NaN` token (invalid JSON). Fall back to null instead.
    prob_min = float(finite.min()) if finite.size else None
    prob_max = float(finite.max()) if finite.size else None
    return {
        "schema_version": PRODUCT_SCHEMA_VERSION,
        "product": "china_sunset_quality",
        "target_date": target_date.isoformat(),
        "generated_utc": _utc(generated_at).isoformat(),
        "image": image_name,
        "model": "GFS 0.25 degree",
        "source_label": field.source_label,
        "valid_times_utc": [value.isoformat() for value in field.valid_times],
        "sunset_range_utc": [value.isoformat() for value in field.sunset_range_utc],
        "n_points": field.n_points,
        "probability_range": {"min": prob_min, "max": prob_max},
        "performance": {
            "surface_fetches": field.surface_fetches,
            "additional_surface_fetches": field.additional_surface_fetches,
            "download_bytes": field.download_bytes,
            "additional_download_bytes": field.additional_download_bytes,
            "decoded_input_bytes": field.decoded_input_bytes,
            "additional_decoded_input_bytes": field.additional_decoded_input_bytes,
            "runtime_s": field.runtime_s,
            "peak_mem_mb": field.peak_mem_mb,
        },
    }


def save_product(
    field: NationalField,
    target_date: date,
    output_dir: str | Path,
    context: MapContext,
    *,
    generated_at: datetime | None = None,
    dpi: int = 160,
) -> ProductArtifacts:
    """Atomically write the canonical PNG and its JSON sidecar."""
    if dpi <= 0:
        raise ValueError("dpi must be positive")
    generated = _utc(generated_at or datetime.now(timezone.utc))
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stem = f"firecloud-cn-{target_date:%Y%m%d}"
    image_path = directory / f"{stem}.png"
    metadata_path = directory / f"{stem}.json"

    figure = plot_sunsetwx_product(
        field,
        target_date,
        context,
        generated_at=generated,
    )
    image_tmp = directory / f".{stem}.png.tmp"
    figure.savefig(image_tmp, format="png", dpi=dpi, facecolor="white")
    image_tmp.replace(image_path)
    figure.clear()

    metadata = _metadata(field, target_date, image_path.name, generated)
    metadata_tmp = directory / f".{stem}.json.tmp"
    metadata_tmp.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    metadata_tmp.replace(metadata_path)
    return ProductArtifacts(image_path=image_path, metadata_path=metadata_path)


def _intersects(bounds, bbox) -> bool:
    min_x, min_y, max_x, max_y = bounds
    south, west, north, east = bbox
    return not (max_x < west or min_x > east or max_y < south or min_y > north)


def load_map_context() -> MapContext:
    """Load Natural Earth context plus detailed China province geometry."""
    import cartopy.io.shapereader as shpreader
    countries_path = shpreader.natural_earth(
        resolution="110m", category="cultural", name="admin_0_countries"
    )
    country = None
    surrounding: list[object] = []
    for record in shpreader.Reader(countries_path).records():
        geometry = record.geometry
        if not _intersects(geometry.bounds, CN_BBOX):
            continue
        attributes = record.attributes
        name = attributes.get("NAME") or attributes.get("ADMIN")
        if name == "China":
            country = geometry
        else:
            surrounding.append(geometry)
    if country is None:
        raise ValueError("China geometry not found in Natural Earth")

    provinces_path = shpreader.natural_earth(
        resolution="10m",
        category="cultural",
        name="admin_1_states_provinces_lakes",
    )
    provinces: list[object] = []
    for record in shpreader.Reader(provinces_path).records():
        attributes = record.attributes
        code = attributes.get("adm0_a3") or attributes.get("ADM0_A3")
        if code == "CHN":
            provinces.append(record.geometry)
    return MapContext(
        country=country,
        surrounding=tuple(surrounding),
        admin1=tuple(province.boundary for province in provinces),
    )


def generate_product(
    target_date: date,
    output_dir: str | Path = "products",
    *,
    dpi: int = 160,
    source=None,
) -> ProductArtifacts:
    """Fetch, score, render and save one local China sunset product."""
    context = load_map_context()
    south, west, north, east = CN_BBOX
    field = build_national_field(
        source or GFSSource(),
        (south, north, west, east),
        target_date,
        domain_mask=lambda lats, lons: geometry_mask(context.country, lats, lons),
    )
    return save_product(field, target_date, output_dir, context, dpi=dpi)


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must be YYYY-MM-DD") from exc


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate one local SunsetWx-style China forecast PNG + JSON."
    )
    parser.add_argument("--date", required=True, type=_parse_date, help="YYYY-MM-DD")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("products"),
        help="artifact directory (default: products)",
    )
    parser.add_argument("--dpi", type=_positive_int, default=160)
    args = parser.parse_args(argv)

    artifacts = generate_product(args.date, args.output_dir, dpi=args.dpi)
    print(f"image    : {artifacts.image_path}")
    print(f"metadata : {artifacts.metadata_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
