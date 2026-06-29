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
    GeometryResult, OverheadWindow, AerosolGroundRange,
    compute_geometry, equivalent_cloud_base_from_aod_m,
    equivalent_cloud_base_range_from_aod_m,
    viewing_elevation_deg, overhead_firecloud_window,
    viewing_extension_min, total_observed_duration_min,
)
from predictor.spatial import (
    SunwardProfile, destination_point, sunward_coordinates,
    DEFAULT_SUNWARD_DISTANCES_KM,
)
from predictor.ray_path import RayClearance, ray_height_m, trace_ray_clearance
from predictor.sunward_section import (
    assemble_sunward_cross_section, sunward_cross_section_for_point,
    score_point_with_sunward_section, score_point_with_cube,
)
from predictor.local_field import LocalField, build_local_field, local_grid
from predictor.local_product import (
    generate_local_product, plot_local_product, save_local_product,
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
    "GeometryResult", "OverheadWindow", "AerosolGroundRange",
    "compute_geometry", "equivalent_cloud_base_from_aod_m",
    "equivalent_cloud_base_range_from_aod_m",
    "viewing_elevation_deg", "overhead_firecloud_window",
    "viewing_extension_min", "total_observed_duration_min",
    "SunwardProfile", "destination_point", "sunward_coordinates",
    "DEFAULT_SUNWARD_DISTANCES_KM",
    "RayClearance", "ray_height_m", "trace_ray_clearance",
    "assemble_sunward_cross_section", "sunward_cross_section_for_point",
    "score_point_with_sunward_section", "score_point_with_cube",
    "LocalField", "build_local_field", "local_grid",
    "generate_local_product", "plot_local_product", "save_local_product",
]
