"""Offline SunsetWx-style national product tests (#45)."""
from datetime import date, datetime, timezone
import json

import matplotlib.image as mpimg
import numpy as np
import pytest
from shapely.geometry import box

import predictor.national_product as product_mod
from predictor.national_field import NationalField
from predictor.national_product import (
    MapContext,
    plot_sunsetwx_product,
    save_product,
)

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
    assert "Sunset Quality" in text
    assert "GFS 0.25" in text
    assert "Initialized" in text
    # Caption shows the true per-cell sunset range (sunset_range_utc), not the
    # wider snapped GFS hourly bracket (valid_times 10:00–15:00).
    assert "10:53–14:36 UTC" in text
    assert "Warmer Colors" in text
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
    assert metadata["schema_version"] == "v1"
    assert metadata["product"] == "china_sunset_quality"
    assert metadata["target_date"] == "2026-06-24"
    assert metadata["generated_utc"] == "2026-06-24T05:30:00+00:00"
    assert metadata["image"] == artifacts.image_path.name
    assert metadata["valid_times_utc"][0] == "2026-06-24T10:00:00+00:00"
    assert metadata["valid_times_utc"][-1] == "2026-06-24T15:00:00+00:00"
    assert metadata["source_label"].startswith("gfs@2026-06-24T00Z")
    assert metadata["n_points"] == 12
    assert metadata["probability_range"] == {"min": 0.0, "max": 1.0}
    assert metadata["performance"]["download_bytes"] == 35_191_577


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


def test_cli_help_does_not_generate(monkeypatch):
    monkeypatch.setattr(
        product_mod,
        "generate_product",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected")),
    )

    with pytest.raises(SystemExit) as exc:
        product_mod.main(["--help"])

    assert exc.value.code == 0
