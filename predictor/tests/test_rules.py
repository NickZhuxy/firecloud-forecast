# predictor/tests/test_rules.py
from dataclasses import replace
from predictor.rules import MidHighCloudPresence


def test_mid_high_cloud_zero_cover_scores_zero(base_features):
    f = replace(base_features, cloud_mid_pct=0, cloud_high_pct=0)
    assert MidHighCloudPresence().evaluate(f) == 0.0


def test_mid_high_cloud_full_cover_scores_zero(base_features):
    f = replace(base_features, cloud_mid_pct=100, cloud_high_pct=100)
    assert MidHighCloudPresence().evaluate(f) == 0.0


def test_mid_high_cloud_sweet_spot_scores_one(base_features):
    # Average mid+high = 50 → in [30, 70] plateau → 1.0
    f = replace(base_features, cloud_mid_pct=50, cloud_high_pct=50)
    assert MidHighCloudPresence().evaluate(f) == 1.0


def test_mid_high_cloud_low_end_ramp(base_features):
    # Avg = 15 → linear from 0 at 0% to 1 at 30%  → 0.5
    f = replace(base_features, cloud_mid_pct=10, cloud_high_pct=20)
    assert abs(MidHighCloudPresence().evaluate(f) - 0.5) < 1e-9


# Append to predictor/tests/test_rules.py
from predictor.rules import LowCloudObstruction


def test_low_cloud_zero_scores_one(base_features):
    f = replace(base_features, cloud_low_pct=0)
    assert LowCloudObstruction().evaluate(f) == 1.0


def test_low_cloud_small_scores_one(base_features):
    f = replace(base_features, cloud_low_pct=15)
    assert LowCloudObstruction().evaluate(f) == 1.0


def test_low_cloud_full_scores_zero(base_features):
    f = replace(base_features, cloud_low_pct=100)
    assert LowCloudObstruction().evaluate(f) == 0.0


def test_low_cloud_mid_range_linear(base_features):
    # Linear ramp from 1.0 at 20% to 0.0 at 100% → at 60% should be 0.5
    f = replace(base_features, cloud_low_pct=60)
    assert abs(LowCloudObstruction().evaluate(f) - 0.5) < 1e-9
