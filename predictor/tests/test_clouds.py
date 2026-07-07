"""Unit tests for multi-layer cloud diagnosis (#10)."""
from datetime import datetime, timezone

import numpy as np
import pytest

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


def test_signal_margin_is_populated():
    p = _profile(
        [500, 1500, 3000, 4000, 5000, 8000],
        clw=[0, 0, 1e-4, 1e-4, 0, 0], ice=[0, 0, 0, 0, 0, 0],
    )
    layer = diagnose_clouds(p)[0]
    # Peak condensate 1e-4 over threshold 1e-6 → margin ×100.
    assert layer.signal_margin == pytest.approx(100.0)


def test_single_level_layer_has_reduced_confidence():
    p = _profile(
        [500, 1500, 3000, 5000, 8000],
        clw=[0, 0, 1e-4, 0, 0], ice=[0, 0, 0, 0, 0],
    )
    layers = diagnose_clouds(p)
    assert len(layers) == 1
    assert layers[0].confidence < 0.8  # single-level support penalized


# ---------------------------------------------------------------------------
# FA-C1: cloud optical depth from condensate (manual §1.3.2)
# τ = 1.5·∫ρ·q dz / (ρ_cond·r_e); dense liquid low cloud opaque (τ>10), cirrus τ<1.
# ---------------------------------------------------------------------------


def test_liquid_layer_optical_depth_is_opaque():
    p = _profile(
        [500, 1500, 2000, 3000, 4000, 8000],
        clw=[0, 0, 5e-4, 5e-4, 0, 0], ice=[0, 0, 0, 0, 0, 0],
        temp=[288, 283, 280, 274, 268, 230],
    )
    layers = diagnose_clouds(p)
    assert len(layers) == 1
    assert np.isfinite(layers[0].optical_depth)
    assert layers[0].optical_depth > 10.0  # dense low water deck → opaque
    # Pin the value so a coefficient/unit/Q_ext slip can't hide behind the bound.
    assert layers[0].optical_depth == pytest.approx(51.8, rel=0.02)


def test_thin_cirrus_optical_depth_is_transparent():
    p = _profile(
        [500, 5000, 8000, 10000, 12000],
        clw=[0, 0, 0, 0, 0], ice=[0, 0, 5e-6, 5e-6, 0],
        temp=[288, 250, 230, 220, 215],
    )
    layers = diagnose_clouds(p)
    assert len(layers) == 1
    assert 0.0 < layers[0].optical_depth < 1.0  # ice + large crystals → transparent
    # Pin it: would read ~1.07 (fails) if ice used liquid optics — locks the ice path.
    assert layers[0].optical_depth == pytest.approx(0.389, rel=0.03)


def test_optical_depth_increases_with_condensate():
    geom = dict(heights=[500, 1500, 2000, 3000, 4000, 8000],
                temp=[288, 283, 280, 274, 268, 230])
    light = diagnose_clouds(_profile(clw=[0, 0, 3e-4, 3e-4, 0, 0], ice=[0] * 6, **geom))
    dense = diagnose_clouds(_profile(clw=[0, 0, 9e-4, 9e-4, 0, 0], ice=[0] * 6, **geom))
    assert dense[0].optical_depth > light[0].optical_depth


def test_low_water_more_opaque_than_high_cirrus():
    # The manual's point, now from real content: a thin dense low water deck is
    # optically thicker than a deep wispy cirrus.
    low = diagnose_clouds(_profile(
        [500, 1500, 2000, 2500, 4000, 8000],
        clw=[0, 0, 5e-4, 5e-4, 0, 0], ice=[0] * 6, temp=[288, 283, 280, 277, 268, 230],
    ))
    cirrus = diagnose_clouds(_profile(
        [500, 5000, 8000, 11000, 12000],
        clw=[0] * 5, ice=[0, 0, 5e-6, 5e-6, 0], temp=[288, 250, 230, 218, 215],
    ))
    assert low[0].optical_depth > cirrus[0].optical_depth


