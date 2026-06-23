"""Live smoke test for the GFS adapter — performs a real network fetch.

Not part of the default pytest run. Use it to confirm the adapter pulls a
complete Shanghai pressure-level profile from live GFS data:

    python -m predictor.gfs_smoke --lat 31.23 --lon 121.47

Defaults to Shanghai at the current UTC time.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

from predictor.gfs import GFSSource


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Live GFS profile smoke test.")
    parser.add_argument("--lat", type=float, default=31.23, help="latitude (default: Shanghai)")
    parser.add_argument("--lon", type=float, default=121.47, help="longitude (default: Shanghai)")
    parser.add_argument(
        "--time",
        type=str,
        default=None,
        help="valid time ISO-8601 UTC (default: now)",
    )
    args = parser.parse_args(argv)

    valid_time = (
        datetime.fromisoformat(args.time).replace(tzinfo=timezone.utc)
        if args.time
        else datetime.now(timezone.utc)
    )

    src = GFSSource()
    profile = src.fetch_profile(args.lat, args.lon, valid_time)

    print(f"source     : {profile.source_label}")
    print(f"grid point : {profile.lat:.2f}, {profile.lon:.2f}")
    print(f"valid_time : {profile.valid_time.isoformat()}")
    if profile.missing:
        print(f"missing    : {', '.join(profile.missing)}")
    print()
    print(f"{'hPa':>6} {'T(K)':>8} {'RH%':>6} {'gh(m)':>9} {'u':>7} {'v':>7} {'w(Pa/s)':>9}")
    for i, level in enumerate(profile.levels_hpa):
        print(
            f"{level:6.0f} {profile.temperature_k[i]:8.1f} "
            f"{profile.relative_humidity_pct[i]:6.0f} "
            f"{profile.geopotential_height_m[i]:9.0f} "
            f"{profile.u_wind_m_s[i]:7.1f} {profile.v_wind_m_s[i]:7.1f} "
            f"{profile.vertical_velocity_pa_s[i]:9.3f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
