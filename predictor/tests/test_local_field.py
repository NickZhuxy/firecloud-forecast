# predictor/tests/test_local_field.py
"""Tests for the local fine-product field (#62), offline with a synthetic cube."""
import math
import logging
from datetime import datetime, timezone

import numpy as np
import pytest

from predictor.fetch import FakeSource, WeatherSnapshot
from predictor.local_field import LocalField, build_local_field, local_grid
from predictor.profiles import AtmosphericCube
from predictor.rules import standard_predictor
from predictor.spatial import build_sunward_path
from predictor.sunward_section import score_point_with_sunward_section

_VALID = datetime(2026, 6, 29, 9, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# local_grid
# ---------------------------------------------------------------------------


def test_local_grid_centers_on_the_coordinate():
    lats, lons = local_grid(30.0, 120.0, radius_km=150.0, resolution_deg=0.1)
    assert any(abs(la - 30.0) < 1e-9 for la in lats)
    assert any(abs(lo - 120.0) < 1e-9 for lo in lons)
    assert np.all(np.diff(lats) > 0) and np.all(np.diff(lons) > 0)  # ascending


def test_local_grid_spans_about_the_radius():
    lats, lons = local_grid(30.0, 120.0, radius_km=150.0, resolution_deg=0.1)
    # lat half-span ≈ radius/111 deg ≈ 1.35; the grid reaches close to that.
    assert lats[-1] - 30.0 == pytest.approx(150.0 / 111.0, abs=0.1)
    # lon span is wider in degrees than lat (÷cos lat).
    assert (lons[-1] - lons[0]) > (lats[-1] - lats[0])


def test_local_grid_resolution_is_the_step():
    lats, _ = local_grid(30.0, 120.0, radius_km=150.0, resolution_deg=0.1)
    assert float(np.diff(lats)[0]) == pytest.approx(0.1)


def test_local_grid_caps_point_count_to_control_latency():
    with pytest.raises(ValueError, match="max_points|too many|grid"):
        local_grid(30.0, 120.0, radius_km=400.0, resolution_deg=0.05, max_points=900)


def test_local_grid_defaults_work_across_the_whole_china_domain():
    # Cell count grows toward the poles (lon span ÷cos lat); the default cap must
    # admit the default radius/resolution everywhere from Hainan (~18°N) to the
    # northern border (~53.5°N), not crash for Beijing/Harbin.
    for lat in (18.3, 30.0, 39.9, 45.8, 53.5):
        lats, lons = local_grid(lat, 116.0)   # all defaults
        assert lats.size > 0 and lons.size > 0


# ---------------------------------------------------------------------------
# build_local_field — the acceptance invariant
# ---------------------------------------------------------------------------

_LEVELS = np.array([925.0, 850.0, 700.0, 500.0, 400.0, 300.0])
_GPH = np.array([750.0, 1500.0, 3000.0, 5500.0, 7200.0, 9000.0])
_TEMP = np.array([283.0, 278.0, 270.0, 255.0, 245.0, 233.0])
_Q = np.array([3e-3, 2e-3, 1e-3, 3e-4, 1e-4, 5e-5])
_MID = np.array([0.0, 0.0, 5e-4, 5e-4, 0.0, 0.0])


def _cube() -> AtmosphericCube:
    lats = np.arange(26.0, 34.01, 0.5)
    lons = np.arange(112.0, 122.01, 0.5)
    nz, ny, nx = _LEVELS.size, lats.size, lons.size

    def grid(col):
        return np.broadcast_to(np.asarray(col, float)[:, None, None], (nz, ny, nx)).copy()

    return AtmosphericCube(
        lats=lats, lons=lons, levels_hpa=_LEVELS,
        temperature_k=grid(_TEMP), relative_humidity_pct=grid(np.full(nz, 30.0)),
        specific_humidity_kg_kg=grid(_Q), geopotential_height_m=grid(_GPH),
        u_wind_m_s=grid(np.zeros(nz)), v_wind_m_s=grid(np.zeros(nz)),
        vertical_velocity_pa_s=grid(np.zeros(nz)),
        cloud_water_kg_kg=grid(_MID), cloud_ice_kg_kg=grid(np.zeros(nz)),
        run_time=_VALID, valid_time=_VALID, source_label="gfs@test", retrieved_at=_VALID,
        missing=[],
    )


class _FakeCubeSource:
    def __init__(self, cube):
        self._cube = cube
        self.calls = 0

    def fetch_cube(self, bbox, time):
        self.calls += 1
        return self._cube


def _snapshot():
    return WeatherSnapshot(
        cloud_low_pct=0.0, cloud_mid_pct=55.0, cloud_high_pct=0.0, humidity_pct=50.0,
        source_label="t", retrieved_at=_VALID, sunset_time=_VALID, aerosol_optical_depth=0.1,
    )


def test_build_local_field_shape_and_one_cube_fetch():
    predictor = standard_predictor(FakeSource(snapshot=_snapshot()))
    src = _FakeCubeSource(_cube())
    field = build_local_field(
        predictor, src, 30.0, 120.0, _VALID,
        radius_km=40.0, resolution_deg=0.2, distances_km=[0.0, 100.0, 200.0],
    )
    assert isinstance(field, LocalField)
    assert field.probability.shape == (field.lats.size, field.lons.size)
    assert np.all((field.probability >= 0.0) & (field.probability <= 1.0))
    assert src.calls == 1   # ONE shared cube for the whole grid


def test_build_local_field_logs_progress(caplog):
    predictor = standard_predictor(FakeSource(snapshot=_snapshot()))
    caplog.set_level(logging.INFO, logger="predictor.local_field")

    build_local_field(
        predictor, _FakeCubeSource(_cube()), 30.0, 120.0, _VALID,
        radius_km=40.0, resolution_deg=0.2, distances_km=[0.0, 100.0, 200.0],
    )

    messages = [record.getMessage() for record in caplog.records]
    assert any("Local product grid:" in message for message in messages)
    assert any("Local product GFS cube: fetching" in message for message in messages)
    assert any("Local product weather: loaded" in message for message in messages)
    assert any("Local product scoring:" in message for message in messages)


def test_shared_cube_bbox_covers_every_cell_sunward_path():
    # The single shared cube must span every cell's sunward path, else profile_at
    # would grab an out-of-region edge column for real GFS.
    captured = {}

    class _RecordingCubeSource:
        def fetch_cube(self, bbox, time):
            captured["bbox"] = bbox
            return _cube()

    predictor = standard_predictor(FakeSource(snapshot=_snapshot()))
    dist = [0.0, 100.0, 200.0]
    build_local_field(
        predictor, _RecordingCubeSource(), 30.0, 120.0, _VALID,
        radius_km=40.0, resolution_deg=0.2, distances_km=dist,
    )
    lat_min, lat_max, lon_min, lon_max = captured["bbox"]
    lats, lons = local_grid(30.0, 120.0, radius_km=40.0, resolution_deg=0.2)
    for la in lats:
        for lo in lons:
            for s in build_sunward_path(float(la), float(lo), _VALID, distances_km=dist).samples:
                assert lat_min <= s.lat <= lat_max
                assert lon_min <= s.lon <= lon_max


def test_build_local_field_batches_snapshots_when_source_supports_it():
    # A source exposing fetch_many is batched in one call set, not N sequential fetches.
    class _BatchSource:
        def __init__(self, snap):
            self.snap = snap
            self.batch_calls = 0
            self.single_calls = 0

        def fetch_many(self, coords, time):
            self.batch_calls += 1
            return [self.snap for _ in coords]

        def fetch(self, lat, lon, time):
            self.single_calls += 1
            return self.snap

    src = _BatchSource(_snapshot())
    predictor = standard_predictor(src)
    build_local_field(
        predictor, _FakeCubeSource(_cube()), 30.0, 120.0, _VALID,
        radius_km=40.0, resolution_deg=0.2, distances_km=[0.0, 100.0, 200.0],
    )
    assert src.batch_calls == 1
    assert src.single_calls == 0


def test_local_field_cell_equals_standalone_single_point():
    # #62 acceptance: a grid cell's score is identical to the standalone detailed
    # single-point score for that coordinate (same predictor/cube/snapshot).
    predictor = standard_predictor(FakeSource(snapshot=_snapshot()))
    cube = _cube()
    dist = [0.0, 100.0, 200.0]
    field = build_local_field(
        predictor, _FakeCubeSource(cube), 30.0, 120.0, _VALID,
        radius_km=40.0, resolution_deg=0.2, distances_km=dist,
    )
    j = int(np.argmin(np.abs(field.lats - 30.0)))
    i = int(np.argmin(np.abs(field.lons - 120.0)))
    standalone = score_point_with_sunward_section(
        predictor, _FakeCubeSource(cube), float(field.lats[j]), float(field.lons[i]),
        _VALID, distances_km=dist,
    ).probability
    assert field.probability[j, i] == pytest.approx(standalone)
