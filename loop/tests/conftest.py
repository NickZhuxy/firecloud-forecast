"""Synthetic-data builders for the harness tests.

All data here is generated in-memory for plumbing tests only. Nothing is written
to disk; in particular nothing creates ``data/holdout/`` or ``reports/``.
"""
import numpy as np
import pandas as pd
import pytest

from firecloud_ml.schema import FEATURE_COLUMNS


def _frame(rng, dates, rows_per_date, signal):
    """A schema-valid frame; ``signal`` controls how learnable ``label`` is."""
    records = []
    for d in dates:
        for k in range(rows_per_date):
            feats = {c: float(rng.uniform(0, 100)) for c in FEATURE_COLUMNS}
            # A simple learnable rule: moist mid-levels + some high cloud → 火烧云.
            score = (
                feats["rh_700_pct"] + feats["cloud_high_pct"] - feats["cloud_low_pct"]
            ) / 100.0
            noise = rng.normal(0, 1 - signal)
            label = int((score + noise) > 1.0)
            records.append({"date": d, "location_id": f"loc{k}", **feats, "label": label})
    return pd.DataFrame.from_records(records)


@pytest.fixture
def make_frame():
    def _make(n_dates=20, rows_per_date=8, signal=0.9, seed=0):
        rng = np.random.default_rng(seed)
        dates = pd.date_range("2026-01-01", periods=n_dates, freq="D")
        return _frame(rng, dates, rows_per_date, signal)

    return _make
