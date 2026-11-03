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
    # This is the recorded product timestamp, not the PNG write completion time.
    assert any("product timestamp 2026-06-29" in t.get_text() for t in fig.texts)
    assert any("Uncalibrated diagnostic" in t.get_text() for t in fig.texts)


def test_local_display_uses_the_full_scientific_condition_index():
    fig = plot_local_product(
        _field(), _DATE, solar_event=SolarEvent.SUNRISE, generated_at=_GEN
    )
    image = fig.axes[0].collections[0]
    assert image.cmap.name == "firecloud_index_warm"
    assert tuple(image.norm.boundaries) == DISPLAY_INDEX_BOUNDS
    assert image.get_alpha() == pytest.approx(1.0)
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
    assert _format_local_lon(-74.006, None) == "74.0°W"
    assert _format_local_lat(-31.5, None) == "31.5°S"


@pytest.mark.parametrize("span, precision", [(0.4, 2), (2.0, 1)])
def test_local_axis_precision_keeps_small_area_ticks_distinct(span, precision):
    import dataclasses

    field = _field((40.7128, -74.006))
    field = dataclasses.replace(
        field,
        lats=np.linspace(field.center[0] - span / 2, field.center[0] + span / 2, 5),
        lons=np.linspace(field.center[1] - span / 2, field.center[1] + span / 2, 5),
    )
    ax = plot_local_product(field, _DATE, region="us-nyc").axes[0]
    assert ax.xaxis.get_major_formatter()(-74.05, None) == f"{74.05:.{precision}f}°W"
    assert ax.yaxis.get_major_formatter()(40.75, None) == f"{40.75:.{precision}f}°N"
    for labels in (ax.get_xticklabels(), ax.get_yticklabels()):
        texts = [label.get_text() for label in labels]
        assert len(texts) == len(set(texts))


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


def test_local_product_los_angeles_uses_requested_evening(monkeypatch, tmp_path):
    from zoneinfo import ZoneInfo
    from astral import Observer
    from astral.sun import sun
    import predictor.local_product as mod

    captured = {}
    def fake_build(pred, cubes, lat, lon, event_time, **kwargs):
        captured["event_time"] = event_time
        return _field()

    monkeypatch.setattr(mod, "build_local_field", fake_build)
    monkeypatch.setattr(mod, "load_map_context", lambda: None)
    monkeypatch.setattr(mod, "save_local_product", lambda *a, **k: None)
    target_date = date(2026, 9, 14)
    mod.generate_local_product(target_date, tmp_path, 34.05, -118.24,
                               source=object(), cube_source=object(), predictor=object(),
                               satellite=False)
    expected = sun(Observer(34.05, -118.24), date=target_date,
                   tzinfo=ZoneInfo("America/Los_Angeles"))["sunset"]
    assert captured["event_time"] == expected


@pytest.mark.parametrize(
    "instant, abbreviation",
    [
        (datetime(2026, 7, 4, 0, 30, tzinfo=timezone.utc), "EDT"),
        (datetime(2026, 12, 3, 21, 30, tzinfo=timezone.utc), "EST"),
    ],
)
def test_nyc_caption_has_local_date_timezone_and_west_longitude(instant, abbreviation):
    from dataclasses import replace
    from zoneinfo import ZoneInfo

    field = replace(_field((40.7128, -74.006)), valid_time=instant)
    local = instant.astimezone(ZoneInfo("America/New_York"))
    fig = plot_local_product(field, local.date(), generated_at=instant, region="us-nyc")
    texts = [t.get_text() for t in fig.texts]
    assert any("New York City" in text for text in texts)
    assert any("40.71°N, 74.01°W" in text for text in texts)
    assert any(local.strftime("%d %b %Y %H:%M") in text and abbreviation in text for text in texts)
    assert any(instant.strftime("%d %b %H:%M UTC") in text for text in texts)
    fig.clear()


