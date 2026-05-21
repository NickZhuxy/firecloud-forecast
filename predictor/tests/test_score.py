from datetime import datetime
from predictor.score import Forecast


def test_forecast_construction_and_str():
    f = Forecast(
        probability=0.62,
        components={"mid_high_cloud_presence": 0.8, "low_cloud_obstruction": 0.4},
        explanation="Decent canvas with some low cloud blocking",
        inputs={"cloud_low_pct": 20.0},
    )
    assert 0.0 <= f.probability <= 1.0
    assert "mid_high_cloud_presence" in f.components
    assert "Decent canvas" in f.explanation
    assert f.inputs["cloud_low_pct"] == 20.0


def test_forecast_inputs_defaults_to_empty_dict():
    f = Forecast(probability=0.1, components={}, explanation="")
    assert f.inputs == {}
