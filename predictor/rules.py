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


class LowCloudObstruction:
    """Penalize low cloud cover that blocks sunlight from reaching the canvas.

    Score 1.0 up to 20%, linear ramp to 0.0 by 100%.
    """
    name = "low_cloud_obstruction"

    def evaluate(self, f: Features) -> float:
        if f.cloud_low_pct <= 20:
            return 1.0
        return max(0.0, 1.0 - (f.cloud_low_pct - 20) / 80.0)


class SolarAngleAtSunset:
    """Score how close the query time is to the local sunset.

    1.0 within ±30 min of sunset; linear ramp to 0 by ±60 min; 0 beyond.
    """
    name = "solar_angle"

    def evaluate(self, f: Features) -> float:
        diff_min = abs((f.query_time - f.sunset_time).total_seconds()) / 60.0
        if diff_min <= 30:
            return 1.0
        if diff_min >= 60:
            return 0.0
        return (60 - diff_min) / 30.0


class HumidityFactor:
    """Reward middling humidity (40–80%); penalize extremes."""
    name = "humidity"

    def evaluate(self, f: Features) -> float:
        return _trapezoid(f.humidity_pct, low0=20, low1=40, high1=80, high0=95)
