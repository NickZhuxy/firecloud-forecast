# predictor/tests/test_cli.py
"""Tests for the unified ``firecloud`` CLI entry (#61), offline."""
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

import predictor.cli as cli_mod
from predictor.cli import PlannedProduct, build_parser, main, plan_products
from predictor.remote_product import RemoteProductResult, RemoteProductUnavailable
from predictor.solar_event import SolarEvent


# --- argument parsing ---


@pytest.fixture(autouse=True)
def _remote_feed_is_offline_by_default(monkeypatch):
    original = cli_mod._fetch_remote_product

    def unavailable(*args, **kwargs):
        raise RemoteProductUnavailable("test feed offline")

    monkeypatch.setattr(cli_mod, "_fetch_remote_product", unavailable)
    return original


def test_defaults_national_both_events_today():
    args = build_parser().parse_args([])
    assert args.event == "both"
    assert args.lat is None and args.lon is None
    assert args.date is None            # resolved to today in main()
    assert args.output == Path("output")
    assert args.source == "auto"
    assert args.scope == "all"
    assert args.region == "china"


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


def test_plan_local_scope_includes_only_requested_location_and_events(tmp_path):
    plan = plan_products(
        date(2026, 6, 29), "both", 31.2, 121.5,
        output_base=tmp_path, scope="local",
    )
    assert [(p.scope, p.solar_event, p.lat, p.lon) for p in plan] == [
        ("point", SolarEvent.SUNRISE, 31.2, 121.5),
        ("point", SolarEvent.SUNSET, 31.2, 121.5),
    ]
    assert all(p.output_dir == tmp_path / "2026-06-29" for p in plan)


def test_plan_national_scope_preserves_national_plan():
    assert plan_products(date(2026, 6, 29), "both", None, None, scope="national") == (
        plan_products(date(2026, 6, 29), "both", None, None)
    )


@pytest.mark.parametrize(
    ("scope", "lat", "lon", "message"),
    [
        ("local", None, None, "requires --lat and --lon"),
        ("local", 31.2, None, "must be given together"),
        ("national", 31.2, 121.5, "does not accept coordinates"),
        ("unsupported", None, None, "scope must be"),
    ],
)
def test_plan_rejects_invalid_scope_coordinate_combinations(scope, lat, lon, message):
    with pytest.raises(ValueError, match=message):
        plan_products(date(2026, 6, 29), "sunset", lat, lon, scope=scope)


def test_nyc_plan_is_local_only_and_uses_a_region_directory(tmp_path):
    plan = plan_products(
        date(2026, 10, 4), "sunset", 40.7128, -74.0060,
        scope="local", region="us-nyc", output_base=tmp_path,
    )
    assert plan == [PlannedProduct(
        "point", SolarEvent.SUNSET, tmp_path / "us-nyc" / "2026-10-04",
        40.7128, -74.0060, "us-nyc",
    )]


@pytest.mark.parametrize("scope", ["all", "national"])
def test_nyc_plan_rejects_national_scope(scope):
    with pytest.raises(ValueError, match="only supports --scope local"):
        plan_products(
            date(2026, 10, 4), "sunset", 40.7128, -74.0060,
            scope=scope, region="us-nyc",
        )


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


@pytest.mark.parametrize("source", ["auto", "local"])
def test_main_local_scope_computes_only_local_products(
    monkeypatch, tmp_path, capsys, source
):
    local = []

    def national_should_not_run(*args, **kwargs):
        pytest.fail("location-only requests must not generate national maps")

    def fake_local(target_date, output_dir, lat, lon, **kwargs):
        local.append((lat, lon, kwargs["solar_event"], kwargs["satellite"]))
        return _fake_artifact(tmp_path, f"point-{kwargs['solar_event'].value}")

    monkeypatch.setattr(cli_mod, "generate_product", national_should_not_run)
    monkeypatch.setattr(cli_mod, "generate_local_product", fake_local)
    rc = main([
        "--date", "2026-06-29", "--scope", "local", "--event", "both",
        "--lat", "31.2", "--lon", "121.5", "--source", source,
        "--no-satellite", "--output", str(tmp_path),
    ])

    assert rc == 0
    assert local == [
        (31.2, 121.5, SolarEvent.SUNRISE, False),
        (31.2, 121.5, SolarEvent.SUNSET, False),
    ]
    out = capsys.readouterr().out
    assert "sunrise + sunset · local" in out
    assert "Summary: 2/2 products" in out
    assert "National" not in out


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (["--scope", "local"], "--scope local requires --lat and --lon"),
        (["--scope", "local", "--lat", "31.2"], "must be given together"),
        (["--scope", "national", "--lat", "31.2", "--lon", "121.5"],
         "does not accept coordinates"),
    ],
)
def test_main_validates_scope_before_data_access(monkeypatch, capsys, arguments, message):
    def should_not_run(*args, **kwargs):
        pytest.fail("invalid requests must fail before any data access")

    monkeypatch.setattr(cli_mod, "_fetch_remote_product", should_not_run)
    monkeypatch.setattr(cli_mod, "generate_product", should_not_run)
    monkeypatch.setattr(cli_mod, "generate_local_product", should_not_run)
    with pytest.raises(SystemExit) as exc:
        main(arguments)
    assert exc.value.code == 2
    assert message in capsys.readouterr().err


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
    assert "Plan" in out and "2" in out          # plan header names the product count
    assert "cache" in out                          # cold/warm cache label present
    assert "[1/2]" in out and "[2/2]" in out       # per-product frame
    assert "Summary" in out and "2/2" in out          # run summary


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
    assert "Retry later" in out and "--no-refine" in out   # actionable recovery advice
    assert "1/2" in out                                 # summary flags the partial result
    assert rc != 0                                      # a requested product failed


