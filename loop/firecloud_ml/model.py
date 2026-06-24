"""A small, dependency-free logistic-regression baseline.

Standardises features on the training fold, then fits weights by full-batch
gradient descent with L2. It is intentionally simple — a credible baseline to
beat once real data exists, not a tuned model. ``base_rate`` is the null model
(predict the training prevalence for everyone); any real model must beat it.
"""
from __future__ import annotations

import numpy as np


def base_rate(y_train) -> float:
    """The training-set prevalence — the no-skill baseline probability."""
    y = np.asarray(y_train, dtype=float)
    return float(y.mean()) if y.size else 0.5


class LogisticRegression:
    def __init__(self, lr: float = 0.1, n_iter: int = 800, l2: float = 1e-3):
        self.lr = lr
        self.n_iter = n_iter
        self.l2 = l2

    def fit(self, X, y) -> "LogisticRegression":
        X = np.asarray(X, dtype=float)
        y = np.asarray(y, dtype=float)
        if X.ndim != 2:
            raise ValueError("X must be 2-D (n_samples, n_features)")
        self.mean_ = X.mean(axis=0)
        self.std_ = X.std(axis=0)
        self.std_[self.std_ == 0] = 1.0
        Xs = (X - self.mean_) / self.std_

        n, d = Xs.shape
        self.w_ = np.zeros(d)
        self.b_ = 0.0
        # Some BLAS builds (numpy 2.0 + Accelerate) leak benign FP flags out of
        # matmul as RuntimeWarnings; the math is well-conditioned (standardised
        # features, L2, clipped sigmoid), so silence them for pristine output.
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            for _ in range(self.n_iter):
                p = _sigmoid(Xs @ self.w_ + self.b_)
                err = p - y
                self.w_ -= self.lr * (Xs.T @ err / n + self.l2 * self.w_)
                self.b_ -= self.lr * err.mean()
        return self

    def predict_proba(self, X) -> np.ndarray:
        X = np.asarray(X, dtype=float)
        Xs = (X - self.mean_) / self.std_
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            return _sigmoid(Xs @ self.w_ + self.b_)


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30.0, 30.0)))
