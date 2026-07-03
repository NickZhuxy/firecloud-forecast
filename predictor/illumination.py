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
from collections.abc import Mapping
from dataclasses import dataclass

from predictor.clouds import CloudLayer, tier_from_height
from predictor.geometry import characteristic_duration_min


# Opacity proxy for grazing sunlight that lights the canvas. A layer this thick
# is treated as fully opaque; thinner layers attenuate proportionally. Liquid
# attenuates most, glaciated (ice) cirrus least, mixed in between.
_FULL_OPACITY_THICKNESS_M = 2000.0
_PHASE_OPACITY = {"liquid": 1.0, "mixed": 0.7, "ice": 0.4}

# FA-C2 (manual §4.1.1): multi-criteria canvas selection. Cover is the dominant
# criterion — the only one allowed to zero a candidate; the others are bounded
# modifiers with floors so a thin-but-real deck stays viable (thin cirrus burns
# beautifully — thinness means "less robust", not "not a canvas").
# Mirrors features._LAYER_PRESENCE_THRESHOLD; features imports this module, so
# the constant cannot be imported the other way without a cycle.
_CANVAS_PRESENCE_COVER_PCT = 10.0
_SUBSTANCE_FLOOR = 0.5
_HEIGHT_FLOOR = 0.6
_HEIGHT_SPAN = 0.4
_HEIGHT_FULL_M = 8000.0
_EXTENT_FLOOR = 0.5


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


@dataclass
class CanvasCandidate:
    """One diagnosed deck's standing in the canvas selection (FA-C2)."""

    layer: CloudLayer
    tier: str                  # WMO étage of the deck's base
    eligible: bool             # passed étage precedence (low ≠ canvas under mid/high)
    is_canvas: bool
    cover_pct: float | None    # étage cover fed in; None = unknown
    boundary_km: float | None  # sunward étage boundary fed in; None = unknown
    cover_term: float
    substance_term: float
    height_term: float
    extent_term: float
    score: float               # cover · substance · height · extent


@dataclass
class CanvasSelection:
    """The chosen canvas plus the per-candidate criteria that explain it."""

    layer: CloudLayer | None
    candidates: list[CanvasCandidate]


def _tier_value(
    mapping: Mapping[str, float] | None, tier: str
) -> float | None:
    if mapping is None:
        return None
    value = mapping.get(tier)
    if value is None:
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def select_canvas(
    layers: list[CloudLayer],
    *,
    cover_pct_by_tier: Mapping[str, float] | None = None,
    boundary_km_by_tier: Mapping[str, float] | None = None,
) -> CanvasSelection:
    """Pick the colour canvas by the manual's multi-criteria logic (FA-C2, §4.1.1).

    Two steps, mirroring the 伊春 worked example ("高云云量没有中云多,而且高云
    边界比中云边界近,所以直接看中云"):

    1. Étage precedence: candidates are the mid/high decks whose étage cover is
       unknown or ≥ the presence threshold — low cloud under a present elevated
       deck is obstruction, not canvas (#13). Only when no elevated deck is
       present does the whole sky compete (深圳 stratocumulus case).
    2. ``score = cover · substance · height · extent`` over the candidates;
       ties break to the higher base (the old rule's degenerate case). Cover is
       dominant; substance (τ, thickness×phase fallback), height and boundary
       extent are floored modifiers — robustness signals, not vetoes.

    ``cover_pct_by_tier``/``boundary_km_by_tier`` map étage → value from the
    same-source cover field / sunward transect; missing entries read neutral.
    With no auxiliary data at all, equal-substance decks fall back to the old
    "highest deck wins" behaviour.
    """
    if not layers:
        return CanvasSelection(layer=None, candidates=[])

    tiers = [tier_from_height(layer.base_m) for layer in layers]
    covers = [_tier_value(cover_pct_by_tier, tier) for tier in tiers]

    def _present(idx: int) -> bool:
        cover = covers[idx]
        return cover is None or cover >= _CANVAS_PRESENCE_COVER_PCT

    elevated = [
        idx for idx, tier in enumerate(tiers) if tier != "low" and _present(idx)
    ]
    eligible = set(elevated) if elevated else set(range(len(layers)))

    boundaries = [_tier_value(boundary_km_by_tier, tier) for tier in tiers]
    boundary_ref = max(
        (boundaries[idx] for idx in eligible if boundaries[idx] is not None),
        default=None,
    )

    candidates: list[CanvasCandidate] = []
    for idx, layer in enumerate(layers):
        cover = covers[idx]
        cover_term = (
            1.0 if cover is None else min(100.0, max(0.0, cover)) / 100.0
        )
        substance_term = (
            _SUBSTANCE_FLOOR + (1.0 - _SUBSTANCE_FLOOR) * _layer_opacity(layer)
        )
        base_m = layer.base_m if math.isfinite(layer.base_m) else 0.0
        height_term = _HEIGHT_FLOOR + _HEIGHT_SPAN * min(
            max(base_m, 0.0) / _HEIGHT_FULL_M, 1.0
        )
        boundary = boundaries[idx]
        if boundary is None or boundary_ref is None or boundary_ref <= 0.0:
            extent_term = 1.0
        else:
            extent_term = _EXTENT_FLOOR + (1.0 - _EXTENT_FLOOR) * min(
                boundary / boundary_ref, 1.0
            )
        candidates.append(
            CanvasCandidate(
                layer=layer,
                tier=tiers[idx],
                eligible=idx in eligible,
                is_canvas=False,
                cover_pct=cover,
                boundary_km=boundary,
                cover_term=cover_term,
                substance_term=substance_term,
                height_term=height_term,
                extent_term=extent_term,
                score=cover_term * substance_term * height_term * extent_term,
            )
        )

    winner = max(
        (cand for cand in candidates if cand.eligible),
        key=lambda cand: (cand.score, cand.layer.base_m),
    )
    winner.is_canvas = True
    return CanvasSelection(layer=winner.layer, candidates=candidates)


def canvas_layer_from_diagnosis(
    layers: list[CloudLayer],
    *,
    cover_pct_by_tier: Mapping[str, float] | None = None,
    boundary_km_by_tier: Mapping[str, float] | None = None,
) -> CloudLayer | None:
    """The canvas deck per :func:`select_canvas` (FA-C2), or None without layers."""
    return select_canvas(
        layers,
        cover_pct_by_tier=cover_pct_by_tier,
        boundary_km_by_tier=boundary_km_by_tier,
    ).layer


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
