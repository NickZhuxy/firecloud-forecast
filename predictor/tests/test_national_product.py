"""Offline SunsetWx-style national product tests (#45)."""
import argparse
from datetime import date, datetime, timezone
import json

import matplotlib.image as mpimg
from matplotlib.figure import Figure
from matplotlib.path import Path as MplPath
import numpy as np
import pytest
from shapely.geometry import box, LineString, MultiLineString, Point

import predictor.national_product as product_mod
from predictor.national_field import NationalField
from predictor.national_product import (
    DISPLAY_EDGE_FADE_WIDTH,
    DISPLAY_PROBABILITY_THRESHOLD,
    DISPLAY_UPSAMPLE_FACTOR,
    MapContext,
    display_candidate_alpha,
    display_candidates,
    display_quality,
    plot_sunsetwx_product,
    save_product,
    upsample_display_quality,
)


# Minimal stubs for testing _geom_to_path with degenerate polygon rings without
# relying on shapely's ring-validity enforcement.
class _RingStub:
    def __init__(self, coords):
        self.coords = coords


class _PolyStub:
    geom_type = "Polygon"

    def __init__(self, exterior_coords, hole_coords=()):
        self.exterior = _RingStub(exterior_coords)
        self.interiors = [_RingStub(c) for c in hole_coords]

_DATE = date(2026, 6, 24)
_GENERATED = datetime(2026, 6, 24, 5, 30, tzinfo=timezone.utc)


def _field() -> NationalField:
    lats = np.array([17.0, 35.5, 54.0])
    lons = np.array([73.0, 94.0, 115.0, 136.0])
    probability = np.array([
        [0.05, 0.20, 0.45, 0.70],
        [0.10, 0.35, 0.65, 0.90],
        [0.00, 0.25, 0.55, 1.00],
    ])
    valid_times = tuple(
        datetime(2026, 6, 24, hour, tzinfo=timezone.utc)
        for hour in range(10, 16)
    )
    return NationalField(
        lats=lats,
        lons=lons,
        probability=probability,
        valid_times=valid_times,
        sunset_range_utc=(
            datetime(2026, 6, 24, 10, 53, tzinfo=timezone.utc),
            datetime(2026, 6, 24, 14, 36, tzinfo=timezone.utc),
        ),
        source_label=" | ".join(
            f"gfs@2026-06-24T00Z+f{hour:02d}" for hour in range(10, 16)
        ),
        n_points=12,
        surface_fetches=6,
        additional_surface_fetches=5,
        decoded_input_bytes=9_066_576,
        additional_decoded_input_bytes=7_555_480,
        download_bytes=35_191_577,
        additional_download_bytes=29_289_438,
        runtime_s=141.642,
        peak_mem_mb=234.048,
    )


def _context() -> MapContext:
    return MapContext(
        country=box(73.0, 17.0, 136.0, 54.0),
        surrounding=(),
        admin1=(),
    )


def test_plot_is_complete_sunsetwx_scientific_product():
    fig = plot_sunsetwx_product(
        _field(), _DATE, _context(), generated_at=_GENERATED
    )

    text = " ".join(item.get_text() for item in fig.texts)
    assert "Firecloud Potential" in text
    assert "GFS 0.25" in text
    assert "Initialized" in text
    # Caption shows the true per-cell sunset range (sunset_range_utc), not the
    # wider snapped GFS hourly bracket (valid_times 10:00–15:00).
    assert "10:53–14:36 UTC" in text
    assert "Orange/Red" in text
    assert len(fig.axes) == 2  # map + vertical colorbar
    assert fig.get_facecolor()[-1] == 1.0


