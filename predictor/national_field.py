"""Assemble the national quality field from one GFS read (#19).

Ties the GFS surface-grid reader (one read + decode for the whole region) to the
vectorized grid scorer, replacing the ~190-point per-request Open-Meteo overview
with a ~25 km GFS field. Records data volume, runtime and peak memory.
"""
from __future__ import annotations

import time
import tracemalloc
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from predictor.grid_score import GridInputs, score_grid


@dataclass
class NationalField:
    lats: np.ndarray         # 1-D, ascending (south → north)
    lons: np.ndarray         # 1-D, ascending (west → east)
    probability: np.ndarray  # (ny, nx)
    valid_time: datetime
    source_label: str
    n_points: int
    runtime_s: float
    peak_mem_mb: float


def _finite(arr: np.ndarray, default: float) -> np.ndarray:
    a = np.asarray(arr, dtype=float)
    return np.where(np.isfinite(a), a, default)


def build_national_field(gfs_source, bbox, valid_time: datetime) -> NationalField:
    """One GFS read → vectorized national quality field, with perf metrics.

    ``gfs_source`` must expose ``fetch_surface_grid(bbox, valid_time)``. Missing
    humidity/visibility cells fall back to neutral defaults so a gap never zeroes
    a cell. Latitudes are returned ascending for rendering.
    """
    tracemalloc.start()
    t0 = time.perf_counter()

    grid = gfs_source.fetch_surface_grid(bbox, valid_time)
    order = np.argsort(grid.lats)  # GFS latitudes run north→south; flip ascending
    inputs = GridInputs(
        cloud_low_pct=grid.cloud_low_pct[order],
        cloud_mid_pct=grid.cloud_mid_pct[order],
        cloud_high_pct=grid.cloud_high_pct[order],
        humidity_pct=_finite(grid.humidity_pct[order], 50.0),
        visibility_m=_finite(grid.visibility_m[order], 25000.0),
    )
    probability = score_grid(inputs)

    runtime_s = time.perf_counter() - t0
    peak_mem_mb = tracemalloc.get_traced_memory()[1] / 1e6
    tracemalloc.stop()

    return NationalField(
        lats=grid.lats[order],
        lons=np.asarray(grid.lons, dtype=float),
        probability=probability,
        valid_time=grid.valid_time,
        source_label=grid.source_label,
        n_points=grid.n_points,
        runtime_s=runtime_s,
        peak_mem_mb=peak_mem_mb,
    )
