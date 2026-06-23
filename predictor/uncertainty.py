"""Confidence with structured reasons and cross-time consistency (#11).

A single threshold on a single model cycle gives over-precise cloud heights.
This module turns a diagnosed ``CloudLayer`` into a ``ConfidenceBreakdown``: an
overall 0–1 score *and* the named factors that produced it (source fallback,
sparse vertical support, threshold-edge detection, and divergence across
adjacent GFS run/valid times), so the result is auditable, not a black box.

Cross-time comparison takes ``neighbor_diagnoses`` — layer lists from other free
diagnoses (adjacent GFS cycles, or any pluggable free model). It deliberately
introduces no paid ECMWF dependency.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from predictor.clouds import CloudLayer
from predictor.profiles import NormalizedProfile


@dataclass
class ConfidenceFactor:
    name: str
    multiplier: float   # 0–1 contribution to the overall score
    detail: str


@dataclass
class ConfidenceBreakdown:
    overall: float
    factors: list[ConfidenceFactor]


@dataclass(frozen=True)
class UncertaintyConfig:
    match_tolerance_m: float = 800.0     # layers within this base/top distance "agree"
    edge_margin_ratio: float = 2.0       # signal_margin below this → threshold-edge penalty
    rh_source_mult: float = 0.6          # RH fallback is weaker evidence than condensate
    single_level_mult: float = 0.7       # one supporting level → weak vertical structure
    min_edge_mult: float = 0.5           # floor for the threshold-edge factor
    min_time_mult: float = 0.5           # full divergence still leaves this (1 cycle ≠ certainty)


DEFAULT_UNCERTAINTY_CONFIG = UncertaintyConfig()


def _layers_overlap(a: CloudLayer, b: CloudLayer, tol_m: float) -> bool:
    """Two layers agree if their bases and tops are within tolerance."""
    return abs(a.base_m - b.base_m) <= tol_m and abs(a.top_m - b.top_m) <= tol_m


def cross_time_agreement(
    layer: CloudLayer, neighbor_diagnoses: list[list[CloudLayer]], tol_m: float
) -> float:
    """Fraction of neighbor diagnoses that contain a matching layer (0–1)."""
    if not neighbor_diagnoses:
        return math.nan
    hits = sum(
        any(_layers_overlap(layer, other, tol_m) for other in diagnosis)
        for diagnosis in neighbor_diagnoses
    )
    return hits / len(neighbor_diagnoses)


def _levels_in_layer(profile: NormalizedProfile, layer: CloudLayer) -> int:
    h = np.asarray(profile.geometric_height_m, dtype=float)
    return int(np.sum((h >= layer.base_m) & (h <= layer.top_m)))


def assess_layer(
    layer: CloudLayer,
    profile: NormalizedProfile,
    neighbor_diagnoses: list[list[CloudLayer]],
    config: UncertaintyConfig = DEFAULT_UNCERTAINTY_CONFIG,
) -> ConfidenceBreakdown:
    """Build a structured confidence breakdown for one diagnosed layer."""
    factors: list[ConfidenceFactor] = []

    # 1. Diagnostic source.
    if layer.source == "rh":
        factors.append(ConfidenceFactor(
            "rh_fallback", config.rh_source_mult,
            "RH 回退诊断(无凝结物),证据弱于凝结物",
        ))
    else:
        factors.append(ConfidenceFactor(
            "condensate_source", 1.0, "由凝结物直接诊断",
        ))

    # 2. Vertical support (how many levels span the layer).
    levels = _levels_in_layer(profile, layer)
    if levels <= 1:
        factors.append(ConfidenceFactor(
            "sparse_levels", config.single_level_mult,
            f"仅 {levels} 个廓线层支撑,垂直结构稀疏",
        ))
    else:
        factors.append(ConfidenceFactor(
            "vertical_support", 1.0, f"{levels} 个廓线层支撑",
        ))

    # 3. Threshold-edge proximity.
    margin = layer.signal_margin
    if math.isfinite(margin):
        if margin >= config.edge_margin_ratio:
            factors.append(ConfidenceFactor(
                "threshold_margin", 1.0, f"信号远高于阈值 (×{margin:.1f})",
            ))
        else:
            span = config.edge_margin_ratio - 1.0
            frac = (margin - 1.0) / span if span > 0 else 0.0
            mult = config.min_edge_mult + (1.0 - config.min_edge_mult) * max(0.0, min(1.0, frac))
            factors.append(ConfidenceFactor(
                "threshold_edge", round(mult, 3), f"信号接近阈值 (×{margin:.2f})",
            ))

    # 4. Cross-time consistency.
    agreement = cross_time_agreement(layer, neighbor_diagnoses, config.match_tolerance_m)
    if math.isnan(agreement):
        factors.append(ConfidenceFactor(
            "no_cross_time", 1.0, "无相邻时次对照,未计入时次一致性",
        ))
    else:
        mult = config.min_time_mult + (1.0 - config.min_time_mult) * agreement
        n = len(neighbor_diagnoses)
        factors.append(ConfidenceFactor(
            "time_consistency", round(mult, 3),
            f"相邻时次一致 {round(agreement * n)}/{n}",
        ))

    overall = 1.0
    for f in factors:
        overall *= f.multiplier
    return ConfidenceBreakdown(overall=round(overall, 3), factors=factors)
