# predictor/tests/test_local_product.py
"""Tests for the local fine-product renderer (#62 PR-B), offline."""
import json
from datetime import date, datetime, timezone

import numpy as np
import pytest

from predictor.local_field import LocalField
from predictor.local_product import plot_local_product, save_local_product
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


def test_plot_local_product_returns_figure_with_event_title():
    fig = plot_local_product(_field(), _DATE, solar_event=SolarEvent.SUNRISE, generated_at=_GEN)
    assert any("Sunrise" in t.get_text() for t in fig.texts)
    # The generated timestamp is drawn (caption parity with the national figure).
    assert any("Generated 2026-06-29" in t.get_text() for t in fig.texts)


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
