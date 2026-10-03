"""Unified ``firecloud`` command-line entry (#61).

One command, flags rather than subcommands. With no arguments it produces today's
national firecloud potential for **both** events (sunrise + sunset) into a per-date folder
``output/{date}/``:

    firecloud                              # today · national · sunrise + sunset
    firecloud --date 2026-06-29
    firecloud --event sunrise              # only the morning glow
    firecloud --lat 31.2 --lon 121.5       # + local fine product
    firecloud --scope local --lat 31.2 --lon 121.5  # local products only
    firecloud --region us-nyc --scope local --lat 40.71 --lon -74.01

Default ``--event both`` runs the national overview twice (one GFS read per event;
that doubled fetch is intended). With ``--lat/--lon`` (or ``--lat/--long``), it also
generates the local fine product for each selected event. ``--scope local`` limits
the request to local products; ``--scope national`` requests only national maps.
"""
from __future__ import annotations

import argparse
import logging
import time
import traceback
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from predictor.gfs import GFSSource, GFSUnavailable
from predictor.local_product import generate_local_product
from predictor.national_product import generate_product
from predictor.regions import REGION_KEYS, get_region
from predictor.remote_product import (
    RemoteProductClient,
    RemoteProductUnavailable,
)
from predictor.solar_event import SolarEvent

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlannedProduct:
    scope: str                 # "national" | "point"
    solar_event: SolarEvent
    output_dir: Path           # the per-date folder the artifact lands in
    lat: float | None = None
    lon: float | None = None
    region: str = "china"


def _events(event: str) -> list[SolarEvent]:
    """Resolve the ``--event`` choice to the events to render (chronological)."""
    if event == "both":
        return [SolarEvent.SUNRISE, SolarEvent.SUNSET]
    return [SolarEvent(event)]


def plan_products(
    target_date: date,
    event: str,
    lat: float | None,
    lon: float | None,
    *,
    output_base: str | Path = "output",
    scope: str = "all",
    region: str = "china",
) -> list[PlannedProduct]:
    """Pure plan: the products one invocation should produce (offline-testable).

    The default includes national maps and, when coordinates are supplied, local
    maps. ``local`` requires coordinates; ``national`` rejects them so a location
    request cannot be silently ignored. China keeps ``{output_base}/{date}/``;
    pilot products use ``{output_base}/{region}/{date}/``.
    """
    selected_region = get_region(region)
    if scope not in {"all", "national", "local"}:
        raise ValueError("scope must be all, national, or local")
    if not selected_region.national_enabled and scope != "local":
        raise ValueError(f"{selected_region.name} only supports --scope local")
    if (lat is None) != (lon is None):
        raise ValueError("--lat and --lon must be given together")
    if scope == "local" and lat is None:
        raise ValueError("--scope local requires --lat and --lon")
    if scope == "national" and lat is not None:
        raise ValueError(
            "--scope national does not accept coordinates; use --scope local or all"
        )
    if lat is not None and lon is not None:
        selected_region.validate_center(lat, lon)
    root = Path(output_base)
    if selected_region.key != "china":
        root /= selected_region.key
    date_dir = root / target_date.isoformat()
    events = _events(event)
    plan = []
    if scope != "local":
        plan += [
            PlannedProduct("national", e, date_dir, region=selected_region.key)
            for e in events
        ]
    if scope != "national" and lat is not None and lon is not None:
        plan += [
            PlannedProduct("point", e, date_dir, lat, lon, selected_region.key)
            for e in events
        ]
    return plan


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="firecloud",
        description="Generate firecloud (sunrise/sunset glow) forecast products. "
                    "China is supported; New York City is a local pilot.",
    )
    parser.add_argument(
        "--region", choices=REGION_KEYS, default="china",
        help="coverage profile: china or the local-only us-nyc pilot (default: china)",
    )
    parser.add_argument(
        "--date", type=date.fromisoformat, default=None,
        help="YYYY-MM-DD local event date (default: today; us-nyc uses New York time)",
    )
    parser.add_argument(
        "--event", choices=["sunrise", "sunset", "both"], default="both",
        help="which solar event(s) to forecast (default: both)",
    )
    parser.add_argument(
        "--scope", choices=["all", "national", "local"], default="all",
        help="products to generate: all includes national maps plus local maps when "
             "coordinates are supplied; local requires --lat and --lon (default: all)",
    )
    parser.add_argument("--lat", type=float, default=None, help="local product latitude")
    parser.add_argument(
        "--lon", "--long", dest="lon", type=float, default=None,
        help="local product longitude",
    )
    parser.add_argument(
        "--radius", type=float, default=150.0,
        help="local product radius in km (default: 150)",
    )
    parser.add_argument(
        "--resolution", type=float, default=0.1,
        help="local product grid resolution in degrees (default: 0.1)",
    )
    parser.add_argument(
        "--output", type=Path, default=Path("output"),
        help="output base directory; China uses {output}/{date}/ and the NYC pilot "
             "uses {output}/us-nyc/{date}/ (default: output)",
    )
    parser.add_argument("--dpi", type=int, default=160)
    parser.add_argument(
        "--no-refine", action="store_true",
        help="skip Stage B ray-trace refinement for the national product "
             "(a cold run downloads pressure data for several forecast hours; "
             "downloads are cached and resume after interruption)",
    )
    parser.add_argument(
        "--no-satellite", action="store_true",
        help="skip Stage C satellite nowcast (it only fetches two Himawari "
             "frames when generating within ~2 h of the event; missing data "
             "or dependencies are skipped safely either way)",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="show full technical detail (DEBUG logs + tracebacks) on errors",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="only show the plan/product/summary frame, hide per-stage progress",
    )
    parser.add_argument(
        "--source",
        choices=["auto", "remote", "local"],
        default="auto",
        help="product source: remote-first, remote-only, or local compute",
    )
    parser.add_argument(
        "--remote-base-url",
        default=None,
        help=argparse.SUPPRESS,
    )
    return parser


