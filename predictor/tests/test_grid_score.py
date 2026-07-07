"""Vectorized grid scoring matches the scalar predictor (#19)."""
from datetime import datetime, timezone

import numpy as np

from predictor.fetch import FakeSource, WeatherSnapshot
from predictor.grid_score import GridInputs, score_grid
from predictor.rules import standard_predictor

_T = datetime(2026, 6, 23, 11, 0, tzinfo=timezone.utc)


def _scalar_predictor():
    dummy = WeatherSnapshot(0, 0, 0, 0, "x", _T)
    return standard_predictor(FakeSource(dummy))


def _scalar_score(low, mid, high, humidity, visibility):
    snap = WeatherSnapshot(
        cloud_low_pct=low, cloud_mid_pct=mid, cloud_high_pct=high, humidity_pct=humidity,
        source_label="cell", retrieved_at=_T, visibility_m=visibility,
        sunset_time=_T,  # scored AT sunset → solar_angle gate = 1.0
    )
    return _scalar_predictor().score_snapshot(snap, 31.0, 121.0, _T).probability


def test_grid_matches_scalar_predictor_within_tolerance():
    low = np.array([[5.0, 40.0], [10.0, 0.0]])
    mid = np.array([[55.0, 20.0], [70.0, 0.0]])
    high = np.array([[40.0, 10.0], [10.0, 0.0]])
    humidity = np.array([[60.0, 85.0], [50.0, 30.0]])
    visibility = np.array([[25000.0, 8000.0], [30000.0, 25000.0]])

    grid = score_grid(GridInputs(low, mid, high, humidity, visibility_m=visibility))

    for j in range(2):
        for i in range(2):
            scalar = _scalar_score(low[j, i], mid[j, i], high[j, i], humidity[j, i], visibility[j, i])
            assert abs(grid[j, i] - scalar) < 1e-9, f"cell ({j},{i}): {grid[j,i]} vs {scalar}"


def test_absent_canvas_gates_to_zero():
    grid = score_grid(GridInputs(
        cloud_low_pct=np.array([[10.0]]), cloud_mid_pct=np.array([[0.0]]),
        cloud_high_pct=np.array([[0.0]]), humidity_pct=np.array([[60.0]]),
        visibility_m=np.array([[25000.0]]),
    ))
    assert grid[0, 0] == 0.0


def test_heavy_low_cloud_gates_to_zero():
    grid = score_grid(GridInputs(
        cloud_low_pct=np.array([[100.0]]), cloud_mid_pct=np.array([[60.0]]),
        cloud_high_pct=np.array([[40.0]]), humidity_pct=np.array([[60.0]]),
        visibility_m=np.array([[25000.0]]),
    ))
    assert grid[0, 0] == 0.0


def test_aod_path_matches_scalar():
    # When AOD is supplied it takes precedence over visibility, matching LocalAerosolPerception.
    low = np.array([[5.0]]); mid = np.array([[55.0]]); high = np.array([[40.0]])
    humidity = np.array([[60.0]]); aod = np.array([[0.25]])
    grid = score_grid(GridInputs(low, mid, high, humidity, aerosol_optical_depth=aod))

    snap = WeatherSnapshot(
        cloud_low_pct=5.0, cloud_mid_pct=55.0, cloud_high_pct=40.0, humidity_pct=60.0,
        source_label="cell", retrieved_at=_T, aerosol_optical_depth=0.25, sunset_time=_T,
    )
    scalar = _scalar_predictor().score_snapshot(snap, 31.0, 121.0, _T).probability
    assert abs(grid[0, 0] - scalar) < 1e-9


def test_optional_sunward_gate_blocks_cloud_deck_without_reachable_edge():
    base_kwargs = dict(
        cloud_low_pct=np.array([[5.0]]),
        cloud_mid_pct=np.array([[55.0]]),
        cloud_high_pct=np.array([[40.0]]),
        humidity_pct=np.array([[60.0]]),
        visibility_m=np.array([[25000.0]]),
        cloud_base_m=np.array([[3500.0]]),
        sunward_profile_max_km=np.array([[800.0]]),
        sunward_aod_mean=np.array([[0.02]]),
    )

    no_edge = score_grid(GridInputs(
        **base_kwargs,
        sunward_cloud_boundary_km=np.array([[np.nan]]),
    ))
    near_edge = score_grid(GridInputs(
        **base_kwargs,
        sunward_cloud_boundary_km=np.array([[100.0]]),
    ))

    assert no_edge[0, 0] == 0.0
    assert near_edge[0, 0] > 0.0


def test_missing_clean_air_signals_are_neutral_like_scalar():
    # When neither visibility nor AOD is available, both sides omit the clean_air
    # component (FA-A3 missing-data contract) — parity must hold.
    low = np.array([[5.0]]); mid = np.array([[55.0]]); high = np.array([[40.0]])
    humidity = np.array([[60.0]])
    grid = score_grid(GridInputs(low, mid, high, humidity))

    scalar = _scalar_score(5.0, 55.0, 40.0, 60.0, None)
    assert abs(grid[0, 0] - scalar) < 1e-9


def test_output_shape_and_range():
    shape = (12, 20)
    rng = np.linspace(0, 100, shape[0] * shape[1]).reshape(shape)
    grid = score_grid(GridInputs(
        cloud_low_pct=rng * 0.3, cloud_mid_pct=rng * 0.6, cloud_high_pct=rng * 0.4,
        humidity_pct=rng, visibility_m=np.full(shape, 25000.0),
    ))
    assert grid.shape == shape
    assert np.all((grid >= 0.0) & (grid <= 1.0))


def test_heavy_local_aerosol_dims_but_does_not_zero_grid():
    # FA-A3: perception aerosol is a modifier — an AOD in the "污烧" band drags
    # quality down without zeroing the probability, and stays in lockstep with
    # the scalar predictor.
    low = np.array([[5.0]]); mid = np.array([[55.0]]); high = np.array([[40.0]])
    humidity = np.array([[60.0]]); aod = np.array([[0.9]])
    grid = score_grid(GridInputs(low, mid, high, humidity, aerosol_optical_depth=aod))

    snap = WeatherSnapshot(
        cloud_low_pct=5.0, cloud_mid_pct=55.0, cloud_high_pct=40.0, humidity_pct=60.0,
        source_label="cell", retrieved_at=_T, aerosol_optical_depth=0.9, sunset_time=_T,
    )
    scalar = _scalar_predictor().score_snapshot(snap, 31.0, 121.0, _T).probability
    assert grid[0, 0] > 0.0
    assert abs(grid[0, 0] - scalar) < 1e-9
