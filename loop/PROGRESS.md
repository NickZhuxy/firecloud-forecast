# PROGRESS — Firecloud Forecast physics-hardening loop
# Append-only, newest at the bottom. The loop reads this FIRST every iteration.
# This is the agent's only long-term memory between context resets.

## Mission
Harden the physics of `predictor/` (robustness, physical correctness, offline test coverage).
External gate (verify.sh): offline suite green AND predictor/ source coverage ≥ COV_FLOOR (95%).
No ML, no labelled data, no probability calibration — this project validates with offline
physics scenarios + public-data cross-checks (see repo README).

## Baseline — 2026-06-25 (loop repurposed)
- offline suite: 279 passed (`PYTHONPATH=. uv run pytest -m "not integration" -q`).
- predictor/ SOURCE coverage (coveragerc scope, excl tests & gfs_smoke): ~92%.  Floor = 95%.
- weakest source modules: national_product (~77%), gfs (~91%), national_field (~88%),
  sunset_grid (~83%), rules / features / profiles / clouds / cross_section (~90–95%).
- PIVOT NOTE: this loop was first set up for a supervised next-day *probability* model on a
  frozen labelled holdout. That goal had no data and no label source and contradicted the
  project's documented "no training set / not a probability" stance, so per the owner's
  decision (2026-06-25) it was dropped and the harness re-centered on hardening the existing
  physics. The earlier ML scaffold (firecloud_ml/, its tests, data contract) was removed.

## Log
<!-- iteration entries appended below, e.g.:
### 2026-06-25  iter 1
hardened: scores-in-[0,1] invariant over fuzzed Features; found+fixed a NaN leak in rules.py.
cov 92.0% -> 92.6%. suite green. next: cloud-geometry top≥base≥surface invariant.
-->
