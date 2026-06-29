# predictor/tests/test_sunrise_mirror.py
"""#60 acceptance: sunrise is the east-west mirror of sunset.

The fire-cloud physics is symmetric about the observer's meridian. Sunrise and
sunset azimuths are mirror images about due south (sunrise_az = 360 − sunset_az),
so reflecting a scene about the observer's meridian (lon' = 2·lon_obs − lon) and
scoring it at the *other* event must reproduce the original score. We never added a
direction parameter — the eastern vs western bearing falls out entirely of which
event TIME is fed in, which these tests pin.
"""
from datetime import datetime, timezone

import numpy as np
import pytest

from predictor.features import compute_event_time
from predictor.fetch import FakeSource, WeatherSnapshot
from predictor.profiles import AtmosphericCube
from predictor.solar_event import SolarEvent
from predictor.spatial import build_sunward_path, solar_azimuth
from predictor.rules import standard_predictor
from predictor.sunward_section import score_point_with_sunward_section

_LAT, _LON = 30.0, 120.0
_DAY = datetime(2026, 6, 29, 4, 0, tzinfo=timezone.utc)  # ~midday local at 120°E
_SUNSET = compute_event_time(_LAT, _LON, _DAY, SolarEvent.SUNSET)
_SUNRISE = compute_event_time(_LAT, _LON, _DAY, SolarEvent.SUNRISE)


# ---------------------------------------------------------------------------
# T2 — the bearing flips east↔west from the event time alone
# ---------------------------------------------------------------------------


def test_sunset_is_west_sunrise_is_east():
    az_set = solar_azimuth(_LAT, _LON, _SUNSET)
    az_rise = solar_azimuth(_LAT, _LON, _SUNRISE)
    assert 240.0 < az_set < 320.0     # western half
    assert 40.0 < az_rise < 120.0     # eastern half


def test_sunward_paths_mirror_about_observer_meridian():
    # Each sunset sample lands west of the observer; its sunrise counterpart lands
    # the same distance east, at the same latitude — a meridian reflection.
    dist = [0.0, 100.0, 300.0, 600.0]
    p_set = build_sunward_path(_LAT, _LON, _SUNSET, distances_km=dist, elevation_fn=lambda a, o: 0.0)
    p_rise = build_sunward_path(_LAT, _LON, _SUNRISE, distances_km=dist, elevation_fn=lambda a, o: 0.0)
    for s, r in zip(p_set.samples[1:], p_rise.samples[1:]):
        assert s.lon < _LON < r.lon                              # west vs east
        assert (_LON - s.lon) == pytest.approx(r.lon - _LON, abs=0.05)  # mirror in lon
        assert s.lat == pytest.approx(r.lat, abs=0.05)           # same latitude


# ---------------------------------------------------------------------------
# T1 — full scoring mirror (the headline acceptance)
# ---------------------------------------------------------------------------

_LEVELS = np.array([925.0, 850.0, 700.0, 500.0, 400.0, 300.0])
_GPH = np.array([750.0, 1500.0, 3000.0, 5500.0, 7200.0, 9000.0])
_TEMP = np.array([283.0, 278.0, 270.0, 255.0, 245.0, 233.0])
_Q = np.array([3e-3, 2e-3, 1e-3, 3e-4, 1e-4, 5e-5])
_HIGH = np.array([0.0, 0.0, 0.0, 0.0, 5e-4, 5e-4])   # canvas deck ~7.2–9 km
_LOWDECK = np.array([5e-4, 5e-4, 0.0, 0.0, 0.0, 0.0])  # opaque low deck ~0.75–1.5 km
_CLEAR = np.zeros(6)


