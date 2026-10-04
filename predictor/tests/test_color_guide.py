"""The public color guide uses exact numeric fixtures and no external inputs."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import socket
import urllib.request

from matplotlib.colors import BoundaryNorm
import numpy as np
import pytest
import requests

from predictor.map_style import INDEX_CMAP
from predictor.national_product import DISPLAY_INDEX_BOUNDS

DIRECTORY = Path(__file__).resolve().parents[2] / "examples" / "color-guide"


def _generator():
    spec = importlib.util.spec_from_file_location("firecloud_color_guide_generator", DIRECTORY / "generate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _forbid_external_inputs(monkeypatch):
    import cartopy.io.shapereader as shapereader
    import predictor.local_product as local
    from predictor.fetch import OpenMeteoSource
    from predictor.gfs import GFSSource

    def forbidden(*args, **kwargs):
        raise AssertionError("A numeric illustration must not request external inputs")

    for owner, name in [(socket, "create_connection"), (urllib.request, "urlopen"),
                        (requests.Session, "request"), (shapereader, "natural_earth"),
                        (local, "build_local_field"), (local, "load_map_context"),
                        (local, "load_local_map_context"), (OpenMeteoSource, "__init__"),
                        (GFSSource, "__init__")]:
        monkeypatch.setattr(owner, name, forbidden)


def test_literal_fixtures_cover_every_band_and_preserve_selected_location_meaning():
    data = _generator().load_fixtures()
    cases = data["cases"]
    norm = BoundaryNorm(DISPLAY_INDEX_BOUNDS, INDEX_CMAP.N, clip=True)
    assert list(norm(np.array(cases[0]["values"][0][:6]))) == list(range(6))
    assert cases[0]["values"][0][:6] == [.10, .30, .45, .60, .78, .93]
    assert [case["values"][3][3] for case in cases] == [.60, 1.00, .10, .00]
    peak = np.asarray(cases[1]["values"], dtype=float)
    assert peak[3, 3] == 1
    adjacent = peak[2:5, 2:5].copy()
    adjacent[1, 1] = 0
    assert adjacent.max() == .3 and np.count_nonzero(peak == 1) == 1
    patch = np.asarray(cases[2]["values"], dtype=float)
    assert np.isnan(patch[3, 5]) and patch[3, 4] == patch[3, 6] == .90
    zeros = np.asarray(cases[3]["values"], dtype=float)
    assert np.all(zeros[:, :4] == 0) and np.isnan(zeros[:, 4:]).all()
    assert data["center"] == [40.7128, -74.006]
    np.testing.assert_allclose(np.diff(data["lats"]), .1)
    np.testing.assert_allclose(np.diff(data["lons"]), .1)
    assert "null" in (DIRECTORY / "values.json").read_text()


@pytest.mark.parametrize("case_index", range(4))
def test_individual_figures_use_original_mesh_and_remove_forecast_provenance(monkeypatch, case_index):
    _forbid_external_inputs(monkeypatch)
    generator = _generator()
    data = generator.load_fixtures()
    before = json.dumps(data, sort_keys=True, allow_nan=False)
    case = data["cases"][case_index]
    fig = generator.render_case(case, data)
    mesh = fig.axes[0].collections[0]
    original = np.asarray(case["values"], dtype=float)
    np.testing.assert_equal(np.ma.filled(mesh.get_array(), np.nan), original)
    assert tuple(mesh.norm.boundaries) == DISPLAY_INDEX_BOUNDS
    assert mesh.cmap is INDEX_CMAP
    labels = " ".join(text.get_text() for text in fig.texts)
    assert generator.BANNER in labels and "manually constructed values" in labels
    assert "no weather inputs or observations" in labels
    assert "Illustrative coordinates 40.7128°N, 74.0060°W" in labels
    for forbidden in ("2000", "UTC", "EDT", "EST", "GFS", "generated", "product timestamp"):
        assert forbidden not in labels
    for callout in case["callouts"]:
        assert any(text.get_text() == callout["label"] for text in fig.axes[0].texts)
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    for text in fig.texts:
        bounds = text.get_window_extent(renderer)
        assert 0 <= bounds.x0 <= bounds.x1 <= fig.bbox.width
        assert 0 <= bounds.y0 <= bounds.y1 <= fig.bbox.height
    center = next(text for text in fig.texts if text.get_text().startswith("Center index"))
    caption = next(text for text in fig.texts if text.get_text().startswith("Constructed numeric"))
    assert not center.get_window_extent(renderer).overlaps(caption.get_window_extent(renderer))
    assert json.dumps(data, sort_keys=True, allow_nan=False) == before


def test_regeneration_is_offline_bounded_and_does_not_rewrite_fixture_sources(monkeypatch, tmp_path):
    _forbid_external_inputs(monkeypatch)
    generator = _generator()
    sources = {path: path.read_bytes() for path in (DIRECTORY / "generate.py", DIRECTORY / "values.json")}
    unrelated = tmp_path / "keep.txt"
    unrelated.write_text("Unrelated file")
    paths = generator.generate(tmp_path)
    expected = {f"{case}.png" for case in generator.CASE_IDS} | {"color-reference.png", "comparison-sheet.png"}
    assert {path.name for path in paths} == expected
    assert {path.name for path in tmp_path.iterdir()} == expected | {"keep.txt"}
    assert all(path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n") for path in paths)
    assert unrelated.read_text() == "Unrelated file"
    assert all(path.read_bytes() == contents for path, contents in sources.items())
    # A second generation under the same installed plotting environment is
    # deterministic; no request time or provider result is inserted into PNGs.
    first = {path.name: path.read_bytes() for path in paths}
    generator.generate(tmp_path)
    assert all((tmp_path / name).read_bytes() == content for name, content in first.items())


@pytest.mark.parametrize("problem", ["nonstandard_nan", "incorrect_callout", "unsafe_filename"])
def test_bad_fixture_fails_before_an_illustration_can_misrepresent_values(problem, tmp_path):
    generator = _generator()
    data = generator.load_fixtures()
    if problem == "nonstandard_nan":
        data["cases"][0]["values"][0][0] = float("nan")
    elif problem == "incorrect_callout":
        data["cases"][0]["callouts"][0]["label"] = "0.99"
    else:
        data["cases"][0]["id"] = "../../some-other-file"
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        generator.load_fixtures(path)