def test_main_unexpected_error_is_reassuring_not_bare_traceback(monkeypatch, tmp_path, capsys):
    def boom(target_date, output_dir, *, dpi, source, solar_event, refine, satellite):
        raise RuntimeError("matplotlib exploded at layer 7")

    monkeypatch.setattr(cli_mod, "generate_product", boom)
    rc = main(["--date", "2026-06-29", "--event", "sunset", "--output", str(tmp_path)])
    out = capsys.readouterr().out
    assert "Common causes include" in out         # actionable context without a traceback
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


# ---------------------------------------------------------------------------
# Remote-first national product delivery
# ---------------------------------------------------------------------------


def test_auto_source_uses_remote_without_local_generation(monkeypatch, tmp_path):
    remote = _fake_artifact(tmp_path, "remote-sunrise")
    monkeypatch.setattr(cli_mod, "_fetch_remote_product", lambda *args: remote)

    def local_should_not_run(*args, **kwargs):
        raise AssertionError("local generation should not run on a remote hit")

    monkeypatch.setattr(cli_mod, "generate_product", local_should_not_run)

    rc = main([
        "--date", "2026-06-29", "--event", "sunrise",
        "--output", str(tmp_path),
    ])

    assert rc == 0


def test_auto_source_falls_back_to_local_generation(monkeypatch, tmp_path):
    calls = []

    def fake_generate(target_date, output_dir, **kwargs):
        calls.append(kwargs["solar_event"])
        return _fake_artifact(tmp_path, "local-sunrise")

    monkeypatch.setattr(cli_mod, "generate_product", fake_generate)

    rc = main([
        "--date", "2026-06-29", "--event", "sunrise",
        "--output", str(tmp_path),
    ])

    assert rc == 0
    assert calls == [SolarEvent.SUNRISE]


def test_auto_source_uses_remote_for_published_point_product(monkeypatch, tmp_path):
    scopes = []

    def remote_hit(product, *args):
        scopes.append(product.scope)
        return _fake_artifact(tmp_path, f"remote-{product.scope}")

    monkeypatch.setattr(cli_mod, "_fetch_remote_product", remote_hit)

    def local_should_not_run(*args, **kwargs):
        raise AssertionError("local generation should not run on a remote point hit")

    monkeypatch.setattr(cli_mod, "generate_product", local_should_not_run)
    monkeypatch.setattr(cli_mod, "generate_local_product", local_should_not_run)

    rc = main([
        "--date", "2026-06-29",
        "--event", "sunset",
        "--lat", "31.23",
        "--lon", "121.47",
        "--output", str(tmp_path),
    ])

    assert rc == 0
    assert scopes == ["national", "point"]


def test_remote_only_supports_published_point_product(monkeypatch, tmp_path):
    monkeypatch.setattr(
        cli_mod,
        "_fetch_remote_product",
        lambda product, *args: _fake_artifact(tmp_path, f"remote-{product.scope}"),
    )

    def local_should_not_run(*args, **kwargs):
        raise AssertionError("remote-only mode must not run local point physics")

    monkeypatch.setattr(cli_mod, "generate_product", local_should_not_run)
    monkeypatch.setattr(cli_mod, "generate_local_product", local_should_not_run)

    rc = main([
        "--date", "2026-06-29",
        "--event", "sunset",
        "--lat", "31.23",
        "--lon", "121.47",
        "--source", "remote",
        "--output", str(tmp_path),
    ])

    assert rc == 0


