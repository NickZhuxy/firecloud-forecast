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
    """Gate: is there any mid/high cloud 'canvas' at all?

    Presence ramp on combined mid+high coverage — 0 at 0%, rising linearly to
    1.0 by 20%, saturating thereafter. Whether the *amount* is ideal (the
    40–75% sweet spot) is a separate enhancing concern handled by
    CloudCoverSweetSpot; this gate only enforces that a canvas exists.
    """
    name = "mid_high_cloud_presence"

    def evaluate(self, f: Features) -> float:
        avg = (f.cloud_mid_pct + f.cloud_high_pct) / 2.0
        if avg <= 0:
            return 0.0
        return min(1.0, avg / 20.0)


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
    """Modifier: reward middling humidity (40–80%); penalize extremes."""
    name = "humidity"

    def evaluate(self, f: Features) -> float:
        return _trapezoid(f.humidity_pct, low0=20, low1=40, high1=80, high0=95)


class CleanAirGate:
    """Gate: is the troposphere clean enough to deliver red light to the canvas?

    Uses surface visibility as an aerosol-loading proxy (HRRR and Open-Meteo
    both carry it; AOD is unavailable). Score 1.0 at ≥ 20 km, ramping linearly
    to 0 at ≤ 5 km. When visibility is unknown the gate is permissive (1.0) so
    it never silently zeroes a forecast on missing data. See paper §2.4, §5.4.
    """
    name = "clean_air"

    def evaluate(self, f: Features) -> float:
        vis = f.visibility_m
        if vis is None:
            return 1.0
        vis_km = vis / 1000.0
        if vis_km >= 20.0:
            return 1.0
        if vis_km <= 5.0:
            return 0.0
        return (vis_km - 5.0) / 15.0


class CloudAltitudePreference:
    """Modifier: reward canvases dominated by higher cloud.

    High cloud stays lit longer after sunset and is optically thinner, so a
    high-cloud-dominated canvas yields better colour than a mid-cloud one. Score
    is coverage-weighted altitude quality (high weighted 1.0, mid 0.5),
    normalised to [0, 1]; returns 0 when no mid/high cloud is present.
    """
    name = "cloud_altitude_preference"

    def evaluate(self, f: Features) -> float:
        mid, high = f.cloud_mid_pct, f.cloud_high_pct
        total = mid + high
        if total <= 0:
            return 0.0
        return (1.0 * high + 0.5 * mid) / total


class CloudCoverSweetSpot:
    """Modifier: reward the 40–75% mid+high coverage sweet spot.

    Too little cloud is a thin canvas; too much closes off the western horizon.
    Trapezoidal membership peaking on [40, 75]% of averaged mid+high coverage
    (SunsetWx targets 50–75%, Sunsethue 40–60%).
    """
    name = "cloud_cover_sweet_spot"

    def evaluate(self, f: Features) -> float:
        avg = (f.cloud_mid_pct + f.cloud_high_pct) / 2.0
        return _trapezoid(avg, low0=10, low1=40, high1=75, high0=95)


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


def gate_modifier_parts(
    components: dict[str, float],
    weights: dict[str, float],
    gate_names: set[str],
) -> tuple[float, float]:
    """Return ``(gate, modifier)`` for the two-layer architecture.

        G = ∏ s_i ** (w_i / W_G)   over gates,     W_G = Σ w_i  (gates)
        M = (Σ w_j * s_j) / W_M    over modifiers, W_M = Σ w_j  (modifiers)

    Semantics:
        - Any gate score equal to 0 forces G = 0 → P = G·M = 0.
        - With no gates, G = 1. With no modifiers, M = 1.
        - Gate weight 0 means the rule does not contribute (treated as score 1).

    See paper §6.2 for the derivation and the relation to noisy-AND models.
    """
    gate_scores = {k: v for k, v in components.items() if k in gate_names}
    mod_scores = {k: v for k, v in components.items() if k not in gate_names}

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

    return gate, modifier


