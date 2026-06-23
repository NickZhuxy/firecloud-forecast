"""Headless tests for the sunward cross-section plot (#18)."""
from datetime import datetime, timezone

import numpy as np
from matplotlib.figure import Figure

from predictor.clouds import CloudLayer
from predictor.cross_section import SunwardCrossSection, even_heights
from predictor.cross_section_plot import plot_cross_section

_T = datetime(2026, 6, 23, 10, 20, tzinfo=timezone.utc)


def _xsec(masked_far=False) -> SunwardCrossSection:
    heights = even_heights(10000.0, 11)
    n_h, n_d = len(heights), 3
    rh = np.full((n_h, n_d), 50.0)
    w = np.full((n_h, n_d), -0.1)
    t = np.linspace(290, 220, n_h)[:, None] * np.ones((1, n_d))
    mask = np.ones((n_h, n_d), dtype=bool)
    if masked_far:
        rh[:, 2] = np.nan
        w[:, 2] = np.nan
        t[:, 2] = np.nan
        mask[:, 2] = False
    return SunwardCrossSection(
        distances_km=[0.0, 400.0, 800.0],
        heights_m=heights,
        relative_humidity_pct=rh,
        vertical_velocity_pa_s=w,
        temperature_k=t,
        mask=mask,
        cloud_layers=[
            [CloudLayer(2000.0, 4000.0, 2000.0, "ice", 0.8, "condensate", signal_margin=10.0)],
            [], [],
        ],
        observer=(31.0, 121.0),
        azimuth_deg=290.0,
        target_time=_T,
        source_label="gfs@2026-06-23T00Z+f10",
    )


def _all_text(fig: Figure) -> str:
    parts = [fig._suptitle.get_text() if fig._suptitle else ""]
    for ax in fig.axes:
        parts += [ax.get_title(), ax.get_xlabel(), ax.get_ylabel()]
        parts += [t.get_text() for t in ax.texts]
    return "\n".join(parts)


def test_returns_figure_with_rh_mesh():
    from matplotlib.collections import QuadMesh

    fig = plot_cross_section(_xsec())
    assert isinstance(fig, Figure)
    assert any(isinstance(c, QuadMesh) for ax in fig.axes for c in ax.collections)


def test_axes_are_distance_by_height():
    fig = plot_cross_section(_xsec())
    ax = fig.axes[0]
    assert "km" in ax.get_xlabel().lower()
    assert "height" in ax.get_ylabel().lower() or "m" in ax.get_ylabel().lower()


def test_title_has_source_observer_azimuth():
    text = _all_text(plot_cross_section(_xsec()))
    assert "gfs@2026-06-23T00Z+f10" in text
    assert "31.0" in text and "121.0" in text
    assert "290" in text          # sun azimuth marked


def test_cloud_layer_drawn():
    fig = plot_cross_section(_xsec())
    # The diagnosed layer is drawn as a line segment somewhere on the axes.
    assert any(len(ax.get_lines()) > 0 for ax in fig.axes)


def test_out_of_coverage_marked():
    text = _all_text(plot_cross_section(_xsec(masked_far=True)))
    assert "no data" in text.lower() or "coverage" in text.lower()
