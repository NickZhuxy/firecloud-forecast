"""Draw a numeric color reference and a clearly synthetic comparison sheet.

These figures teach the production map's visual encoding. They do not call
weather providers or estimate forecast performance.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle
from matplotlib.ticker import FuncFormatter

from predictor.map_style import FONT_FAMILY, INDEX_CMAP, NO_DATA_COLOR, raw_grid_mesh
from predictor.national_product import DISPLAY_INDEX_BOUNDS


_TEXT = "#222222"
_MUTED = "#505862"
_LINE = "#c9cdd2"
_BANNER = "Synthetic illustration — not a forecast"
_SAMPLES = (0.10, 0.30, 0.45, 0.60, 0.78, 0.93)
_INTERVALS = (
    "[0.00, 0.20)", "[0.20, 0.40)", "[0.40, 0.50)",
    "[0.50, 0.70)", "[0.70, 0.85)", "[0.85, 1.00]",
)


def _text(fig, x, y, value, *, size=11, weight="normal", color=_TEXT,
          ha="left", va="center"):
    return fig.text(x, y, value, fontsize=size, fontweight=weight,
                    fontfamily=FONT_FAMILY, color=color, ha=ha, va=va)


def _save(fig, output_path):
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(destination, dpi=150, facecolor="white")
    fig.clear()
    return destination


def _swatch(fig, x, y, width, height, color):
    fig.add_artist(Rectangle((x, y), width, height, transform=fig.transFigure,
                             facecolor=color, edgecolor="#6a737c", linewidth=0.6))


def render_color_reference(output_path):
    """Explain all six production colors, their numeric intervals, and missing data."""
    fig = Figure(figsize=(10.5, 7.4), facecolor="white")
    FigureCanvasAgg(fig)
    _text(fig, .07, .955, _BANNER, size=11, weight="semibold")
    _text(fig, .07, .892, "Read the condition-index colors", size=24, weight="semibold")
    _text(fig, .07, .837, "Darker blue means a higher index. Gray means no score.", size=13)

    left, width, gap, bottom, height = .07, .125, .018, .625, .145
    for index, (sample, interval) in enumerate(zip(_SAMPLES, _INTERVALS)):
        x = left + index * (width + gap)
        color = INDEX_CMAP(index)
        _swatch(fig, x, bottom, width, height, color)
        _text(fig, x + width / 2, bottom + height / 2, f"{sample:.2f}",
              size=20, weight="semibold", ha="center",
              color="white" if index >= 4 else _TEXT)
        _text(fig, x + width / 2, .596, interval, size=11, ha="center")
    _text(fig, .07, .548,
          "Numbers inside the swatches are examples. Swatch widths do not represent interval widths.",
          size=10, color=_MUTED)

    _text(fig, .07, .477, "One color, different values", size=15,
          weight="semibold")
    _swatch(fig, .07, .358, .08, .074, INDEX_CMAP(3))
    _text(fig, .17, .405, "0.51 and 0.69 share this color", size=12)
    _text(fig, .17, .370, "Both values are in [0.50, 0.70).", size=10, color=_MUTED)

    _text(fig, .57, .477, "Zero and missing are different", size=15, weight="semibold")
    _swatch(fig, .57, .358, .074, .074, INDEX_CMAP(0))
    _text(fig, .663, .405, "0.00", size=12, weight="semibold")
    _text(fig, .663, .370, "A valid computed value", size=10, color=_MUTED)
    _swatch(fig, .57, .249, .074, .074, NO_DATA_COLOR)
    _text(fig, .663, .297, "No data", size=12, weight="semibold")
    _text(fig, .663, .262, "No usable score for this cell", size=10, color=_MUTED)

    _text(fig, .07, .266, "The boundaries are display choices.", size=11)
    _text(fig, .07, .231, "They are not validated forecast categories.", size=11)
    fig.add_artist(Rectangle((.07, .184), .86, .001, transform=fig.transFigure,
                             facecolor=_LINE, edgecolor="none"))
    _text(fig, .07, .143, "The colors show score intervals, not cloud heights or predicted sky colors.", size=11)
    _text(fig, .07, .100, "The condition index is an uncalibrated diagnostic, not an occurrence probability.",
          size=10, color=_MUTED)
    _text(fig, .07, .048, "Interval notation: [ includes the boundary; ) excludes it. 1.00 belongs to the final interval.",
          size=9.5, color=_MUTED)
    return _save(fig, output_path)


def _annotations(case):
    if "annotations" in case:
        return case["annotations"]
    return [(value["row"], value["column"], value["label"])
            for value in case.get("callouts", ())]


def render_comparison_sheet(cases, lats, lons, center, output_path):
    """Compare four constructed grids with one shared, fixed production scale."""
    if len(cases) != 4:
        raise ValueError("the comparison sheet requires exactly four cases")
    latitudes, longitudes = np.asarray(lats, dtype=float), np.asarray(lons, dtype=float)
    clat, clon = map(float, center)
    center_j = int(np.argmin(abs(latitudes - clat)))
    center_i = int(np.argmin(abs(longitudes - clon)))
    aspect = 1.0 / max(float(np.cos(np.deg2rad(clat))), 1e-6)
    fig = Figure(figsize=(9.8, 12.6), facecolor="white")
    FigureCanvasAgg(fig)
    _text(fig, .07, .982, _BANNER, size=11, weight="semibold")
    _text(fig, .07, .946, "One scale, four different patterns", size=23, weight="semibold")
    _text(fig, .07, .914, "The same color always means the same numeric interval.", size=12)

    mesh = None
    for index, case in enumerate(cases):
        column, row = index % 2, index // 2
        left = .07 + column * .49
        title_y = .876 - row * .392
        values = np.ma.masked_invalid(np.ma.array(case["values"], dtype=float, copy=True))
        selected = float(np.ma.filled(values, np.nan)[center_j, center_i])
        selected_label = f"{selected:.2f}" if np.isfinite(selected) else "No data"
        title = str(case["title"])
        # Case titles share one leading edge and one small type scale.
        _text(fig, left, title_y, f"{index + 1:02d}  {title}", size=14, weight="semibold")
        _text(fig, left, title_y - .026, f"Selected location: {selected_label}", size=11)
        ax = fig.add_axes([left, .55 - row * .392, .37, .282])
        field = SimpleNamespace(lats=latitudes, lons=longitudes, probability=values)
        mesh, lat_edges, lon_edges = raw_grid_mesh(ax, field, DISPLAY_INDEX_BOUNDS)
        ax.set_xlim(lon_edges[0], lon_edges[-1])
        ax.set_ylim(lat_edges[0], lat_edges[-1])
        ax.set_aspect(aspect, adjustable="box")
        ax.set_xticks(longitudes[[0, len(longitudes) // 2, -1]])
        ax.set_yticks(latitudes[[0, len(latitudes) // 2, -1]])
        ax.xaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{abs(value):.2f}°W"))
        ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:.2f}°N"))
        ax.tick_params(labelsize=8.5, length=3)
        for label in (*ax.get_xticklabels(), *ax.get_yticklabels()):
            label.set_fontfamily(FONT_FAMILY)
        ax.plot(clon, clat, "+", color="white", markersize=14, markeredgewidth=3.5, zorder=6)
        ax.plot(clon, clat, "+", color=_TEXT, markersize=14, markeredgewidth=1.5, zorder=7)
        for j, i, label in _annotations(case):
            if j == center_j and i == center_i:
                continue
            # The longer missing-data label needs a different baseline from
            # neighboring numeric labels; its anchor remains the original cell.
            offset = (0, 12) if label == "No data" else (0, 0)
            ax.annotate(label, (longitudes[i], latitudes[j]), xytext=offset,
                        textcoords="offset points", ha="center", va="center",
                        fontfamily=FONT_FAMILY, fontsize=9, color=_TEXT, zorder=8,
                        bbox={"facecolor": "white", "edgecolor": "none", "pad": 1.5, "alpha": .95})
        _text(fig, left, .527 - row * .392, str(case["lesson"]), size=10,
              color=_MUTED, va="top")

    colorbar_ax = fig.add_axes([.21, .067, .50, .019])
    colorbar = fig.colorbar(mesh, cax=colorbar_ax, orientation="horizontal",
                          boundaries=DISPLAY_INDEX_BOUNDS, ticks=DISPLAY_INDEX_BOUNDS,
                          spacing="proportional")
    colorbar.ax.tick_params(labelsize=8.5, length=3)
    for label in colorbar.ax.get_xticklabels():
        label.set_fontfamily(FONT_FAMILY)
    _swatch(fig, .78, .067, .024, .019, NO_DATA_COLOR)
    _text(fig, .814, .0765, "No data", size=10)
    _text(fig, .46, .033, "Condition index (0–1) · + selected location", size=10, ha="center")
    _text(fig, .07, .012, "Constructed scores only. No weather data. The index is not a calibrated probability.",
          size=9, color=_MUTED)
    return _save(fig, output_path)
