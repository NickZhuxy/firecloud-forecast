"""Per-cell sunset interpolation and GFS timestep selection (#43)."""
from datetime import date, datetime, timezone

import numpy as np
import pytest
from astral import Observer
from astral.sun import sun

from predictor.sunset_grid import (
    _axis,
    _inclusive_axis,
    _sunset_timestamp,
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


# --- #60 PR-2: solar_event on the national time grid ---

def test_sunset_grid_default_matches_explicit_sunset():
    from predictor.solar_event import SolarEvent
    d = date(2026, 6, 29)
    lats = np.array([20.0, 35.0, 50.0]); lons = np.array([100.0, 115.0, 130.0])
    assert np.array_equal(
        sunset_utc_grid(d, lats, lons),
        sunset_utc_grid(d, lats, lons, solar_event=SolarEvent.SUNSET),
    )


def test_sunrise_grid_differs_from_sunset_by_hours():
    from predictor.solar_event import SolarEvent
    d = date(2026, 6, 29)
    lats = np.array([20.0, 35.0, 50.0]); lons = np.array([100.0, 115.0, 130.0])
    sset = sunset_utc_grid(d, lats, lons, solar_event=SolarEvent.SUNSET).astype("int64")
    srise = sunset_utc_grid(d, lats, lons, solar_event=SolarEvent.SUNRISE).astype("int64")
    assert not np.array_equal(sset, srise)
    assert np.median(np.abs(sset - srise)) > 4 * 3600  # the two events are hours apart


def test_sunset_timestamp_sunrise_reads_sunrise_key():
    from predictor.solar_event import SolarEvent
    d = date(2026, 6, 29)
    expected = sun(
        Observer(latitude=35.0, longitude=115.0), date=d, tzinfo=timezone.utc
    )["sunrise"].timestamp()
    assert _sunset_timestamp(d, 35.0, 115.0, SolarEvent.SUNRISE) == expected
    assert _sunset_timestamp(d, 35.0, 115.0, SolarEvent.SUNRISE) != _sunset_timestamp(
        d, 35.0, 115.0, SolarEvent.SUNSET
    )


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


# ---------------------------------------------------------------------------
# _axis input validation
# ---------------------------------------------------------------------------

def test_axis_rejects_empty_array():
    with pytest.raises(ValueError, match="non-empty 1-D"):
        _axis([], "lats")


def test_axis_rejects_2d_array():
    with pytest.raises(ValueError, match="non-empty 1-D"):
        _axis([[1.0, 2.0], [3.0, 4.0]], "lats")


def test_axis_rejects_non_finite_values():
    with pytest.raises(ValueError, match="finite"):
        _axis([1.0, float("nan"), 3.0], "lats")


def test_axis_rejects_inf():
    with pytest.raises(ValueError, match="finite"):
        _axis([1.0, float("inf")], "lons")


# ---------------------------------------------------------------------------
# _inclusive_axis input validation
# ---------------------------------------------------------------------------

def test_inclusive_axis_rejects_zero_step():
    with pytest.raises(ValueError, match="positive"):
        _inclusive_axis(0.0, 10.0, 0.0)


def test_inclusive_axis_rejects_negative_step():
    with pytest.raises(ValueError, match="positive"):
        _inclusive_axis(0.0, 10.0, -2.0)


def test_inclusive_axis_rejects_nan_step():
    with pytest.raises(ValueError, match="positive"):
        _inclusive_axis(0.0, 10.0, float("nan"))


# ---------------------------------------------------------------------------
# Polar / midnight-sun fallback (physical invariant)
# ---------------------------------------------------------------------------

def test_polar_midnight_sun_timestamp_is_finite():
    """At 80°N in midsummer the sun never sets; fallback must return a finite float."""
    ts = _sunset_timestamp(date(2026, 6, 22), 80.0, 0.0)
    assert np.isfinite(ts)


def test_polar_midnight_sun_fallback_equals_18h_local_solar_time():
    """Polar fallback is deterministic: midnight UTC + (18 h − lon/15 h)."""
    lon = 0.0
    ts = _sunset_timestamp(date(2026, 6, 22), 80.0, lon)
    expected = datetime(2026, 6, 22, 18, 0, 0, tzinfo=timezone.utc).timestamp()
    # The except-branch computes this exactly, no rounding.
    assert abs(ts - expected) < 1.0


def test_polar_midnight_sun_fallback_shifts_with_longitude():
    """Fallback local solar time advances westward: lon=120°E → 10:00 UTC."""
    lon = 120.0
    ts = _sunset_timestamp(date(2026, 6, 22), 80.0, lon)
    # 18.0 - 120/15 = 18 - 8 = 10:00 UTC
    expected = datetime(2026, 6, 22, 10, 0, 0, tzinfo=timezone.utc).timestamp()
    assert abs(ts - expected) < 1.0


def test_polar_midnight_sun_propagates_through_grid():
    """sunset_utc_grid over a domain containing polar cells must return non-NaT output."""
    lats = np.array([70.0, 80.0])
    lons = np.array([0.0, 30.0])
    result = sunset_utc_grid(date(2026, 6, 22), lats, lons, coarse_step_deg=10.0)
    assert result.shape == (2, 2)
    assert not np.isnat(result).any()


# ---------------------------------------------------------------------------
# hourly_valid_times error cases
# ---------------------------------------------------------------------------

def test_hourly_valid_times_rejects_empty_array():
    with pytest.raises(ValueError, match="non-empty"):
        hourly_valid_times(np.array([], dtype="datetime64[s]"))


def test_hourly_valid_times_rejects_nat_values():
    sunsets = np.array(["2026-06-22T10:00:00", "NaT"], dtype="datetime64[s]")
    with pytest.raises(ValueError, match="finite"):
        hourly_valid_times(sunsets)


# ---------------------------------------------------------------------------
# nearest_valid_time_indices error cases
# ---------------------------------------------------------------------------

def test_nearest_valid_time_rejects_empty_sunsets():
    with pytest.raises(ValueError, match="non-empty"):
        nearest_valid_time_indices(
            np.array([], dtype="datetime64[s]"),
            (datetime(2026, 6, 22, 10, tzinfo=timezone.utc),),
        )


def test_nearest_valid_time_rejects_nat_in_sunsets():
    sunsets = np.array(["2026-06-22T10:00:00", "NaT"], dtype="datetime64[s]")
    with pytest.raises(ValueError, match="finite"):
        nearest_valid_time_indices(
            sunsets,
            (datetime(2026, 6, 22, 10, tzinfo=timezone.utc),),
        )


def test_nearest_valid_time_rejects_empty_valid_times():
    sunsets = np.array(["2026-06-22T10:00:00"], dtype="datetime64[s]")
    with pytest.raises(ValueError, match="not be empty"):
        nearest_valid_time_indices(sunsets, ())


def test_nearest_valid_time_rejects_non_increasing_valid_times():
    sunsets = np.array(["2026-06-22T10:00:00"], dtype="datetime64[s]")
    valid_times = (
        datetime(2026, 6, 22, 11, tzinfo=timezone.utc),
        datetime(2026, 6, 22, 10, tzinfo=timezone.utc),  # out of order
    )
    with pytest.raises(ValueError, match="strictly increasing"):
        nearest_valid_time_indices(sunsets, valid_times)
