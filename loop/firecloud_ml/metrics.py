"""Probabilistic scoring — hand-rolled to keep the harness dependency-free.

``brier_score`` (lower better) and ``roc_auc`` (higher better) are the two gates
the external ``verify.sh`` checks. ROC-AUC uses the Mann–Whitney rank identity
with tie-averaged ranks, so it matches ``sklearn.metrics.roc_auc_score`` without
the dependency.
"""
from __future__ import annotations

import numpy as np


def brier_score(y_true, p) -> float:
    """Mean squared error between predicted probabilities and 0/1 outcomes."""
    y = np.asarray(y_true, dtype=float)
    prob = np.asarray(p, dtype=float)
    if y.shape != prob.shape:
        raise ValueError("y_true and p must have the same shape")
    if y.size == 0:
        return float("nan")
    return float(np.mean((prob - y) ** 2))


def _average_ranks(sorted_vals: np.ndarray) -> np.ndarray:
    """Ranks 1..n for an ascending array, ties sharing their average rank."""
    n = sorted_vals.size
    ranks = np.arange(1, n + 1, dtype=float)
    i = 0
    while i < n:
        j = i
        while j + 1 < n and sorted_vals[j + 1] == sorted_vals[i]:
            j += 1
        if j > i:
            ranks[i : j + 1] = (i + 1 + j + 1) / 2.0
        i = j + 1
    return ranks


def roc_auc(y_true, p) -> float:
    """Area under the ROC curve. ``nan`` if only one class is present."""
    y = np.asarray(y_true, dtype=float)
    prob = np.asarray(p, dtype=float)
    if y.shape != prob.shape:
        raise ValueError("y_true and p must have the same shape")
    pos = y == 1
    n_pos = int(pos.sum())
    n_neg = int((y == 0).sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan")

    order = np.argsort(prob, kind="mergesort")
    ranks = np.empty(prob.size, dtype=float)
    ranks[order] = _average_ranks(prob[order])
    sum_pos = ranks[pos].sum()
    return float((sum_pos - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg))
