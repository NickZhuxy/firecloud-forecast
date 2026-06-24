"""Tests for per-cell-sunset national field assembly (#19, #43), no network."""
from dataclasses import replace
from datetime import date, datetime, timezone

import numpy as np
import pytest

import predictor.national_field as national_field_mod
from predictor.fetch import FakeSource, WeatherSnapshot
from predictor.gfs import SurfaceGrid
from predictor.grid_score import GridInputs, score_grid
from predictor.national_field import NationalField, build_national_field
from predictor.rules import standard_predictor

_DATE = date(2026, 6, 22)
_T = datetime(2026, 6, 22, 11, tzinfo=timezone.utc)
_BBOX = (20.0, 40.0, 100.0, 120.0)  # lat_min, lat_max, lon_min, lon_max


class _FakeGFS:
    def __init__(self, grid_or_factory):
        self.grid_or_factory = grid_or_factory
        self.calls = []

    def fetch_surface_grid(self, bbox, valid_time):
        self.calls.append((bbox, valid_time))
        grid = (
            self.grid_or_factory(valid_time)
            if callable(self.grid_or_factory)
            else self.grid_or_factory
        )
        return replace(
            grid,
            valid_time=valid_time,
            source_label=f"gfs@test+f{valid_time.hour:02d}",
        )


def _grid(*, humidity=None, visibility=None, shape=(3, 3)) -> SurfaceGrid:
    if shape == (3, 3):
        lats = np.array([40.0, 30.0, 20.0])  # north→south, like GFS
        lons = np.array([100.0, 110.0, 120.0])
    else:
        lats = np.array([40.0, 20.0])
        lons = np.array([100.0, 120.0])
    return SurfaceGrid(
        lats=lats,
        lons=lons,
        cloud_low_pct=np.full(shape, 5.0),
        cloud_mid_pct=np.full(shape, 55.0),
        cloud_high_pct=np.full(shape, 40.0),
        humidity_pct=humidity if humidity is not None else np.full(shape, 60.0),
        visibility_m=visibility if visibility is not None else np.full(shape, 25000.0),
        run_time=_T,
        valid_time=_T,
        source_label="gfs@test",
        missing=[],
    )


def test_build_returns_field_with_multitime_metrics():
    gfs = _FakeGFS(_grid())
    field = build_national_field(gfs, _BBOX, _DATE)

    assert isinstance(field, NationalField)
    assert field.probability.shape == (3, 3)
    assert field.n_points == 9
    assert field.runtime_s >= 0.0
    assert field.peak_mem_mb > 0.0
    assert field.surface_fetches == len(gfs.calls) == len(field.valid_times)
    assert field.surface_fetches >= 2
    assert field.additional_surface_fetches == field.surface_fetches - 1
    assert all(call[0] == _BBOX for call in gfs.calls)
    assert [call[1] for call in gfs.calls] == list(field.valid_times)
    assert field.decoded_input_bytes > 0
    assert field.additional_decoded_input_bytes > 0


def test_latitudes_returned_ascending():
    field = build_national_field(_FakeGFS(_grid()), _BBOX, _DATE)
    assert field.lats.tolist() == [20.0, 30.0, 40.0]
    assert np.all(np.diff(field.lats) > 0)


def test_probability_in_range():
    field = build_national_field(_FakeGFS(_grid()), _BBOX, _DATE)
    assert np.all((field.probability >= 0.0) & (field.probability <= 1.0))


def test_missing_humidity_visibility_fall_back_not_nan():
    nan = np.full((3, 3), np.nan)
    field = build_national_field(
        _FakeGFS(_grid(humidity=nan, visibility=nan)), _BBOX, _DATE
    )
    assert np.all(np.isfinite(field.probability))
    assert np.all(field.probability > 0.0)


def _controlled_sunsets(*_args, **_kwargs):
    return np.array(
        [["2026-06-22T10:10:00", "2026-06-22T10:50:00"],
         ["2026-06-22T11:20:00", "2026-06-22T11:50:00"]],
        dtype="datetime64[s]",
    )


def _time_varying_grid(valid_time: datetime) -> SurfaceGrid:
    k = valid_time.hour - 10
    shape = (2, 2)
    grid = _grid(shape=shape)
    return replace(
        grid,
        cloud_low_pct=np.full(shape, 5.0 + 10.0 * k),
        cloud_mid_pct=np.full(shape, 30.0 + 15.0 * k),
        cloud_high_pct=np.full(shape, 40.0 - 10.0 * k),
        humidity_pct=np.full(shape, 45.0 + 15.0 * k),
        visibility_m=np.full(shape, 25000.0 - 6000.0 * k),
    )


