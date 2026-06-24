"""(c) metrics correctness + end-to-end pipeline sanity (in valid range)."""
import math

import numpy as np

from firecloud_ml.metrics import brier_score, roc_auc
from firecloud_ml.pipeline import train_and_evaluate
from firecloud_ml.split import split_by_date


def test_brier_known_values():
    y = [1, 0, 1, 0]
    assert brier_score(y, [1, 0, 1, 0]) == 0.0          # perfect
    assert brier_score(y, [0.5] * 4) == 0.25            # max-uncertainty


def test_auc_known_values():
    y = [0, 0, 1, 1]
    assert roc_auc(y, [0.1, 0.2, 0.8, 0.9]) == 1.0      # perfectly separated
    assert roc_auc(y, [0.9, 0.8, 0.2, 0.1]) == 0.0      # perfectly inverted
    assert roc_auc(y, [0.5, 0.5, 0.5, 0.5]) == 0.5      # all ties → chance


def test_auc_is_nan_for_single_class():
    assert math.isnan(roc_auc([1, 1, 1], [0.2, 0.5, 0.9]))


def test_pipeline_metrics_are_in_range_and_show_signal(make_frame):
    df = make_frame(n_dates=40, rows_per_date=10, signal=0.9, seed=1)
    train, holdout = split_by_date(df, holdout_frac=0.25)
    m = train_and_evaluate(train, holdout)

    assert set(m) >= {"brier", "auc", "base_rate", "n_train", "n_holdout"}
    assert 0.0 <= m["brier"] <= 1.0
    assert 0.0 <= m["auc"] <= 1.0
    assert m["n_train"] > 0 and m["n_holdout"] > 0
    # The baseline must extract the planted signal: clearly better than chance.
    assert m["auc"] > 0.75
    assert not np.isnan(m["auc"])
