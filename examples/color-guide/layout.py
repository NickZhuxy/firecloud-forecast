"""Compact, offline illustrations of the forecast map's numeric color scale."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.colors import to_rgb
from matplotlib.patches import Rectangle
from matplotlib.ticker import FuncFormatter

from predictor.map_style import FONT_FAMILY, INDEX_CMAP, NO_DATA_COLOR, raw_grid_mesh
from predictor.national_product import DISPLAY_INDEX_BOUNDS

_TEXT = "#29252a"
_MUTED = "#77716e"
_LINE = "#e3ded8"
_BANNER = "Synthetic examples"
_SAMPLES = (0.10, 0.30, 0.45, 0.60, 0.78, 0.93)
_INTERVALS = (
    "[0.00, 0.20)", "[0.20, 0.40)", "[0.40, 0.50)",
    "[0.50, 0.70)", "[0.70, 0.85)", "[0.85, 1.00]",
)


def _text(fig, x, y, value, *, size=10, weight="normal", color=_TEXT,
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
                             facecolor=color, edgecolor="none"))


def _rule(fig, y, *, left=.055, right=.945):
    _swatch(fig, left, y, right - left, .001, _LINE)


def _contrast(color):
    red, green, blue = to_rgb(color)
    luminance = .2126 * red + .7152 * green + .0722 * blue
    return "white" if luminance < .52 else _TEXT


def render_color_reference(output_path):
    """Show exact intervals and distinguish valid zero from missing data."""
    fig = Figure(figsize=(13.2, 4.1), facecolor="white")
    FigureCanvasAgg(fig)
    _text(fig, .055, .915, "Condition index · color scale", size=16, weight="semibold")
    _text(fig, .945, .918, _BANNER, size=9, color=_MUTED, ha="right")
    _text(fig, .055, .847, "A higher score moves from ivory to amber, orange, red and burgundy.",
          size=10, color=_MUTED)
    left, width, gap, bottom, height = .055, .14, .012, .53, .22
    for index, (sample, interval) in enumerate(zip(_SAMPLES, _INTERVALS)):
        x = left + index * (width + gap)
        _swatch(fig, x, bottom, width, height, INDEX_CMAP(index))
        _text(fig, x + width / 2, bottom + height / 2, f"{sample:.2f}",
              size=16, weight="semibold", ha="center", color=_contrast(INDEX_CMAP(index)))
        _text(fig, x + width / 2, .477, interval, size=9, ha="center")
    _text(fig, .055, .412, "Example scores above. Exact intervals below. Equal swatch widths are for comparison.",
          size=8.5, color=_MUTED)
    _rule(fig, .361)

    _text(fig, .055, .302, "Same shade, different scores", size=10, weight="semibold")
    for x, value in ((.055, "0.51"), (.115, "0.69")):
        _swatch(fig, x, .184, .053, .085, INDEX_CMAP(3))
        _text(fig, x + .0265, .2265, value, size=9, ha="center", color=_contrast(INDEX_CMAP(3)))
    _text(fig, .187, .227, "Both in [0.50, 0.70).", size=9, color=_MUTED)

    _text(fig, .44, .302, "Valid zero", size=10, weight="semibold")
    _swatch(fig, .44, .184, .053, .085, INDEX_CMAP(0))
    _text(fig, .4665, .2265, "0.00", size=9, ha="center")
    _text(fig, .506, .227, "A computed score.", size=9, color=_MUTED)

    _text(fig, .715, .302, "Missing data", size=10, weight="semibold")
    _swatch(fig, .715, .184, .053, .085, NO_DATA_COLOR)
    _text(fig, .781, .227, "No usable score.", size=9, color=_MUTED)
    _text(fig, .055, .067, "Colors encode score intervals; they do not predict sky colors. The index is uncalibrated.",
          size=8.5, color=_MUTED)
    _text(fig, .945, .067, "[ includes · ) excludes", size=8.5, color=_MUTED, ha="right")
    return _save(fig, output_path)


def _annotations(case):
    if "annotations" in case:
        return case["annotations"]
    return [(item["row"], item["column"], item["label"])
            for item in case.get("callouts", ())]


def _selected(case, lats, lons, center):
    j = int(np.argmin(abs(np.asarray(lats, dtype=float) - center[0])))
    i = int(np.argmin(abs(np.asarray(lons, dtype=float) - center[1])))
    value = float(np.asarray(case["values"], dtype=float)[j, i])
    return j, i, f"{value:.2f}" if np.isfinite(value) else "No data"


def _grid(fig, case, lats, lons, center, bounds, *, latitude_labels=True, label_size=8):
    latitudes, longitudes = np.asarray(lats, dtype=float), np.asarray(lons, dtype=float)
    values = np.ma.masked_invalid(np.ma.array(case["values"], dtype=float, copy=True))
    ax = fig.add_axes(bounds)
    mesh, lat_edges, lon_edges = raw_grid_mesh(
        ax, SimpleNamespace(lats=latitudes, lons=longitudes, probability=values), DISPLAY_INDEX_BOUNDS)
    ax.set_xlim(lon_edges[0], lon_edges[-1])
    ax.set_ylim(lat_edges[0], lat_edges[-1])
    ax.set_aspect(1 / max(float(np.cos(np.deg2rad(center[0]))), 1e-6), adjustable="box")
    ax.set_xticks(longitudes[[0, -1]])
    ax.set_yticks(latitudes[[0, -1]])
    ax.xaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{abs(value):.2f}°W"))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:.2f}°N"))
    ax.tick_params(labelsize=label_size, length=0, pad=6, labelcolor=_MUTED,
                   labelleft=latitude_labels)
    for label in (*ax.get_xticklabels(), *ax.get_yticklabels()):
        label.set_fontfamily(FONT_FAMILY)
    for spine in ax.spines.values():
        spine.set_color(_LINE)
        spine.set_linewidth(.6)
    ax.plot(center[1], center[0], "+", color="white", markersize=10,
            markeredgewidth=3.5, zorder=6)
    ax.plot(center[1], center[0], "+", color=_TEXT, markersize=10,
            markeredgewidth=1.5, zorder=7)
    center_j, center_i, _ = _selected(case, lats, lons, center)
    for j, i, label in _annotations(case):
        if j == center_j and i == center_i:
            continue
        if label == "No data":
            # A small dash identifies the gray cell. The shared legend supplies
            # its meaning without forcing a long label into one narrow cell.
            label = "—"
        color = NO_DATA_COLOR if np.ma.is_masked(values[j, i]) else INDEX_CMAP(mesh.norm(values[j, i]))
        # Six adjacent score bands have little horizontal room at README width.
        # Alternating baselines preserve their exact cell anchors and separate
        # the numbers without labels or decorative boxes over the map.
        offset = (0, 8 if i % 2 == 0 else -8) if len(_annotations(case)) == 6 else (0, 0)
        ax.annotate(label, (longitudes[i], latitudes[j]), xytext=offset,
                    textcoords="offset points", ha="center", va="center",
                    fontfamily=FONT_FAMILY, fontsize=label_size, color=_contrast(color), zorder=8)
    return ax, mesh


def _scale(fig, mesh, *, y=.088, height=.018, left=.265, width=.45, text_size=9, tick_size=8):
    colorbar_ax = fig.add_axes([left, y, width, height])
    colorbar = fig.colorbar(mesh, cax=colorbar_ax, orientation="horizontal",
                          boundaries=DISPLAY_INDEX_BOUNDS, ticks=DISPLAY_INDEX_BOUNDS,
                          spacing="proportional")
    colorbar.outline.set_visible(False)
    colorbar.ax.tick_params(labelsize=tick_size, length=0, pad=5, labelcolor=_MUTED)
    for label in colorbar.ax.get_xticklabels():
        label.set_fontfamily(FONT_FAMILY)
    _text(fig, .055, y + height / 2, "Condition index", size=text_size, weight="semibold")
    _swatch(fig, .80, y, .018, height, NO_DATA_COLOR)
    _text(fig, .827, y + height / 2, "No data", size=text_size, color=_MUTED)


def render_comparison_sheet(cases, lats, lons, center, output_path):
    """Compare four raw score grids using a compact, shared visual system."""
    if len(cases) != 4:
        raise ValueError("the comparison sheet requires exactly four cases")
    fig = Figure(figsize=(14.2, 6.9), facecolor="white")
    FigureCanvasAgg(fig)
    _text(fig, .055, .941, "Forecast map · color guide", size=19)
    _text(fig, .945, .944, _BANNER, size=9, color=_MUTED, ha="right")
    _text(fig, .055, .901, "Four patterns on the same grid. Each + marks the selected point.",
          size=12, color=_MUTED)
    _rule(fig, .865)
    mesh = None
    for index, case in enumerate(cases):
        left = .055 + index * .235
        _, _, selected = _selected(case, lats, lons, center)
        _text(fig, left, .821, f"{index + 1:02d}  {case['title']}", size=12.5, weight="semibold")
        _text(fig, left, .767, selected, size=25)
        _text(fig, left + .09, .763, "selected point", size=10.5, color=_MUTED)
        _, mesh = _grid(fig, case, lats, lons, center, [left, .229, .20, .487],
                        latitude_labels=index == 0, label_size=12)
        _text(fig, left, .165, str(case["lesson"]), size=11.5, color=_MUTED, va="top")
    _scale(fig, mesh, y=.075, height=.017, text_size=11.5, tick_size=10.5)
    _text(fig, .055, .018, "Synthetic numeric examples · raw cells · fixed 0–1 scale · uncalibrated index",
          size=10.5, color=_MUTED)
    _text(fig, .945, .018, "Colors show scores, not sky colors.", size=10.5, color=_MUTED, ha="right")
    return _save(fig, output_path)


def render_case(case, lats, lons, center):
    """Return one direct illustration, without invented forecast provenance."""
    fig = Figure(figsize=(9.5, 6.9), facecolor="white")
    FigureCanvasAgg(fig)
    _text(fig, .055, .94, f"{case['id'][:2]}  {case['title']}", size=17, weight="semibold")
    _text(fig, .945, .943, "Synthetic example", size=9, color=_MUTED, ha="right")
    _rule(fig, .888)
    _, mesh = _grid(fig, case, lats, lons, center, [.074, .211, .44, .607], label_size=10)
    _, _, selected = _selected(case, lats, lons, center)
    _text(fig, .615, .779, "Selected point", size=8.5, color=_MUTED)
    _text(fig, .615, .701, selected, size=34)
    _text(fig, .615, .559, str(case["lesson"]), size=11, color=_MUTED, va="top")
    _text(fig, .615, .355, "Manually constructed scores.\nNo weather inputs or observations.",
          size=9, color=_MUTED, va="top")
    _text(fig, .615, .268, "+ marks the selected point.", size=9, color=_MUTED)
    _scale(fig, mesh, y=.097, height=.021, left=.28, width=.43)
    _text(fig, .055, .026, "Illustrative grid · raw cells · 0.1° spacing · uncalibrated index",
          size=8.5, color=_MUTED)
    _text(fig, .945, .026, "Colors show scores, not sky colors.", size=8.5, color=_MUTED, ha="right")
    return fig
