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


def _layer(base, top, *, conf, phase="ice"):
    return CloudLayer(base, top, top - base, phase, conf, "condensate", signal_margin=10.0)


def test_diagnosed_layers_drive_cloud_base():
    # Use a confidence (0.63) distinct from clouds.py's 0.8 prior so the asserted
    # value provably comes from the layer, not a coincidental default.
    feats = derive(_snapshot(), 31.0, 121.0, _T, cloud_layers=[_layer(7000.0, 9000.0, conf=0.63)])
    assert feats.cloud_base_m == 7000.0
    assert feats.cloud_base_source == "diagnosed"
    assert feats.cloud_base_confidence == 0.63
    # Old three-tier estimate (mid deck → 3500 m) retained for comparison.
    assert feats.cloud_base_fixed_m == 3500.0


def test_canvas_layer_confidence_wins_among_multiple_layers():
    # A low deck (conf 0.3) and a high deck (conf 0.9): the canvas is the HIGHEST
    # deck, so its base AND its confidence must propagate — not the low deck's.
    low = _layer(800.0, 1500.0, conf=0.3, phase="liquid")
    high = _layer(7000.0, 9000.0, conf=0.9)
    feats = derive(_snapshot(), 31.0, 121.0, _T, cloud_layers=[low, high])
    assert feats.cloud_base_m == 7000.0
    assert feats.cloud_base_confidence == 0.9


def test_fallback_to_fixed_estimate_lowers_confidence():
    feats = derive(_snapshot(), 31.0, 121.0, _T)  # no layers, no source base
    assert feats.cloud_base_m == 3500.0
    assert feats.cloud_base_source == "fixed_estimate"
    assert feats.cloud_base_confidence == 0.4
    assert feats.cloud_base_fixed_m == 3500.0


def test_source_reported_base_used_when_no_layers():
    feats = derive(_snapshot(cloud_base_m=2200.0), 31.0, 121.0, _T)
    assert feats.cloud_base_m == 2200.0
    assert feats.cloud_base_source == "source_reported"
    assert feats.cloud_base_confidence == 0.7
    assert feats.cloud_base_fixed_m == 3500.0


def test_confidence_ordering_diagnosed_gt_source_gt_fixed():
    # The new-vs-old comparison hinges on this ordering: a diagnosed base is the
    # most trustworthy, a source-reported base next, the fixed estimate least.
    diagnosed = derive(_snapshot(), 31.0, 121.0, _T,
                       cloud_layers=[_layer(7000.0, 9000.0, conf=0.8)]).cloud_base_confidence
    source = derive(_snapshot(cloud_base_m=2200.0), 31.0, 121.0, _T).cloud_base_confidence
    fixed = derive(_snapshot(), 31.0, 121.0, _T).cloud_base_confidence
    assert diagnosed > source > fixed


def test_existing_behavior_unchanged_without_layers():
    # Backward compatibility: same cloud_base_m as the pre-#13 estimate path.
    feats = derive(_snapshot(), 31.0, 121.0, _T)
    assert feats.cloud_base_m == 3500.0  # mid deck representative height


def test_virga_lowers_effective_base_but_not_etage_identity():
    # FA-C6: the canvas's fall streaks lower the GEOMETRY base (reach/duration
    # shrink with it), but the deck's étage identity keeps the true base — the
    # manual measures "云底（不算落幡）".
    virga_canvas = CloudLayer(
        6500.0, 9000.0, 2500.0, "ice", 0.63, "condensate",
        signal_margin=10.0, virga_extension_m=800.0,
    )
    feats = derive(_snapshot(), 31.0, 121.0, _T, cloud_layers=[virga_canvas])
    assert feats.cloud_base_m == 5700.0        # 6500 − 800: effective base
    assert feats.canvas_layer == "high"        # étage by true base (6500 > 6 km)
