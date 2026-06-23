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

from dataclasses import dataclass

from predictor.clouds import CloudLayer
from predictor.geometry import characteristic_duration_min


@dataclass
class LayerContribution:
    base_m: float
    top_m: float
    phase_hint: str
    confidence: float
    duration_min: float   # characteristic lit window from this deck's height
    obstructed: bool      # a lower diagnosed layer sits beneath it
    is_canvas: bool       # the deck selected as the colour canvas


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
        obstructed = any(other.base_m < layer.base_m for other in layers)
        contributions.append(
            LayerContribution(
                base_m=layer.base_m,
                top_m=layer.top_m,
                phase_hint=layer.phase_hint,
                confidence=layer.confidence,
                duration_min=characteristic_duration_min(layer.base_m, lat),
                obstructed=obstructed,
                is_canvas=layer is canvas,
            )
        )
    return contributions
