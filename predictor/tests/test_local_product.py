# predictor/tests/test_local_product.py
"""Tests for the local fine-product renderer (#62 PR-B), offline."""
import json
from datetime import date, datetime, timezone

import numpy as np
import pytest
from shapely.geometry import LineString, box

from predictor.local_field import LocalField
from predictor.local_product import (
    _format_local_lat,
    _format_local_lon,
    local_display_candidates,
    plot_local_product,
    save_local_product,
)
from predictor.national_product import DISPLAY_PROBABILITY_THRESHOLD, MapContext
from predictor.solar_event import SolarEvent

_DATE = date(2026, 6, 29)
_GEN = datetime(2026, 6, 29, 5, 30, tzinfo=timezone.utc)
_VALID = datetime(2026, 6, 29, 9, tzinfo=timezone.utc)


def _field(center=(30.0, 120.0)):
    lats = np.round(np.arange(center[0] - 0.2, center[0] + 0.21, 0.1), 6)
    lons = np.round(np.arange(center[1] - 0.2, center[1] + 0.21, 0.1), 6)
    prob = np.linspace(0.0, 1.0, lats.size * lons.size).reshape(lats.size, lons.size)
    return LocalField(
        lats=lats, lons=lons, probability=prob, center=center, radius_km=40.0,
        valid_time=_VALID, source_label="gfs@2026-06-29T00Z+f09",
    )


def _low_field(center=(31.5, 121.5)):
    lats = np.round(np.arange(center[0] - 0.2, center[0] + 0.21, 0.1), 6)
    lons = np.round(np.arange(center[1] - 0.2, center[1] + 0.21, 0.1), 6)
    prob = np.array([
        [0.10, 0.20, 0.30, 0.40, 0.49],
        [0.05, 0.15, 0.25, 0.35, 0.45],
        [0.00, 0.12, 0.22, 0.32, 0.42],
        [0.08, 0.18, 0.28, 0.38, 0.48],
        [0.04, 0.14, 0.24, 0.34, 0.44],
    ])
    return LocalField(
        lats=lats, lons=lons, probability=prob, center=center, radius_km=40.0,
        valid_time=_VALID, source_label="gfs@2026-06-29T00Z+f09",
    )


def _context() -> MapContext:
    return MapContext(
        country=box(121.0, 31.0, 122.0, 32.0),
        surrounding=(box(120.0, 30.0, 120.8, 32.4),),
        admin1=(LineString([(121.0, 31.5), (122.0, 31.5)]),),
    )


def test_plot_local_product_returns_figure_with_event_title():
    fig = plot_local_product(_field(), _DATE, solar_event=SolarEvent.SUNRISE, generated_at=_GEN)
    assert any("Sunrise" in t.get_text() for t in fig.texts)
    # The generated timestamp is drawn (caption parity with the national figure).
    assert any("Generated 2026-06-29" in t.get_text() for t in fig.texts)


def test_local_display_keeps_candidate_threshold_semantics():
    low = np.array([[0.0, 0.12], [0.18, 0.22]])
    quality = local_display_candidates(low)
    assert np.ma.getmaskarray(quality).all()

    fig = plot_local_product(
        _field(), _DATE, solar_event=SolarEvent.SUNRISE, generated_at=_GEN
    )
    image = fig.axes[0].images[0]
    assert image.get_clim() == (DISPLAY_PROBABILITY_THRESHOLD, 1.0)


def test_plot_local_product_draws_map_context_and_center():
    fig = plot_local_product(
        _low_field(), _DATE, solar_event=SolarEvent.SUNRISE,
        generated_at=_GEN, context=_context(),
    )
    ax = fig.axes[0]
    assert len(ax.patches) >= 2  # land/context polygons under the forecast layer
    assert len(ax.lines) >= 3    # admin line + crosshair halo + crosshair
    assert ax.get_facecolor()[2] > ax.get_facecolor()[0]  # pale blue water background


def test_local_axis_labels_show_decimal_degrees():
    assert _format_local_lon(121.5, None) == "121.5°E"
    assert _format_local_lat(31.5, None) == "31.5°N"


def test_save_local_product_names_by_coords_and_event(tmp_path):
    art = save_local_product(
        _field((31.2, 121.5)), _DATE, tmp_path, solar_event=SolarEvent.SUNSET,
        generated_at=_GEN, dpi=70,
    )
    assert art.image_path.name == "point-31.2_121.5-sunset.png"
    assert art.metadata_path.name == "point-31.2_121.5-sunset.json"
    assert art.image_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    md = json.loads(art.metadata_path.read_text())
    assert md["solar_event"] == "sunset"
    assert md["product"] == "china_firecloud_local"
    assert md["center"] == [31.2, 121.5]
    assert md["radius_km"] == 40.0
    assert "probability_range" in md


def test_save_local_product_sunrise_filename(tmp_path):
    art = save_local_product(
        _field(), _DATE, tmp_path, solar_event=SolarEvent.SUNRISE, generated_at=_GEN, dpi=70,
    )
    assert art.image_path.name == "point-30_120-sunrise.png"
