"""The per-column diagnosis cache must reproduce uncached results exactly."""
import dataclasses
import importlib.util
import math
import pathlib

import numpy as np
import pytest

from predictor.column_cache import ColumnDiagnosisCache
from predictor.local_field import local_grid
from predictor.rules import standard_predictor
from predictor.spatial import build_sunward_path
from predictor.sunward_section import (
    DETAIL_SUNWARD_DISTANCES_KM,
    assemble_sunward_cross_section,
    score_point_with_cube,
)


def _load_benchmark():
    root = pathlib.Path(__file__).resolve().parents[2]
    path = root / "research" / "experiments" / "local_field_benchmark.py"
    spec = importlib.util.spec_from_file_location("local_field_benchmark", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BENCH = _load_benchmark()
VALID = BENCH.SYNTHETIC_VALID


def assert_same(a, b, where="value"):
    """Deep exact equality across dataclasses, containers, arrays and NaN floats."""
    if dataclasses.is_dataclass(a) and not isinstance(a, type):
        assert type(a) is type(b), where
        for f in dataclasses.fields(a):
            assert_same(getattr(a, f.name), getattr(b, f.name), f"{where}.{f.name}")
    elif isinstance(a, np.ndarray) or isinstance(b, np.ndarray):
        np.testing.assert_array_equal(np.asarray(a), np.asarray(b), err_msg=where)
    elif isinstance(a, dict):
        assert a.keys() == b.keys(), where
        for key in a:
            assert_same(a[key], b[key], f"{where}[{key!r}]")
    elif isinstance(a, (list, tuple)):
        assert len(a) == len(b), where
        for i, (x, y) in enumerate(zip(a, b)):
            assert_same(x, y, f"{where}[{i}]")
    elif isinstance(a, float) and isinstance(b, float) and math.isnan(a):
        assert math.isnan(b), where
    else:
        assert a == b, where


def _shanghai_cube():
    return BENCH.heterogeneous_cube((21.0, 41.0), (107.0, 136.0))


def _nyc_cube():
    return BENCH.heterogeneous_cube((31.0, 51.0), (-88.0, -60.0))


def test_cache_key_matches_profile_at_nearest_column():
    cache = ColumnDiagnosisCache(_shanghai_cube())
    assert cache.key(30.01, 120.02) == cache.key(30.09, 120.11)
    assert cache.key(30.10, 120.0) != cache.key(30.15, 120.0)
    nyc = ColumnDiagnosisCache(_nyc_cube())
    assert nyc.key(40.71, -74.01) == nyc.key(40.74, -73.96)
    assert nyc.key(40.71, -74.01) != nyc.key(40.71, -74.20)
    profile = nyc.cube.profile_at(40.71, -74.01)
    yi, xi = nyc.key(40.71, -74.01)
    assert (profile.lat, profile.lon) == (float(nyc.cube.lats[yi]), float(nyc.cube.lons[xi]))


def test_cache_memoizes_per_column():
    cache = ColumnDiagnosisCache(_shanghai_cube())
    first = cache.layers(30.0, 120.0)
    again = cache.layers(30.01, 120.01)
    cache.layers(31.0, 121.0)
    assert again is first
    assert (cache.misses, cache.hits) == (2, 1)


def test_cache_rejects_a_different_config():
    from predictor.clouds import CloudDiagnosisConfig

    cube = _shanghai_cube()
    path = build_sunward_path(30.0, 120.0, VALID, distances_km=DETAIL_SUNWARD_DISTANCES_KM)
    with pytest.raises(ValueError):
        assemble_sunward_cross_section(
            path, cube, config=CloudDiagnosisConfig(), column_cache=ColumnDiagnosisCache(cube),
        )


def test_cross_section_with_cache_equals_without():
    cube = _shanghai_cube()
    cache = ColumnDiagnosisCache(cube)
    # The first two observers are neighbours, so their paths share columns.
    for lat, lon in ((31.23, 121.47), (31.25, 121.48), (30.5, 120.2)):
        path = build_sunward_path(lat, lon, VALID, distances_km=DETAIL_SUNWARD_DISTANCES_KM)
        assert len(path.samples) == 33
        plain = assemble_sunward_cross_section(path, cube)
        cached = assemble_sunward_cross_section(path, cube, column_cache=cache)
        assert_same(plain, cached, "cross_section")
    assert cache.hits > 0


@pytest.mark.parametrize(
    ("center", "cube_factory", "count"),
    [((31.23, 121.47), _shanghai_cube, 20), ((40.7128, -74.006), _nyc_cube, 10)],
)
def test_score_point_with_cube_cache_and_path_parity(center, cube_factory, count):
    cube = cube_factory()
    predictor = standard_predictor(BENCH.SyntheticSource())
    lats, lons = local_grid(*center, radius_km=150.0, resolution_deg=0.1)
    rng = np.random.default_rng(7)
    picks = [(float(rng.choice(lats)), float(rng.choice(lons))) for _ in range(count)]
    shared = ColumnDiagnosisCache(cube)   # one cache across cells: the mutation guard
    for lat, lon in picks:
        snapshot = BENCH.synthetic_snapshot(lat, lon)
        plain = score_point_with_cube(
            predictor, cube, snapshot, lat, lon, VALID, distances_km=DETAIL_SUNWARD_DISTANCES_KM,
        )
        path = build_sunward_path(lat, lon, VALID, distances_km=DETAIL_SUNWARD_DISTANCES_KM)
        cached = score_point_with_cube(
            predictor, cube, snapshot, lat, lon, VALID,
            distances_km=DETAIL_SUNWARD_DISTANCES_KM, column_cache=shared, path=path,
        )
        assert_same(plain, cached, f"forecast({lat}, {lon})")
    assert shared.hits > 0
