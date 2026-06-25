"""Tests for sunward vertical cross-section assembly (#18)."""
from datetime import datetime, timezone

import numpy as np
import pytest

from predictor.clouds import CloudLayer
from predictor.cross_section import SunwardCrossSection, build_cross_section, even_heights
from predictor.profiles import NormalizedProfile
from predictor.spatial import build_sunward_path

_T = datetime(2026, 6, 23, 10, 20, tzinfo=timezone.utc)


def _profile(lat, lon, *, rh_top=20.0, base_h=1000.0):
    # A simple 4-level column: RH high near base_h, drying aloft.
    heights = np.array([base_h, base_h + 2000, base_h + 5000, base_h + 9000])
    n = heights.size
    return NormalizedProfile(
        lat=lat, lon=lon,
        pressure_hpa=np.array([900.0, 700.0, 500.0, 300.0]),
        geometric_height_m=heights,
        geopotential_height_m=heights,
        temperature_k=np.array([290.0, 277.0, 256.0, 230.0]),
        relative_humidity_pct=np.array([85.0, 70.0, 40.0, rh_top]),
        dewpoint_k=np.array([288.0, 273.0, 245.0, 215.0]),
        specific_humidity_kg_kg=np.full(n, 0.004),
        u_wind_m_s=np.zeros(n), v_wind_m_s=np.zeros(n),
        vertical_velocity_pa_s=np.array([-0.2, -0.1, 0.0, 0.1]),
        cloud_water_kg_kg=np.full(n, np.nan),
        cloud_ice_kg_kg=np.full(n, np.nan),
        run_time=_T, valid_time=_T, source_label="gfs@test", retrieved_at=_T, missing=[],
    )


def _path(n=3):
    return build_sunward_path(
        31.0, 121.0, _T, azimuth_deg=290.0,
        distances_km=[0.0, 400.0, 800.0][:n],
        elevation_fn=lambda la, lo: 0.0,
    )


def test_even_heights_spans_range():
    h = even_heights(max_m=15000.0, count=31)
    assert h[0] == 0.0 and h[-1] == 15000.0 and len(h) == 31


def test_cross_section_shape_and_coords():
    path = _path(3)
    profiles = [_profile(s.lat, s.lon) for s in path.samples]
    layers = [[] for _ in path.samples]
    xsec = build_cross_section(path, profiles, layers, heights_m=even_heights(12000.0, 25))

    assert isinstance(xsec, SunwardCrossSection)
    assert xsec.distances_km == [0.0, 400.0, 800.0]
    assert xsec.relative_humidity_pct.shape == (25, 3)   # (height, distance)
    assert xsec.vertical_velocity_pa_s.shape == (25, 3)
    assert xsec.temperature_k.shape == (25, 3)
    assert xsec.mask.shape == (25, 3)
    assert xsec.azimuth_deg == 290.0


def test_interpolation_is_linear_in_height():
    path = _path(1)
    profiles = [_profile(31.0, 121.0, base_h=1000.0)]
    # Sample exactly at a height midway between the 900 hPa (h=1000, RH=85) and
    # 700 hPa (h=3000, RH=70) levels → linear RH = 77.5.
    xsec = build_cross_section(path, profiles, [[]], heights_m=[2000.0])
    assert abs(xsec.relative_humidity_pct[0, 0] - 77.5) < 1e-6
    assert xsec.mask[0, 0]


def test_below_terrain_and_above_profile_are_masked():
    path = build_sunward_path(
        31.0, 121.0, _T, azimuth_deg=290.0, distances_km=[0.0],
        elevation_fn=lambda la, lo: 1500.0,   # terrain at 1500 m
    )
    profiles = [_profile(31.0, 121.0, base_h=1000.0)]  # profile spans 1000–10000 m
    xsec = build_cross_section(path, profiles, [[]], heights_m=[500.0, 2000.0, 20000.0])
    # 500 m is below terrain → masked; 2000 m valid; 20000 m above profile → masked.
    assert not xsec.mask[0, 0]
    assert xsec.mask[1, 0]
    assert not xsec.mask[2, 0]
    assert np.isnan(xsec.relative_humidity_pct[0, 0])
    assert np.isnan(xsec.relative_humidity_pct[2, 0])


def test_out_of_domain_column_fully_masked():
    path = build_sunward_path(
        31.0, 121.0, _T, azimuth_deg=90.0, distances_km=[0.0, 800.0],
        elevation_fn=lambda la, lo: 0.0, domain=(30.0, 32.0, 120.0, 122.0),
    )
    # Far sample is out of the domain bbox → no profile, whole column masked.
    profiles = [_profile(31.0, 121.0), None]
    xsec = build_cross_section(path, profiles, [[], []], heights_m=even_heights(10000.0, 10))
    assert xsec.mask[:, 0].any()          # observer column has valid cells
    assert not xsec.mask[:, 1].any()      # out-of-domain column fully masked
    assert np.isnan(xsec.relative_humidity_pct[:, 1]).all()


def test_cloud_layers_are_carried_per_column():
    path = _path(2)
    profiles = [_profile(s.lat, s.lon) for s in path.samples]
    layer = CloudLayer(2000.0, 4000.0, 2000.0, "ice", 0.8, "condensate", signal_margin=10.0)
    xsec = build_cross_section(path, profiles, [[layer], []], heights_m=even_heights(10000.0, 10))
    assert xsec.cloud_layers[0] == [layer]
    assert xsec.cloud_layers[1] == []


def test_even_heights_count_less_than_2_returns_single_zero():
    """even_heights with count < 2 returns [0.0] instead of calling linspace."""
    assert even_heights(max_m=15000.0, count=1) == [0.0]
    assert even_heights(max_m=15000.0, count=0) == [0.0]


def test_build_cross_section_raises_on_length_mismatch():
    """profiles/layers_per_point must align with path samples; mismatched length raises ValueError."""
    path = _path(3)
    profiles = [_profile(s.lat, s.lon) for s in path.samples]
    with pytest.raises(ValueError, match="must align"):
        build_cross_section(path, profiles, [[], []])   # 2 layers for 3-sample path


def test_empty_profile_column_is_fully_masked():
    """A profile with zero-length geometric_height_m is skipped (column stays NaN/masked)."""
    path = _path(1)
    p = _profile(31.0, 121.0)
    object.__setattr__(p, "geometric_height_m", np.array([], dtype=float))
    xsec = build_cross_section(path, [p], [[]], heights_m=even_heights(10000.0, 10))
    assert not xsec.mask[:, 0].any()
    assert np.isnan(xsec.relative_humidity_pct[:, 0]).all()


def test_profile_span_entirely_outside_heights_is_masked():
    """When no target heights fall within the profile span, valid is all-False → column stays masked."""
    path = _path(1)
    # Profile spans 1000–10000 m; requested heights are all above that.
    p = _profile(31.0, 121.0, base_h=1000.0)
    xsec = build_cross_section(path, [p], [[]], heights_m=[12000.0, 14000.0])
    assert not xsec.mask[:, 0].any()
    assert np.isnan(xsec.relative_humidity_pct[:, 0]).all()
