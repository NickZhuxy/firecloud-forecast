"""Render the bounded, synthetic color guide without requesting any weather."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np


DIRECTORY = Path(__file__).resolve().parent
CASE_IDS = ("01-score-bands", "02-isolated-peak", "03-nearby-patch", "04-zero-and-missing")
BANNER = "Synthetic example"


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
    """Draw one literal illustration with the shared production raw-cell style."""
    return _load_layout().render_case(case, data["lats"], data["lons"], data["center"])


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
