"""Unified ``firecloud`` command-line entry (#61).

One command, flags rather than subcommands. With no arguments it produces today's
national firecloud potential for **both** events (朝霞 + 晚霞) into a per-date folder
``output/{date}/``:

    firecloud                              # today · national · sunrise + sunset
    firecloud --date 2026-06-29
    firecloud --event sunrise              # only the morning glow
    firecloud --lat 31.2 --lon 121.5       # + local fine product

Default ``--event both`` runs the national overview twice (one GFS read per event;
that doubled fetch is intended). With ``--lat/--lon`` (or ``--lat/--long``), it also
generates the local fine product for each selected event.
"""
from __future__ import annotations

import argparse
import logging
import time
import traceback
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from predictor.gfs import GFSSource, GFSUnavailable
from predictor.local_product import generate_local_product
from predictor.national_product import generate_product
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
) -> list[PlannedProduct]:
    """Pure plan: the products one invocation should produce (offline-testable).

    National products always; when both ``lat`` and ``lon`` are given, a local
    product per event is added. All land in ``{output_base}/{date}/``.
    """
    date_dir = Path(output_base) / target_date.isoformat()
    events = _events(event)
    plan = [PlannedProduct("national", e, date_dir) for e in events]
    if lat is not None and lon is not None:
        plan += [PlannedProduct("point", e, date_dir, lat, lon) for e in events]
    return plan


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="firecloud",
        description="Generate China firecloud (sunrise/sunset glow) forecast products.",
    )
    parser.add_argument(
        "--date", type=date.fromisoformat, default=None,
        help="YYYY-MM-DD (default: today)",
    )
    parser.add_argument(
        "--event", choices=["sunrise", "sunset", "both"], default="both",
        help="which solar event(s) to forecast (default: both)",
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
        help="output base directory; products land in {output}/{date}/ (default: output)",
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
        help="national product source: remote-first, remote-only, or local compute",
    )
    parser.add_argument(
        "--remote-base-url",
        default=None,
        help=argparse.SUPPRESS,
    )
    return parser


# --- progress framing + humanized errors (#106) ---------------------------

_EVENT_CN = {SolarEvent.SUNRISE: "日出", SolarEvent.SUNSET: "日落"}
_EVENTS_CN = {"both": "日出+日落", "sunrise": "日出", "sunset": "日落"}


def _product_label(product: PlannedProduct) -> str:
    event_cn = _EVENT_CN[product.solar_event]
    if product.scope == "national":
        return f"国家{event_cn}图"
    return f"本地{event_cn}图 ({product.lat}, {product.lon})"


def _format_elapsed(seconds: float) -> str:
    whole = int(round(seconds))
    if whole < 60:
        return f"{whole}s"
    minutes, secs = divmod(whole, 60)
    return f"{minutes}分{secs}s"


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
) -> str:
    scope = "全国+本地" if lat is not None else "全国"
    cache = "冷(需下载)" if cold else "热(已缓存)"
    eta = "预计 ~10–20 分钟,取决于网速" if cold else "预计 1–3 分钟"
    if source == "remote":
        source_status = "来源:仅远端 · 不启动本地下载"
    elif source == "local":
        source_status = f"来源:本地计算 · 缓存:{cache} · {eta}"
    else:
        source_status = f"来源:远端优先 · 本地回退缓存:{cache}"
    return (
        f"firecloud · {target_date.isoformat()} · {_EVENTS_CN[event]} · {scope}\n"
        f"计划:{n} 个产品 · {source_status}"
    )


def _fetch_remote_product(product: PlannedProduct, target_date: date, args):
    result = RemoteProductClient(base_url=args.remote_base_url).fetch(
        target_date,
        product.solar_event,
        product.output_dir,
    )
    origin = "本地远端缓存" if result.cached else "远端预计算"
    model = ", ".join(result.model_runs) or "unknown model run"
    logger.info("%s命中: %s · 生成于 %s", origin, model, result.generated_at.isoformat())
    return result.artifacts


