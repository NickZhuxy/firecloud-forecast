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
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from predictor.local_product import generate_local_product
from predictor.national_product import generate_product
from predictor.solar_event import SolarEvent


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
             "(first refined run downloads ~210 MB of pressure data per sunset "
             "hour; later runs hit the disk cache)",
    )
    return parser


def _national_product_mod():
    """Indirection so tests can reach ProductArtifacts without importing twice."""
    import predictor.national_product as mod

    return mod


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if (args.lat is None) != (args.lon is None):
        parser.error("--lat and --lon must be given together")
    if args.dpi <= 0:
        parser.error("--dpi must be positive")

    target_date = args.date or date.today()
    plan = plan_products(target_date, args.event, args.lat, args.lon, output_base=args.output)

    # Surface the GFS download progress so a slow multi-hour fetch reads as working.
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    for product in plan:
        if product.scope == "national":
            artifacts = generate_product(
                target_date, product.output_dir, dpi=args.dpi, source=None,
                solar_event=product.solar_event, refine=not args.no_refine,
            )
            print(f"image    : {artifacts.image_path}")
            print(f"metadata : {artifacts.metadata_path}")
        else:
            artifacts = generate_local_product(
                target_date, product.output_dir, product.lat, product.lon,
                dpi=args.dpi, solar_event=product.solar_event,
                radius_km=args.radius, resolution_deg=args.resolution,
            )
            print(f"image    : {artifacts.image_path}")
            print(f"metadata : {artifacts.metadata_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
