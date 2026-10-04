"""Shared presentation for faithful, unsmoothed forecast grids."""
from __future__ import annotations

import numpy as np
from matplotlib.colors import BoundaryNorm, ListedColormap
from matplotlib.patches import Rectangle

FONT_FAMILY = "STIXGeneral"
NO_DATA_COLOR = "#a8adb3"
INDEX_CMAP = ListedColormap(
    ["#f7fbff", "#dbe9f6", "#adcde5", "#6fa9d2", "#377eb8", "#084b80"],
    name="firecloud_index_blues",
)
INDEX_CMAP.set_bad(NO_DATA_COLOR, alpha=1.0)


def sample_edges(centers, *, singleton_step: float = 0.25) -> np.ndarray:
    """Return midpoint cell edges around ascending geographic sample centers."""
    values = np.asarray(centers, dtype=float)
    if values.ndim != 1 or not values.size or not np.all(np.isfinite(values)):
        raise ValueError("grid coordinates must be a nonempty finite one-dimensional array")
    if values.size == 1:
        if not np.isfinite(singleton_step) or singleton_step <= 0:
            raise ValueError("singleton grid footprint must be positive and finite")
        return values[0] + np.array([-0.5, 0.5]) * singleton_step
    if np.any(np.diff(values) <= 0):
        raise ValueError("grid coordinates must be strictly increasing")
    return np.r_[values[0] - (values[1] - values[0]) / 2,
                 (values[:-1] + values[1:]) / 2,
                 values[-1] + (values[-1] - values[-2]) / 2]


def raw_grid_mesh(ax, field, bounds, *, transform=None, singleton_steps=(0.25, 0.25)):
    """Draw source values and their validity mask without spatial interpolation."""
    lats, lons = np.asarray(field.lats), np.asarray(field.lons)
    values = np.ma.masked_invalid(np.ma.array(field.probability, dtype=float, copy=True))
    if values.shape != (lats.size, lons.size):
        raise ValueError("forecast values must match the latitude/longitude grid")
    lat_edges = sample_edges(lats, singleton_step=singleton_steps[0])
    lon_edges = sample_edges(lons, singleton_step=singleton_steps[1])
    kwargs = {"transform": transform} if transform is not None else {}
    mesh = ax.pcolormesh(
        lon_edges, lat_edges, values, cmap=INDEX_CMAP,
        norm=BoundaryNorm(bounds, INDEX_CMAP.N, clip=True),
        shading="flat", edgecolors="none", linewidth=0,
        alpha=1.0, rasterized=True, zorder=2, **kwargs,
    )
    return mesh, lat_edges, lon_edges


def horizontal_scale(fig, mesh, bounds) -> None:
    """Use one compact, shared index scale with an explicit missing-data swatch."""
    colorbar_ax = fig.add_axes([0.21, 0.15, 0.50, 0.025])
    colorbar = fig.colorbar(mesh, cax=colorbar_ax, orientation="horizontal",
                          boundaries=bounds, ticks=bounds, spacing="proportional")
    colorbar.ax.tick_params(labelsize=8, length=3)
    for label in colorbar.ax.get_xticklabels():
        label.set_fontfamily(FONT_FAMILY)
    colorbar.set_label("Condition index (0–1)",
                       fontsize=8.5, fontfamily=FONT_FAMILY, labelpad=7)
    fig.add_artist(Rectangle((0.77, 0.15), 0.021, 0.025,
                             transform=fig.transFigure, facecolor=NO_DATA_COLOR,
                             edgecolor="#72777d", linewidth=0.5))
    fig.text(0.80, 0.162, "No data", va="center", fontsize=8.5,
             fontfamily=FONT_FAMILY, color="#333333")


def sampling_text(field) -> str:
    lat_spacing = np.median(np.diff(field.lats)) if len(field.lats) > 1 else None
    lon_spacing = np.median(np.diff(field.lons)) if len(field.lons) > 1 else None
    if lat_spacing is None or lon_spacing is None:
        return "single-sample axis; footprint is a display convention"
    if np.isclose(lat_spacing, lon_spacing):
        return f"{lat_spacing:g}° evaluation spacing"
    return f"{lat_spacing:g}° lat × {lon_spacing:g}° lon evaluation spacing"


def display_metadata(field, bounds, *, projection: dict) -> dict:
    """Describe the actual render independently of legacy interpolation helpers."""
    lat_spacing = float(np.median(np.diff(field.lats))) if len(field.lats) > 1 else None
    lon_spacing = float(np.median(np.diff(field.lons))) if len(field.lons) > 1 else None
    return {
        "metric": "uncalibrated_condition_index", "method": "raw_grid_cells",
        "class_bounds": list(bounds), "class_breaks_semantics": "display_only",
        "contour_levels": [], "field_alpha": 1.0, "colormap": INDEX_CMAP.name,
        "font_family": FONT_FAMILY, "upsample_factor": 1, "smoothing_passes": 0,
        "missing_data_color": NO_DATA_COLOR, "missing_data_semantics": "original_nonfinite_or_masked_cells",
        "grid_registration": "sample_centers_with_midpoint_edges",
        "sampling": {"latitude_spacing_deg": lat_spacing, "longitude_spacing_deg": lon_spacing,
                     "changes_model_resolution": False},
        "projection": projection,
    }