def _run_product(product: PlannedProduct, target_date: date, args) -> object:
    if product.scope == "national":
        if args.source != "local":
            try:
                return _fetch_remote_product(product, target_date, args)
            except RemoteProductUnavailable as exc:
                if args.source == "remote":
                    raise
                logger.warning("远端预计算产品不可用，转为本地计算: %s", exc)
        return generate_product(
            target_date, product.output_dir, dpi=args.dpi, source=None,
            solar_event=product.solar_event, refine=not args.no_refine,
            satellite=not args.no_satellite,
        )
    return generate_local_product(
        target_date, product.output_dir, product.lat, product.lon,
        dpi=args.dpi, solar_event=product.solar_event,
        radius_km=args.radius, resolution_deg=args.resolution,
        satellite=not args.no_satellite,
    )


def _print_data_failure(i: int, n: int, label: str) -> None:
    print(f"[{i}/{n}] ✗ {label}失败:数据源连不上(NOAA/网络,已自动重试多次)")
    print("  多半是网络或 NOAA 源临时问题,不是你的操作。")
    print("  → 稍后重跑(已下载的分片会复用,不会重下)")
    print("  → 或加 --no-refine 先出粗图(跳过气压立体数据下载)")


def _print_unexpected_failure(i: int, n: int, label: str, verbose: bool) -> None:
    print(f"[{i}/{n}] ✗ {label}出错了(通常不是你的操作问题)")
    print("  常见原因是网络、NOAA 源或本地依赖临时异常。")
    if verbose:
        traceback.print_exc()
    else:
        print("  (加 --verbose 看完整技术细节)")


def _print_remote_failure(i: int, n: int, label: str) -> None:
    print(f"[{i}/{n}] ✗ {label}失败:远端预计算产品不可用")
    print("  已按 --source remote 禁止本地大文件下载。")
    print("  → 稍后重试，或使用 --source local 明确启动本地计算")


def _national_product_mod():
    """Indirection so tests can reach ProductArtifacts without importing twice."""
    import predictor.national_product as mod

    return mod


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if (args.lat is None) != (args.lon is None):
        parser.error("--lat and --lon must be given together")
    if args.source == "remote" and args.lat is not None:
        parser.error("--source remote currently supports national products only")
    if args.dpi <= 0:
        parser.error("--dpi must be positive")

    target_date = args.date or date.today()
    plan = plan_products(target_date, args.event, args.lat, args.lon, output_base=args.output)

    # Surface the GFS download progress so a slow multi-hour fetch reads as working.
    # --verbose lifts the veil (transient-retry detail, tracebacks); --quiet drops
    # the per-stage INFO lines but keeps the plan/product/summary frame below.
    level = logging.DEBUG if args.verbose else logging.WARNING if args.quiet else logging.INFO
    logging.basicConfig(level=level, format="%(message)s")

    cold = _cache_is_cold(target_date)
    print(_plan_header(target_date, args.event, args.lat, len(plan), cold, args.source))

    n = len(plan)
    succeeded = 0
    run_started = time.perf_counter()
    for i, product in enumerate(plan, start=1):
        label = _product_label(product)
        print(f"\n[{i}/{n}] {label}…")
        started = time.perf_counter()
        try:
            artifacts = _run_product(product, target_date, args)
        except RemoteProductUnavailable:
            _print_remote_failure(i, n, label)
            continue
        except GFSUnavailable:
            _print_data_failure(i, n, label)
            continue
        except Exception:  # noqa: BLE001 — user-facing catch-all, one product only
            _print_unexpected_failure(i, n, label, args.verbose)
            continue
        elapsed = _format_elapsed(time.perf_counter() - started)
        print(f"[{i}/{n}] ✓ {artifacts.image_path}  ·  {elapsed}")
        print(f"        metadata: {artifacts.metadata_path}")
        succeeded += 1

    total = _format_elapsed(time.perf_counter() - run_started)
    tail = "" if succeeded == n else f"({n - succeeded} 失败)"
    print(f"\n总结:{succeeded}/{n} 出图  ·  总耗时 {total}{tail}")
    return 0 if succeeded == n else 1


if __name__ == "__main__":
    raise SystemExit(main())
