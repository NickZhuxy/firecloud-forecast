"""Offline check of the local-field benchmark harness (synthetic mode)."""
import importlib.util
import pathlib

import numpy as np


def _load_benchmark():
    root = pathlib.Path(__file__).resolve().parents[2]
    path = root / "research" / "experiments" / "local_field_benchmark.py"
    spec = importlib.util.spec_from_file_location("local_field_benchmark", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_synthetic_benchmark_reports_timings_and_field():
    bench = _load_benchmark()
    result = bench.run_synthetic((30.0, 120.0), 40.0, 0.2)
    for key in ("bbox_s", "snapshots_s", "scoring_s", "total_s"):
        assert result[key] >= 0.0
    probability = result["probability"]
    assert result["n_cells"] == probability.size
    assert np.isfinite(probability).all()
    # The synthetic atmosphere varies by column, so the field is not uniform.
    assert np.unique(np.round(probability, 9)).size >= 2


def test_heterogeneous_cube_columns_differ():
    bench = _load_benchmark()
    cube = bench.heterogeneous_cube((28.0, 32.0), (118.0, 122.0))
    columns = {
        tuple(np.round(cube.cloud_water_kg_kg[:, j, i], 12))
        for j in range(cube.lats.size)
        for i in range(cube.lons.size)
    }
    assert len(columns) > 3
    assert cube.temperature_k.shape == (cube.levels_hpa.size, cube.lats.size, cube.lons.size)


def test_benchmark_has_no_workers_option():
    # Parallel scoring was not built; the flag must not reach build_local_field.
    bench = _load_benchmark()
    try:
        bench.main(["synthetic", "--radius", "20", "--resolution", "0.2", "--workers", "2"])
    except SystemExit as exit_:
        assert exit_.code == 2
    else:
        raise AssertionError("--workers was accepted")