def test_save_product_writes_png_and_metadata(tmp_path):
    artifacts = save_product(
        _field(),
        _DATE,
        tmp_path,
        _context(),
        generated_at=_GENERATED,
        dpi=80,
    )

    assert artifacts.image_path.name == "firecloud-cn-20260624.png"
    assert artifacts.metadata_path.name == "firecloud-cn-20260624.json"
    assert artifacts.image_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    image = mpimg.imread(artifacts.image_path)
    assert image.shape[0] >= 600 and image.shape[1] >= 800
    assert image.shape[-1] == 4
    assert np.allclose(image[..., 3], 1.0)  # complete opaque product, not overlay

    metadata = json.loads(artifacts.metadata_path.read_text())
    assert metadata["schema_version"] == "v2"
    assert metadata["product"] == "china_firecloud_potential"
    assert metadata["target_date"] == "2026-06-24"
    assert metadata["generated_utc"] == "2026-06-24T05:30:00+00:00"
    assert metadata["image"] == artifacts.image_path.name
    assert metadata["valid_times_utc"][0] == "2026-06-24T10:00:00+00:00"
    assert metadata["valid_times_utc"][-1] == "2026-06-24T15:00:00+00:00"
    assert metadata["source_label"].startswith("gfs@2026-06-24T00Z")
    assert metadata["n_points"] == 12
    assert metadata["probability_range"] == {"min": 0.0, "max": 1.0}
    assert metadata["performance"]["download_bytes"] == 35_191_577
    assert metadata["display"] == {
        "probability_threshold": DISPLAY_PROBABILITY_THRESHOLD,
        "edge_fade_width": DISPLAY_EDGE_FADE_WIDTH,
        "colormap": "firecloud_orange_red",
        "basemap": "white",
        "boundary_resolution": "Natural Earth 10m",
        "upsample_factor": DISPLAY_UPSAMPLE_FACTOR,
    }


def test_metadata_all_nan_probability_serializes_as_null():
    import dataclasses

    nan_probability = np.full_like(_field().probability, np.nan)
    field = dataclasses.replace(_field(), probability=nan_probability)
    meta = product_mod._metadata(
        field, date(2026, 6, 24), "x.png", datetime(2026, 6, 24, tzinfo=timezone.utc)
    )
    assert meta["probability_range"] == {"min": None, "max": None}
    # Strict JSON rejects bare NaN tokens; this must not raise.
    json.dumps(meta, allow_nan=False)


def test_cli_parses_local_generation_request(monkeypatch, tmp_path, capsys):
    calls = []

    def fake_generate(target_date, output_dir, *, dpi):
        calls.append((target_date, output_dir, dpi))
        return product_mod.ProductArtifacts(
            image_path=tmp_path / "forecast.png",
            metadata_path=tmp_path / "forecast.json",
        )

    monkeypatch.setattr(product_mod, "generate_product", fake_generate)

    result = product_mod.main([
        "--date", "2026-06-24",
        "--output-dir", str(tmp_path),
        "--dpi", "120",
    ])

    assert result == 0
    assert calls == [(_DATE, tmp_path, 120)]
    output = capsys.readouterr().out
    assert "forecast.png" in output and "forecast.json" in output


def test_generate_product_reuses_national_field_with_converted_bbox_and_mask(
    monkeypatch, tmp_path
):
    context = MapContext(
        country=box(80.0, 20.0, 120.0, 50.0),
        surrounding=(),
        admin1=(),
    )
    source = object()
    calls = {}
    built_field = _field()
    expected = product_mod.ProductArtifacts(
        image_path=tmp_path / "forecast.png",
        metadata_path=tmp_path / "forecast.json",
    )

    def fake_build(received_source, bbox, target_date, *, domain_mask):
        calls["build"] = (received_source, bbox, target_date)
        mask = domain_mask(
            np.array([17.0, 35.0, 54.0]),
            np.array([73.0, 100.0, 136.0]),
        )
        assert mask.tolist() == [
            [False, False, False],
            [False, True, False],
            [False, False, False],
        ]
        return built_field

    def fake_save(field, target_date, output_dir, received_context, *, dpi):
        calls["save"] = (field, target_date, output_dir, received_context, dpi)
        return expected

    monkeypatch.setattr(product_mod, "load_map_context", lambda: context)
    monkeypatch.setattr(product_mod, "build_national_field", fake_build)
    monkeypatch.setattr(product_mod, "save_product", fake_save)

    result = product_mod.generate_product(_DATE, tmp_path, dpi=120, source=source)

    assert result == expected
    assert calls["build"] == (source, (17.0, 54.0, 73.0, 136.0), _DATE)
    assert calls["save"][0] is built_field
    assert calls["save"][1:] == (_DATE, tmp_path, context, 120)


