"""Render the bounded, synthetic color guide without requesting any weather."""
from __future__ import annotations

import argparse
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
import sys

import matplotlib.patheffects as path_effects
import numpy as np

from predictor.local_field import LocalField
from predictor.local_product import plot_local_product
from predictor.map_style import FONT_FAMILY

DIRECTORY = Path(__file__).resolve().parent
CASE_IDS = ("01-score-bands", "02-isolated-peak", "03-nearby-patch", "04-zero-and-missing")
BANNER = "Synthetic illustration — not a forecast"
# The production renderer requires a datetime. It is not source data, and every
# date/model/generation caption is replaced before any illustration is saved.
_RENDERER_TIME = datetime(2000, 1, 1, tzinfo=timezone.utc)


def _reject_constant(value):
    raise ValueError(f"Nonstandard JSON numeric constant: {value}")


def load_fixtures(path: Path = DIRECTORY / "values.json") -> dict:
    """Read literal arrays and validate the exact, bounded illustration inputs."""
    data = json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject_constant)
    lats, lons = np.asarray(data["lats"], dtype=float), np.asarray(data["lons"], dtype=float)
    if lats.shape != (7,) or lons.shape != (7,) or not np.all(np.isfinite([lats, lons])):
        raise ValueError("Illustrations require finite 7 × 7 coordinate axes")
    if np.any(np.diff(lats) <= 0) or np.any(np.diff(lons) <= 0):
        raise ValueError("Illustration coordinates must be ascending")
    if not (np.allclose(np.diff(lats), .1, rtol=0, atol=1e-10)
            and np.allclose(np.diff(lons), .1, rtol=0, atol=1e-10)):
        raise ValueError("The fixed illustrations use 0.1° coordinate spacing")
    if tuple(case["id"] for case in data["cases"]) != CASE_IDS:
        raise ValueError("The color guide has exactly four fixed illustration filenames")
    if not np.allclose(data["center"], [lats[3], lons[3]], rtol=0, atol=1e-10):
        raise ValueError("The selected coordinates must be the center cell")
    for case in data["cases"]:
        values = np.asarray(case["values"], dtype=float)
        if values.shape != (7, 7):
            raise ValueError("Each illustration requires a 7 × 7 value array")
        finite = values[np.isfinite(values)]
        if np.any((finite < 0) | (finite > 1)) or np.any(np.isinf(values)):
            raise ValueError("Synthetic scores must lie in 0–1 or be null")
        if not 3 <= len(case["callouts"]) <= 6:
            raise ValueError("Each illustration has three to six exact-value callouts")
        for callout in case["callouts"]:
            row, column = callout["row"], callout["column"]
            if not (isinstance(row, int) and isinstance(column, int) and 0 <= row < 7 and 0 <= column < 7):
                raise ValueError("Callouts must identify an existing cell")
            value = values[row, column]
            expected = f"{value:.2f}" if np.isfinite(value) else "No data"
            if callout["label"] != expected:
                raise ValueError("A callout label must equal the original cell value")
            if len(callout["offset_points"]) != 2 or not np.all(np.isfinite(callout["offset_points"])):
                raise ValueError("Callout offsets must be a finite pair")
    return data


def render_case(case: dict, data: dict):
    """Use the unchanged production map, replacing only illustration captions."""
    field = LocalField(
        lats=np.asarray(data["lats"], dtype=float),
        lons=np.asarray(data["lons"], dtype=float),
        probability=np.asarray(case["values"], dtype=float),
        center=tuple(data["center"]), radius_km=35,
        valid_time=_RENDERER_TIME, source_label="synthetic numeric fixture",
    )
    fig = plot_local_product(field, _RENDERER_TIME.date(), generated_at=_RENDERER_TIME,
                             context=None, region="us-nyc")
    for text in fig.texts:
        current = text.get_text()
        if " condition index — " in current:
            text.set_text(f"{case['id'][:2]} · {case['title']}")
        elif " · event " in current:
            text.set_text("Constructed numeric field · fixed 0–1 color scale")
        elif current.startswith("Observer "):
            text.set_text(case["lesson"])
        elif current.startswith("GFS "):
            text.set_text("Source: manually constructed values · no weather inputs or observations")
        elif "evaluated cells" in current:
            lat, lon = data["center"]
            text.set_text(f"Illustrative coordinates {lat:.4f}°N, {abs(lon):.4f}°W · "
                          "49 fixture cells · 0.1° spacing · raw values")
        elif current.startswith("Uncalibrated diagnostic"):
            text.set_text("Index colors are display bins. They do not represent predicted sky colors.")
    fig.text(.075, .992, BANNER, va="top", fontsize=10, fontweight="bold",
             fontfamily=FONT_FAMILY, color="#263849",
             bbox={"facecolor": "#edf2f7", "edgecolor": "#b8c4cf", "pad": 4})
    ax = fig.axes[0]
    halo = [path_effects.withStroke(linewidth=3, foreground="white")]
    for callout in case["callouts"]:
        row, column = callout["row"], callout["column"]
        point = (field.lons[column], field.lats[row])
        offset = callout["offset_points"]
        arrow = ({"arrowstyle": "-", "color": "#333333", "linewidth": .8,
                  "path_effects": halo} if any(offset) else None)
        ax.annotate(callout["label"], xy=point, xytext=offset,
                    textcoords="offset points", ha="center", va="center",
                    fontsize=8.5, fontfamily=FONT_FAMILY, color="#111111",
                    path_effects=halo, arrowprops=arrow, zorder=10)
    return fig


def _load_layout():
    spec = importlib.util.spec_from_file_location("firecloud_color_guide_layout", DIRECTORY / "layout.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("Color-guide layout module is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def generate(output: str | Path = DIRECTORY) -> list[Path]:
    """Write only the six named gallery assets in the selected output folder."""
    data = load_fixtures()
    layout = _load_layout()
    directory = Path(output)
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for case in data["cases"]:
        fig = render_case(case, data)
        path = directory / f"{case['id']}.png"
        fig.savefig(path, dpi=140, facecolor="white")
        fig.clear()
        paths.append(path)
    reference = directory / "color-reference.png"
    comparison = directory / "comparison-sheet.png"
    layout.render_color_reference(reference)
    cases = [{**case, "values": np.asarray(case["values"], dtype=float),
              "annotations": [(item["row"], item["column"], item["label"])
                              for item in case["callouts"]]} for case in data["cases"]]
    layout.render_comparison_sheet(cases, data["lats"], data["lons"], data["center"], comparison)
    return [*paths, reference, comparison]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DIRECTORY,
                        help="Output folder; default rewrites only the six named gallery PNGs")
    args = parser.parse_args(argv)
    for path in generate(args.output):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
