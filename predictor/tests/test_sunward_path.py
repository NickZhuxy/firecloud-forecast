"""Tests for the sunward 3D sampling path (#12)."""
import math
from datetime import datetime, timezone

from predictor.spatial import (
    GFS_GRID_RES_DEG,
    SunwardPath,
    SunwardSample,
    build_sunward_path,
    even_distances,
    grid_index,
    haversine_km,
    solar_azimuth,
)


# --- geographic distance / bearing accuracy ---------------------------------

def test_haversine_known_distance():
    # ~1 degree of latitude ≈ 111.19 km on a 6371 km sphere.
    assert abs(haversine_km(0.0, 0.0, 1.0, 0.0) - 111.19) < 0.5


def test_destination_distance_matches_request():
    # Each sample's great-circle distance from the observer matches its label.
    path = build_sunward_path(
        31.0, 121.0, _T, azimuth_deg=290.0, distances_km=[0.0, 250.0, 800.0]
    )
    for s in path.samples:
        got = haversine_km(31.0, 121.0, s.lat, s.lon)
        assert abs(got - s.distance_km) < 1.0   # within 1 km over 800 km


def test_initial_bearing_matches_azimuth():
    # The first step's bearing from the observer ≈ the requested azimuth.
    path = build_sunward_path(31.0, 121.0, _T, azimuth_deg=290.0, distances_km=[0.0, 10.0])
    near = path.samples[1]
    bearing = _initial_bearing(31.0, 121.0, near.lat, near.lon)
    assert abs((bearing - 290.0 + 180.0) % 360.0 - 180.0) < 0.5


# --- grid index --------------------------------------------------------------

def test_grid_index_known_point():
    # GFS 0.25°: lat idx = (90-lat)/0.25, lon idx = lon/0.25 (lon in 0–360).
    assert grid_index(90.0, 0.0) == (0, 0)
    assert grid_index(31.0, 121.0) == (236, 484)


def test_grid_index_wraps_longitude_seam():
    # Negative longitude maps onto the 0–360 grid; 360 wraps to 0.
    assert grid_index(0.0, -179.75)[1] == grid_index(0.0, 180.25)[1]
    assert grid_index(0.0, 359.99)[1] == 0     # wraps to column 0


# --- path construction -------------------------------------------------------

_T = datetime(2026, 6, 23, 10, 20, tzinfo=timezone.utc)


def test_even_distances_spans_zero_to_max():
    d = even_distances(max_km=800.0, count=9)
    assert d[0] == 0.0 and d[-1] == 800.0 and len(d) == 9
    assert abs(d[1] - 100.0) < 1e-9


def test_path_outputs_per_sample_fields():
    elev = {(31.0, 121.0): 4.0}
    path = build_sunward_path(
        31.0, 121.0, _T, azimuth_deg=290.0, distances_km=[0.0, 800.0],
        elevation_fn=lambda la, lo: 4.0,
    )
    assert isinstance(path, SunwardPath)
    assert path.azimuth_deg == 290.0
    assert len(path.samples) == 2
    s0 = path.samples[0]
    assert isinstance(s0, SunwardSample)
    assert s0.distance_km == 0.0 and s0.lat == 31.0 and s0.lon == 121.0
    assert s0.grid_lat_idx == 236 and s0.grid_lon_idx == 484
    assert s0.elevation_m == 4.0 and s0.in_domain is True


def test_out_of_domain_flags_and_skips_elevation():
    # A tight domain bbox around the observer excludes the far sample.
    calls = []

    def elev(la, lo):
        calls.append((la, lo))
        return 100.0

    path = build_sunward_path(
        31.0, 121.0, _T, azimuth_deg=90.0, distances_km=[0.0, 800.0],
        elevation_fn=elev, domain=(30.0, 32.0, 120.0, 122.0),
    )
    assert path.samples[0].in_domain is True
    assert path.samples[1].in_domain is False
    assert path.samples[1].elevation_m is None
    # Elevation only queried for in-domain points.
    assert len(calls) == 1


def test_solar_azimuth_is_a_valid_bearing():
    az = solar_azimuth(31.0, 121.0, _T)
    assert 0.0 <= az < 360.0


def _initial_bearing(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0
