"""Reviewable sounding plot with cloud annotations (#8).

Turns the manual Windy/sounding judgement into an inspectable diagnostic figure:
temperature and dewpoint vs height, wind barbs, and shaded diagnosed cloud
layers labelled with base/top/thickness/confidence — alongside the model, run
and valid times, location, and whether the data came from cache.

The plot layer is decoupled from the diagnosis algorithm: it consumes an
already-normalized profile and a list of already-diagnosed ``CloudLayer``s, and
never imports the diagnosis code.
"""
from __future__ import annotations

import numpy as np
from matplotlib.figure import Figure

from predictor.clouds import CloudLayer
from predictor.profiles import NormalizedProfile

_KELVIN_0C = 273.15  # display-only K→°C offset


def plot_sounding(
    profile: NormalizedProfile,
    layers: list[CloudLayer],
    *,
    cached: bool = False,
    figure: Figure | None = None,
) -> Figure:
    """Render a sounding figure. Pure presentation — no data fetching."""
    fig = figure or Figure(figsize=(7, 9))
    ax = fig.add_subplot(1, 1, 1)

    height = np.asarray(profile.geometric_height_m, dtype=float)
    temp_c = np.asarray(profile.temperature_k, dtype=float) - _KELVIN_0C
    dew_c = np.asarray(profile.dewpoint_k, dtype=float) - _KELVIN_0C

    ax.plot(temp_c, height, color="#c0392b", marker="o", label="Temperature (°C)")
    ax.plot(dew_c, height, color="#2980b9", marker="o", label="Dewpoint (°C)")
    ax.set_xlabel("Temperature / Dewpoint (°C)")
    ax.set_ylabel("Geometric height (m)")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper right")

    _annotate_layers(ax, layers)
    _add_wind_barbs(ax, profile, height)

    fig.suptitle(_title(profile, cached), fontsize=10)
    return fig


def save_sounding(
    profile: NormalizedProfile,
    layers: list[CloudLayer],
    path: str,
    *,
    cached: bool = False,
) -> str:
    """Render and export a PNG for side-by-side comparison with Windy."""
    fig = plot_sounding(profile, layers, cached=cached)
    fig.savefig(path, dpi=130, bbox_inches="tight")
    return path


def _annotate_layers(ax, layers: list[CloudLayer]) -> None:
    for layer in layers:
        ax.axhspan(layer.base_m, layer.top_m, color="#7f8c8d", alpha=0.22)
        label = (
            f"{layer.phase_hint} [{layer.source}]\n"
            f"base {layer.base_m:.0f} m  top {layer.top_m:.0f} m\n"
            f"Δ {layer.thickness_m:.0f} m  conf {layer.confidence}"
        )
        ax.text(
            0.02,
            (layer.base_m + layer.top_m) / 2.0,
            label,
            transform=ax.get_yaxis_transform(),
            fontsize=8,
            va="center",
            bbox=dict(boxstyle="round", facecolor="white", alpha=0.7),
        )


def _add_wind_barbs(ax, profile: NormalizedProfile, height: np.ndarray) -> None:
    u = np.asarray(profile.u_wind_m_s, dtype=float)
    v = np.asarray(profile.v_wind_m_s, dtype=float)
    finite = np.isfinite(u) & np.isfinite(v) & np.isfinite(height)
    if not finite.any():
        return
    # Place barbs in a fixed column at the right edge (axes-fraction x).
    x = np.full(finite.sum(), 0.96)
    ax.barbs(
        x,
        height[finite],
        u[finite],
        v[finite],
        transform=ax.get_yaxis_transform(),
        length=6,
    )


def _title(profile: NormalizedProfile, cached: bool) -> str:
    status = "cached" if cached else "live"
    return (
        f"{profile.source_label}\n"
        f"valid {profile.valid_time.isoformat()}  ·  run {profile.run_time.isoformat()}\n"
        f"({profile.lat:.2f}, {profile.lon:.2f})  ·  {status}"
    )