# --- progress framing + humanized errors (#106) ---------------------------

_EVENT_LABEL = {SolarEvent.SUNRISE: "sunrise", SolarEvent.SUNSET: "sunset"}
_EVENT_LABELS = {"both": "sunrise + sunset", "sunrise": "sunrise", "sunset": "sunset"}
_BEIJING_TZ = ZoneInfo("Asia/Shanghai")


def _product_label(product: PlannedProduct) -> str:
    event_label = _EVENT_LABEL[product.solar_event]
    if product.scope == "national":
        return f"National {event_label} map"
    return f"Local {event_label} map ({product.lat}, {product.lon})"


def _format_elapsed(seconds: float) -> str:
    whole = int(round(seconds))
    if whole < 60:
        return f"{whole}s"
    minutes, secs = divmod(whole, 60)
    return f"{minutes}m {secs}s"


def _format_beijing_time(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(_BEIJING_TZ).strftime("%Y-%m-%d %H:%M UTC+08:00")


def _format_model_run(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    utc = parsed.astimezone(timezone.utc)
    return f"{_format_beijing_time(utc)} ({utc:%m-%d %HZ})"


def _remote_hit_message(result) -> str:
    origin = "Cached remote product" if result.cached else "Remote precomputed product"
    runs = ", ".join(_format_model_run(run) for run in result.model_runs)
    if not runs:
        runs = "not provided"
    return (
        f"{origin} found\n"
        f"  Model initialization: {runs}\n"
        f"  Product generated: {_format_beijing_time(result.generated_at)}"
    )


def _cache_is_cold(target_date: date, cache_root: Path | str | None = None) -> bool:
    """True when no pressure-cube subset for ``target_date`` is on disk yet.

    A coarse cold/warm signal for the plan header: a warm cache means the slow
    multi-hundred-MB downloads are already local and the run is seconds, not
    minutes. Approximate (checks the target date's cycle dir, not the exact
    fallback cycle) — good enough to set expectations.
    """
    root = Path(cache_root) if cache_root is not None else Path(GFSSource.DEFAULT_CACHE_DIR)
    dated = root / "pressure" / "gfs" / target_date.strftime("%Y%m%d")
    return not any(dated.glob("subset_*"))


def _plan_header(
    target_date: date,
    event: str,
    lat: float | None,
    n: int,
    cold: bool,
    source: str,
    scope: str = "all",
    region: str = "china",
) -> str:
    if scope == "local":
        display_scope = "local"
    else:
        display_scope = "national + local" if lat is not None else "national"
    cache = "cold (downloads required)" if cold else "warm (cached)"
    eta = "estimate ~10–20 min, depending on network speed" if cold else "estimate 1–3 min"
    if source == "remote":
        source_status = "source: remote only · no local data downloads"
    elif source == "local":
        source_status = f"source: local computation · cache: {cache} · {eta}"
    else:
        source_status = f"source: remote first · local fallback cache: {cache}"
    region_label = "" if region == "china" else f" · {get_region(region).name}"
    return (
        f"firecloud · {target_date.isoformat()} · {_EVENT_LABELS[event]} · {display_scope}{region_label}\n"
        f"Plan: {n} products · {source_status}"
    )


def _fetch_remote_product(product: PlannedProduct, target_date: date, args):
    region = get_region(product.region)
    if not region.remote_enabled:
        raise RemoteProductUnavailable(
            f"{region.name} has no published remote feed; use --source local"
        )
    client = RemoteProductClient(base_url=args.remote_base_url)
    if product.scope == "point":
        result = client.fetch_point(
            target_date,
            product.solar_event,
            product.output_dir,
            product.lat,
            product.lon,
            radius_km=args.radius,
            resolution_deg=args.resolution,
        )
    else:
        result = client.fetch(
            target_date,
            product.solar_event,
            product.output_dir,
        )
    logger.info(_remote_hit_message(result))
    return result.artifacts


def _run_product(product: PlannedProduct, target_date: date, args) -> object:
    if args.source != "local":
        try:
            return _fetch_remote_product(product, target_date, args)
        except RemoteProductUnavailable as exc:
            if args.source == "remote":
                raise
            logger.warning("Remote precomputed product unavailable; falling back to local computation: %s", exc)
    if product.scope == "national":
        return generate_product(
            target_date, product.output_dir, dpi=args.dpi, source=None,
            solar_event=product.solar_event, refine=not args.no_refine,
            satellite=not args.no_satellite,
        )
    region = get_region(product.region)
    region_options = {"region": region.key} if region.key != "china" else {}
    return generate_local_product(
        target_date, product.output_dir, product.lat, product.lon,
        dpi=args.dpi, solar_event=product.solar_event,
        radius_km=args.radius, resolution_deg=args.resolution,
        satellite=not args.no_satellite and region.satellite_enabled,
        **region_options,
    )


def _print_data_failure(i: int, n: int, label: str, scope: str = "national") -> None:
    print(f"[{i}/{n}] ✗ {label} failed: data source unreachable (NOAA/network; retries exhausted)")
    print("  This is likely a temporary network or NOAA source issue, not your input.")
    print("  → Retry later (downloaded subsets will be reused)")
    if scope == "national":
        print("  → Or add --no-refine for a coarse national map (skips national pressure-cube refinement)")


def _print_unexpected_failure(i: int, n: int, label: str, verbose: bool) -> None:
    print(f"[{i}/{n}] ✗ {label} failed (usually a network, data-source, or dependency issue)")
    print("  Common causes include network, NOAA source, or local dependency failures.")
    if verbose:
        traceback.print_exc()
    else:
        print("  (Add --verbose for full technical details)")


def _print_remote_failure(
    i: int, n: int, label: str, reason: str | None = None,
    *, remote_enabled: bool = True,
) -> None:
    print(f"[{i}/{n}] ✗ {label} failed: Remote precomputed product unavailable")
    print("  --source remote prevents local weather-data downloads.")
    if reason:
        print(f"  {reason}")
    if remote_enabled:
        print("  → Retry later, or use --source local to compute locally")
    else:
        print("  → Use --source local to compute locally")


def _national_product_mod():
    """Indirection so tests can reach ProductArtifacts without importing twice."""
    import predictor.national_product as mod

    return mod


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.dpi <= 0:
        parser.error("--dpi must be positive")

    region = get_region(args.region)
    default_date = (
        datetime.now(ZoneInfo(region.timezone_name)).date()
        if region.key != "china" else date.today()
    )
    target_date = args.date or default_date
    try:
        plan = plan_products(
            target_date, args.event, args.lat, args.lon,
            output_base=args.output, scope=args.scope, region=region.key,
        )
    except ValueError as exc:
        parser.error(str(exc))

    # Surface the GFS download progress so a slow multi-hour fetch reads as working.
    # --verbose lifts the veil (transient-retry detail, tracebacks); --quiet drops
    # the per-stage INFO lines but keeps the plan/product/summary frame below.
    level = logging.DEBUG if args.verbose else logging.WARNING if args.quiet else logging.INFO
    logging.basicConfig(level=level, format="%(message)s")

    cold = _cache_is_cold(target_date)
    print(_plan_header(
        target_date, args.event, args.lat, len(plan), cold, args.source, args.scope, region.key,
    ))

    n = len(plan)
    succeeded = 0
    run_started = time.perf_counter()
    for i, product in enumerate(plan, start=1):
        label = _product_label(product)
        print(f"\n[{i}/{n}] {label}…")
        started = time.perf_counter()
        try:
            artifacts = _run_product(product, target_date, args)
        except RemoteProductUnavailable as exc:
            _print_remote_failure(
                i, n, label, str(exc), remote_enabled=region.remote_enabled,
            )
            continue
        except GFSUnavailable:
            _print_data_failure(i, n, label, product.scope)
            continue
        except Exception:  # noqa: BLE001 — user-facing catch-all, one product only
            _print_unexpected_failure(i, n, label, args.verbose)
            continue
        elapsed = _format_elapsed(time.perf_counter() - started)
        print(f"[{i}/{n}] ✓ {artifacts.image_path}  ·  {elapsed}")
        print(f"        metadata: {artifacts.metadata_path}")
        succeeded += 1

    total = _format_elapsed(time.perf_counter() - run_started)
    tail = "" if succeeded == n else f" ({n - succeeded} failed)"
    print(f"\nSummary: {succeeded}/{n} products  ·  elapsed {total}{tail}")
    return 0 if succeeded == n else 1


if __name__ == "__main__":
    raise SystemExit(main())
