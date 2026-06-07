"""Scoring rules and the rule-based predictor."""
from __future__ import annotations
from typing import Callable, Protocol
from predictor.features import Features, derive
from predictor.fetch import WeatherSource
from predictor.score import Forecast


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


# ---------------------------------------------------------------------------
# Combiner + predictor
# ---------------------------------------------------------------------------


def weighted_average(components: dict[str, float], weights: dict[str, float]) -> float:
    """Weighted average with default weight 1.0 for missing keys."""
    total_w = 0.0
    acc = 0.0
    for name, value in components.items():
        w = weights.get(name, 1.0)
        acc += w * value
        total_w += w
    return acc / total_w if total_w > 0 else 0.0


def gate_modifier_combiner(
    gate_names: set[str],
) -> Callable[[dict[str, float], dict[str, float]], float]:
    """Build a combiner implementing the two-layer gate × modifier architecture.

    Rules whose ``name`` is in ``gate_names`` form the gate layer; the remaining
    rules form the modifier layer. The composite is ``P = G * M`` where:

        G = ∏ s_i ** (w_i / W_G)   over gates,  W_G = Σ w_i   (gates)
        M = (Σ w_j * s_j) / W_M    over modifiers, W_M = Σ w_j (modifiers)

    Semantics:
        - Any gate score equal to 0 forces G = 0 → P = 0 regardless of modifiers.
        - With no gates, G = 1 and P = M (pure weighted-average).
        - With no modifiers, M = 1 and P = G (pure weighted geometric mean).
        - Gate weight 0 means the rule does not contribute (treated as score 1).

    See paper §6.2 for the derivation and the relation to noisy-AND models.
    """
    gate_set = set(gate_names)

    def combiner(components: dict[str, float], weights: dict[str, float]) -> float:
        gate_scores = {k: v for k, v in components.items() if k in gate_set}
        mod_scores = {k: v for k, v in components.items() if k not in gate_set}

        # Gate layer: weighted geometric mean.
        if not gate_scores:
            gate = 1.0
        else:
            total_w_gate = sum(weights.get(k, 1.0) for k in gate_scores)
            if total_w_gate <= 0:
                gate = 1.0
            else:
                gate = 1.0
                for name, score in gate_scores.items():
                    w = weights.get(name, 1.0)
                    if w <= 0:
                        continue
                    if score <= 0:
                        gate = 0.0
                        break
                    gate *= score ** (w / total_w_gate)

        # Modifier layer: weighted arithmetic mean.
        if not mod_scores:
            modifier = 1.0
        else:
            total_w_mod = sum(weights.get(k, 1.0) for k in mod_scores)
            if total_w_mod <= 0:
                modifier = 1.0
            else:
                modifier = sum(
                    weights.get(k, 1.0) * v for k, v in mod_scores.items()
                ) / total_w_mod

        return gate * modifier

    return combiner


class RuleBasedPredictor:
    def __init__(
        self,
        rules: list[ScoringRule],
        weights: dict[str, float] | None = None,
        source: WeatherSource | None = None,
        combiner: Callable[[dict[str, float], dict[str, float]], float] = weighted_average,
    ):
        if source is None:
            raise ValueError("RuleBasedPredictor requires a WeatherSource")
        self.rules = rules
        self.weights = weights or {}
        self.source = source
        self.combiner = combiner

    def score(self, lat: float, lon: float, time) -> Forecast:
        snapshot = self.source.fetch(lat, lon, time)
        feats = derive(snapshot, lat, lon, time)
        components = {r.name: r.evaluate(feats) for r in self.rules}
        prob = self.combiner(components, self.weights)
        return Forecast(
            probability=prob,
            components=components,
            explanation=self._explain(components, prob),
            inputs=snapshot.to_dict(),
        )

    def _explain(self, components: dict[str, float], prob: float) -> str:
        pieces = [f"{k}={v:.2f}" for k, v in components.items()]
        return f"Composite={prob:.2f} from " + ", ".join(pieces)
