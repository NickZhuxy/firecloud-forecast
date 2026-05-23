"""Figure 4: Fire cloud spatiotemporal triangle.

For a flat-bottom layered cloud with base altitude h_CB, the region in (time,
distance-along-sunset-direction) space where direct fire-cloud illumination
is geometrically possible forms a triangle. Far boundary (set by Earth's
shadow) and near boundary (set by the cloud's own boundary obstruction) meet
at two corner points, defining a triangular illumination region.

Usage: uv run python research/paper/figures/fig4_spatiotemporal_triangle.py
"""
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


def main() -> None:
    R_earth_km = 6371.0
    h_CB_km = 5.0  # representative mid/high cloud base
    # Sunset linear velocity ≈ R * dphi/dt. Mid-latitude near equinox: ~21 km/min.
    v = 21.0  # km/min

    L = np.sqrt(2 * R_earth_km * h_CB_km)  # max penetration distance, km
    t_max = L / v  # half-width of time window, minutes

    fig, ax = plt.subplots(figsize=(8.5, 6))

    # Triangle vertices in (t [min], l [km]) — author's geometry:
    #   l_far(t)  = -L + vt           for t ∈ [-T, T]
    #   l_near(t) = 2vt if t ≤ 0 else 0
    # Both boundaries meet at (-T, -2L) and (T, 0); upper boundary kinks at (0, 0).
    V_left   = (-t_max, -2 * L)
    V_kink   = (0.0, 0.0)
    V_right  = (t_max, 0.0)

    triangle = plt.Polygon([V_left, V_kink, V_right], closed=True,
                           facecolor="#C8B4E6", edgecolor="#5B3A8A",
                           alpha=0.55, linewidth=1.8, zorder=2)
    ax.add_patch(triangle)

    # Reference line: local sunset terminator l = vt (passes through origin)
    t_line = np.linspace(-t_max - 2, t_max + 2, 50)
    ax.plot(t_line, v * t_line, color="#7F7F7F", linewidth=0.9, linestyle="--",
            label="reference: terminator $l = vt$")

    # Vertices + annotations
    for V in (V_left, V_kink, V_right):
        ax.plot(*V, "o", color="black", markersize=5, zorder=3)

    ax.annotate(rf"$(-\sqrt{{2Rh_{{CB}}}}/v,\ -2\sqrt{{2Rh_{{CB}}}})$" + f"\n= ({-t_max:.1f} min, {-2*L:.0f} km)",
                xy=V_left, xytext=(V_left[0] + 1, V_left[1] - 40), fontsize=9,
                ha="left", arrowprops=dict(arrowstyle="->", color="gray", lw=0.7))
    ax.annotate("(0, 0)\nnear-boundary kink",
                xy=V_kink, xytext=(V_kink[0] - 6, V_kink[1] + 35), fontsize=9,
                ha="left", arrowprops=dict(arrowstyle="->", color="gray", lw=0.7))
    ax.annotate(rf"$(\sqrt{{2Rh_{{CB}}}}/v,\ 0)$" + f"\n= ({t_max:.1f} min, 0 km)",
                xy=V_right, xytext=(V_right[0] - 4, V_right[1] + 25), fontsize=9,
                ha="center", arrowprops=dict(arrowstyle="->", color="gray", lw=0.7))

    # Mark interior duration as vertical slice at fixed time
    t_slice = -3.0
    l_far_at_slice = -L + v * t_slice
    l_near_at_slice = 2 * v * t_slice if t_slice <= 0 else 0.0
    ax.plot([t_slice, t_slice], [l_near_at_slice, l_far_at_slice],
            color="#E74C3C", linewidth=2.8, zorder=4,
            label=rf"$\Delta l(t = {t_slice:+.0f}\,\mathrm{{min}})$ — illuminated extent")

    ax.set_xlabel(r"Time after local apparent sunset $t$ (min)")
    ax.set_ylabel(r"Signed distance along sunset direction $l$ (km)")
    ax.set_title(
        f"Figure 4. Fire-cloud spatiotemporal illumination triangle\n"
        f"(cloud base $h_{{CB}}$ = {h_CB_km:.0f} km, sunset rate $v$ = {v:.0f} km/min)",
    )
    ax.axhline(0, color="black", linewidth=0.4)
    ax.axvline(0, color="black", linewidth=0.4)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper left", fontsize=9)
    ax.set_xlim(-t_max - 5, t_max + 5)
    ax.set_ylim(-2 * L - 60, 80)

    fig.tight_layout()
    out = Path(__file__).parent / "fig4_spatiotemporal_triangle.png"
    fig.savefig(out, dpi=160, bbox_inches="tight")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
