from predictor.score import Forecast, Predictor
from predictor.fetch import (
    WeatherSnapshot, WeatherSource, FakeSource, HRRRSource, OpenMeteoSource,
)
from predictor.features import (
    Features, derive, estimate_cloud_base_m, select_canvas_layer,
    analyze_sunward_profile,
)
from predictor.rules import (
    ScoringRule,
    MidHighCloudPresence, LowCloudObstruction,
    SolarAngleAtSunset, HumidityFactor,
    CleanAirGate, CloudAltitudePreference, CloudCoverSweetSpot,
    SunwardIlluminationGate, BoundaryConfidence,
    RuleBasedPredictor, weighted_average,
    gate_modifier_combiner, gate_modifier_parts,
    standard_predictor, STANDARD_WEIGHTS, STANDARD_GATES,
)
from predictor.geometry import (
    GeometryResult, compute_geometry, equivalent_cloud_base_from_aod_m,
)
from predictor.spatial import (
    SunwardProfile, destination_point, sunward_coordinates,
    DEFAULT_SUNWARD_DISTANCES_KM,
)

__all__ = [
    "Forecast", "Predictor", "Features", "derive", "estimate_cloud_base_m",
    "select_canvas_layer", "analyze_sunward_profile",
    "WeatherSnapshot", "WeatherSource", "FakeSource", "HRRRSource", "OpenMeteoSource",
    "ScoringRule", "RuleBasedPredictor", "weighted_average",
    "gate_modifier_combiner", "gate_modifier_parts",
    "standard_predictor", "STANDARD_WEIGHTS", "STANDARD_GATES",
    "MidHighCloudPresence", "LowCloudObstruction",
    "SolarAngleAtSunset", "HumidityFactor",
    "CleanAirGate", "CloudAltitudePreference", "CloudCoverSweetSpot",
    "SunwardIlluminationGate", "BoundaryConfidence",
    "GeometryResult", "compute_geometry", "equivalent_cloud_base_from_aod_m",
    "SunwardProfile", "destination_point", "sunward_coordinates",
    "DEFAULT_SUNWARD_DISTANCES_KM",
]