def _cube(column_clw):
    """Build a cube whose per-lon-column condensate is given by ``column_clw[lon]``."""
    lats = np.array([28.0, 30.0, 32.0])
    lons = np.array([116.0, 117.0, 118.0, 119.0, 120.0, 121.0, 122.0, 123.0, 124.0])
    nz, ny, nx = _LEVELS.size, lats.size, lons.size

    def fill(per_col):  # per_col: (nx,) list of (nz,) arrays
        a = np.zeros((nz, ny, nx))
        for xi in range(nx):
            a[:, :, xi] = per_col[xi][:, None]
        return a

    def same(col):
        return fill([col] * nx)

    clw = fill([column_clw(lon) for lon in lons])
    return AtmosphericCube(
        lats=lats, lons=lons, levels_hpa=_LEVELS,
        temperature_k=same(_TEMP), relative_humidity_pct=same(np.full(nz, 30.0)),
        specific_humidity_kg_kg=same(_Q), geopotential_height_m=same(_GPH),
        u_wind_m_s=same(np.zeros(nz)), v_wind_m_s=same(np.zeros(nz)),
        vertical_velocity_pa_s=same(np.zeros(nz)),
        cloud_water_kg_kg=clw, cloud_ice_kg_kg=same(np.zeros(nz)),
        run_time=_DAY, valid_time=_DAY, source_label="gfs@test", retrieved_at=_DAY, missing=[],
    )


def _mirror_cube(cube):
    """Reflect the cube about the observer meridian (lon → 2·_LON − lon)."""
    new_lons = (2 * _LON - cube.lons)[::-1]
    def flip(a):
        return np.asarray(a)[:, :, ::-1].copy()
    return AtmosphericCube(
        lats=cube.lats, lons=new_lons, levels_hpa=cube.levels_hpa,
        temperature_k=flip(cube.temperature_k), relative_humidity_pct=flip(cube.relative_humidity_pct),
        specific_humidity_kg_kg=flip(cube.specific_humidity_kg_kg),
        geopotential_height_m=flip(cube.geopotential_height_m),
        u_wind_m_s=flip(cube.u_wind_m_s), v_wind_m_s=flip(cube.v_wind_m_s),
        vertical_velocity_pa_s=flip(cube.vertical_velocity_pa_s),
        cloud_water_kg_kg=flip(cube.cloud_water_kg_kg), cloud_ice_kg_kg=flip(cube.cloud_ice_kg_kg),
        run_time=cube.run_time, valid_time=cube.valid_time,
        source_label=cube.source_label, retrieved_at=cube.retrieved_at, missing=[],
    )


class _FakeCubeSource:
    def __init__(self, cube):
        self._cube = cube

    def fetch_cube(self, bbox, time):
        return self._cube


def _snapshot(event_time):
    # High canvas present; event time in the slot. No sunward_profile (keeps the
    # mirror purely a function of the cube + event time).
    return WeatherSnapshot(
        cloud_low_pct=0.0, cloud_mid_pct=0.0, cloud_high_pct=60.0, humidity_pct=50.0,
        source_label="t", retrieved_at=event_time, sunset_time=event_time,
        aerosol_optical_depth=0.1,
    )


def test_sunrise_score_mirrors_sunset_score():
    # Observer (lon 120) has a high canvas; an opaque low deck sits to the WEST.
    # West deck → on the sunset light path (vetoes); the meridian mirror puts the
    # deck to the EAST → on the sunrise light path. Both must score identically.
    def west_deck(lon):
        if lon == _LON:
            return _HIGH          # observer column: the canvas
        return _LOWDECK if lon < _LON else _CLEAR
    cube = _cube(west_deck)

    fc_set = score_point_with_sunward_section(
        standard_predictor(FakeSource(_snapshot(_SUNSET))), _FakeCubeSource(cube),
        _LAT, _LON, _SUNSET, distances_km=[0.0, 100.0, 200.0, 300.0, 400.0],
    )
    fc_rise = score_point_with_sunward_section(
        standard_predictor(FakeSource(_snapshot(_SUNRISE))), _FakeCubeSource(_mirror_cube(cube)),
        _LAT, _LON, _SUNRISE, distances_km=[0.0, 100.0, 200.0, 300.0, 400.0],
    )
    assert fc_rise.probability == pytest.approx(fc_set.probability, abs=1e-9)
    # Non-vacuous: the west/east deck actually vetoes the sunward gate in both.
    assert fc_set.components["sunward_illumination"] == 0.0
    assert fc_rise.components["sunward_illumination"] == 0.0
