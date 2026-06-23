"""Offline cloud-diagnosis regression tests over controlled scenarios (#7)."""
import pytest

from predictor.clouds import DEFAULT_CLOUD_CONFIG, diagnose_clouds
from predictor.tests.cloud_scenarios import SCENARIOS


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s.name for s in SCENARIOS])
def test_scenario_layer_count(scenario):
    layers = diagnose_clouds(scenario.profile)
    assert len(layers) == scenario.n_layers


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s.name for s in SCENARIOS])
def test_scenario_layer_geometry_and_confidence(scenario):
    layers = diagnose_clouds(scenario.profile)
    assert len(layers) == len(scenario.layers)
    for layer, expect in zip(layers, scenario.layers):
        lo, hi = expect.base_m
        assert lo <= layer.base_m <= hi, f"{scenario.name} base {layer.base_m}"
        lo, hi = expect.top_m
        assert lo <= layer.top_m <= hi, f"{scenario.name} top {layer.top_m}"
        assert layer.top_m > layer.base_m
        assert 0.0 <= layer.confidence <= expect.conf_max
        if expect.phase_hint is not None:
            assert layer.phase_hint == expect.phase_hint
        if expect.source is not None:
            assert layer.source == expect.source


def test_config_defaults_are_pinned():
    # These pin the thresholds the scenarios were written against. Changing a
    # default here forces a deliberate review of cloud_scenarios.py expectations.
    cfg = DEFAULT_CLOUD_CONFIG
    assert cfg.condensate_threshold_kg_kg == 1e-6
    assert cfg.rh_threshold_pct == 90.0
    assert cfg.merge_gap_m == 300.0
    assert cfg.min_geometric_height_m == 0.0
    assert cfg.condensate_confidence == 0.8
    assert cfg.rh_confidence == 0.5
