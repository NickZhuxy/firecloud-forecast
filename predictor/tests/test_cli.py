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


def test_long_alias_parses_as_lon():
    args = build_parser().parse_args(["--lat", "31.5", "--long", "121.5"])
    assert args.lat == 31.5
    assert args.lon == 121.5


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

    def fake_generate(target_date, output_dir, *, dpi, source, solar_event, refine,
                      satellite):
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


def test_main_with_coords_generates_both_national_and_local(monkeypatch, tmp_path):
    national, local = [], []

    def fake_generate(target_date, output_dir, *, dpi, source, solar_event, refine,
                      satellite):
        national.append(solar_event)
        return _fake_artifact(tmp_path, f"national-{solar_event.value}")

    def fake_local(target_date, output_dir, lat, lon, *, dpi, solar_event,
                   radius_km, resolution_deg, satellite):
        local.append((lat, lon, solar_event, radius_km, resolution_deg))
        return _fake_artifact(tmp_path, f"point-{lat}_{lon}-{solar_event.value}")

    monkeypatch.setattr(cli_mod, "generate_product", fake_generate)
    monkeypatch.setattr(cli_mod, "generate_local_product", fake_local)
    rc = main([
        "--date", "2026-06-29", "--event", "sunset",
        "--lat", "31.2", "--lon", "121.5", "--output", str(tmp_path),
        "--radius", "120", "--resolution", "0.2",
    ])
    assert rc == 0
    assert national == [SolarEvent.SUNSET]                          # national ran
    assert local == [(31.2, 121.5, SolarEvent.SUNSET, 120.0, 0.2)]  # local ran with flags


def test_no_refine_flag_propagates(monkeypatch, tmp_path):
    seen = []

    def fake_generate(target_date, output_dir, *, dpi, source, solar_event, refine,
                      satellite):
        seen.append(refine)
        return _fake_artifact(tmp_path, f"national-{solar_event.value}")

    monkeypatch.setattr(cli_mod, "generate_product", fake_generate)
    main(["--date", "2026-06-29", "--event", "sunset", "--output", str(tmp_path)])
    main(["--date", "2026-06-29", "--event", "sunset", "--output", str(tmp_path),
          "--no-refine"])

    assert seen == [True, False]


def test_no_satellite_flag_propagates_to_both_products(monkeypatch, tmp_path):
    seen = {"national": [], "local": []}

    def fake_generate(target_date, output_dir, *, dpi, source, solar_event, refine,
                      satellite):
        seen["national"].append(satellite)
        return _fake_artifact(tmp_path, f"national-{solar_event.value}")

    def fake_local(target_date, output_dir, lat, lon, *, dpi, solar_event,
                   radius_km, resolution_deg, satellite):
        seen["local"].append(satellite)
        return _fake_artifact(tmp_path, f"point-{solar_event.value}")

    monkeypatch.setattr(cli_mod, "generate_product", fake_generate)
    monkeypatch.setattr(cli_mod, "generate_local_product", fake_local)
    base = ["--date", "2026-06-29", "--event", "sunset", "--output", str(tmp_path),
            "--lat", "31.2", "--lon", "121.5"]
    main(base)
    main(base + ["--no-satellite"])

    assert seen["national"] == [True, False]
    assert seen["local"] == [True, False]


# ---------------------------------------------------------------------------
# #106 Story A+C: stage progress framing + humanized errors (offline)
# ---------------------------------------------------------------------------

from predictor.gfs import GFSUnavailable


def _ok_generate(tmp_path):
    def fake(target_date, output_dir, *, dpi, source, solar_event, refine, satellite):
        return _fake_artifact(tmp_path, f"national-{solar_event.value}")
    return fake


def test_main_prints_plan_header_and_per_product_frame(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli_mod, "generate_product", _ok_generate(tmp_path))
    rc = main(["--date", "2026-06-29", "--event", "both", "--output", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "计划" in out and "2" in out          # plan header names the product count
    assert "缓存" in out                          # cold/warm cache label present
    assert "[1/2]" in out and "[2/2]" in out       # per-product frame
    assert "总结" in out and "2/2" in out          # run summary


def test_main_humanizes_gfs_unavailable_and_continues(monkeypatch, tmp_path, capsys):
    seen = []

    def flaky(target_date, output_dir, *, dpi, source, solar_event, refine, satellite):
        seen.append(solar_event)
        if solar_event is SolarEvent.SUNRISE:
            raise GFSUnavailable("no usable GFS cycle after fallbacks")
        return _fake_artifact(tmp_path, "national-sunset")

    monkeypatch.setattr(cli_mod, "generate_product", flaky)
    rc = main(["--date", "2026-06-29", "--event", "both", "--output", str(tmp_path)])
    out = capsys.readouterr().out
    # The sunset product still ran despite the sunrise failure (no all-or-nothing).
    assert len(seen) == 2
    assert "✗" in out
    assert "稍后重跑" in out and "--no-refine" in out   # actionable Chinese advice
    assert "1/2" in out                                 # summary flags the partial result
    assert rc != 0                                      # a requested product failed


def test_main_unexpected_error_is_reassuring_not_bare_traceback(monkeypatch, tmp_path, capsys):
    def boom(target_date, output_dir, *, dpi, source, solar_event, refine, satellite):
        raise RuntimeError("matplotlib exploded at layer 7")

    monkeypatch.setattr(cli_mod, "generate_product", boom)
    rc = main(["--date", "2026-06-29", "--event", "sunset", "--output", str(tmp_path)])
    out = capsys.readouterr().out
    assert "不是你的操作" in out                 # reassuring, human framing
    assert "Traceback" not in out               # no scary stack dump by default
    assert "matplotlib exploded" not in out     # raw exception text hidden
    assert rc != 0


def test_main_verbose_reveals_technical_detail(monkeypatch, tmp_path, capsys):
    def boom(target_date, output_dir, *, dpi, source, solar_event, refine, satellite):
        raise RuntimeError("matplotlib exploded at layer 7")

    monkeypatch.setattr(cli_mod, "generate_product", boom)
    main(["--date", "2026-06-29", "--event", "sunset", "--output", str(tmp_path),
          "--verbose"])
    combined = capsys.readouterr()
    text = combined.out + combined.err
    assert "matplotlib exploded" in text        # detail surfaced on demand


def test_cache_is_cold_when_no_pressure_subset(tmp_path):
    from predictor.cli import _cache_is_cold

    root = tmp_path / "gfs"
    assert _cache_is_cold(date(2026, 6, 29), cache_root=root) is True
    dated = root / "pressure" / "gfs" / "20260629"
    dated.mkdir(parents=True)
    (dated / "subset_abc__gfs.t00z.pgrb2.0p25.f019").write_bytes(b"\0" * 10)
    assert _cache_is_cold(date(2026, 6, 29), cache_root=root) is False
