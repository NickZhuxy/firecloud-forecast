"""Reviewable sunward vertical cross-section plot (#18).

Renders the distance × geometric-height field assembled by ``cross_section`` so a
forecaster can see, along the real sunset direction, which moist layers, ascent
regions, and diagnosed cloud decks the low-angle sunlight crosses — exportable
for side-by-side comparison with Windy / manual sounding charts.

Pure presentation, built on a bare ``matplotlib.figure.Figure`` (no pyplot) so it
renders headless. Masked (out-of-coverage / sub-terrain) cells are left blank and
fully-masked columns are explicitly marked.
"""
from __future__ import annotations

import numpy as np
from matplotlib.figure import Figure

from predictor.cross_section import SunwardCrossSection

_KELVIN_0C = 273.15


def plot_cross_section(xsec: SunwardCrossSection, *, figure: Figure | None = None) -> Figure:
    fig = figure or Figure(figsize=(9, 6))
    ax = fig.add_subplot(1, 1, 1)

    dist = np.asarray(xsec.distances_km, dtype=float)
    height = np.asarray(xsec.heights_m, dtype=float)
    X, Y = np.meshgrid(dist, height)

    rh = np.ma.masked_invalid(xsec.relative_humidity_pct)
    mesh = ax.pcolormesh(X, Y, rh, cmap="YlGnBu", vmin=0, vmax=100, shading="nearest")
    fig.colorbar(mesh, ax=ax, label="Relative humidity (%)")

    # Ascent regions (vertical velocity < 0 in Pa/s = upward) hatched.
    w = np.ma.masked_invalid(xsec.vertical_velocity_pa_s)
    if w.count() and float(w.min()) < 0:
        ax.contourf(X, Y, w, levels=[float(w.min()) - 1e-6, 0.0], colors="none",
                    hatches=["////"], alpha=0.0)

    # 0 °C isotherm (rough phase divider) where temperature is present.
    t_c = np.ma.masked_invalid(xsec.temperature_k) - _KELVIN_0C
    if t_c.count() and float(t_c.min()) < 0 < float(t_c.max()):
        ax.contour(X, Y, t_c, levels=[0.0], colors="#c0392b", linewidths=1.0, linestyles="--")

    # Diagnosed cloud decks: a vertical bar per column from base to top.
    for d, layers in zip(dist, xsec.cloud_layers):
        for layer in layers or []:
            ax.plot([d, d], [layer.base_m, layer.top_m], color="#34495e", linewidth=4,
                    solid_capstyle="butt", alpha=0.8)

    # Mark fully out-of-coverage columns.
    mask = np.asarray(xsec.mask, dtype=bool)
    y_mid = float(height.mean())
    for j, d in enumerate(dist):
        if not mask[:, j].any():
            ax.text(d, y_mid, "no data", rotation=90, ha="center", va="center",
                    fontsize=8, color="#7f8c8d")

    # Observer at distance 0 and the sun direction.
    ax.scatter([0.0], [0.0], marker="^", s=80, color="#000000", zorder=5)
    ax.text(0.0, 0.0, " observer", fontsize=8, va="bottom")
    ax.annotate(
        f"→ toward sun (az {xsec.azimuth_deg:.0f}°)",
        xy=(0.98, 1.02), xycoords="axes fraction", ha="right", fontsize=9,
    )
    # Legend for the overlays (hatch = ascent, dashed = freezing level, bar = deck).
    ax.annotate(
        "hatch = ascent (w<0)  ·  red dashed = 0 °C  ·  bar = diagnosed deck",
        xy=(0.0, 1.02), xycoords="axes fraction", ha="left", fontsize=8, color="#555555",
    )

    ax.set_xlabel("Distance along sunset azimuth (km)")
    ax.set_ylabel("Geometric height (m)")
    ax.set_ylim(float(height.min()), float(height.max()))
    fig.suptitle(_title(xsec), fontsize=10)
    return fig


def save_cross_section(xsec: SunwardCrossSection, path: str) -> str:
    fig = plot_cross_section(xsec)
    fig.savefig(path, dpi=130, bbox_inches="tight")
    return path


def _title(xsec: SunwardCrossSection) -> str:
    lat, lon = xsec.observer
    src = xsec.source_label or "—"
    return (
        f"{src}\nsunward cross-section  ·  valid {xsec.target_time.isoformat()}\n"
        f"observer ({lat:.1f}, {lon:.1f})  ·  azimuth {xsec.azimuth_deg:.0f}°"
    )
