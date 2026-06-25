"""Assemble a national field from per-cell-sunset GFS timesteps (#19, #43).

The China-wide sunset interval is bracketed by hourly GFS surface grids.  Each
cell selects the grid closest to its interpolated local sunset, then the mosaiced
cloud/RH/visibility inputs are scored once with the vectorized overview rules.
"""
from __future__ import annotations

import time
import tracemalloc
from dataclasses import dataclass
from datetime import date, datetime, timezone

import numpy as np

from predictor.grid_score import GridInputs, score_grid
from predictor.sunset_grid import (
    hourly_valid_times,
    nearest_valid_time_indices,
    sunset_utc_grid,
)


@dataclass
class NationalField:
    lats: np.ndarray         # 1-D, ascending (south → north)
    lons: np.ndarray         # 1-D, ascending (west → east)
    probability: np.ndarray  # (ny, nx)
    valid_times: tuple[datetime, ...]
    sunset_range_utc: tuple[datetime, datetime]
    source_label: str
    n_points: int
    surface_fetches: int
    additional_surface_fetches: int
    decoded_input_bytes: int
    additional_decoded_input_bytes: int
    download_bytes: int | None
    additional_download_bytes: int | None
    runtime_s: float
    peak_mem_mb: float


def _finite(arr: np.ndarray, default: float) -> np.ndarray:
    a = np.asarray(arr, dtype=float)
    return np.where(np.isfinite(a), a, default)


def _utc_datetime(value: np.datetime64) -> datetime:
    return datetime.fromtimestamp(
        int(value.astype("datetime64[s]").astype("int64")), tz=timezone.utc
    )


def _range_axis(start: float, end: float, step: float = 0.5) -> np.ndarray:
    """Inclusive coarse axis used to observe interior sunset extrema."""
    values = np.arange(start, end + step * 0.5, step, dtype=float)
    values = values[values <= end]
    if values.size == 0:
        values = np.array([start], dtype=float)
    if not np.isclose(values[-1], end):
        values = np.append(values, end)
    return values


def _active_sunsets(
    sunsets: np.ndarray,
    lats: np.ndarray,
    lons: np.ndarray,
    domain_mask,
) -> np.ndarray:
    if domain_mask is None:
        return sunsets.ravel()
    mask = np.asarray(domain_mask(lats, lons), dtype=bool)
    if mask.shape != sunsets.shape:
        raise ValueError("domain_mask must return one boolean per grid cell")
    if not mask.any():
        raise ValueError("domain_mask excludes every grid cell")
    return sunsets[mask]


def _ordered(grid):
    lat_order = np.argsort(np.asarray(grid.lats, dtype=float))
    lon_order = np.argsort(np.asarray(grid.lons, dtype=float))

    def field(name: str) -> np.ndarray:
        array = np.asarray(getattr(grid, name), dtype=float)
        return array[np.ix_(lat_order, lon_order)]

    return (
        np.asarray(grid.lats, dtype=float)[lat_order],
        np.asarray(grid.lons, dtype=float)[lon_order],
        {
            name: field(name)
            for name in (
                "cloud_low_pct",
                "cloud_mid_pct",
                "cloud_high_pct",
                "humidity_pct",
                "visibility_m",
            )
        },
    )


