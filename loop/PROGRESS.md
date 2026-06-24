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

### 2026-06-25  iter 2
hardened: polar/midnight-sun fallback + all error branches in `sunset_grid.py`.
Added 17 tests to `predictor/tests/test_sunset_grid.py` covering:
- `_axis()` raises on empty / 2-D / non-finite inputs (lines 20, 22).
- `_inclusive_axis()` raises on zero / negative / NaN step (line 28).
- `_sunset_timestamp()` polar fallback: at 80°N on 2026-06-22 (midnight sun) astral
  raises ValueError; fallback returns `midnight UTC + (18h − lon/15h)` — three tests
  pin the exact values for lon=0° (18:00 UTC) and lon=120°E (10:00 UTC) and verify
  that `sunset_utc_grid` over a polar domain yields non-NaT output (lines 44-51).
- `hourly_valid_times()` raises on empty and NaT-containing arrays (line 95).
- `nearest_valid_time_indices()` raises on empty/NaT sunsets, empty valid_times,
  and non-increasing valid_times (lines 112, 114, 128).
Line 33 in `_inclusive_axis()` is unreachable defensive code (insert when first value
doesn't align with lo) — skipped; will not be covered by normal usage.
cov 92% → 93% (1957 stmts, 146 missed). suite green (296 passed, 5 deselected).
sunset_grid.py now at 98% (only line 33 unreachable).
next: close the 13-line gap in national_field.py (lines 59, 61, 75, 77, 121, 123,
  126, 143, 163, 183-187, 196) — many are trivial error-branch tests requiring no GFS
  mock; tackle them as the next atomic step.
need 48 more lines to reach 95% floor.
