"""GFS mid/high cover drives presence/sweet-spot gates coherently (#35)."""
from datetime import datetime, timezone

from predictor.clouds import CloudLayer
from predictor.features import derive
from predictor.fetch import WeatherSnapshot
from predictor.gfs import EtageCloudCover
from predictor.rules import CloudCoverSweetSpot, MidHighCloudPresence

_T = datetime(2026, 6, 23, 10, 20, tzinfo=timezone.utc)


def _snapshot(**over) -> WeatherSnapshot:
    base = dict(
        cloud_low_pct=5.0, cloud_mid_pct=0.0, cloud_high_pct=0.0, humidity_pct=55.0,
        source_label="test", retrieved_at=datetime(2026, 6, 23, 5, tzinfo=timezone.utc),
        sunset_time=datetime(2026, 6, 23, 10, 30, tzinfo=timezone.utc),
    )
    base.update(over)
    return WeatherSnapshot(**base)


def _high(conf=0.8):
    return CloudLayer(7000.0, 9000.0, 2000.0, "ice", conf, "condensate", signal_margin=10.0)


def _low(conf=0.8):
    return CloudLayer(800.0, 1500.0, 700.0, "liquid", conf, "condensate", signal_margin=10.0)


def test_gfs_cover_resolves_open_meteo_disagreement():
    # Open-Meteo reports ZERO high cloud, but GFS diagnoses a high canvas and
    # GFS HCDC says 60% — the presence gate must see the GFS cover, not be zeroed.
    cover = EtageCloudCover(low_pct=5.0, mid_pct=0.0, high_pct=60.0)
    feats = derive(_snapshot(), 31.0, 121.0, _T, cloud_layers=[_high()], cloud_cover=cover)
    assert feats.diagnosed_mid_high_cover_pct == 60.0
    assert feats.canvas_cloud_pct == 60.0   # canvas deck (high) cover
    assert MidHighCloudPresence().evaluate(feats) == 1.0      # would be 0 on snapshot
    assert CloudCoverSweetSpot().evaluate(feats) > 0.0


def test_low_canvas_still_sees_gfs_mid_high_cover():
    # Regression guard (review blocker): a LOW diagnosed canvas must NOT erase the
    # mid/high cloud GFS itself reports — presence uses max(MCDC, HCDC), not the
    # canvas tier's (low) cover.
    cover = EtageCloudCover(low_pct=90.0, mid_pct=50.0, high_pct=0.0)
    feats = derive(_snapshot(), 31.0, 121.0, _T, cloud_layers=[_low()], cloud_cover=cover)
    assert feats.diagnosed_mid_high_cover_pct == 50.0
    assert MidHighCloudPresence().evaluate(feats) == 1.0      # NOT zeroed by low canvas


def test_no_gfs_mid_high_cover_zeroes_presence_self_consistently():
    # GFS reports only low cloud → no mid/high canvas per the same source.
    cover = EtageCloudCover(low_pct=90.0, mid_pct=0.0, high_pct=0.0)
    feats = derive(_snapshot(), 31.0, 121.0, _T, cloud_layers=[_low()], cloud_cover=cover)
    assert feats.diagnosed_mid_high_cover_pct == 0.0
    assert MidHighCloudPresence().evaluate(feats) == 0.0


def test_gates_use_snapshot_without_gfs_cover():
    feats = derive(_snapshot(cloud_mid_pct=50.0), 31.0, 121.0, _T, cloud_layers=[_high()])
    assert feats.diagnosed_mid_high_cover_pct is None
    assert MidHighCloudPresence().evaluate(feats) == 1.0       # from snapshot mid 50%


def test_gates_unchanged_without_diagnosis():
    feats = derive(_snapshot(cloud_high_pct=60.0), 31.0, 121.0, _T)
    assert feats.diagnosed_mid_high_cover_pct is None
    assert MidHighCloudPresence().evaluate(feats) == 1.0
