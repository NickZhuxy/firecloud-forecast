"""Per-cell sunset interpolation and GFS timestep selection (#43)."""
from datetime import date, datetime, timezone

import numpy as np
from astral import Observer
from astral.sun import sun

from predictor.sunset_grid import (
    hourly_valid_times,
    nearest_valid_time_indices,
    sunset_utc_grid,
)


def test_bilinear_sunset_grid_stays_close_to_direct_astral():
    target_date = date(2026, 6, 22)
    lats = np.array([18.3, 31.2, 43.7, 52.6])
    lons = np.array([75.4, 98.8, 117.3, 133.2])

    interpolated = sunset_utc_grid(target_date, lats, lons, coarse_step_deg=4.0)

    assert interpolated.shape == (lats.size, lons.size)
    assert interpolated.dtype == np.dtype("datetime64[s]")
    for j, lat in enumerate(lats):
        for i, lon in enumerate(lons):
            direct = sun(
                Observer(latitude=float(lat), longitude=float(lon)),
                date=target_date,
                tzinfo=timezone.utc,
            )["sunset"]
            direct64 = np.datetime64(int(direct.timestamp()), "s")
            error_s = abs((interpolated[j, i] - direct64) / np.timedelta64(1, "s"))
            assert error_s <= 120.0, (lat, lon, error_s)


def test_sunset_grid_preserves_requested_axis_order():
    lats = np.array([40.0, 30.0, 20.0])
    lons = np.array([120.0, 100.0])
    result = sunset_utc_grid(date(2026, 6, 22), lats, lons)

    assert result.shape == (3, 2)
    # At the same latitude, western China has a later UTC sunset.
    assert np.all(result[:, 1] > result[:, 0])


def test_hourly_times_bracket_complete_sunset_range():
    sunsets = np.array(
        [["2026-06-22T09:12:00", "2026-06-22T10:40:00"],
         ["2026-06-22T11:20:00", "2026-06-22T12:00:00"]],
        dtype="datetime64[s]",
    )

    times = hourly_valid_times(sunsets)

    assert times == tuple(
        datetime(2026, 6, 22, hour, tzinfo=timezone.utc)
        for hour in (9, 10, 11, 12)
    )


def test_nearest_valid_time_uses_earlier_hour_on_tie():
    sunsets = np.array(
        [["2026-06-22T10:29:59", "2026-06-22T10:30:00", "2026-06-22T10:30:01"]],
        dtype="datetime64[s]",
    )
    valid_times = (
        datetime(2026, 6, 22, 10, tzinfo=timezone.utc),
        datetime(2026, 6, 22, 11, tzinfo=timezone.utc),
    )

    indices = nearest_valid_time_indices(sunsets, valid_times)

    assert indices.tolist() == [[0, 0, 1]]
