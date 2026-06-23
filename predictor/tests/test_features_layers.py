"""derive() integration with diagnosed cloud layers and fallback (#13)."""
from datetime import datetime, timezone

from predictor.clouds import CloudLayer
from predictor.features import derive
from predictor.fetch import WeatherSnapshot


def _snapshot(**over) -> WeatherSnapshot:
    base = dict(
        cloud_low_pct=5.0, cloud_mid_pct=50.0, cloud_high_pct=40.0, humidity_pct=60.0,
        source_label="test", retrieved_at=datetime(2026, 6, 23, 5, tzinfo=timezone.utc),
        sunset_time=datetime(2026, 6, 23, 10, 30, tzinfo=timezone.utc),
    )
    base.update(over)
    return WeatherSnapshot(**base)


_T = datetime(2026, 6, 23, 10, 20, tzinfo=timezone.utc)


def _high_layer():
    return CloudLayer(7000.0, 9000.0, 2000.0, "ice", 0.8, "condensate", signal_margin=10.0)


def test_diagnosed_layers_drive_cloud_base():
    feats = derive(_snapshot(), 31.0, 121.0, _T, cloud_layers=[_high_layer()])
    assert feats.cloud_base_m == 7000.0
    assert feats.cloud_base_source == "diagnosed"
    assert feats.cloud_base_confidence == 0.8
    # Old three-tier estimate (mid deck → 3500 m) retained for comparison.
    assert feats.cloud_base_fixed_m == 3500.0


def test_fallback_to_fixed_estimate_lowers_confidence():
    feats = derive(_snapshot(), 31.0, 121.0, _T)  # no layers, no source base
    assert feats.cloud_base_m == 3500.0
    assert feats.cloud_base_source == "fixed_estimate"
    assert feats.cloud_base_confidence is not None and feats.cloud_base_confidence < 0.5
    assert feats.cloud_base_fixed_m == 3500.0


def test_source_reported_base_used_when_no_layers():
    feats = derive(_snapshot(cloud_base_m=2200.0), 31.0, 121.0, _T)
    assert feats.cloud_base_m == 2200.0
    assert feats.cloud_base_source == "source_reported"


def test_existing_behavior_unchanged_without_layers():
    # Backward compatibility: same cloud_base_m as the pre-#13 estimate path.
    feats = derive(_snapshot(), 31.0, 121.0, _T)
    assert feats.cloud_base_m == 3500.0  # mid deck representative height