def test_geometry_mask_uses_precise_polygon_holes():
    from shapely.geometry import Polygon

    polygon = Polygon(
        [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0)],
        holes=[[(1.0, 1.0), (3.0, 1.0), (3.0, 3.0), (1.0, 3.0)]],
    )

    mask = product_mod.geometry_mask(
        polygon,
        np.array([0.5, 2.0, 3.5]),
        np.array([0.5, 2.0, 3.5]),
    )

    assert mask.tolist() == [
        [True, True, True],
        [True, False, True],
        [True, True, True],
    ]


def test_load_map_context_requests_10m_country_and_province_shapes(monkeypatch):
    import cartopy.io.shapereader as shpreader

    calls = []

    class _Record:
        def __init__(self, geometry, attributes):
            self.geometry = geometry
            self.attributes = attributes

    class _Reader:
        def __init__(self, path):
            self.path = path

        def records(self):
            if self.path == "countries":
                return [
                    _Record(box(73.0, 17.0, 136.0, 54.0), {"NAME": "China"}),
                    _Record(box(130.0, 20.0, 140.0, 30.0), {"NAME": "Neighbor"}),
                ]
            return [
                _Record(box(80.0, 20.0, 90.0, 30.0), {"adm0_a3": "CHN"}),
                _Record(box(80.0, 20.0, 90.0, 30.0), {"adm0_a3": "MNG"}),
            ]

    def fake_natural_earth(*, resolution, category, name):
        calls.append((resolution, category, name))
        if name == "admin_0_countries":
            return "countries"
        if name == "admin_1_states_provinces_lakes":
            return "provinces"
        raise AssertionError(name)

    monkeypatch.setattr(shpreader, "natural_earth", fake_natural_earth)
    monkeypatch.setattr(shpreader, "Reader", _Reader)

    context = product_mod.load_map_context()

    assert calls == [
        ("10m", "cultural", "admin_0_countries"),
        ("10m", "cultural", "admin_1_states_provinces_lakes"),
    ]
    assert context.country.bounds == (73.0, 17.0, 136.0, 54.0)
    assert len(context.surrounding) == 1
    assert len(context.admin1) == 1


def test_cli_help_does_not_generate(monkeypatch):
    monkeypatch.setattr(
        product_mod,
        "generate_product",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected")),
    )

    with pytest.raises(SystemExit) as exc:
        product_mod.main(["--help"])

    assert exc.value.code == 0


# ---------------------------------------------------------------------------
# _geom_to_path edge cases (lines 61, 67)
# ---------------------------------------------------------------------------

def test_geom_to_path_skips_degenerate_interior_ring():
    # line 61: interior ring with < 3 points triggers `continue`; valid exterior
    # means the path is still built successfully.
    poly = _PolyStub(
        [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)],  # 4 pts: valid exterior
        hole_coords=[[(0.5, 0.5), (0.6, 0.5)]],  # 2 pts: degenerate → skipped
    )
    path = product_mod._geom_to_path(poly)
    assert isinstance(path, MplPath)
    # Only exterior ring contributes vertices (4 pts); degenerate interior skipped.
    assert len(path.vertices) == 4


def test_geom_to_path_raises_on_all_degenerate_rings():
    # line 67: every ring is degenerate → no vertices accumulated → ValueError
    poly = _PolyStub([(0.0, 0.0), (1.0, 0.0)])  # 2 pts: degenerate exterior
    with pytest.raises(ValueError, match="no polygon rings"):
        product_mod._geom_to_path(poly)


# ---------------------------------------------------------------------------
# _draw_polygon_boundary non-polygon early return (line 73)
# ---------------------------------------------------------------------------

def test_draw_polygon_boundary_ignores_non_polygon_geometry():
    # line 73: returns immediately for a non-Polygon/MultiPolygon shape
    fig = Figure()
    ax = fig.add_subplot(111)
    product_mod._draw_polygon_boundary(ax, Point(0, 0), color="red", linewidth=1.0)
    assert len(ax.patches) == 0


# ---------------------------------------------------------------------------
# _line_parts generator (lines 87-91)
# ---------------------------------------------------------------------------

def test_line_parts_yields_linestring_directly():
    # lines 87-88: a LineString is yielded as-is
    ls = LineString([(0, 0), (1, 1), (2, 0)])
    parts = list(product_mod._line_parts(ls))
    assert parts == [ls]


