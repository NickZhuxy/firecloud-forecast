"""Scoring rules and the rule-based predictor."""
from __future__ import annotations
from typing import Protocol
from predictor.features import Features


class ScoringRule(Protocol):
    name: str
    def evaluate(self, features: Features) -> float: ...   # returns 0.0–1.0


def _trapezoid(x: float, low0: float, low1: float, high1: float, high0: float) -> float:
    """Trapezoidal membership function.

    0 outside [low0, high0], 1 inside [low1, high1], linear ramps on each side.
    """
    if x <= low0 or x >= high0:
        return 0.0
    if low1 <= x <= high1:
        return 1.0
    if x < low1:
        return (x - low0) / (low1 - low0)
    return (high0 - x) / (high0 - high1)


class MidHighCloudPresence:
    """Reward 30–70% combined mid+high cloud cover (the 'canvas')."""
    name = "mid_high_cloud_presence"

    def evaluate(self, f: Features) -> float:
        avg = (f.cloud_mid_pct + f.cloud_high_pct) / 2.0
        return _trapezoid(avg, low0=0, low1=30, high1=70, high0=100)
