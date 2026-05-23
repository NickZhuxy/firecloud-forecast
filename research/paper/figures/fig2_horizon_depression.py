"""Figure 2: Cloud altitude and direct-illumination geometry.

Left panel: horizon depression angle d(h) = arccos(R / (R + h)) as a function
of cloud altitude, with WMO three-tier altitude bands shaded.

Right panel: direct-illumination time window Δt(h) = 2 d(h) / |dα/dt| from
apparent sunset, using a mid-latitude approximate solar rate of 0.20°/min.

Usage: uv run python docs/paper/figures/fig2_horizon_depression.py
"""
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


def main() -> None:
    R_earth_km = 6371.0
    h_km = np.linspace(0.05, 20.0, 400)

    d_deg = np.degrees(np.arccos(R_earth_km / (R_earth_km + h_km)))

    solar_rate_deg_per_min = 0.20  # mid-latitude, equinox approximate
    dt_min = 2.0 * d_deg / solar_rate_deg_per_min

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.5, 5.0))

    # ---- Left: depression angle ----
    ax1.plot(h_km, d_deg, color="#1F4E79", linewidth=2.4)
    ax1.set_xlabel("Cloud altitude $h$ (km)")
    ax1.set_ylabel(r"Horizon depression angle $d(h)$ (degrees)")
    ax1.set_xlim(0, 20)
    ax1.set_ylim(0, 5.2)
    ax1.grid(True, alpha=0.3)
    ax1.set_title("(a) Horizon depression angle")

    ax1.axvspan(0, 2, alpha=0.18, color="#7F7F7F", label="Low clouds (< 2 km)")
    ax1.axvspan(2, 6, alpha=0.18, color="#9ACBE6", label="Mid clouds (2–6 km)")
    ax1.axvspan(6, 13, alpha=0.18, color="#D6EAF8", label="High clouds (6–13 km)")
    ax1.axvspan(13, 20, alpha=0.10, color="#EAEDED", label="Above tropopause (temperate)")
    ax1.legend(loc="lower right", fontsize=8)

    # ---- Right: time window ----
    ax2.plot(h_km, dt_min, color="#943126", linewidth=2.4)
    ax2.set_xlabel("Cloud altitude $h$ (km)")
    ax2.set_ylabel(r"Direct-illumination window $\Delta t$ (min)")
    ax2.set_xlim(0, 20)
    ax2.set_ylim(0, 50)
    ax2.grid(True, alpha=0.3)
    ax2.set_title(r"(b) Direct-illumination window (|d$\alpha$/dt| = 0.20°/min)")

    ax2.axvspan(0, 2, alpha=0.18, color="#7F7F7F")
    ax2.axvspan(2, 6, alpha=0.18, color="#9ACBE6")
    ax2.axvspan(6, 13, alpha=0.18, color="#D6EAF8")
    ax2.axvspan(13, 20, alpha=0.10, color="#EAEDED")

    for name, h in [("Cumulus (1 km)", 1.0), ("Altocumulus (4 km)", 4.0),
                    ("Cirrostratus (8 km)", 8.0), ("Cirrus (12 km)", 12.0)]:
        d = float(np.degrees(np.arccos(R_earth_km / (R_earth_km + h))))
        dt = 2.0 * d / solar_rate_deg_per_min
        ax2.plot([h], [dt], "o", color="black", markersize=5)
        ax2.annotate(name, xy=(h, dt), xytext=(h + 0.7, dt - 4.5),
                     fontsize=8.5, color="black")

    fig.suptitle("Figure 2. Cloud altitude controls illumination duration after sunset", y=1.02)
    fig.tight_layout()

    out = Path(__file__).parent / "fig2_horizon_depression.png"
    fig.savefig(out, dpi=160, bbox_inches="tight")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