def test_nyc_metadata_separates_event_and_discrete_weather_times():
    from dataclasses import replace
    import predictor.local_product as mod

    event = datetime(2026, 10, 3, 22, 34, tzinfo=timezone.utc)
    field = replace(
        _field((40.7128, -74.006)), valid_time=event,
        source_label="gfs@2026-10-03T12Z+f11",
        provenance={"weather_snapshots": {"selected_hourly_times_utc": ["2026-10-03T23:00:00+00:00"]}},
        center_diagnostics={
            "stage": "model_before_nowcast",
            "grid_cell": {"lat": 40.7128, "lon": -74.006, "row": np.int64(2), "column": np.int64(2)},
            "components": {"sunward_illumination": np.float64(0.4)},
            "geometry": {"missing": np.nan},
        },
    )
    md = mod._metadata(field, event.date(), "nyc.png", event, "sunset", region="us-nyc")
    assert md["product"] == "us_nyc_firecloud_local"
    assert md["region"] == "us-nyc"
    assert md["timezone"] == "America/New_York"
    assert md["event_timezone_abbreviation"] == "EDT"
    assert md["event_time_local"] == "2026-10-03T18:34:00-04:00"
    assert md["valid_time_semantics"] == "requested_solar_event"
    assert md["gfs_timing"]["initialization_time_utc"] == "2026-10-03T12:00:00+00:00"
    assert md["gfs_timing"]["forecast_hour"] == 11
    assert md["gfs_timing"]["valid_time_utc"] == "2026-10-03T23:00:00+00:00"
    assert md["event_time_utc"] != md["gfs_timing"]["valid_time_utc"]
    assert md["center_diagnostics"]["stage"] == "model_before_nowcast"
    assert md["center_diagnostics"]["grid_cell"] == {"lat": 40.7128, "lon": -74.006, "row": 2, "column": 2}
    assert md["center_diagnostics"]["geometry"]["missing"] is None
    json.dumps(md, allow_nan=False)


@pytest.mark.parametrize("satellite", [True, False])
def test_nyc_generation_skips_unsupported_satellite_and_preserves_scores(monkeypatch, tmp_path, satellite):
    from dataclasses import replace
    from zoneinfo import ZoneInfo
    from astral import Observer
    from astral.sun import sun
    import predictor.local_product as mod

    built = replace(_field((40.7128, -74.006)), radius_km=25)
    captured = {}

    def fake_build(pred, cubes, lat, lon, event_time, **kwargs):
        captured["event_time"] = event_time
        return built

    def fake_context(country_code, bbox):
        captured["map_country"] = country_code
        captured["map_bbox"] = bbox
        return None

    def fake_save(field, *args, **kwargs):
        captured["field"] = field
        captured["region"] = kwargs["region"]
        return None

    def forbidden(*args, **kwargs):
        raise AssertionError("Unsupported satellite or China map IO must not run")

    monkeypatch.setattr(mod, "build_local_field", fake_build)
    monkeypatch.setattr(mod, "load_local_map_context", fake_context)
    monkeypatch.setattr(mod, "load_map_context", forbidden)
    monkeypatch.setattr(mod, "_with_nowcast", forbidden)
    monkeypatch.setattr(mod, "save_local_product", fake_save)
    mod.generate_local_product(
        date(2026, 10, 3), tmp_path, 40.7128, -74.006,
        source=object(), cube_source=object(), predictor=object(),
        satellite=satellite, satellite_source=object(), region="us-nyc",
        radius_km=25, resolution_deg=.1,
    )
    expected = sun(Observer(40.7128, -74.006), date=date(2026, 10, 3),
                   tzinfo=ZoneInfo("America/New_York"))["sunset"]
    assert captured["event_time"] == expected
    assert captured["map_country"] == "USA"
    assert captured["map_bbox"][2] < -74.006 < captured["map_bbox"][3]
    assert captured["region"] == "us-nyc"
    assert np.array_equal(captured["field"].probability, built.probability)
    assert captured["field"].nowcast["applied"] is False
    assert "unsupported satellite coverage" in captured["field"].nowcast["reason"]
    assert captured["field"].nowcast["cells_corrected"] == 0


def test_nyc_invalid_center_fails_before_product_io(monkeypatch, tmp_path):
    import predictor.local_product as mod

    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid pilot centers must fail before IO")

    monkeypatch.setattr(mod, "load_local_map_context", forbidden)
    monkeypatch.setattr(mod, "build_local_field", forbidden)
    with pytest.raises(ValueError, match="pilot centers"):
        mod.generate_local_product(date(2026, 10, 3), tmp_path, 34.05, -118.24, region="us-nyc")


def test_generation_freezes_gfs_availability_to_request_time(monkeypatch, tmp_path):
    import predictor.local_product as mod
    import predictor.gfs as gfs

    captured = {}

    def fake_cube_source(*, as_of):
        captured["as_of"] = as_of
        return object()

    monkeypatch.setattr(gfs, "GFSSource", fake_cube_source)
    monkeypatch.setattr(mod, "load_local_map_context", lambda *args: None)
    monkeypatch.setattr(mod, "build_local_field", lambda *args, **kwargs: _field((40.7128, -74.006)))
    monkeypatch.setattr(mod, "save_local_product", lambda *args, **kwargs: None)
    request = datetime(2026, 10, 3, 20, tzinfo=timezone.utc)
    mod.generate_local_product(
        date(2026, 10, 3), tmp_path, 40.7128, -74.006,
        source=object(), predictor=object(), now=request, region="us-nyc",
    )
    assert captured["as_of"] == request


