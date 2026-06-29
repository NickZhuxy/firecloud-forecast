"""Vectorized per-cell sunset times and forecast-hour selection (#43).

Astral is evaluated only on a coarse geographic mesh.  The UTC timestamps are
then bilinearly interpolated to the model grid, avoiding tens of thousands of
Python-level solar calculations for every national overlay refresh.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from functools import lru_cache

import numpy as np
from astral import Observer
from astral.sun import sun

from predictor.solar_event import SolarEvent, spec_for


def _axis(values, name: str) -> np.ndarray:
    axis = np.asarray(values, dtype=float)
    if axis.ndim != 1 or axis.size == 0:
        raise ValueError(f"{name} must be a non-empty 1-D axis")
    if not np.all(np.isfinite(axis)):
        raise ValueError(f"{name} must contain only finite values")
    return axis


def _inclusive_axis(start: float, end: float, step: float) -> np.ndarray:
    if not np.isfinite(step) or step <= 0:
        raise ValueError("coarse_step_deg must be positive")
    lo, hi = sorted((float(start), float(end)))
    values = np.arange(lo, hi + step * 0.5, step, dtype=float)
    values = values[values <= hi]
    if values.size == 0 or not np.isclose(values[0], lo):
        values = np.insert(values, 0, lo)
    if not np.isclose(values[-1], hi):
        values = np.append(values, hi)
    return values


@lru_cache(maxsize=4096)
def _sunset_timestamp(
    target_date: date, lat: float, lon: float, solar_event: SolarEvent = SolarEvent.SUNSET
) -> float:
    spec = spec_for(solar_event)
    observer = Observer(latitude=lat, longitude=lon)
    try:
        event = sun(observer, date=target_date, tzinfo=timezone.utc)[spec.astral_key]
    except ValueError:
        # Deterministic polar-edge degradation: the event's local solar hour (dusk
        # 18 / dawn 6).  China's 17–54 N domain does not take this path, but a failed
        # edge sample should not invalidate an otherwise usable national field.
        midnight = datetime(
            target_date.year, target_date.month, target_date.day, tzinfo=timezone.utc
        )
        event = midnight + timedelta(hours=spec.fallback_solar_hour - lon / 15.0)
    return event.timestamp()


def sunset_utc_grid(
    target_date: date,
    lats,
    lons,
    *,
    coarse_step_deg: float = 4.0,
    solar_event: SolarEvent | str = SolarEvent.SUNSET,
) -> np.ndarray:
    """Return a ``(lat, lon)`` UTC solar-event field as ``datetime64[s]``.

    Target axes may be ascending or descending.  Sampling axes always include
    the exact target bounds, so interpolation never extrapolates. ``solar_event``
    (#60) selects sunset (default) or sunrise; the rest of the pipeline (GFS-hour
    selection) just tracks whichever event-time grid this returns.
    """
    event = SolarEvent(solar_event)
    target_lats = _axis(lats, "lats")
    target_lons = _axis(lons, "lons")
    coarse_lats = _inclusive_axis(target_lats.min(), target_lats.max(), coarse_step_deg)
    coarse_lons = _inclusive_axis(target_lons.min(), target_lons.max(), coarse_step_deg)

    samples = np.empty((coarse_lats.size, coarse_lons.size), dtype=float)
    for j, lat in enumerate(coarse_lats):
        for i, lon in enumerate(coarse_lons):
            samples[j, i] = _sunset_timestamp(
                target_date, round(float(lat), 8), round(float(lon), 8), event
            )

    # np.interp accepts unsorted target x values while requiring only the sample
    # axis (xp) to be sorted.  This naturally preserves caller axis order.
    along_lon = np.vstack(
        [np.interp(target_lons, coarse_lons, row) for row in samples]
    )
    interpolated = np.vstack(
        [np.interp(target_lats, coarse_lats, along_lon[:, i])
         for i in range(target_lons.size)]
    ).T
    return np.rint(interpolated).astype("int64").astype("datetime64[s]")


def hourly_valid_times(sunset_times: np.ndarray) -> tuple[datetime, ...]:
    """UTC hours bracketing the complete finite sunset-time range."""
    times = np.asarray(sunset_times, dtype="datetime64[s]")
    if times.size == 0 or np.isnat(times).any():
        raise ValueError("sunset_times must be non-empty and finite")
    seconds = times.astype("int64")
    hour_s = 3600
    start = int(seconds.min() // hour_s * hour_s)
    end = int((seconds.max() + hour_s - 1) // hour_s * hour_s)
    return tuple(
        datetime.fromtimestamp(timestamp, tz=timezone.utc)
        for timestamp in range(start, end + 1, hour_s)
    )


def nearest_valid_time_indices(
    sunset_times: np.ndarray, valid_times: tuple[datetime, ...]
) -> np.ndarray:
    """Index of the closest valid time for every cell; ties choose the earlier."""
    sunsets = np.asarray(sunset_times, dtype="datetime64[s]")
    if sunsets.size == 0 or np.isnat(sunsets).any():
        raise ValueError("sunset_times must be non-empty and finite")
    if not valid_times:
        raise ValueError("valid_times must not be empty")

    timestamps = np.array(
        [
            int(
                (time if time.tzinfo is not None else time.replace(tzinfo=timezone.utc))
                .astimezone(timezone.utc)
                .timestamp()
            )
            for time in valid_times
        ],
        dtype="int64",
    )
    if timestamps.size > 1 and np.any(np.diff(timestamps) <= 0):
        raise ValueError("valid_times must be strictly increasing")
    deltas = np.abs(timestamps[:, None, None] - sunsets.astype("int64")[None, ...])
    # np.argmin returns the first minimum, which implements the earlier-hour tie.
    return np.argmin(deltas, axis=0)
