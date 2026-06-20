from predictor.score import Forecast, Predictor
from predictor.fetch import (
    WeatherSnapshot, WeatherSource, FakeSource, HRRRSource, OpenMeteoSource,
)
from predictor.features import Features, derive, estimate_cloud_base_m
from predictor.rules import (
    ScoringRule,
    MidHighCloudPresence, LowCloudObstruction,
    SolarAngleAtSunset, HumidityFactor,
    CleanAirGate, CloudAltitudePreference, CloudCoverSweetSpot,
    RuleBasedPredictor, weighted_average,
    gate_modifier_combiner, gate_modifier_parts,
    standard_predictor, STANDARD_WEIGHTS, STANDARD_GATES,
)
from predictor.geometry import GeometryResult, compute_geometry

__all__ = [
    "Forecast", "Predictor", "Features", "derive", "estimate_cloud_base_m",
    "WeatherSnapshot", "WeatherSource", "FakeSource", "HRRRSource", "OpenMeteoSource",
    "ScoringRule", "RuleBasedPredictor", "weighted_average",
    "gate_modifier_combiner", "gate_modifier_parts",
    "standard_predictor", "STANDARD_WEIGHTS", "STANDARD_GATES",
    "MidHighCloudPresence", "LowCloudObstruction",
    "SolarAngleAtSunset", "HumidityFactor",
    "CleanAirGate", "CloudAltitudePreference", "CloudCoverSweetSpot",
    "GeometryResult", "compute_geometry",
]
