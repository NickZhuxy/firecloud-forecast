"""Unit tests for multi-layer cloud diagnosis (#10)."""
from datetime import datetime, timezone

import numpy as np

from predictor.clouds import CloudLayer, diagnose_clouds
from predictor.profiles import NormalizedProfile


def _profile(heights, *, clw=None, ice=None, rh=None, temp=None) -> NormalizedProfile:
    h = np.asarray(heights, dtype=float)
    n = h.size
    nan = np.full(n, np.nan)
    return NormalizedProfile(
        lat=31.0, lon=121.0,
        pressure_hpa=np.linspace(900, 200, n),
        geometric_height_m=h,
        geopotential_height_m=h,
        temperature_k=np.asarray(temp, dtype=float) if temp is not None else np.full(n, 270.0),
        relative_humidity_pct=np.asarray(rh, dtype=float) if rh is not None else np.full(n, 30.0),
        dewpoint_k=np.full(n, 260.0),
        specific_humidity_kg_kg=np.full(n, 0.001),
        u_wind_m_s=np.zeros(n), v_wind_m_s=np.zeros(n),
        vertical_velocity_pa_s=np.zeros(n),
        cloud_water_kg_kg=np.asarray(clw, dtype=float) if clw is not None else nan.copy(),
        cloud_ice_kg_kg=np.asarray(ice, dtype=float) if ice is not None else nan.copy(),
        run_time=datetime(2026, 6, 23, 0, tzinfo=timezone.utc),
        valid_time=datetime(2026, 6, 23, 6, tzinfo=timezone.utc),
        source_label="gfs@test", retrieved_at=datetime(2026, 6, 23, 5, tzinfo=timezone.utc),
        missing=[],
    )


def test_no_cloud_returns_empty():
    p = _profile([500, 1500, 3000, 5000], clw=[0, 0, 0, 0], ice=[0, 0, 0, 0])
    assert diagnose_clouds(p) == []


def test_single_condensate_layer():
    p = _profile(
        [500, 1500, 3000, 4000, 5000, 8000],
        clw=[0, 0, 1e-4, 1e-4, 0, 0], ice=[0, 0, 0, 0, 0, 0],
    )
    layers = diagnose_clouds(p)
    assert len(layers) == 1
    layer = layers[0]
    assert isinstance(layer, CloudLayer)
    assert 1500 < layer.base_m < 3001
    assert 4000 <= layer.top_m < 5000
    assert layer.thickness_m == layer.top_m - layer.base_m
    assert layer.source == "condensate"
    assert layer.phase_hint == "liquid"
    assert layer.confidence == 0.8


def test_two_layers_separated_by_large_gap():
    p = _profile(
        [500, 1500, 3000, 5000, 7000, 9000],
        clw=[1e-4, 1e-4, 0, 0, 1e-4, 1e-4], ice=[0, 0, 0, 0, 0, 0],
    )
    layers = diagnose_clouds(p)
    assert len(layers) == 2
    assert layers[0].base_m < layers[1].base_m


def test_small_gap_is_merged():
    p = _profile(
        [500, 800, 1000, 1300],
        clw=[1e-4, 0, 1e-4, 1e-4], ice=[0, 0, 0, 0],
    )
    # One clear level at 800 m; midpoint boundaries leave a 250 m gap
    # (< merge_gap 300 m) → single merged layer.
    layers = diagnose_clouds(p)
    assert len(layers) == 1


def test_rh_fallback_when_condensate_missing_lowers_confidence():
    p = _profile(
        [500, 1500, 3000, 4000, 5000],
        rh=[40, 95, 95, 40, 40],  # condensate left as NaN → RH path
    )
    layers = diagnose_clouds(p)
    assert len(layers) == 1
    assert layers[0].source == "rh"
    assert layers[0].confidence <= 0.5


def test_below_ground_levels_ignored():
    p = _profile(
        [-200, 500, 1500, 3000, 5000],
        clw=[1e-3, 0, 0, 0, 0], ice=[0, 0, 0, 0, 0],
    )
    # The only condensate sits at a below-ground level → ignored → no cloud.
    assert diagnose_clouds(p) == []


def test_ice_phase_hint_from_dominant_ice_condensate():
    p = _profile(
        [500, 6000, 8000, 10000, 12000],
        clw=[0, 0, 0, 0, 0], ice=[0, 0, 1e-4, 1e-4, 0],
        temp=[290, 250, 240, 235, 230],
    )
    layers = diagnose_clouds(p)
    assert len(layers) == 1
    assert layers[0].phase_hint == "ice"


def test_condensate_boundaries_use_midpoint_not_threshold_crossing():
    # Condensate is a step (0 → large), so a near-zero threshold crossing would
    # pin the edge onto the adjacent clear level and inflate thickness. The
    # boundary should instead sit at the half-gap midpoint.
    p = _profile(
        [500, 1500, 3000, 4000, 5000, 8000],
        clw=[0, 0, 1e-4, 1e-4, 0, 0], ice=[0, 0, 0, 0, 0, 0],
    )
    layer = diagnose_clouds(p)[0]
    assert layer.base_m == 2250.0   # midpoint(1500, 3000)
    assert layer.top_m == 4500.0    # midpoint(4000, 5000)


def test_rh_path_still_interpolates_the_crossing():
    p = _profile(
        [500, 1500, 3000, 4000, 5000],
        rh=[40, 95, 95, 40, 40],
    )
    layer = diagnose_clouds(p)[0]
    # Signal genuinely ramps for RH → interpolate, not a midpoint (which is 1000).
    assert 1350 < layer.base_m < 1450


def test_single_level_layer_has_reduced_confidence():
    p = _profile(
        [500, 1500, 3000, 5000, 8000],
        clw=[0, 0, 1e-4, 0, 0], ice=[0, 0, 0, 0, 0],
    )
    layers = diagnose_clouds(p)
    assert len(layers) == 1
    assert layers[0].confidence < 0.8  # single-level support penalized
