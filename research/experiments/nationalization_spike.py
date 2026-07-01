"""Offline benchmark for #58 intelligent nationalization research.

The script deliberately uses synthetic but spatially structured weather fields:
it is a repeatable harness for comparing nationwide approximations against the
current detailed single-point path without touching production national code.
Run from the repository root:

    PYTHONPATH=. uv run --no-sync python research/experiments/nationalization_spike.py
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from predictor.clouds import diagnose_clouds
from predictor.fetch import WeatherSnapshot
from predictor.features import derive
from predictor.grid_score import GridInputs, score_grid
from predictor.normalize import normalize
from predictor.profiles import AtmosphericCube
from predictor.rules import standard_predictor
from predictor.spatial import SunwardProfile, sunward_coordinates
from predictor.sunward_section import score_point_with_cube

VALID_TIME = datetime(2026, 7, 1, 10, tzinfo=timezone.utc)
AZIMUTH_DEG = 270.0
TRUTH_DISTANCES_KM = tuple(float(d) for d in range(0, 801, 25))


@dataclass(frozen=True)
class GridSpec:
    lats: np.ndarray
    lons: np.ndarray

    @property
    def shape(self) -> tuple[int, int]:
        return (self.lats.size, self.lons.size)

    @property
    def size(self) -> int:
        return int(self.lats.size * self.lons.size)


class SyntheticSource:
    def __init__(self, distances_km: tuple[float, ...] | list[float]):
        self.distances_km = tuple(float(d) for d in distances_km)

    def fetch(self, lat: float, lon: float, time: datetime) -> WeatherSnapshot:
        distances = list(self.distances_km)
        coords = sunward_coordinates(lat, lon, AZIMUTH_DEG, distances)
        low = [_low_cloud_pct(la, lo) for la, lo in coords]
        mid = [_mid_cloud_pct(la, lo) for la, lo in coords]
        high = [_high_cloud_pct(la, lo) for la, lo in coords]
        aod = [_aod(la, lo) for la, lo in coords]
        return WeatherSnapshot(
            cloud_low_pct=low[0],
            cloud_mid_pct=mid[0],
            cloud_high_pct=high[0],
            humidity_pct=_humidity_pct(lat, lon),
            visibility_m=_visibility_m(lat, lon),
            aerosol_optical_depth=aod[0],
            source_label="synthetic-nationalization-spike",
            retrieved_at=time,
            sunset_time=time,
            wind_speed_850_m_s=7.0,
            wind_direction_850_deg=250.0,
            wind_speed_700_m_s=11.0,
            wind_direction_700_deg=265.0,
            wind_speed_400_m_s=18.0,
            wind_direction_400_deg=275.0,
            sunward_profile=SunwardProfile(
                azimuth_deg=AZIMUTH_DEG,
                distances_km=distances,
                cloud_low_pct=low,
                cloud_mid_pct=mid,
                cloud_high_pct=high,
                aerosol_optical_depth=aod,
                wind_speed_850_m_s=[7.0 for _ in distances],
                wind_direction_850_deg=[250.0 for _ in distances],
                wind_speed_700_m_s=[11.0 for _ in distances],
                wind_direction_700_deg=[265.0 for _ in distances],
                wind_speed_400_m_s=[18.0 for _ in distances],
                wind_direction_400_deg=[275.0 for _ in distances],
            ),
        )


def _sigmoid(x: float | np.ndarray) -> float | np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def _cloud_edge_lon(lat: float) -> float:
    return 101.5 + 2.5 * np.sin((lat - 27.0) / 6.0)


def _canvas_pct(lat: float, lon: float) -> float:
    edge = _cloud_edge_lon(lat)
    broad_shield = 82.0 * _sigmoid((lon - edge) / 1.35)
    meridional = 0.65 + 0.35 * np.exp(-((lat - 34.0) / 8.5) ** 2)
    wave = 8.0 * np.sin((lon - 108.0) / 4.5) * np.cos((lat - 33.0) / 5.0)
    return float(np.clip(broad_shield * meridional + wave, 0.0, 95.0))


def _mid_cloud_pct(lat: float, lon: float) -> float:
    canvas = _canvas_pct(lat, lon)
    mid_bias = 0.70 + 0.10 * np.cos((lat - 32.0) / 4.0)
    return float(np.clip(canvas * mid_bias, 0.0, 95.0))


def _high_cloud_pct(lat: float, lon: float) -> float:
    canvas = _canvas_pct(lat, lon)
    jet_streak = 26.0 * np.exp(-((lat - 39.0) / 4.0) ** 2) * _sigmoid((lon - 105.0) / 3.0)
    return float(np.clip(canvas * 0.46 + jet_streak, 0.0, 95.0))


def _low_cloud_pct(lat: float, lon: float) -> float:
    coastal_deck = 64.0 * np.exp(-((lat - 30.5) / 3.7) ** 2 - ((lon - 116.0) / 4.8) ** 2)
    basin_deck = 38.0 * np.exp(-((lat - 29.0) / 4.0) ** 2 - ((lon - 103.5) / 4.2) ** 2)
    background = 8.0 + 5.0 * np.sin((lat + lon) / 6.5)
    return float(np.clip(background + coastal_deck + basin_deck, 0.0, 98.0))


def _humidity_pct(lat: float, lon: float) -> float:
    moist_east = 22.0 * _sigmoid((lon - 111.0) / 3.5)
    dry_north = -10.0 * _sigmoid((lat - 39.0) / 2.5)
    local = 8.0 * np.cos((lat - 31.0) / 5.5) * np.cos((lon - 108.0) / 6.0)
    return float(np.clip(52.0 + moist_east + dry_north + local, 25.0, 94.0))


def _aod(lat: float, lon: float) -> float:
    haze_basin = 0.22 * np.exp(-((lat - 31.0) / 4.2) ** 2 - ((lon - 103.0) / 5.2) ** 2)
    haze_east = 0.10 * np.exp(-((lat - 34.0) / 6.0) ** 2 - ((lon - 116.0) / 6.5) ** 2)
    west_path = 0.035 * _sigmoid((102.0 - lon) / 3.0)
    clean_corridor = -0.018 * np.exp(-((lat - 40.0) / 5.5) ** 2 - ((lon - 103.0) / 4.5) ** 2)
    return float(np.clip(0.028 + haze_basin + haze_east + west_path + clean_corridor, 0.015, 0.75))


def _visibility_m(lat: float, lon: float) -> float:
    return float(np.clip(26000.0 * (1.0 - 0.85 * _aod(lat, lon)), 5000.0, 26000.0))


def _synthetic_cube() -> AtmosphericCube:
    lats = np.arange(18.0, 47.01, 1.0)
    lons = np.arange(72.0, 128.01, 1.0)
    levels = np.array([925.0, 850.0, 700.0, 500.0, 400.0, 300.0])
    heights = np.array([750.0, 1500.0, 3000.0, 5500.0, 7200.0, 9000.0])
    temps = np.array([285.0, 280.0, 270.0, 255.0, 245.0, 233.0])
    q = np.array([5e-3, 4e-3, 2e-3, 8e-4, 3e-4, 1e-4])
    nz, ny, nx = levels.size, lats.size, lons.size

    temperature = np.empty((nz, ny, nx), dtype=float)
    rh = np.empty_like(temperature)
    specific_humidity = np.empty_like(temperature)
    geopotential_height = np.empty_like(temperature)
    u_wind = np.empty_like(temperature)
    v_wind = np.empty_like(temperature)
    vertical_velocity = np.zeros_like(temperature)
    cloud_water = np.zeros_like(temperature)
    cloud_ice = np.zeros_like(temperature)

    for j, lat in enumerate(lats):
        for i, lon in enumerate(lons):
            low = _low_cloud_pct(float(lat), float(lon))
            mid = _mid_cloud_pct(float(lat), float(lon))
            high = _high_cloud_pct(float(lat), float(lon))
            hum = _humidity_pct(float(lat), float(lon))
            for k in range(nz):
                temperature[k, j, i] = temps[k] - 0.25 * (lat - 32.0)
                rh[k, j, i] = np.clip(hum + (8.0 if k in (2, 3) else 0.0), 10.0, 99.0)
                specific_humidity[k, j, i] = q[k]
                geopotential_height[k, j, i] = heights[k]
                u_wind[k, j, i] = 6.0 + 0.15 * (lon - 100.0)
                v_wind[k, j, i] = -2.0 + 0.08 * (lat - 30.0)
            if low >= 22.0:
                cloud_water[0:2, j, i] = (low / 100.0) * np.array([2.5e-4, 3.5e-4])
            if mid >= 14.0:
                cloud_water[2:4, j, i] = (mid / 100.0) * np.array([1.8e-4, 1.3e-4])
            if high >= 16.0:
                cloud_ice[4:6, j, i] = (high / 100.0) * np.array([6.0e-5, 4.0e-5])

    return AtmosphericCube(
        lats=lats,
        lons=lons,
        levels_hpa=levels,
        temperature_k=temperature,
        relative_humidity_pct=rh,
        specific_humidity_kg_kg=specific_humidity,
        geopotential_height_m=geopotential_height,
        u_wind_m_s=u_wind,
        v_wind_m_s=v_wind,
        vertical_velocity_pa_s=vertical_velocity,
        cloud_water_kg_kg=cloud_water,
        cloud_ice_kg_kg=cloud_ice,
        run_time=VALID_TIME,
        valid_time=VALID_TIME,
        source_label="synthetic-gfs@nationalization-spike",
        retrieved_at=VALID_TIME,
        missing=[],
    )


def _grid() -> GridSpec:
    return GridSpec(
        lats=np.linspace(24.0, 43.0, 9),
        lons=np.linspace(96.0, 122.0, 14),
    )


def _for_each_cell(grid: GridSpec):
    for j, lat in enumerate(grid.lats):
        for i, lon in enumerate(grid.lons):
            yield j, i, float(lat), float(lon)


def _aod_fn(lat: float, lon: float) -> float:
    return _aod(lat, lon)


def _full_scores(
    grid: GridSpec,
    cube: AtmosphericCube,
    distances_km: tuple[float, ...] | list[float],
) -> tuple[np.ndarray, float]:
    predictor = standard_predictor(SyntheticSource(distances_km))
    out = np.empty(grid.shape, dtype=float)
    t0 = time.perf_counter()
    for j, i, lat, lon in _for_each_cell(grid):
        out[j, i] = score_point_with_cube(
            predictor,
            cube,
            predictor.source.fetch(lat, lon, VALID_TIME),
            lat,
            lon,
            VALID_TIME,
            distances_km=distances_km,
            azimuth_deg=AZIMUTH_DEG,
            aod_fn=_aod_fn,
        ).probability
    return out, time.perf_counter() - t0


def _overview_scores(grid: GridSpec) -> tuple[np.ndarray, float]:
    low = np.empty(grid.shape, dtype=float)
    mid = np.empty_like(low)
    high = np.empty_like(low)
    humidity = np.empty_like(low)
    visibility = np.empty_like(low)
    aod = np.empty_like(low)
    for j, i, lat, lon in _for_each_cell(grid):
        low[j, i] = _low_cloud_pct(lat, lon)
        mid[j, i] = _mid_cloud_pct(lat, lon)
        high[j, i] = _high_cloud_pct(lat, lon)
        humidity[j, i] = _humidity_pct(lat, lon)
        visibility[j, i] = _visibility_m(lat, lon)
        aod[j, i] = _aod(lat, lon)
    t0 = time.perf_counter()
    out = score_grid(
        GridInputs(
            cloud_low_pct=low,
            cloud_mid_pct=mid,
            cloud_high_pct=high,
            humidity_pct=humidity,
            visibility_m=visibility,
            aerosol_optical_depth=aod,
        )
    )
    return out, time.perf_counter() - t0


def _diagnosed_1d_scores(grid: GridSpec, cube: AtmosphericCube) -> tuple[np.ndarray, float]:
    distances = tuple(float(d) for d in range(0, 801, 100))
    predictor = standard_predictor(SyntheticSource(distances))
    out = np.empty(grid.shape, dtype=float)
    t0 = time.perf_counter()
    for j, i, lat, lon in _for_each_cell(grid):
        profile = normalize(cube.profile_at(lat, lon))
        layers = diagnose_clouds(profile)
        snapshot = predictor.source.fetch(lat, lon, VALID_TIME)
        out[j, i] = predictor.score_snapshot(
            snapshot,
            lat,
            lon,
            VALID_TIME,
            cloud_layers=layers,
        ).probability
    return out, time.perf_counter() - t0


def _nearest_anchor_reuse(truth: np.ndarray, stride: int) -> tuple[np.ndarray, float]:
    t0 = time.perf_counter()
    ny, nx = truth.shape
    anchor_y = np.arange(0, ny, stride)
    anchor_x = np.arange(0, nx, stride)
    if anchor_y[-1] != ny - 1:
        anchor_y = np.append(anchor_y, ny - 1)
    if anchor_x[-1] != nx - 1:
        anchor_x = np.append(anchor_x, nx - 1)
    out = np.empty_like(truth)
    for j in range(ny):
        aj = int(anchor_y[np.argmin(np.abs(anchor_y - j))])
        for i in range(nx):
            ai = int(anchor_x[np.argmin(np.abs(anchor_x - i))])
            out[j, i] = truth[aj, ai]
    return out, time.perf_counter() - t0


def _tiered_budget(overview: np.ndarray, truth: np.ndarray, band: float) -> tuple[np.ndarray, float, float]:
    t0 = time.perf_counter()
    selected = np.abs(overview - 0.50) <= band
    out = overview.copy()
    out[selected] = truth[selected]
    return out, time.perf_counter() - t0, float(selected.mean())


def _tiered_screen(screen: np.ndarray, truth: np.ndarray, threshold: float) -> tuple[np.ndarray, float, float]:
    t0 = time.perf_counter()
    selected = screen >= threshold
    out = screen.copy()
    out[selected] = truth[selected]
    return out, time.perf_counter() - t0, float(selected.mean())


def _gradient_mae(pred: np.ndarray, truth: np.ndarray) -> float:
    pred_grad = np.concatenate([np.diff(pred, axis=0).ravel(), np.diff(pred, axis=1).ravel()])
    truth_grad = np.concatenate([np.diff(truth, axis=0).ravel(), np.diff(truth, axis=1).ravel()])
    return float(np.mean(np.abs(pred_grad - truth_grad)))


def _classification(pred: np.ndarray, truth: np.ndarray, threshold: float = 0.50) -> dict[str, float | int]:
    p = pred >= threshold
    t = truth >= threshold
    tp = int(np.count_nonzero(p & t))
    fp = int(np.count_nonzero(p & ~t))
    fn = int(np.count_nonzero(~p & t))
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2.0 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": round(float(precision), 4),
        "recall": round(float(recall), 4),
        "f1": round(float(f1), 4),
    }


def _metrics(name: str, pred: np.ndarray, truth: np.ndarray, seconds: float, cost_units: float) -> dict:
    abs_err = np.abs(pred - truth)
    out = {
        "name": name,
        "mae": round(float(np.mean(abs_err)), 4),
        "rmse": round(float(np.sqrt(np.mean(abs_err ** 2))), 4),
        "p90_abs_error": round(float(np.quantile(abs_err, 0.90)), 4),
        "max_abs_error": round(float(np.max(abs_err)), 4),
        "gradient_mae": round(_gradient_mae(pred, truth), 4),
        "wall_ms": round(float(seconds * 1000.0), 2),
        "relative_physics_cost": round(float(cost_units), 4),
    }
    out.update(_classification(pred, truth))
    return out


def run() -> dict:
    grid = _grid()
    cube = _synthetic_cube()
    truth, truth_s = _full_scores(grid, cube, TRUTH_DISTANCES_KM)
    overview, overview_s = _overview_scores(grid)
    diagnosed, diagnosed_s = _diagnosed_1d_scores(grid, cube)

    candidates = [
        _metrics("current_overview_grid_score", overview, truth, overview_s, 0.02),
        _metrics("observer_diagnosis_plus_1d_sunward_100km", diagnosed, truth, diagnosed_s, 0.18),
    ]

    for step in (200, 100, 50):
        distances = tuple(float(d) for d in range(0, 801, step))
        pred, seconds = _full_scores(grid, cube, distances)
        candidates.append(
            _metrics(
                f"coarse_2d_ray_{step}km_columns",
                pred,
                truth,
                seconds,
                len(distances) / len(TRUTH_DISTANCES_KM),
            )
        )

    for stride in (4, 3, 2):
        pred, seconds = _nearest_anchor_reuse(truth, stride)
        anchor_fraction = (
            len(set(list(range(0, truth.shape[0], stride)) + [truth.shape[0] - 1]))
            * len(set(list(range(0, truth.shape[1], stride)) + [truth.shape[1] - 1]))
            / truth.size
        )
        candidates.append(
            _metrics(
                f"nearest_full_physics_anchor_stride_{stride}",
                pred,
                truth,
                seconds,
                anchor_fraction,
            )
        )

    for band in (0.10, 0.20, 0.30):
        pred, seconds, selected_fraction = _tiered_budget(overview, truth, band)
        candidates.append(
            _metrics(
                f"tiered_overview_plus_full_band_{band:.2f}",
                pred,
                truth,
                seconds,
                selected_fraction,
            )
        )

    for threshold in (0.30, 0.50, 0.70):
        pred, seconds, selected_fraction = _tiered_screen(diagnosed, truth, threshold)
        candidates.append(
            _metrics(
                f"tiered_1d_screen_plus_full_ge_{threshold:.2f}",
                pred,
                truth,
                seconds,
                0.18 + selected_fraction,
            )
        )

    return {
        "benchmark": "nationalization_spike_58",
        "valid_time": VALID_TIME.isoformat(),
        "grid_shape": list(grid.shape),
        "n_points": grid.size,
        "truth": {
            "name": "full_single_point_25km_columns",
            "distances_km": list(TRUTH_DISTANCES_KM),
            "wall_ms": round(float(truth_s * 1000.0), 2),
            "probability_min": round(float(np.min(truth)), 4),
            "probability_max": round(float(np.max(truth)), 4),
            "candidate_fraction_ge_0_50": round(float(np.mean(truth >= 0.50)), 4),
        },
        "candidates": candidates,
        "notes": [
            "relative_physics_cost is normalized to the 25 km full single-point path; overview has no pressure-level ray trace.",
            "The synthetic field contains a west-edge mid/high shield, two low-cloud obstruction regions, and spatially varying AOD.",
        ],
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = run()
    text = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