def test_line_parts_recurses_into_multilinestring():
    # lines 89-91: a MultiLineString recurses and yields each child LineString
    mls = MultiLineString([[(0, 0), (1, 1)], [(2, 2), (3, 3)]])
    parts = list(product_mod._line_parts(mls))
    assert len(parts) == 2
    assert all(p.geom_type == "LineString" for p in parts)


# ---------------------------------------------------------------------------
# _draw_admin_lines body (lines 96-99)
# ---------------------------------------------------------------------------

def test_draw_admin_lines_plots_each_line_segment():
    # lines 96-99: inner loop body executes when a non-empty LineString is present
    fig = Figure()
    ax = fig.add_subplot(111)
    ls = LineString([(73, 17), (100, 35), (136, 54)])
    product_mod._draw_admin_lines(ax, (ls,))
    assert len(ax.lines) == 1


# ---------------------------------------------------------------------------
# _initialized_label no-match branch (line 133)
# ---------------------------------------------------------------------------

def test_initialized_label_returns_unknown_for_unrecognized_source():
    # line 133: source label with no GFS pattern → "unknown"
    assert product_mod._initialized_label("HRRR 2026-06-24 00Z") == "unknown"
    assert product_mod._initialized_label("") == "unknown"


# ---------------------------------------------------------------------------
# _utc naive-datetime branch (line 143)
# ---------------------------------------------------------------------------

def test_utc_converts_naive_datetime_to_utc():
    # line 143: naive datetime gets UTC tzinfo attached before conversion
    naive = datetime(2026, 6, 24, 12, 0)
    result = product_mod._utc(naive)
    assert result.tzinfo is not None
    assert result.utcoffset().total_seconds() == 0
    assert result.hour == 12


# ---------------------------------------------------------------------------
# plot_sunsetwx_product surrounding loop body (line 174)
# ---------------------------------------------------------------------------

def test_plot_sunsetwx_product_draws_surrounding_geometries():
    # line 174: loop body executes when context.surrounding is non-empty;
    # a surrounding polygon should add a patch (clipped to data coords)
    ctx = MapContext(
        country=box(73.0, 17.0, 136.0, 54.0),
        surrounding=(box(40.0, 17.0, 73.0, 54.0),),
        admin1=(),
    )
    fig = plot_sunsetwx_product(_field(), _DATE, ctx, generated_at=_GENERATED)
    assert len(fig.axes) == 2  # map + colorbar axes still present


# ---------------------------------------------------------------------------
# save_product dpi validation (line 305)
# ---------------------------------------------------------------------------

def test_save_product_rejects_non_positive_dpi(tmp_path):
    # line 305: dpi ≤ 0 must raise ValueError before any I/O
    with pytest.raises(ValueError, match="dpi must be positive"):
        save_product(_field(), _DATE, tmp_path, _context(), dpi=0)
    with pytest.raises(ValueError, match="dpi must be positive"):
        save_product(_field(), _DATE, tmp_path, _context(), dpi=-1)


# ---------------------------------------------------------------------------
# _intersects pure function (lines 335-337)
# ---------------------------------------------------------------------------

def test_intersects_detects_overlap_and_disjoint():
    # lines 335-337: pure geometric intersection check
    cn_bbox = (17.0, 73.0, 54.0, 136.0)  # south, west, north, east
    # Bounds that overlap China's bounding box
    assert product_mod._intersects((70, 15, 140, 55), cn_bbox)
    # Bounds entirely west of China (max_x < west)
    assert not product_mod._intersects((0, 0, 10, 20), cn_bbox)


# ---------------------------------------------------------------------------
# CLI helper error branches (lines 401-402, 408)
# ---------------------------------------------------------------------------

def test_parse_date_rejects_non_iso_string():
    # lines 401-402: invalid date string → ArgumentTypeError with hint
    with pytest.raises(argparse.ArgumentTypeError, match="YYYY-MM-DD"):
        product_mod._parse_date("24-June-2026")
    with pytest.raises(argparse.ArgumentTypeError, match="YYYY-MM-DD"):
        product_mod._parse_date("not-a-date")


def test_positive_int_rejects_non_positive():
    # line 408: zero and negative values → ArgumentTypeError
    with pytest.raises(argparse.ArgumentTypeError, match="positive"):
        product_mod._positive_int("0")
    with pytest.raises(argparse.ArgumentTypeError, match="positive"):
        product_mod._positive_int("-3")