def test_rh_diagnosed_layer_has_nan_optical_depth():
    # No condensate reported → RH-fallback layer carries no optical depth.
    p = _profile([500, 1500, 3000, 4000, 6000, 8000],
                 rh=[30, 30, 95, 95, 30, 30])  # clw/ice default NaN
    layers = diagnose_clouds(p)
    assert len(layers) == 1
    assert layers[0].source == "rh"
    assert np.isnan(layers[0].optical_depth)


def test_single_level_condensate_layer_optical_depth_nan():
    # One in-cloud level can't be trapezoid-integrated → NaN (falls back later).
    p = _profile([500, 1500, 3000, 5000, 8000], clw=[0, 0, 1e-4, 0, 0], ice=[0] * 5)
    layers = diagnose_clouds(p)
    assert len(layers) == 1
    assert np.isnan(layers[0].optical_depth)


# ---------------------------------------------------------------------------
# FA-C6: virga (落幡) lowering the effective base
# ---------------------------------------------------------------------------

_VIRGA_HEIGHTS = [500, 1500, 2500, 3500, 4500, 5500, 6500, 7500]
_COLD_AT_BASE = [285, 280, 275, 270, 265, 258, 250, 242]  # T(5500 m) = −15 °C
_THICK_ICE = [0, 0, 0, 0, 0, 1e-3, 1e-3, 1e-3]            # τ ≫ 1 ice deck 5.5–7.5 km


def _virga_rh(humid_levels):
    return [70.0 if h in humid_levels else 30.0 for h in _VIRGA_HEIGHTS]


def test_cold_precipitating_layer_with_humid_subbase_gets_virga_capped():
    # Cold (−15 °C) thick ice deck over a deep contiguous humid layer: the fall
    # streaks reach down through it, capped at the configured maximum.
    p = _profile(
        _VIRGA_HEIGHTS, ice=_THICK_ICE, temp=_COLD_AT_BASE,
        rh=_virga_rh({2500, 3500, 4500}),
    )
    (layer,) = diagnose_clouds(p)
    assert layer.virga_extension_m == pytest.approx(1500.0)  # cap bites (raw 2500)


def test_virga_stops_at_the_first_dry_sublayer():
    # Only the level right under the base is humid; the streaks evaporate at
    # the dry layer below it.
    p = _profile(
        _VIRGA_HEIGHTS, ice=_THICK_ICE, temp=_COLD_AT_BASE,
        rh=_virga_rh({4500}),
    )
    (layer,) = diagnose_clouds(p)
    assert layer.virga_extension_m == pytest.approx(500.0)  # base 5000 → 4500


def test_warm_base_layer_gets_no_virga():
    # +5 °C base: no ice-phase fall-streak propensity (manual: 落幡 is a cold
    # altocumulus / high-cloud phenomenon).
    warm = [295, 292, 289, 286, 283, 278, 272, 266]
    p = _profile(
        _VIRGA_HEIGHTS, ice=_THICK_ICE, temp=warm, rh=_virga_rh({2500, 3500, 4500}),
    )
    (layer,) = diagnose_clouds(p)
    assert layer.virga_extension_m == 0.0


def test_dry_subbase_gets_no_virga():
    p = _profile(_VIRGA_HEIGHTS, ice=_THICK_ICE, temp=_COLD_AT_BASE, rh=_virga_rh(set()))
    (layer,) = diagnose_clouds(p)
    assert layer.virga_extension_m == 0.0


def test_optically_thin_layer_gets_no_virga():
    # Barely-detected wisp (τ < 1): nothing substantial to shed.
    thin = [0, 0, 0, 0, 0, 2e-6, 2e-6, 2e-6]
    p = _profile(
        _VIRGA_HEIGHTS, ice=thin, temp=_COLD_AT_BASE, rh=_virga_rh({2500, 3500, 4500}),
    )
    layers = diagnose_clouds(p)
    assert len(layers) == 1
    assert layers[0].virga_extension_m == 0.0
