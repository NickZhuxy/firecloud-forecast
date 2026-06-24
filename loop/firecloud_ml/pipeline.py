"""Train + evaluate orchestration: frames in, metrics out.

``train_and_evaluate`` is pure (no I/O) so tests can drive it with synthetic
frames. ``run`` is the only thing that touches disk, and only ever to READ a
real dataset and WRITE ``reports/metrics.json`` — never to write ``data/holdout/``.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from firecloud_ml.metrics import brier_score, roc_auc
from firecloud_ml.model import LogisticRegression, base_rate
from firecloud_ml.schema import FEATURE_COLUMNS, LABEL_COLUMN, validate
from firecloud_ml.split import split_by_date


def train_and_evaluate(train_df: pd.DataFrame, holdout_df: pd.DataFrame) -> dict:
    """Fit the baseline on ``train_df`` and score it on ``holdout_df``."""
    train = validate(train_df)
    holdout = validate(holdout_df)

    overlap = set(train["date"].unique()) & set(holdout["date"].unique())
    if overlap:
        raise ValueError(f"train/holdout share dates (leakage): {sorted(overlap)[:3]}…")

    X_train = train[FEATURE_COLUMNS].to_numpy()
    y_train = train[LABEL_COLUMN].to_numpy()
    X_hold = holdout[FEATURE_COLUMNS].to_numpy()
    y_hold = holdout[LABEL_COLUMN].to_numpy()

    model = LogisticRegression().fit(X_train, y_train)
    p_hold = model.predict_proba(X_hold)

    return {
        "brier": brier_score(y_hold, p_hold),
        "auc": roc_auc(y_hold, p_hold),
        "base_rate": base_rate(y_train),
        "n_train": int(len(train)),
        "n_holdout": int(len(holdout)),
        "n_features": len(FEATURE_COLUMNS),
    }


class DatasetMissing(FileNotFoundError):
    """Raised when the real labelled dataset is not present on disk."""


def run(data_dir: str | Path, reports_path: str | Path) -> dict:
    """Read a real dataset, score, and persist ``metrics.json``.

    Expects ``<data_dir>/train.parquet`` and ``<data_dir>/holdout/holdout.parquet``.
    Raises :class:`DatasetMissing` (writing nothing) if either is absent, so the
    external gate never passes on data that does not exist.
    """
    data_dir = Path(data_dir)
    train_path = data_dir / "train.parquet"
    holdout_path = data_dir / "holdout" / "holdout.parquet"
    if not train_path.exists() or not holdout_path.exists():
        raise DatasetMissing(
            f"need {train_path} and {holdout_path}; neither is fabricated by this harness"
        )

    metrics = train_and_evaluate(pd.read_parquet(train_path), pd.read_parquet(holdout_path))
    reports_path = Path(reports_path)
    reports_path.parent.mkdir(parents=True, exist_ok=True)
    reports_path.write_text(json.dumps(metrics, indent=2, default=float) + "\n")
    return metrics