@pytest.mark.parametrize("source", ["auto", "remote"])
def test_local_scope_remote_hit_requests_only_point_products(monkeypatch, tmp_path, source):
    scopes = []

    def remote_hit(product, *args):
        scopes.append(product.scope)
        return _fake_artifact(tmp_path, "remote-point")

    def should_not_compute(*args, **kwargs):
        pytest.fail("a matching remote local product must skip local computation")

    monkeypatch.setattr(cli_mod, "_fetch_remote_product", remote_hit)
    monkeypatch.setattr(cli_mod, "generate_product", should_not_compute)
    monkeypatch.setattr(cli_mod, "generate_local_product", should_not_compute)
    rc = main([
        "--scope", "local", "--date", "2026-06-29", "--event", "sunset",
        "--lat", "31.23", "--lon", "121.47", "--source", source,
        "--output", str(tmp_path),
    ])
    assert rc == 0
    assert scopes == ["point"]


def test_local_scope_remote_failure_never_computes(monkeypatch, tmp_path, capsys):
    def should_not_compute(*args, **kwargs):
        pytest.fail("remote-only mode must not compute missing local products")

    monkeypatch.setattr(cli_mod, "generate_product", should_not_compute)
    monkeypatch.setattr(cli_mod, "generate_local_product", should_not_compute)
    rc = main([
        "--scope", "local", "--date", "2026-06-29", "--event", "sunset",
        "--lat", "31.23", "--lon", "121.47", "--source", "remote",
        "--output", str(tmp_path),
    ])
    assert rc == 1
    assert "Summary: 0/1 products" in capsys.readouterr().out


def test_local_scope_data_failure_does_not_suggest_national_refinement_flag(
    monkeypatch, tmp_path, capsys
):
    def unavailable(*args, **kwargs):
        raise GFSUnavailable("no usable local cube")

    monkeypatch.setattr(cli_mod, "generate_local_product", unavailable)
    rc = main([
        "--scope", "local", "--event", "sunset", "--source", "local",
        "--lat", "31.23", "--lon", "121.47", "--output", str(tmp_path),
    ])
    assert rc == 1
    out = capsys.readouterr().out
    assert "Retry later" in out
    assert "--no-refine" not in out


@pytest.mark.parametrize("source", ["local", "auto"])
def test_nyc_cli_computes_only_local_preserving_region_and_disabling_satellite(
    monkeypatch, tmp_path, capsys, source, _remote_feed_is_offline_by_default
):
    calls = []
    monkeypatch.setattr(
        cli_mod, "_fetch_remote_product", _remote_feed_is_offline_by_default
    )

    def forbidden_source(*args, **kwargs):
        pytest.fail("the NYC pilot must not fetch China maps or the remote feed")

    def fake_local(target_date, output_dir, lat, lon, **kwargs):
        calls.append((target_date, Path(output_dir), lat, lon, kwargs))
        return _fake_artifact(tmp_path, "nyc-sunset")

    monkeypatch.setattr(cli_mod, "RemoteProductClient", forbidden_source)
    monkeypatch.setattr(cli_mod, "generate_product", forbidden_source)
    monkeypatch.setattr(cli_mod, "generate_local_product", fake_local)
    rc = main([
        "--region", "us-nyc", "--scope", "local", "--date", "2026-10-04",
        "--lat", "40.7128", "--lon", "-74.0060", "--event", "sunset",
        "--source", source, "--output", str(tmp_path), "--radius", "25",
    ])
    assert rc == 0
    assert calls == [(
        date(2026, 10, 4), tmp_path / "us-nyc" / "2026-10-04", 40.7128, -74.0060,
        {"dpi": 160, "solar_event": SolarEvent.SUNSET, "radius_km": 25.0,
         "resolution_deg": 0.1, "satellite": False, "region": "us-nyc"},
    )]
    out = capsys.readouterr().out
    assert "local · New York City" in out
    assert "Summary: 1/1 products" in out


