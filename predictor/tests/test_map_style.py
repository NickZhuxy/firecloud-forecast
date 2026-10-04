"""Scientific display regressions using synthetic grids and geometry only."""
from dataclasses import replace
from datetime import date, datetime, timezone

import cartopy.crs as ccrs
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.colors import to_rgba
from matplotlib.figure import Figure
import numpy as np
import pytest
from shapely.geometry import Polygon, box

from predictor.map_style import INDEX_CMAP, NO_DATA_COLOR, raw_grid_mesh, sample_edges
from predictor.national_product import DISPLAY_INDEX_BOUNDS, MapContext, plot_sunsetwx_product
from predictor.tests.test_local_product import _field as local_field
from predictor.tests.test_national_product import _field as national_field

DATE = date(2026, 10, 4)
GENERATED = datetime(2026, 10, 4, 17, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize('values', [
    np.array([[0., 0., 0.], [0., 1., 0.], [0., 0., 0.]]),
    np.array([[1., 1., 1.], [1., 0., 1.], [1., 1., 1.]]),
    np.array([[1., 1., 1.], [1., np.nan, 1.], [1., 1., 1.]]),
])
def test_mesh_preserves_isolated_peaks_zero_troughs_and_missing(values):
    field = replace(local_field(), lats=np.array([30., 30.1, 30.2]),
                    lons=np.array([120., 120.1, 120.2]), probability=values)
    before = values.copy()
    fig = Figure()
    ax = fig.add_subplot()
    mesh, lat_edges, lon_edges = raw_grid_mesh(ax, field, DISPLAY_INDEX_BOUNDS)
    np.testing.assert_equal(np.ma.filled(mesh.get_array(), np.nan), before)
    np.testing.assert_equal(values, before)
    np.testing.assert_allclose(lat_edges, [29.95, 30.05, 30.15, 30.25])
    np.testing.assert_allclose(lon_edges, [119.95, 120.05, 120.15, 120.25])
    coordinates = mesh.get_coordinates()
    np.testing.assert_allclose(coordinates[:, 0, 1], lat_edges)
    np.testing.assert_allclose(coordinates[0, :, 0], lon_edges)


def test_explicit_mask_and_nonfinite_cells_remain_missing_without_input_mutation():
    values = np.ma.array([[0., 0.6], [np.nan, 1.]], mask=[[False, True], [False, False]])
    field = replace(local_field(), lats=np.array([30., 30.1]),
                    lons=np.array([120., 120.1]), probability=values)
    before_data, before_mask = values.data.copy(), values.mask.copy()
    mesh, _, _ = raw_grid_mesh(Figure().add_subplot(), field, DISPLAY_INDEX_BOUNDS)
    np.testing.assert_equal(mesh.get_array().mask, [[False, True], [True, False]])
    np.testing.assert_equal(values.data, before_data)
    np.testing.assert_equal(values.mask, before_mask)


@pytest.mark.parametrize('centers', [[], [np.nan], [1., 1.], [2., 1.], [[1., 2.]]])
def test_invalid_coordinates_fail_instead_of_misregistering_cells(centers):
    with pytest.raises(ValueError):
        sample_edges(centers)


def test_nonuniform_edges_and_explicit_single_sample_footprint():
    np.testing.assert_equal(sample_edges([0., 1., 3.]), [-.5, .5, 2., 4.])
    np.testing.assert_equal(sample_edges([40.], singleton_step=.4), [39.8, 40.2])
    with pytest.raises(ValueError):
        sample_edges([40.], singleton_step=0)


def test_warm_sequential_palette_has_ordered_lightness_and_distinct_opaque_no_data():
    rgb = np.array([to_rgba(color)[:3] for color in INDEX_CMAP.colors])
    linear_rgb = np.where(rgb <= .04045, rgb / 12.92, ((rgb + .055) / 1.055) ** 2.4)
    luminance = linear_rgb @ np.array([.2126, .7152, .0722])
    assert np.all(np.diff(luminance) < 0)
    assert np.all(rgb[:, 0] > rgb[:, 1])
    assert np.all(rgb[:, 0] > rgb[:, 2])
    missing = INDEX_CMAP(np.ma.masked)
    assert missing == pytest.approx(to_rgba(NO_DATA_COLOR))
    assert missing[3] == 1
    assert np.all(np.linalg.norm(np.array(missing[:3]) - rgb, axis=1) > .35)


def _canvas_pixel(fig, ax, lon, lat):
    point = ax.projection.transform_point(lon, lat, ccrs.PlateCarree())
    x, y = ax.transData.transform(point)
    pixels = np.asarray(fig.canvas.buffer_rgba())
    return pixels[pixels.shape[0] - 1 - int(round(y)), int(round(x)), :3] / 255


def test_national_projection_clips_both_valid_and_missing_cells_and_polygon_holes():
    # The interior ring deliberately has the exterior direction. The renderer
    # normalizes it before clipping, rather than filling the hole with forecast.
    country = Polygon([(80, 20), (130, 20), (130, 50), (80, 50), (80, 20)],
                      holes=[[(99, 29), (111, 29), (111, 41), (99, 41), (99, 29)]])
    values = np.ones((3, 3))
    values[1, 0] = np.nan
    field = replace(national_field(), lats=np.array([25., 35., 45.]),
                    lons=np.array([85., 105., 125.]), probability=values)
    fig = plot_sunsetwx_product(field, DATE, MapContext(country, (), ()), generated_at=GENERATED)
    ax = fig.axes[0]
    assert isinstance(ax.projection, ccrs.LambertConformal)
    fig.canvas.draw()
    np.testing.assert_allclose(_canvas_pixel(fig, ax, 105, 35), [1, 1, 1], atol=.02)
    # Sample away from the 35° gridline so antialiasing cannot obscure the
    # coverage-clipping check when the physical map size changes.
    np.testing.assert_allclose(_canvas_pixel(fig, ax, 76, 34), [1, 1, 1], atol=.02)
    np.testing.assert_allclose(_canvas_pixel(fig, ax, 84, 34), to_rgba(NO_DATA_COLOR)[:3], atol=.02)
    np.testing.assert_allclose(_canvas_pixel(fig, ax, 124, 34), to_rgba(INDEX_CMAP.colors[-1])[:3], atol=.02)
    np.testing.assert_equal(field.probability, values)
