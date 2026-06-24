"""Foundation for an offline next-day 火烧云 (burning-cloud) sunset predictor.

Scaffold only. It provides a leakage-free, label-agnostic train/eval harness:
a row schema, a strictly temporal (no future leakage) split, hand-rolled Brier /
ROC-AUC scoring, and a small dependency-free logistic baseline. It deliberately
does NOT ship any data, any labels, or a ``reports/metrics.json`` — those require
a real labelled dataset, which the project does not yet have (see PROGRESS.md).

Nothing here reads or writes ``data/holdout/``; the entrypoint refuses to run
until a real dataset is supplied, so the external ``verify.sh`` gate stays
honestly red rather than passing on fabricated numbers.
"""
from firecloud_ml.metrics import brier_score, roc_auc
from firecloud_ml.model import LogisticRegression, base_rate
from firecloud_ml.schema import FEATURE_COLUMNS, REQUIRED_COLUMNS, SchemaError, validate
from firecloud_ml.split import split_by_date

__all__ = [
    "brier_score",
    "roc_auc",
    "LogisticRegression",
    "base_rate",
    "FEATURE_COLUMNS",
    "REQUIRED_COLUMNS",
    "SchemaError",
    "validate",
    "split_by_date",
]