def test_nyc_remote_only_fails_before_client_or_local_computation(
    monkeypatch, tmp_path, capsys, _remote_feed_is_offline_by_default
):
    monkeypatch.setattr(
        cli_mod, "_fetch_remote_product", _remote_feed_is_offline_by_default
    )

    def forbidden_source(*args, **kwargs):
        pytest.fail("unsupported NYC remote-only requests must not access sources")

    monkeypatch.setattr(cli_mod, "RemoteProductClient", forbidden_source)
    monkeypatch.setattr(cli_mod, "generate_product", forbidden_source)
    monkeypatch.setattr(cli_mod, "generate_local_product", forbidden_source)
    rc = main([
        "--region", "us-nyc", "--scope", "local", "--date", "2026-10-04",
        "--lat", "40.7128", "--lon", "-74.0060", "--event", "sunset",
        "--source", "remote", "--output", str(tmp_path),
    ])
    assert rc == 1
    out = capsys.readouterr().out
    assert "New York City has no published remote feed" in out
    assert "→ Use --source local to compute locally" in out
    assert "Retry later" not in out
    assert "Summary: 0/1 products" in out


@pytest.mark.parametrize(
    "arguments",
    [
        ["--region", "us-nyc"],
        ["--region", "us-nyc", "--scope", "national"],
        ["--region", "us-nyc", "--scope", "local"],
        ["--region", "us-nyc", "--scope", "local", "--lat", "40.7"],
        ["--region", "us-nyc", "--scope", "local", "--lat", "35", "--lon", "-74"],
        ["--region", "us-nyc", "--scope", "local", "--lat", "40.7", "--lon", "nan"],
        ["--lat", "nan", "--lon", "121.5"],
        ["--lat", "31.2", "--lon", "241.75"],
    ],
)
def test_region_coordinate_validation_precedes_all_sources(monkeypatch, arguments):
    def forbidden_source(*args, **kwargs):
        pytest.fail("invalid regional requests must fail before any source access")

    monkeypatch.setattr(cli_mod, "_fetch_remote_product", forbidden_source)
    monkeypatch.setattr(cli_mod, "generate_product", forbidden_source)
    monkeypatch.setattr(cli_mod, "generate_local_product", forbidden_source)
    with pytest.raises(SystemExit) as exc:
        main(arguments)
    assert exc.value.code == 2


@pytest.mark.parametrize(
    ("region", "expected_date"),
    [("us-nyc", date(2026, 10, 3)), ("china", date(2026, 10, 4))],
)
def test_default_date_uses_new_york_timezone_and_preserves_china_host_date(
    monkeypatch, tmp_path, region, expected_date
):
    selected_dates = []

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            frozen = cls(2026, 10, 4, 2, tzinfo=timezone.utc)
            return frozen.astimezone(tz) if tz is not None else frozen.replace(tzinfo=None)

    class FrozenDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 10, 4)

    def fake_local(target_date, *args, **kwargs):
        selected_dates.append(target_date)
        return _fake_artifact(tmp_path, "dated-point")

    monkeypatch.setattr(cli_mod, "datetime", FrozenDateTime)
    monkeypatch.setattr(cli_mod, "date", FrozenDate)
    monkeypatch.setattr(cli_mod, "generate_local_product", fake_local)
    lat, lon = ("40.7128", "-74.0060") if region == "us-nyc" else ("31.23", "121.47")
    rc = main([
        "--region", region, "--scope", "local", "--lat", lat, "--lon", lon,
        "--source", "local", "--event", "sunset", "--output", str(tmp_path),
    ])
    assert rc == 0
    assert selected_dates == [expected_date]


@pytest.mark.parametrize(
    ("cached", "heading"),
    [(False, "Remote precomputed product found"), (True, "Cached remote product found")],
)
def test_remote_hit_message_labels_times_in_beijing_time(tmp_path, cached, heading):
    result = RemoteProductResult(
        artifacts=_fake_artifact(tmp_path, "remote-sunset"),
        model_runs=("2026-07-12T18:00:00Z",),
        generated_at=datetime(2026, 7, 12, 23, 32, 28, tzinfo=timezone.utc),
        cached=cached,
    )

    message = cli_mod._remote_hit_message(result)

    assert message.splitlines() == [
        heading,
        "  Model initialization: 2026-07-13 02:00 UTC+08:00 (07-12 18Z)",
        "  Product generated: 2026-07-13 07:32 UTC+08:00",
    ]


def test_remote_source_failure_never_starts_large_local_download(
    monkeypatch, tmp_path, capsys
):
    def local_should_not_run(*args, **kwargs):
        raise AssertionError("remote-only mode must not run locally")

    monkeypatch.setattr(cli_mod, "generate_product", local_should_not_run)

    rc = main([
        "--date", "2026-06-29", "--event", "sunrise",
        "--source", "remote", "--output", str(tmp_path),
    ])
    out = capsys.readouterr().out

    assert rc == 1
    assert "Remote precomputed product unavailable" in out
    assert "Retry later, or use --source local" in out
