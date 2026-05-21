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


class Predictor(Protocol):
    def score(self, lat: float, lon: float, time: datetime) -> Forecast: ...
