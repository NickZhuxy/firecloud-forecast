"""Tests for #59 affordable national physics approximations."""
from __future__ import annotations

import numpy as np

from predictor.national_physics import build_sunward_screen


def test_sunward_screen_detects_western_cloud_edge():
    lats = np.array([29.0, 30.0, 31.0])
    lons = np.array([100.0, 101.0, 102.0, 103.0, 104.0])
    low = np.zeros((3, 5))
    mid = np.tile(np.array([[0.0, 0.0, 5.0, 70.0, 70.0]]), (3, 1))
    high = np.zeros((3, 5))
    event_times = np.full((3, 5), np.datetime64("2026-06-22T11:00:00", "s"))

    screen = build_sunward_screen(
        lats,
        lons,
        low,
        mid,
        high,
        event_times,
        distances_km=(0.0, 100.0, 200.0, 300.0),
        azimuth_deg=270.0,
    )

    assert np.isfinite(screen.sunward_cloud_boundary_km[1, 4])
    assert screen.sunward_cloud_boundary_km[1, 4] > 0.0
    assert screen.cloud_base_m[1, 4] == 3500.0
    assert screen.sampled_points > 0
