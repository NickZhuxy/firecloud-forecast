"""Illumination / obstruction from diagnosed cloud layers (#13).

Upgrades the fixed 1 / 3.5 / 7 km representative heights to real diagnosed cloud
bases, tops and thicknesses. Multi-layer skies get a per-layer contribution: how
long each deck stays lit (geometry) and whether a lower deck obstructs it.

This module consumes ``CloudLayer`` lists (#10) and reuses ``geometry`` for the
illumination window. It does not fetch data and does not import the scoring
rules; ``features.derive`` wires the chosen canvas base into the existing gates,
with a graceful fallback to the three-tier estimate when no layers are given.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from predictor.clouds import CloudLayer
from predictor.geometry import characteristic_duration_min


# Opacity proxy for grazing sunlight that lights the canvas. A layer this thick
# is treated as fully opaque; thinner layers attenuate proportionally. Liquid
# attenuates most, glaciated (ice) cirrus least, mixed in between.
_FULL_OPACITY_THICKNESS_M = 2000.0
_PHASE_OPACITY = {"liquid": 1.0, "mixed": 0.7, "ice": 0.4}


@dataclass
class LayerContribution:
    base_m: float
    top_m: float
    phase_hint: str
    confidence: float
    duration_min: float        # characteristic lit window from this deck's height
    obstructed: bool           # any lower diagnosed layer sits beneath it
    obstruction_fraction: float  # graded 0–1: light blocked by the layers below
    is_canvas: bool            # the deck selected as the colour canvas


def _layer_opacity(layer: CloudLayer) -> float:
    """Opacity (0–1) of a single layer, confidence-weighted.

    Prefers the diagnosed cloud optical depth τ (FA-C1): transmittance
    ``1 − exp(−τ)`` supersedes the coarse thickness×phase proxy, so a thin-but-
    dense water deck reads opaque and a deep-but-wispy cirrus reads sheer. When τ
    is unavailable (RH-fallback or single-level layer → NaN), it falls back to the
    ``thickness × phase`` estimate. Confidence weights the result either way, so an
    uncertain deck hedges rather than vetoes the whole forecast.
    """
    confidence = layer.confidence if math.isfinite(layer.confidence) else 0.0
    confidence = min(1.0, max(0.0, confidence))

    optical_depth = layer.optical_depth
    if math.isfinite(optical_depth):
        return (1.0 - math.exp(-max(0.0, optical_depth))) * confidence

    thickness_m = layer.thickness_m
    if not math.isfinite(thickness_m) or thickness_m <= 0:
        return 0.0
    thickness = min(1.0, thickness_m / _FULL_OPACITY_THICKNESS_M)
    phase = _PHASE_OPACITY.get(layer.phase_hint, _PHASE_OPACITY["mixed"])
    return thickness * phase * confidence


def _obstruction_below(layer: CloudLayer, layers: list[CloudLayer]) -> float:
    """Graded fraction of light blocked by all layers below ``layer``.

    Precondition: ``layers`` are vertically disjoint (as ``diagnose_clouds``
    emits) — the transmittance product ``1 − Π(1 − opacity)`` only holds for
    non-overlapping decks. "Below" is a base-height comparison; a hand-built deck
    that interpenetrates the canvas would be overcounted.
    """
    clear = 1.0
    for other in layers:
        if other.base_m < layer.base_m:
            clear *= 1.0 - _layer_opacity(other)
    return 1.0 - clear


def canvas_obstruction_fraction(layers: list[CloudLayer]) -> float | None:
    """Graded obstruction (0–1) of the canvas layer, or None without layers."""
    canvas = canvas_layer_from_diagnosis(layers)
    if canvas is None:
        return None
    return _obstruction_below(canvas, layers)


def canvas_layer_from_diagnosis(layers: list[CloudLayer]) -> CloudLayer | None:
    """Pick the colour canvas: the highest diagnosed deck (lit longest)."""
    if not layers:
        return None
    return max(layers, key=lambda layer: layer.base_m)


def cloud_base_from_diagnosis(layers: list[CloudLayer]) -> float | None:
    """Base height (m) of the canvas layer, or None when there are no layers."""
    canvas = canvas_layer_from_diagnosis(layers)
    return canvas.base_m if canvas is not None else None


def assess_layer_contributions(
    layers: list[CloudLayer], lat: float
) -> list[LayerContribution]:
    """Per-layer illumination window and obstruction, preserving input order."""
    canvas = canvas_layer_from_diagnosis(layers)
    contributions: list[LayerContribution] = []
    for layer in layers:
        fraction = _obstruction_below(layer, layers)
        contributions.append(
            LayerContribution(
                base_m=layer.base_m,
                top_m=layer.top_m,
                phase_hint=layer.phase_hint,
                confidence=layer.confidence,
                duration_min=characteristic_duration_min(layer.base_m, lat),
                obstructed=any(other.base_m < layer.base_m for other in layers),
                obstruction_fraction=fraction,
                is_canvas=layer is canvas,
            )
        )
    return contributions
