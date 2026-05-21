"""End-to-end smoke test using FakeSource (no network)."""
from datetime import datetime, timezone, timedelta
from predictor.fetch import FakeSource, WeatherSnapshot
from predictor.rules import (
    RuleBasedPredictor,
    MidHighCloudPresence, LowCloudObstruction,
    SolarAngleAtSunset, HumidityFactor,
)


def _default_predictor(snapshot: WeatherSnapshot) -> RuleBasedPredictor:
    return RuleBasedPredictor(
        rules=[
            MidHighCloudPresence(),
            LowCloudObstruction(),
            SolarAngleAtSunset(),
            HumidityFactor(),
        ],
        weights={
            "mid_high_cloud_presence": 2.0,
            "low_cloud_obstruction": 2.0,
            "solar_angle": 1.5,
            "humidity": 1.0,
        },
        source=FakeSource(snapshot),
    )


def test_high_probability_scenario():
    """A 'beautiful sunset' configuration near sunset should score high."""
    snap = WeatherSnapshot(
        cloud_low_pct=10, cloud_mid_pct=50, cloud_high_pct=50,
        humidity_pct=60, source_label="fake",
        retrieved_at=datetime(2026, 5, 20, tzinfo=timezone.utc),
    )
    p = _default_predictor(snap)
    # Boston, just before local sunset on a late-May day:
    t = datetime(2026, 5, 21, 0, 0, tzinfo=timezone.utc)  # ~20:00 EDT
    f = p.score(lat=42.36, lon=-71.06, time=t)
    assert f.probability > 0.7, f"Expected high, got {f.probability}: {f.explanation}"


def test_low_probability_scenario_overcast_at_noon():
    """Heavy low cloud + far from sunset → low score."""
    snap = WeatherSnapshot(
        cloud_low_pct=95, cloud_mid_pct=10, cloud_high_pct=5,
        humidity_pct=95, source_label="fake",
        retrieved_at=datetime(2026, 5, 20, tzinfo=timezone.utc),
    )
    p = _default_predictor(snap)
    t = datetime(2026, 5, 20, 16, 0, tzinfo=timezone.utc)  # noon EDT
    f = p.score(lat=42.36, lon=-71.06, time=t)
    assert f.probability < 0.2, f"Expected low, got {f.probability}: {f.explanation}"
