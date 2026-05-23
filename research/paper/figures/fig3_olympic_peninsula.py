"""Figure 3: Olympic Peninsula case study — weighted-sum vs gate × modifier.

Runs the predictor over the Olympic Peninsula at the Section 5 case-study
query time, computes both scoring schemes from the same per-rule component
scores, and plots side-by-side cartopy heatmaps. The point of the figure
is to show that weighted-sum produces uniform ~0.6 probability where the
gate × modifier architecture correctly returns ~0 (no mid/high cloud canvas).

Usage: uv run python docs/paper/figures/fig3_olympic_peninsula.py
"""
from datetime import datetime, timezone
from pathlib import Path

import cartopy.crs as ccrs
import cartopy.feature as cfeature
import matplotlib.pyplot as plt
import numpy as np

from predictor.fetch import HRRRSource
from predictor.rules import (
    HumidityFactor,
    LowCloudObstruction,
    MidHighCloudPresence,
    RuleBasedPredictor,
    SolarAngleAtSunset,
)

# Case-study parameters from Section 5.1
QUERY_TIME = datetime(2026, 5, 21, 3, 30, tzinfo=timezone.utc)  # 2026-05-20 20:30 PDT
BBOX = (-125.2, 47.3, -123.8, 48.3)  # (lon_min, lat_min, lon_max, lat_max)
GRID_RES = 0.1  # ~10 km
WEIGHTS = {
    "mid_high_cloud_presence": 2.0,
    "low_cloud_obstruction": 2.0,
    "solar_angle": 1.5,
    "humidity": 1.0,
}
GATES = ("mid_high_cloud_presence", "low_cloud_obstruction", "solar_angle")
MODIFIERS = ("humidity",)


def weighted_sum(components: dict[str, float]) -> float:
    num = sum(WEIGHTS[k] * v for k, v in components.items() if k in WEIGHTS)
    den = sum(WEIGHTS[k] for k in components if k in WEIGHTS)
    return num / den if den > 0 else 0.0


def gate_x_modifier(components: dict[str, float]) -> float:
    gates = [components[k] for k in GATES if k in components]
    if not gates:
        return 0.0
    G = float(np.prod([g ** (1.0 / len(gates)) for g in gates]))
    if MODIFIERS:
        mods = [components[k] for k in MODIFIERS if k in components]
        M = float(np.mean(mods)) if mods else 1.0
    else:
        M = 1.0
    return G * M


def main() -> None:
    source = HRRRSource(cache_dir=Path("research/data/cache/hrrr"))
    predictor = RuleBasedPredictor(
        rules=[
            MidHighCloudPresence(),
            LowCloudObstruction(),
            SolarAngleAtSunset(),
            HumidityFactor(),
        ],
        weights=WEIGHTS,
        source=source,
    )

    lon_min, lat_min, lon_max, lat_max = BBOX
    lons = np.arange(lon_min, lon_max + GRID_RES, GRID_RES)
    lats = np.arange(lat_min, lat_max + GRID_RES, GRID_RES)
    LON, LAT = np.meshgrid(lons, lats)

    P_add = np.full_like(LON, np.nan, dtype=float)
    P_gm = np.full_like(LON, np.nan, dtype=float)

    total = len(lats) * len(lons)
    print(f"Scoring {total} grid points (first HRRR fetch slow; subsequent cached)…")

    counter = 0
    for j, lat in enumerate(lats):
        for i, lon in enumerate(lons):
            try:
                forecast = predictor.score(lat=float(lat), lon=float(lon), time=QUERY_TIME)
                P_add[j, i] = weighted_sum(forecast.components)
                P_gm[j, i] = gate_x_modifier(forecast.components)
            except Exception as e:  # outside HRRR domain or grid mismatch
                P_add[j, i] = np.nan
                P_gm[j, i] = np.nan
            counter += 1
            if counter % 20 == 0:
                print(f"  {counter}/{total}")

    fig, axes = plt.subplots(
        1, 2, figsize=(13.5, 6),
        subplot_kw={"projection": ccrs.LambertConformal(central_longitude=-124, central_latitude=47.8)},
    )

    for ax, P, title in [
        (axes[0], P_add, "(a) Weighted-sum scoring"),
        (axes[1], P_gm, "(b) Gate × modifier scoring"),
    ]:
        ax.set_extent([lon_min, lon_max, lat_min, lat_max], crs=ccrs.PlateCarree())
        ax.add_feature(cfeature.COASTLINE, linewidth=0.8)
        ax.add_feature(cfeature.STATES, linewidth=0.4)
        ax.add_feature(cfeature.BORDERS, linewidth=0.4)

        mesh = ax.pcolormesh(
            LON, LAT, P, transform=ccrs.PlateCarree(),
            cmap="magma", vmin=0.0, vmax=1.0, shading="auto",
        )
        for name, lat, lon in [
            ("La Push", 47.91, -124.64),
            ("Ruby Beach", 47.71, -124.42),
            ("Forks", 47.95, -124.39),
        ]:
            ax.plot(lon, lat, marker="*", color="cyan", markersize=12,
                    markeredgecolor="black", transform=ccrs.PlateCarree())
            ax.text(lon + 0.03, lat + 0.03, name, transform=ccrs.PlateCarree(),
                    fontsize=8.5, color="white",
                    bbox=dict(facecolor="black", alpha=0.55, pad=1.2, edgecolor="none"))

        ax.set_title(title)

    # Shared colorbar
    cbar = fig.colorbar(mesh, ax=axes, orientation="horizontal", pad=0.04, fraction=0.04,
                        shrink=0.6)
    cbar.set_label("Fire-cloud probability")

    fig.suptitle(
        f"Figure 3. Olympic Peninsula case study (query time {QUERY_TIME.isoformat()})",
        y=0.98,
    )

    out = Path(__file__).parent / "fig3_olympic_peninsula.png"
    fig.savefig(out, dpi=160, bbox_inches="tight")
    print(f"wrote {out}")

    valid_add = P_add[~np.isnan(P_add)]
    valid_gm = P_gm[~np.isnan(P_gm)]
    print(f"\nSummary statistics (across {valid_add.size} valid cells):")
    print(f"  Weighted-sum:        min={valid_add.min():.3f}  mean={valid_add.mean():.3f}  max={valid_add.max():.3f}")
    print(f"  Gate × modifier:     min={valid_gm.min():.3f}  mean={valid_gm.mean():.3f}  max={valid_gm.max():.3f}")


if __name__ == "__main__":
    main()