def test_masked_center_is_no_data_in_label_mesh_and_strict_metadata():
    from dataclasses import replace
    import predictor.local_product as mod

    source = np.ma.array(np.ones((5, 5)), mask=np.zeros((5, 5), dtype=bool))
    source.mask[2, 2] = True
    field = replace(_field((40.7128, -74.006)), probability=source)
    fig = plot_local_product(field, _DATE, generated_at=_GEN, region="us-nyc")
    md = mod._metadata(field, _DATE, "test.png", _GEN, "sunset", region="us-nyc")
    assert any("Center index  No data" == text.get_text() for text in fig.texts)
    assert fig.axes[0].collections[0].get_array().mask[2, 2]
    assert md["condition_index"]["center_value"] is None
    assert md["condition_index"]["range"] == {"min": 1.0, "max": 1.0}
    assert md["probability_range"] == {"min": 1.0, "max": 1.0}
    json.dumps(md, allow_nan=False)
    assert source.data[2, 2] == 1.0 and source.mask[2, 2]


def test_local_geographic_aspect_is_set_after_raw_mesh_and_preserved_in_metadata():
    import predictor.local_product as mod

    field = _field((40.7128, -74.006))
    fig = plot_local_product(field, _DATE, region="us-nyc", generated_at=_GEN)
    ax = fig.axes[0]
    expected = 1 / np.cos(np.deg2rad(field.center[0]))
    assert ax.get_aspect() == pytest.approx(expected)
    np.testing.assert_allclose(ax.get_xlim(), field.lons[[0, -1]] + [-.05, .05])
    np.testing.assert_allclose(ax.get_ylim(), field.lats[[0, -1]] + [-.05, .05])
    md = mod._metadata(field, _DATE, "test.png", _GEN, "sunset", region="us-nyc")
    assert md["display"]["projection"]["aspect"] == pytest.approx(expected)
    assert md["display"]["method"] == "raw_grid_cells"
    assert md["display"]["smoothing_passes"] == 0
    assert md["display"]["upsample_factor"] == 1
    assert md["display"]["sampling"]["latitude_spacing_deg"] == pytest.approx(.1)
    assert md["condition_index"]["center_value"] == field.probability[2, 2]
    assert md["condition_index"]["range"] == {"min": 0.0, "max": 1.0}


def test_local_caption_separates_exact_event_from_model_hour_and_converts_offsets():
    from dataclasses import replace
    import predictor.local_product as mod

    event = datetime(2026, 10, 4, 22, 32, tzinfo=timezone.utc)
    field = replace(_field((40.7128, -74.006)), valid_time=event,
                    provenance={"gfs": {"valid_time_utc": "2026-10-04T19:00:00-04:00"}})
    fig = plot_local_product(field, event.date(), generated_at=_GEN, region="us-nyc")
    text = " ".join(item.get_text() for item in fig.texts)
    assert "04 Oct 2026 18:32 EDT" in text
    assert "event 04 Oct 22:32 UTC" in text
    assert "weather valid 04 Oct 23:00 UTC" in text
    assert "GFS 0.25°" in text and "0.1° evaluation spacing" in text
    assert mod._model_time_label("2026-10-04T19:00:00-04:00") == "04 Oct 23:00 UTC"


def test_saving_raw_local_grid_preserves_input_values_and_missing_mask(tmp_path):
    from dataclasses import replace

    source = np.ma.array(_field().probability.copy(), mask=np.zeros((5, 5), dtype=bool))
    source[0, 0] = np.nan
    source.mask[2, 2] = True
    before_data, before_mask = source.data.copy(), source.mask.copy()
    artifact = save_local_product(replace(_field(), probability=source), _DATE, tmp_path,
                                  generated_at=_GEN, dpi=50)
    np.testing.assert_equal(source.data, before_data)
    np.testing.assert_equal(source.mask, before_mask)
    metadata = json.loads(artifact.metadata_path.read_text())
    assert metadata["condition_index"]["center_value"] is None
    assert metadata["condition_index"]["range"] == {"min": float(source[0, 1]), "max": 1.0}


def test_compact_local_layout_keeps_missing_center_header_and_footer_inside_canvas():
    from dataclasses import replace

    field = replace(_field((40.7128, -74.006)), probability=np.full((5, 5), np.nan),
                    nowcast={"applied": True, "cells_corrected": 12345})
    fig = plot_local_product(field, _DATE, generated_at=_GEN, region="us-nyc")
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    for text in fig.texts:
        bounds = text.get_window_extent(renderer)
        assert bounds.x0 >= 0 and bounds.x1 <= fig.bbox.width
        assert bounds.y0 >= 0 and bounds.y1 <= fig.bbox.height
    center = next(text for text in fig.texts if text.get_text().startswith("Center index"))
    event = next(text for text in fig.texts if " · event " in text.get_text())
    assert not center.get_window_extent(renderer).overlaps(event.get_window_extent(renderer))
