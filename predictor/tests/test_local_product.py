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
    plot_local_product,
    save_local_product,
)
from predictor.national_product import (
    DISPLAY_FIELD_ALPHA,
    DISPLAY_INDEX_BOUNDS,
    SCIENTIFIC_FONT_FAMILY,
    MapContext,
)
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
    assert any("sunrise" in t.get_text().lower() for t in fig.texts)
    # The generated timestamp is drawn (caption parity with the national figure).
    assert any("generated 2026-06-29" in t.get_text() for t in fig.texts)
    assert any("UNCALIBRATED DIAGNOSTIC" in t.get_text() for t in fig.texts)


def test_local_display_uses_the_full_scientific_condition_index():
    fig = plot_local_product(
        _field(), _DATE, solar_event=SolarEvent.SUNRISE, generated_at=_GEN
    )
    image = fig.axes[0].images[0]
    assert image.cmap.name == "firecloud_scientific_classes"
    assert tuple(image.norm.boundaries) == DISPLAY_INDEX_BOUNDS
    assert image.get_alpha() == pytest.approx(DISPLAY_FIELD_ALPHA)
    assert image.get_array().count() == image.get_array().size


def test_plot_local_product_draws_map_context_and_center():
    fig = plot_local_product(
        _low_field(), _DATE, solar_event=SolarEvent.SUNRISE,
        generated_at=_GEN, context=_context(),
    )
    ax = fig.axes[0]
    assert len(ax.patches) >= 2  # land/context polygons under the forecast layer
    assert len(ax.lines) >= 3    # admin line + crosshair halo + crosshair
    assert ax.get_facecolor()[:3] == pytest.approx((1.0, 1.0, 1.0))
    assert next(line for line in ax.lines if line.get_zorder() == 5)


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
    assert md["condition_index"]["calibrated_probability"] is False
    assert md["condition_index"]["favorable_threshold"] == 0.5
    assert md["display"]["class_bounds"] == list(DISPLAY_INDEX_BOUNDS)
    assert md["display"]["font_family"] == SCIENTIFIC_FONT_FAMILY


def test_save_local_product_sunrise_filename(tmp_path):
    art = save_local_product(
        _field(), _DATE, tmp_path, solar_event=SolarEvent.SUNRISE, generated_at=_GEN, dpi=70,
    )
    assert art.image_path.name == "point-30_120-sunrise.png"


def test_local_metadata_serializes_missing_center_index_as_null():
    import dataclasses
    import predictor.local_product as mod

    field = _field()
    probability = field.probability.copy()
    probability[2, 2] = np.nan
    metadata = mod._metadata(
        dataclasses.replace(field, probability=probability),
        _DATE,
        "point.png",
        _GEN,
        SolarEvent.SUNSET,
    )

    assert metadata["condition_index"]["center_value"] is None
    json.dumps(metadata, allow_nan=False)


# ---- Stage C: satellite nowcast wiring (#84) ----


def _nowcast_result(prob, applied=True):
    from predictor.cloud_motion import MotionVector
    from predictor.nowcast import NowcastStageResult

    mask = np.zeros_like(prob, dtype=bool)
    corrected = prob.copy()
    if applied:
        mask[0, 0] = True
        corrected[0, 0] = 0.99
    return NowcastStageResult(
        corrected_probability=corrected,
        corrected_mask=mask,
        motion=MotionVector(1.5, 0.0, 1.5, "advective", 0.8, "steady", 2),
        applied=applied,
        source="satellite" if applied else "model",
        reason="bounded advective correction" if applied else "no cells in window",
        lead_hr_range=(0.2, 0.2),
    )


def test_generate_local_product_applies_nowcast(monkeypatch, tmp_path):
    import predictor.local_product as mod

    built = _field()
    monkeypatch.setattr(mod, "build_local_field", lambda *a, **k: built)
    monkeypatch.setattr(mod, "load_map_context", lambda: None)
    saved = {}

    def fake_save(field, *a, **k):
        saved["field"] = field
        return mod.ProductArtifacts(image_path=tmp_path / "x.png",
                                    metadata_path=tmp_path / "x.json")

    monkeypatch.setattr(mod, "save_local_product", fake_save)
    monkeypatch.setattr(
        mod, "apply_nowcast",
        lambda prob, lats, lons, times, src, *, now, config=None: _nowcast_result(prob),
    )

    mod.generate_local_product(
        date(2026, 6, 29), tmp_path, 30.0, 120.0,
        source=object(), cube_source=object(), predictor=object(),
        satellite=True, satellite_source=object(),
    )

    field = saved["field"]
    assert field.nowcast is not None and field.nowcast["applied"] is True
    assert field.probability[0, 0] == 0.99


def test_generate_local_product_satellite_off_skips(monkeypatch, tmp_path):
    import predictor.local_product as mod

    built = _field()
    monkeypatch.setattr(mod, "build_local_field", lambda *a, **k: built)
    monkeypatch.setattr(mod, "load_map_context", lambda: None)
    monkeypatch.setattr(
        mod, "save_local_product",
        lambda field, *a, **k: mod.ProductArtifacts(
            image_path=tmp_path / "x.png", metadata_path=tmp_path / "x.json"),
    )

    def boom(*a, **k):
        raise AssertionError("apply_nowcast must not be called")

    monkeypatch.setattr(mod, "apply_nowcast", boom)
    mod.generate_local_product(
        date(2026, 6, 29), tmp_path, 30.0, 120.0,
        source=object(), cube_source=object(), predictor=object(),
        satellite=False,
    )


def test_local_metadata_and_caption_carry_nowcast():
    from dataclasses import replace

    import predictor.local_product as mod

    block = {
        "applied": True, "source": "satellite", "reason": "bounded",
        "regime": "advective", "confidence": 0.8,
        "motion_deg_per_hr": [1.5, 0.0], "cells_corrected": 3,
        "mean_abs_delta": 0.02, "lead_hr_range": [0.2, 0.2],
        "physics_probability_range": {"min": 0.0, "max": 1.0},
    }
    field = replace(_field(), nowcast=block)

    meta = mod._metadata(field, date(2026, 6, 29), "x.png", _VALID, "sunset")
    assert meta["nowcast"] == block

    fig = mod.plot_local_product(field, date(2026, 6, 29), solar_event="sunset",
                                 generated_at=_VALID, context=None)
    assert any("satellite-nudged" in t.get_text() for t in fig.texts)
