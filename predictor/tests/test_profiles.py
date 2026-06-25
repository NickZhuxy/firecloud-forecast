"""Unit tests for the vertical-profile data model (no network)."""
from datetime import datetime, timezone

import numpy as np
import pytest

from predictor.profiles import (
    PROFILE_VARS,
    AtmosphericCube,
    AtmosphericProfile,
    NormalizedProfile,
)


def _build_cube() -> AtmosphericCube:
    """A tiny 3-level, 2x3 synthetic cube with distinct, indexable values."""
    levels = np.array([850.0, 700.0, 500.0])
    lats = np.array([30.0, 31.0])             # ny = 2
    lons = np.array([120.0, 121.0, 122.0])    # nx = 3
    nz, ny, nx = levels.size, lats.size, lons.size

    # Each variable filled so value encodes (z, y, x): v = z*100 + y*10 + x.
    base = np.zeros((nz, ny, nx))
    for z in range(nz):
        for y in range(ny):
            for x in range(nx):
                base[z, y, x] = z * 100 + y * 10 + x

    fields = {var: base + offset for offset, var in enumerate(PROFILE_VARS)}
    return AtmosphericCube(
        lats=lats,
        lons=lons,
        levels_hpa=levels,
        run_time=datetime(2026, 6, 23, 0, tzinfo=timezone.utc),
        valid_time=datetime(2026, 6, 23, 6, tzinfo=timezone.utc),
        source_label="gfs@2026-06-23T00Z+f06",
        retrieved_at=datetime(2026, 6, 23, 5, tzinfo=timezone.utc),
        missing=[],
        **fields,
    )


def test_profile_at_extracts_nearest_grid_column():
    cube = _build_cube()
    # Nearest to (30.9, 121.4) is lat index 1 (31.0), lon index 1 (121.0).
    prof = cube.profile_at(30.9, 121.4)

    assert isinstance(prof, AtmosphericProfile)
    assert prof.lat == 31.0 and prof.lon == 121.0
    # temperature_k is the first PROFILE_VAR (offset 0): value = z*100 + 1*10 + 1.
    np.testing.assert_array_equal(
        prof.temperature_k, np.array([11.0, 111.0, 211.0])
    )
    np.testing.assert_array_equal(prof.levels_hpa, cube.levels_hpa)


def test_profile_at_preserves_metadata_and_all_vars():
    cube = _build_cube()
    prof = cube.profile_at(30.0, 120.0)

    assert prof.run_time == cube.run_time
    assert prof.valid_time == cube.valid_time
    assert prof.source_label == cube.source_label
    assert prof.missing == []
    for var in PROFILE_VARS:
        col = getattr(prof, var)
        assert col.shape == (cube.levels_hpa.size,)


def test_profile_at_handles_longitude_wrap():
    """A grid in 0–360 convention should match a negative query longitude."""
    cube = _build_cube()
    object.__setattr__(cube, "lons", np.array([358.0, 359.0, 0.0]))
    # Query -0.9 deg == 359.1 deg → nearest is index 1 (359.0).
    prof = cube.profile_at(30.0, -0.9)
    assert prof.lon == 359.0
    # And 359.9 deg sits across the seam, nearest the 0.0 entry (== 360).
    assert cube.profile_at(30.0, 359.9).lon == 0.0


def test_missing_propagates_to_profile():
    cube = _build_cube()
    object.__setattr__(cube, "missing", ["cloud_ice_kg_kg"])
    prof = cube.profile_at(30.0, 120.0)
    assert prof.missing == ["cloud_ice_kg_kg"]


def test_profile_to_dict_is_json_friendly():
    cube = _build_cube()
    prof = cube.profile_at(30.0, 120.0)
    d = prof.to_dict()
    assert isinstance(d["temperature_k"], list)
    assert isinstance(d["run_time"], str)
    assert d["lat"] == 30.0


def _build_normalized_profile() -> NormalizedProfile:
    n = 4
    heights = np.array([500.0, 1500.0, 4000.0, 8000.0])
    t = datetime(2026, 6, 23, 10, tzinfo=timezone.utc)
    return NormalizedProfile(
        lat=31.0, lon=121.0,
        pressure_hpa=np.array([950.0, 850.0, 600.0, 400.0]),
        geometric_height_m=heights,
        geopotential_height_m=heights,
        temperature_k=np.array([290.0, 282.0, 260.0, 238.0]),
        relative_humidity_pct=np.array([80.0, 65.0, 35.0, 20.0]),
        dewpoint_k=np.array([286.0, 275.0, 240.0, 215.0]),
        specific_humidity_kg_kg=np.full(n, 0.004),
        u_wind_m_s=np.zeros(n),
        v_wind_m_s=np.zeros(n),
        vertical_velocity_pa_s=np.array([-0.2, -0.1, 0.0, 0.1]),
        cloud_water_kg_kg=np.full(n, np.nan),
        cloud_ice_kg_kg=np.full(n, np.nan),
        run_time=t, valid_time=t, source_label="gfs@test", retrieved_at=t, missing=[],
    )


def test_normalized_profile_to_dict_is_json_friendly():
    """NormalizedProfile.to_dict() serialises arrays to lists and datetimes to ISO strings."""
    prof = _build_normalized_profile()
    d = prof.to_dict()
    assert isinstance(d["temperature_k"], list)
    assert isinstance(d["geometric_height_m"], list)
    assert isinstance(d["run_time"], str)
    assert d["lat"] == 31.0
    assert d["missing"] == []
