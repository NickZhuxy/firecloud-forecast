"""Tests for national field assembly (#19) — mocked GFS, no network."""
from datetime import datetime, timezone

import numpy as np

from predictor.gfs import SurfaceGrid
from predictor.national_field import NationalField, build_national_field

_T = datetime(2026, 6, 23, 11, tzinfo=timezone.utc)


class _FakeGFS:
    def __init__(self, grid):
        self.grid = grid
        self.calls = []

    def fetch_surface_grid(self, bbox, valid_time):
        self.calls.append((bbox, valid_time))
        return self.grid


def _grid(*, humidity=None, visibility=None) -> SurfaceGrid:
    lats = np.array([40.0, 30.0, 20.0])   # north→south, like GFS
    lons = np.array([100.0, 110.0, 120.0])
    shape = (3, 3)
    return SurfaceGrid(
        lats=lats, lons=lons,
        cloud_low_pct=np.full(shape, 5.0),
        cloud_mid_pct=np.full(shape, 55.0),
        cloud_high_pct=np.full(shape, 40.0),
        humidity_pct=humidity if humidity is not None else np.full(shape, 60.0),
        visibility_m=visibility if visibility is not None else np.full(shape, 25000.0),
        run_time=_T, valid_time=_T, source_label="gfs@test", missing=[],
    )


def test_build_returns_field_with_metrics():
    gfs = _FakeGFS(_grid())
    field = build_national_field(gfs, (20.0, 100.0, 40.0, 120.0), _T)

    assert isinstance(field, NationalField)
    assert field.probability.shape == (3, 3)
    assert field.n_points == 9
    assert field.runtime_s >= 0.0
    assert field.peak_mem_mb > 0.0
    assert field.source_label == "gfs@test"
    assert gfs.calls == [((20.0, 100.0, 40.0, 120.0), _T)]


def test_latitudes_returned_ascending():
    field = build_national_field(_FakeGFS(_grid()), (20.0, 100.0, 40.0, 120.0), _T)
    assert field.lats.tolist() == [20.0, 30.0, 40.0]
    assert np.all(np.diff(field.lats) > 0)


def test_probability_in_range():
    field = build_national_field(_FakeGFS(_grid()), (20.0, 100.0, 40.0, 120.0), _T)
    assert np.all((field.probability >= 0.0) & (field.probability <= 1.0))


def test_missing_humidity_visibility_fall_back_not_nan():
    nan = np.full((3, 3), np.nan)
    gfs = _FakeGFS(_grid(humidity=nan, visibility=nan))
    field = build_national_field(gfs, (20.0, 100.0, 40.0, 120.0), _T)
    # Neutral fallbacks keep the field finite (a gap must not zero/NaN a cell).
    assert np.all(np.isfinite(field.probability))
    assert np.all(field.probability > 0.0)