def gate_modifier_combiner(
    gate_names: set[str],
) -> Callable[[dict[str, float], dict[str, float]], float]:
    """Build a combiner returning the composite ``P = G * M``.

    Thin wrapper over :func:`gate_modifier_parts` for callers that only want the
    scalar. See that function for the full definition.
    """
    gate_set = set(gate_names)

    def combiner(components: dict[str, float], weights: dict[str, float]) -> float:
        gate, modifier = gate_modifier_parts(components, weights, gate_set)
        return gate * modifier

    return combiner


# Canonical configuration for the full physics-motivated predictor (paper Table 5).
STANDARD_WEIGHTS: dict[str, float] = {
    "mid_high_cloud_presence": 2.0,
    "low_cloud_obstruction": 2.0,
    "solar_angle": 1.5,
    "clean_air": 1.5,
    "humidity": 1.0,
    "cloud_altitude_preference": 1.0,
    "cloud_cover_sweet_spot": 1.5,
}
STANDARD_GATES: set[str] = {
    "mid_high_cloud_presence",
    "low_cloud_obstruction",
    "solar_angle",
    "clean_air",
}


class RuleBasedPredictor:
    def __init__(
        self,
        rules: list[ScoringRule],
        weights: dict[str, float] | None = None,
        source: WeatherSource | None = None,
        combiner: Callable[[dict[str, float], dict[str, float]], float] = weighted_average,
        gate_names: set[str] | None = None,
    ):
        if source is None:
            raise ValueError("RuleBasedPredictor requires a WeatherSource")
        self.rules = rules
        self.weights = weights or {}
        self.source = source
        self.combiner = combiner
        # When gate_names is set, score() uses the two-layer architecture and
        # records the gate/modifier breakdown on the Forecast. Otherwise it uses
        # the (baseline) `combiner`.
        self.gate_names = set(gate_names) if gate_names is not None else None

    def score(self, lat: float, lon: float, time) -> Forecast:
        snapshot = self.source.fetch(lat, lon, time)
        return self.score_snapshot(snapshot, lat, lon, time)

    def score_snapshot(self, snapshot, lat: float, lon: float, time) -> Forecast:
        """Score a pre-fetched snapshot (the compute half, no IO).

        Lets batch callers (e.g. the map grid) fetch many points in one request
        and then evaluate each without a per-point network round-trip.
        """
        feats = derive(snapshot, lat, lon, time)
        components = {r.name: r.evaluate(feats) for r in self.rules}

        if self.gate_names is not None:
            gate, modifier = gate_modifier_parts(components, self.weights, self.gate_names)
            prob = gate * modifier
            return Forecast(
                probability=prob,
                components=components,
                explanation=self._explain(components, prob, gate, modifier),
                inputs=snapshot.to_dict(),
                gate_score=gate,
                modifier_score=modifier,
            )

        prob = self.combiner(components, self.weights)
        return Forecast(
            probability=prob,
            components=components,
            explanation=self._explain(components, prob),
            inputs=snapshot.to_dict(),
        )

    def _explain(
        self,
        components: dict[str, float],
        prob: float,
        gate: float | None = None,
        modifier: float | None = None,
    ) -> str:
        pieces = [f"{k}={v:.2f}" for k, v in components.items()]
        head = f"Composite={prob:.2f}"
        if gate is not None:
            head += f" (gate={gate:.2f} × modifier={modifier:.2f})"
        return head + " from " + ", ".join(pieces)


def standard_predictor(source: WeatherSource) -> RuleBasedPredictor:
    """Build the full physics-motivated predictor (7 rules, gate × modifier).

    This is the canonical configuration consumed by the web app, notebook, and
    figures: four necessary-condition gates (mid/high canvas, low-cloud horizon,
    solar timing, clean air) and three enhancing modifiers (humidity, cloud
    altitude, cover sweet spot), combined per paper §6.2.
    """
    return RuleBasedPredictor(
        rules=[
            MidHighCloudPresence(),
            LowCloudObstruction(),
            SolarAngleAtSunset(),
            CleanAirGate(),
            HumidityFactor(),
            CloudAltitudePreference(),
            CloudCoverSweetSpot(),
        ],
        weights=STANDARD_WEIGHTS,
        source=source,
        gate_names=STANDARD_GATES,
    )
