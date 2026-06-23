"""Public types for the predictor package."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


@dataclass
class Forecast:
    probability: float
    components: dict[str, float]
    explanation: str
    inputs: dict[str, Any] = field(default_factory=dict)
    # Two-layer breakdown (populated when a gate × modifier predictor is used;
    # None for plain weighted-average scoring). See paper §6.2.
    gate_score: float | None = None
    modifier_score: float | None = None
    # Optional geometry enrichment (duration, reach) attached by callers that
    # also run the spatiotemporal model. Kept loose so scoring stays decoupled.
    geometry: dict[str, Any] | None = None


class Predictor(Protocol):
    def score(self, lat: float, lon: float, time: datetime) -> Forecast: ...
