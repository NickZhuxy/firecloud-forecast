"""Canvas-source unification: canvas_layer + altitude follow the diagnosed canvas (#32)."""
from datetime import datetime, timezone

from predictor.clouds import CloudLayer
from predictor.features import Features, derive, tier_from_height
from predictor.fetch import WeatherSnapshot
from predictor.rules import CloudAltitudePreference

_T = datetime(2026, 6, 23, 10, 20, tzinfo=timezone.utc)


def _snapshot(**over) -> WeatherSnapshot:
    base = dict(
        cloud_low_pct=5.0, cloud_mid_pct=70.0, cloud_high_pct=20.0, humidity_pct=55.0,
        source_label="test", retrieved_at=datetime(2026, 6, 23, 5, tzinfo=timezone.utc),
        sunset_time=datetime(2026, 6, 23, 10, 30, tzinfo=timezone.utc),
    )
    base.update(over)
    return WeatherSnapshot(**base)


def _layer(base, top, *, phase="ice", conf=0.8):
    return CloudLayer(base, top, top - base, phase, conf, "condensate", signal_margin=10.0)


def test_tier_from_height_boundaries():
    assert tier_from_height(1500.0) == "low"
    assert tier_from_height(2000.0) == "mid"   # 2 km is the low/mid boundary
    assert tier_from_height(3500.0) == "mid"
    assert tier_from_height(6000.0) == "high"  # 6 km is the mid/high boundary
    assert tier_from_height(8000.0) == "high"


def test_canvas_layer_follows_diagnosed_height_over_snapshot():
    # Snapshot is mid-dominant (mid 70 > high 20), but the diagnosed canvas is a
    # 7 km high deck → canvas_layer must be "high", not the three-tier "mid".
    feats = derive(_snapshot(), 31.0, 121.0, _T, cloud_layers=[_layer(7000, 9000)])
    assert feats.canvas_layer == "high"
    assert feats.cloud_base_source == "diagnosed"
    # canvas_cloud_pct reflects that tier's snapshot coverage (high → 20%).
    assert feats.canvas_cloud_pct == 20.0


def test_canvas_layer_three_tier_when_no_diagnosis():
    feats = derive(_snapshot(), 31.0, 121.0, _T)  # mid-dominant snapshot
    assert feats.canvas_layer == "mid"
    assert feats.canvas_cloud_pct == 70.0


def test_altitude_preference_follows_diagnosed_canvas():
    # Diagnosed high canvas → altitude preference 1.0 even though the snapshot
    # mid/high blend would give ~0.72.
    feats = derive(_snapshot(), 31.0, 121.0, _T, cloud_layers=[_layer(7000, 9000)])
    assert CloudAltitudePreference().evaluate(feats) == 1.0

    mid_feats = derive(_snapshot(), 31.0, 121.0, _T, cloud_layers=[_layer(3500, 5000)])
    assert mid_feats.canvas_layer == "mid"
    assert CloudAltitudePreference().evaluate(mid_feats) == 0.5


def test_altitude_preference_unchanged_without_diagnosis():
    # mid 70 / high 20 → (1*20 + 0.5*70)/90 = 0.611…, the legacy coverage blend.
    feats = derive(_snapshot(), 31.0, 121.0, _T)
    assert abs(CloudAltitudePreference().evaluate(feats) - (20 + 35) / 90) < 1e-9
