"""Unit tests for cloud-diagnosis uncertainty / cross-time consistency (#11)."""
from predictor.clouds import CloudLayer
from predictor.tests.cloud_scenarios import _profile, _zeros
from predictor.uncertainty import (
    ConfidenceBreakdown,
    assess_layer,
    cross_time_agreement,
)
import numpy as np


def _layer(base, top, *, source="condensate", margin=10.0):
    return CloudLayer(base, top, top - base, "liquid", 0.8, source, signal_margin=margin)


def _profile_with_levels_in(base, top):
    # The shared scenario column; condensate filled so several levels span a layer.
    clw = _zeros()
    return _profile(clw=clw, ice=_zeros())


def test_cross_time_agreement_full_when_all_neighbors_match():
    layer = _layer(3000, 5000)
    neighbors = [[_layer(3100, 5050)], [_layer(2950, 4900)]]
    assert cross_time_agreement(layer, neighbors, tol_m=800) == 1.0


def test_cross_time_agreement_zero_when_no_neighbor_matches():
    layer = _layer(3000, 5000)
    neighbors = [[_layer(9000, 11000)], []]
    assert cross_time_agreement(layer, neighbors, tol_m=800) == 0.0


def test_breakdown_is_structured_and_bounded():
    layer = _layer(2000, 5000)
    bd = assess_layer(layer, _profile_with_levels_in(2000, 5000), [[_layer(2050, 5050)]])
    assert isinstance(bd, ConfidenceBreakdown)
    assert 0.0 <= bd.overall <= 1.0
    assert bd.factors                       # structured reasons, not a black box
    assert all(0.0 <= f.multiplier <= 1.0 for f in bd.factors)
    assert all(f.detail for f in bd.factors)


def test_rh_source_lowers_confidence_with_named_reason():
    prof = _profile_with_levels_in(2000, 5000)
    rh_layer = _layer(2000, 5000, source="rh")
    cond_layer = _layer(2000, 5000, source="condensate")
    rh_bd = assess_layer(rh_layer, prof, [[_layer(2050, 5050)]])
    cond_bd = assess_layer(cond_layer, prof, [[_layer(2050, 5050)]])
    assert rh_bd.overall < cond_bd.overall
    assert any("rh" in f.name.lower() or "回退" in f.detail for f in rh_bd.factors)


def test_time_divergence_lowers_confidence():
    prof = _profile_with_levels_in(2000, 5000)
    layer = _layer(2000, 5000)
    agree = assess_layer(layer, prof, [[_layer(2050, 5050)], [_layer(1990, 4980)]])
    diverge = assess_layer(layer, prof, [[_layer(9000, 11000)], []])
    assert diverge.overall < agree.overall


def test_threshold_edge_lowers_confidence():
    prof = _profile_with_levels_in(2000, 5000)
    edge = assess_layer(_layer(2000, 5000, margin=1.05), prof, [[_layer(2050, 5050)]])
    robust = assess_layer(_layer(2000, 5000, margin=50.0), prof, [[_layer(2050, 5050)]])
    assert edge.overall < robust.overall


def test_no_neighbors_is_neutral_not_zero():
    prof = _profile_with_levels_in(2000, 5000)
    bd = assess_layer(_layer(2000, 5000), prof, [])
    # With no comparison times, confidence is not driven to zero by divergence.
    assert bd.overall > 0.5