def test_each_cell_selects_one_nearest_timestep_for_all_fields(monkeypatch):
    monkeypatch.setattr(national_field_mod, "sunset_utc_grid", _controlled_sunsets)
    gfs = _FakeGFS(_time_varying_grid)

    field = build_national_field(gfs, _BBOX, _DATE)

    assert [t.hour for t in field.valid_times] == [10, 11, 12]
    # Output rows are ascending latitude, so controlled sunsets are interpreted
    # on that final grid. The nearest-hour mosaic is [[10, 11], [11, 12]].
    k = np.array([[0.0, 1.0], [1.0, 2.0]])
    expected = score_grid(GridInputs(
        cloud_low_pct=5.0 + 10.0 * k,
        cloud_mid_pct=30.0 + 15.0 * k,
        cloud_high_pct=40.0 - 10.0 * k,
        humidity_pct=45.0 + 15.0 * k,
        visibility_m=25000.0 - 6000.0 * k,
    ))
    np.testing.assert_allclose(field.probability, expected, rtol=0.0, atol=1e-12)


def test_multitime_grid_matches_equivalent_scalar_points(monkeypatch):
    monkeypatch.setattr(national_field_mod, "sunset_utc_grid", _controlled_sunsets)
    field = build_national_field(_FakeGFS(_time_varying_grid), _BBOX, _DATE)
    sunset_times = _controlled_sunsets()
    chosen_k = np.array([[0, 1], [1, 2]])
    predictor = standard_predictor(FakeSource(WeatherSnapshot(0, 0, 0, 0, "x", _T)))

    for j in range(2):
        for i in range(2):
            k = int(chosen_k[j, i])
            sunset = datetime.fromtimestamp(
                int(sunset_times[j, i].astype("int64")), tz=timezone.utc
            )
            snap = WeatherSnapshot(
                cloud_low_pct=5.0 + 10.0 * k,
                cloud_mid_pct=30.0 + 15.0 * k,
                cloud_high_pct=40.0 - 10.0 * k,
                humidity_pct=45.0 + 15.0 * k,
                visibility_m=25000.0 - 6000.0 * k,
                source_label="cell",
                retrieved_at=_T,
                sunset_time=sunset,
            )
            scalar = predictor.score_snapshot(
                snap, float(field.lats[j]), float(field.lons[i]), sunset
            ).probability
            assert abs(field.probability[j, i] - scalar) < 1e-9


def test_mismatched_timestep_grid_is_rejected(monkeypatch):
    monkeypatch.setattr(national_field_mod, "sunset_utc_grid", _controlled_sunsets)

    def shifted(valid_time):
        grid = _time_varying_grid(valid_time)
        if valid_time.hour == 11:
            return replace(grid, lons=grid.lons + 0.25)
        return grid

    with pytest.raises(ValueError, match="coordinates"):
        build_national_field(_FakeGFS(shifted), _BBOX, _DATE)


def test_covering_times_include_interior_bbox_sunset_extreme(monkeypatch):
    def interior_late_sunset(_date, lats, lons, **_kwargs):
        result = np.full(
            (len(lats), len(lons)),
            np.datetime64("2026-06-22T10:10:00", "s"),
        )
        if len(lats) > 2:
            result[len(lats) // 2, :] = np.datetime64("2026-06-22T12:10:00", "s")
        return result

    monkeypatch.setattr(national_field_mod, "sunset_utc_grid", interior_late_sunset)

    field = build_national_field(_FakeGFS(_grid()), _BBOX, _DATE)

    assert [time.hour for time in field.valid_times] == [10, 11, 12, 13]


def test_domain_mask_excludes_clipped_bbox_corner_times(monkeypatch):
    def late_corners(_date, lats, lons, **_kwargs):
        result = np.full(
            (len(lats), len(lons)),
            np.datetime64("2026-06-22T11:10:00", "s"),
        )
        result[:, 0] = np.datetime64("2026-06-22T09:10:00", "s")
        result[:, -1] = np.datetime64("2026-06-22T15:10:00", "s")
        return result

    def middle_longitudes(_lats, lons):
        return np.broadcast_to(
            (np.asarray(lons) > 100.0) & (np.asarray(lons) < 120.0),
            (len(_lats), len(lons)),
        )

    monkeypatch.setattr(national_field_mod, "sunset_utc_grid", late_corners)

    field = build_national_field(
        _FakeGFS(_grid()), _BBOX, _DATE, domain_mask=middle_longitudes
    )

    assert [time.hour for time in field.valid_times] == [11, 12]
    assert field.sunset_range_utc == (
        datetime(2026, 6, 22, 11, 10, tzinfo=timezone.utc),
        datetime(2026, 6, 22, 11, 10, tzinfo=timezone.utc),
    )
