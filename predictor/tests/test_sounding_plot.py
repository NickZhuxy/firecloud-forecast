"""Unit tests for the sounding plot (#8) — headless, no network."""
from datetime import datetime, timezone

import numpy as np
from matplotlib.figure import Figure

from predictor.clouds import CloudLayer
from predictor.profiles import NormalizedProfile
from predictor.sounding_plot import plot_sounding


def _profile() -> NormalizedProfile:
    n = 6
    h = np.array([500.0, 1500.0, 3000.0, 5000.0, 8000.0, 11000.0])
    return NormalizedProfile(
        lat=31.23, lon=121.47,
        pressure_hpa=np.array([950.0, 850.0, 700.0, 500.0, 350.0, 250.0]),
        geometric_height_m=h,
        geopotential_height_m=h,
        temperature_k=np.array([293.0, 286.0, 276.0, 258.0, 238.0, 223.0]),
        relative_humidity_pct=np.array([60, 80, 90, 70, 40, 30.0]),
        dewpoint_k=np.array([285.0, 283.0, 274.0, 250.0, 225.0, 210.0]),
        specific_humidity_kg_kg=np.full(n, 0.003),
        u_wind_m_s=np.array([2, 5, 10, 20, 30, 25.0]),
        v_wind_m_s=np.array([1, 2, -3, 5, -10, 0.0]),
        vertical_velocity_pa_s=np.zeros(n),
        cloud_water_kg_kg=np.full(n, np.nan),
        cloud_ice_kg_kg=np.full(n, np.nan),
        run_time=datetime(2026, 6, 23, 0, tzinfo=timezone.utc),
        valid_time=datetime(2026, 6, 23, 6, tzinfo=timezone.utc),
        source_label="gfs@2026-06-23T00Z+f06",
        retrieved_at=datetime(2026, 6, 23, 5, tzinfo=timezone.utc),
        missing=[],
    )


def _layers() -> list[CloudLayer]:
    return [CloudLayer(1500.0, 3200.0, 1700.0, "liquid", 0.8, "condensate")]


def _all_text(fig: Figure) -> str:
    parts = [fig._suptitle.get_text() if fig._suptitle else ""]
    for ax in fig.axes:
        parts += [ax.get_title(), ax.get_xlabel(), ax.get_ylabel()]
        parts += [t.get_text() for t in ax.texts]
    return "\n".join(parts)


def test_returns_figure_with_temp_and_dewpoint():
    fig = plot_sounding(_profile(), _layers())
    assert isinstance(fig, Figure)
    ax = fig.axes[0]
    labels = " ".join(line.get_label().lower() for line in ax.get_lines())
    assert "temp" in labels
    assert "dew" in labels


def test_annotates_cloud_layer_metrics():
    text = _all_text(plot_sounding(_profile(), _layers()))
    assert "1500" in text and "3200" in text   # base / top
    assert "0.8" in text                        # confidence
    assert "liquid" in text                     # phase hint


def test_title_has_model_times_location_and_cache_status():
    text = _all_text(plot_sounding(_profile(), _layers(), cached=True))
    assert "gfs@2026-06-23T00Z+f06" in text
    assert "2026-06-23" in text                 # valid time
    assert "31.23" in text and "121.47" in text  # location
    assert "cached" in text.lower()


def test_live_vs_cached_label():
    text = _all_text(plot_sounding(_profile(), _layers(), cached=False))
    assert "live" in text.lower()


def test_wind_barbs_present():
    fig = plot_sounding(_profile(), _layers())
    # barbs add a Barbs collection to some axis.
    from matplotlib.quiver import Barbs
    assert any(
        isinstance(c, Barbs) for ax in fig.axes for c in ax.collections
    )


def test_no_layers_still_plots():
    fig = plot_sounding(_profile(), [])
    assert isinstance(fig, Figure)
