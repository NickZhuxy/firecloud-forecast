"""Metamorphic physics checks for the composite firecloud score.

These tests do not assert a *correct output value* — the predictor has no
ground truth and emits an explainable condition index, not a calibrated
probability. Instead they pin **directional physical laws**: when one input is
perturbed and everything else held fixed, the composite score must move in the
direction the physics demands (or stay put). A violation is an algorithm bug,
not a tolerance miss.

The composite is evaluated through the real canonical predictor configuration
(`standard_predictor`): the same rule list, weights, and gate/modifier combiner
production uses. We bypass `features.derive` on purpose so each test controls a
single `Features` field via `dataclasses.replace`, isolating the relation under
test from incidental coupling in feature derivation.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from predictor.fetch import FakeSource, WeatherSnapshot
from predictor.rules import gate_modifier_parts, standard_predictor

# A throwaway snapshot only needed to construct the canonical predictor; the
# tests score hand-built Features directly, so its field values are irrelevant.
_SNAPSHOT = WeatherSnapshot(
    cloud_low_pct=0.0,
    cloud_mid_pct=0.0,
    cloud_high_pct=0.0,
    humidity_pct=50.0,
    source_label="metamorphic",
    retrieved_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
)
_PREDICTOR = standard_predictor(FakeSource(_SNAPSHOT))


def composite(features) -> float:
    """Composite P = gate × modifier through the real canonical config.

    Mirrors RuleBasedPredictor.score_snapshot's combine step exactly, but from a
    caller-controlled Features instead of a derived one.
    """
    components = {}
    for rule in _PREDICTOR.rules:
        value = rule.evaluate(features)
        if value is not None:
            components[rule.name] = value
    gate, modifier = gate_modifier_parts(
        components, _PREDICTOR.weights, _PREDICTOR.gate_names
    )
    return gate * modifier


def test_more_low_cloud_obstruction_never_raises_score(base_features):
    """Low cloud blocks sunlight from reaching the canvas, so raising the
    obstructing low-cloud cover (all else equal) must never INCREASE the
    composite score. Obstruction is a gate, so the score is monotonically
    non-increasing in low-cloud cover."""
    obstructions = [0, 10, 20, 40, 60, 80, 100]
    scores = [composite(replace(base_features, cloud_low_pct=o)) for o in obstructions]

    # Strictly non-increasing along the sweep.
    for less_obstructed, more_obstructed in zip(scores, scores[1:]):
        assert more_obstructed <= less_obstructed + 1e-12

    # And the relation is non-vacuous at this baseline: full obstruction must
    # actually kill the score, while a clear foreground keeps it positive.
    assert scores[0] > 0.0
    assert scores[-1] == 0.0


def test_high_cloud_canvas_scores_at_least_as_well_as_mid(base_features):
    """High cloud stays lit longer after sunset and is optically thinner, so a
    high-cloud-dominated canvas must score at least as well as a mid-cloud one at
    the SAME coverage, all else equal — the colour quality cannot be worse just
    because the canvas sits higher."""
    cover = 70.0
    mid_canvas = composite(replace(base_features, cloud_mid_pct=cover, cloud_high_pct=0.0))
    high_canvas = composite(replace(base_features, cloud_mid_pct=0.0, cloud_high_pct=cover))

    assert high_canvas >= mid_canvas - 1e-12
    # Non-vacuous at this baseline: the altitude preference is a real, strict
    # advantage here, not a tie that would pass trivially.
    assert high_canvas > mid_canvas


def test_convective_regime_handling_never_pushes_probability_from_half():
    """FA-C4 (#86), manual §4.1.2 as a directional law: the regime treatment
    may only shrink |P − 0.5| (damping toward uninformative) or leave it
    untouched (stratiform / marginal) — for ANY atmosphere, it must never
    manufacture confidence. End-to-end through score_point_with_cube."""
    from predictor.stability import StabilityConfig
    from predictor.sunward_section import score_point_with_cube
    from predictor.tests.test_sunward_section import (
        _LOW_AND_HIGH,
        _VALID,
        _convective_cube,
        _detail_snapshot,
        _uniform_cube,
    )

    predictor = standard_predictor(FakeSource(snapshot=_detail_snapshot()))
    no_regime = StabilityConfig(congestus_min_depth_m=1e9)
    for cube in (_uniform_cube(_LOW_AND_HIGH), _convective_cube()):
        undamped = score_point_with_cube(
            predictor, cube, _detail_snapshot(), 30.0, 120.0, _VALID,
            distances_km=[0.0, 100.0, 200.0], stability_config=no_regime,
        )
        handled = score_point_with_cube(
            predictor, cube, _detail_snapshot(), 30.0, 120.0, _VALID,
            distances_km=[0.0, 100.0, 200.0],
        )
        assert abs(handled.probability - 0.5) <= abs(undamped.probability - 0.5) + 1e-12
        if handled.geometry["cloud_regime"] == "stratiform":
            assert handled.probability == undamped.probability
