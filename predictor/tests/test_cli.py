# predictor/tests/test_cli.py
"""Tests for the unified ``firecloud`` CLI entry (#61), offline."""
from datetime import date
from pathlib import Path

import pytest

import predictor.cli as cli_mod
from predictor.cli import PlannedProduct, build_parser, main, plan_products
from predictor.solar_event import SolarEvent


# --- argument parsing ---

def test_defaults_national_both_events_today():
    args = build_parser().parse_args([])
    assert args.event == "both"
    assert args.lat is None and args.lon is None
    assert args.date is None            # resolved to today in main()
    assert args.output == Path("output")


def test_event_choice_rejects_junk():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--event", "noon"])


# --- planning (pure) ---

def test_plan_both_events_national_only():
    plan = plan_products(date(2026, 6, 29), "both", None, None, output_base=Path("output"))
    assert len(plan) == 2
    assert {p.solar_event for p in plan} == {SolarEvent.SUNRISE, SolarEvent.SUNSET}
    assert all(p.scope == "national" for p in plan)
    assert all(p.output_dir == Path("output/2026-06-29") for p in plan)


def test_plan_single_event():
    plan = plan_products(date(2026, 6, 29), "sunset", None, None)
    assert [p.solar_event for p in plan] == [SolarEvent.SUNSET]


def test_plan_with_coords_adds_point_products():
    plan = plan_products(date(2026, 6, 29), "both", 31.2, 121.5)
    assert len(plan) == 4  # national×2 + point×2
    point = [p for p in plan if p.scope == "point"]
    assert {p.solar_event for p in point} == {SolarEvent.SUNRISE, SolarEvent.SUNSET}
    assert all(p.lat == 31.2 and p.lon == 121.5 for p in point)


# --- main orchestration (generation stubbed; offline) ---

def _fake_artifact(tmp_path, name):
    return cli_mod._national_product_mod().ProductArtifacts(
        image_path=tmp_path / f"{name}.png", metadata_path=tmp_path / f"{name}.json"
    )


def test_main_generates_one_national_product_per_event(monkeypatch, tmp_path):
    calls = []

    def fake_generate(target_date, output_dir, *, dpi, source, solar_event):
        calls.append((target_date, Path(output_dir), solar_event))
        return _fake_artifact(tmp_path, f"national-{solar_event.value}")

    monkeypatch.setattr(cli_mod, "generate_product", fake_generate)
    rc = main(["--date", "2026-06-29", "--event", "both", "--output", str(tmp_path)])

    assert rc == 0
    assert len(calls) == 2
    assert {e for _d, _o, e in calls} == {SolarEvent.SUNRISE, SolarEvent.SUNSET}
    assert all(o == tmp_path / "2026-06-29" for _d, o, _e in calls)


def test_main_requires_lat_and_lon_together():
    with pytest.raises(SystemExit):
        main(["--date", "2026-06-29", "--lat", "31.2"])  # missing --lon


def test_main_with_coords_skips_unimplemented_point_but_still_does_national(
    monkeypatch, tmp_path, capsys
):
    calls = []

    def fake_generate(target_date, output_dir, *, dpi, source, solar_event):
        calls.append(solar_event)
        return _fake_artifact(tmp_path, f"national-{solar_event.value}")

    monkeypatch.setattr(cli_mod, "generate_product", fake_generate)
    rc = main([
        "--date", "2026-06-29", "--event", "sunset",
        "--lat", "31.2", "--lon", "121.5", "--output", str(tmp_path),
    ])
    assert rc == 0
    assert calls == [SolarEvent.SUNSET]                 # national ran
    assert "point" in capsys.readouterr().out.lower()   # point noted as deferred