def build_national_field(
    gfs_source,
    bbox,
    target_date: date,
    *,
    domain_mask=None,
) -> NationalField:
    """Fetch covering GFS hours and score every cell at its nearest sunset hour.

    ``bbox`` is ``(lat_min, lat_max, lon_min, lon_max)``.  The returned axes are
    ascending for rendering.  Missing humidity/visibility cells use the same
    neutral defaults as #19 after timestep selection. ``domain_mask`` may limit
    the sunset range to cells that survive rendering (for example, inside the
    China border); scoring still returns the complete rectangular grid.
    """
    if isinstance(target_date, datetime):
        target_date = target_date.date()
    if not isinstance(target_date, date):
        raise TypeError("target_date must be a date")
    lat_min, lat_max, lon_min, lon_max = map(float, bbox)
    if lat_min > lat_max or lon_min > lon_max:
        raise ValueError("bbox must be (lat_min, lat_max, lon_min, lon_max)")

    trace = not tracemalloc.is_tracing()
    if trace:
        tracemalloc.start()
    t0 = time.perf_counter()

    try:
        # The bbox mesh establishes the full time range before any weather read.
        # It uses the same coarse interpolation as the final GFS axes.
        range_lats = _range_axis(lat_min, lat_max)
        range_lons = _range_axis(lon_min, lon_max)
        bbox_sunsets = sunset_utc_grid(target_date, range_lats, range_lons)
        valid_times = hourly_valid_times(
            _active_sunsets(bbox_sunsets, range_lats, range_lons, domain_mask)
        )
        if hasattr(gfs_source, "fetch_surface_grids"):
            grids = gfs_source.fetch_surface_grids(bbox, valid_times)
        else:
            grids = [
                gfs_source.fetch_surface_grid(bbox, valid_time)
                for valid_time in valid_times
            ]

        ordered = [_ordered(grid) for grid in grids]
        lats, lons, _ = ordered[0]
        for other_lats, other_lons, _fields in ordered[1:]:
            if not (
                np.array_equal(other_lats, lats)
                and np.array_equal(other_lons, lons)
            ):
                raise ValueError("GFS timestep grid coordinates do not match")

        sunsets = sunset_utc_grid(target_date, lats, lons)
        active_sunsets = _active_sunsets(sunsets, lats, lons, domain_mask)
        required_times = hourly_valid_times(active_sunsets)
        if not set(required_times).issubset(valid_times):
            raise ValueError("coarse sunset range did not cover the final grid")
        selected_time = nearest_valid_time_indices(sunsets, valid_times)

        def select(name: str) -> np.ndarray:
            stacked = np.stack([fields[name] for _la, _lo, fields in ordered])
            return np.take_along_axis(stacked, selected_time[None, ...], axis=0)[0]

        inputs = GridInputs(
            cloud_low_pct=select("cloud_low_pct"),
            cloud_mid_pct=select("cloud_mid_pct"),
            cloud_high_pct=select("cloud_high_pct"),
            humidity_pct=_finite(select("humidity_pct"), 50.0),
            visibility_m=_finite(select("visibility_m"), 25000.0),
        )
        probability = score_grid(inputs)

        decoded_sizes = [grid.decoded_bytes for grid in grids]
        decoded_input_bytes = sum(decoded_sizes)
        download_sizes = [grid.download_bytes for grid in grids]
        if all(size is not None for size in download_sizes):
            known_download_sizes = [
                int(size) for size in download_sizes if size is not None
            ]
            download_bytes: int | None = sum(known_download_sizes)
            additional_download_bytes: int | None = sum(known_download_sizes[1:])
        else:
            download_bytes = None
            additional_download_bytes = None

        runtime_s = time.perf_counter() - t0
        if trace:
            peak_mem_mb = tracemalloc.get_traced_memory()[1] / 1e6
        else:
            peak_mem_mb = float("nan")

        return NationalField(
            lats=lats,
            lons=lons,
            probability=probability,
            valid_times=valid_times,
            sunset_range_utc=(
                _utc_datetime(active_sunsets.min()),
                _utc_datetime(active_sunsets.max()),
            ),
            source_label=" | ".join(
                dict.fromkeys(grid.source_label for grid in grids)
            ),
            n_points=int(lats.size * lons.size),
            surface_fetches=len(grids),
            additional_surface_fetches=max(0, len(grids) - 1),
            decoded_input_bytes=decoded_input_bytes,
            additional_decoded_input_bytes=sum(decoded_sizes[1:]),
            download_bytes=download_bytes,
            additional_download_bytes=additional_download_bytes,
            runtime_s=runtime_s,
            peak_mem_mb=peak_mem_mb,
        )
    finally:
        if trace:
            tracemalloc.stop()
