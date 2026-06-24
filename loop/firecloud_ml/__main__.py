"""Train/eval entrypoint:  python -m firecloud_ml

Writes ``reports/metrics.json`` ONLY when a real labelled dataset is present.
With no data it prints what is required and exits non-zero, leaving no metrics
file — so ``verify.sh`` stays honestly red instead of passing on nothing.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from firecloud_ml.pipeline import DatasetMissing, run

_ROOT = Path(__file__).resolve().parent.parent  # the loop/ project root


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="firecloud_ml")
    parser.add_argument("--data-dir", default=str(_ROOT / "data"))
    parser.add_argument("--reports", default=str(_ROOT / "reports" / "metrics.json"))
    args = parser.parse_args(argv)

    try:
        metrics = run(args.data_dir, args.reports)
    except DatasetMissing as exc:
        print(f"DATA REQUIRED — not run: {exc}", file=sys.stderr)
        print(
            "Provide a labelled dataset (see data/README.md). This harness will "
            "not invent labels or a holdout.",
            file=sys.stderr,
        )
        return 2

    print(
        f"brier={metrics['brier']:.4f} auc={metrics['auc']:.4f} "
        f"(base_rate={metrics['base_rate']:.3f}, "
        f"n_train={metrics['n_train']}, n_holdout={metrics['n_holdout']}) "
        f"-> {args.reports}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
