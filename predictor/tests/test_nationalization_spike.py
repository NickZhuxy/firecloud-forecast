"""Offline regression: Stage B refine must beat overview on the synthetic field (#59)."""
import importlib.util
import pathlib


def _load_spike():
    root = pathlib.Path(__file__).resolve().parents[2]
    path = root / "research" / "experiments" / "nationalization_spike.py"
    spec = importlib.util.spec_from_file_location("nationalization_spike", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_stage_b_refine_beats_overview():
    spike = _load_spike()
    result = spike.run()
    by_name = {c["name"]: c for c in result["candidates"]}
    assert "stage_b_refine" in by_name
    overview = by_name["current_overview_grid_score"]
    refine = by_name["stage_b_refine"]
    assert refine["mae"] < overview["mae"]
    assert refine["f1"] >= overview["f1"]
    assert refine["fp"] <= overview["fp"]