# ---------------------------------------------------------------------------
# Smooth SunsetWx-style colour field
# ---------------------------------------------------------------------------

def test_quality_colormap_uses_firecloud_orange_red_ramp():
    cmap = product_mod._QUALITY_CMAP
    assert cmap.name == "firecloud_orange_red"
    assert cmap.N >= 256

    for value in np.linspace(0.0, 1.0, 5):
        red, green, blue, alpha = np.asarray(cmap(value))
        assert alpha == 1.0
        assert red >= green >= blue
        assert red > blue


def test_display_candidates_hides_non_firecloud_probability():
    raw = np.array([
        [0.00, DISPLAY_PROBABILITY_THRESHOLD - 0.01, DISPLAY_PROBABILITY_THRESHOLD],
        [DISPLAY_PROBABILITY_THRESHOLD + 0.01, 0.80, np.nan],
    ])

    candidates = display_candidates(raw, passes=0, upscale=1)

    assert np.ma.is_masked(candidates)
    assert candidates.mask.tolist() == [
        [True, True, False],
        [False, False, True],
    ]
    assert candidates[0, 2] == pytest.approx(DISPLAY_PROBABILITY_THRESHOLD)


def test_display_candidate_alpha_is_solid_inside_with_narrow_soft_edge():
    raw = np.ma.masked_array(
        np.array([
            [DISPLAY_PROBABILITY_THRESHOLD, DISPLAY_PROBABILITY_THRESHOLD + DISPLAY_EDGE_FADE_WIDTH / 2],
            [DISPLAY_PROBABILITY_THRESHOLD + DISPLAY_EDGE_FADE_WIDTH, 0.90],
        ]),
        mask=[[False, False], [False, True]],
    )

    alpha = display_candidate_alpha(raw)

    assert alpha[0, 0] == pytest.approx(0.0)
    assert 0.0 < alpha[0, 1] < 0.96
    assert alpha[1, 0] == pytest.approx(0.96)
    assert alpha[1, 1] == pytest.approx(0.0)


def test_display_quality_upsamples_for_smooth_rendering():
    raw = np.array([[0.0, 1.0], [1.0, 0.0]])

    upsampled = upsample_display_quality(raw, factor=4)

    assert upsampled.shape == (5, 5)
    assert upsampled[0, 0] == pytest.approx(0.0)
    assert upsampled[0, -1] == pytest.approx(1.0)
    assert upsampled[-1, 0] == pytest.approx(1.0)
    assert upsampled[-1, -1] == pytest.approx(0.0)
    assert upsampled[2, 2] == pytest.approx(0.5)


def test_display_quality_smooths_visual_noise_without_changing_shape_or_range():
    raw = np.zeros((5, 5), dtype=float)
    raw[2, 2] = 1.0
    smoothed = display_quality(raw)
    assert smoothed.shape == raw.shape
    assert np.all((smoothed >= 0.0) & (smoothed <= 1.0))
    assert 0.0 < smoothed[2, 2] < 1.0
    assert smoothed[2, 1] > 0.0


def test_display_quality_ignores_nan_without_filling_all_nan_cells():
    raw = np.array([[np.nan, 1.0], [0.0, 0.0]])
    smoothed = display_quality(raw, passes=1)
    assert np.isfinite(smoothed[0, 0])
    assert smoothed[0, 0] > 0.0

    all_nan = display_quality(np.full((2, 2), np.nan), passes=1)
    assert np.isnan(all_nan).all()


def test_plot_uses_one_continuous_raster_not_discrete_contour_bands():
    fig = plot_sunsetwx_product(
        _field(), _DATE, _context(), generated_at=_GENERATED
    )
    ax = fig.axes[0]
    assert len(ax.images) == 1
    image = ax.images[0]
    assert image.get_array().shape[0] > _field().probability.shape[0]
    assert image.get_array().shape[1] > _field().probability.shape[1]
    assert image.get_interpolation() == "bicubic"
    assert image.get_clim() == (DISPLAY_PROBABILITY_THRESHOLD, 1.0)
    assert image.cmap.name == "firecloud_orange_red"
    alpha = np.asarray(image.get_alpha())
    assert alpha.shape == image.get_array().shape
    assert float(np.nanmax(alpha)) <= 0.96
