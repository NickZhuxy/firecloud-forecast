# Efficiency & Conciseness Pass

**Date:** 2026-06-22
**Status:** approved, scoped to Tier 1 + Tier 2

## Goal

Make the system more efficient and concise without rewriting code that is
already clean. The `predictor` package and the single-file frontend are
already well-factored; this pass removes verified waste only.

## Scope

### Tier 1 — waste removal, no behavior change

1. **Remove dead solar-elevation compute.** `Features.solar_elevation_deg` is
   computed in `derive()` via astral `elevation()` but read by no scoring rule
   (only a test references the field). Remove the field, the `elevation()`
   call, and the unused import. Each national overlay build currently makes
   ~187 of these astral calls per refresh, all discarded.

2. **Skip redundant astral `sun()`.** `derive()` recomputes sunset via astral
   even when the snapshot already carries Open-Meteo's daily sunset (it always
   does). Only fall back to astral when `snapshot.sunset_time is None`. This
   removes another ~187 astral calls per overlay build and the duplicate call
   on every point click (server computes sunset, then `derive` recomputed it).

3. **De-duplicate shared helpers.** `SCORE_OFFSET` and `_evening_instant` are
   copy-pasted in `app/server.py` and `app/overlay.py`. Move them to a single
   shared module and import from both.

### Tier 2 — latency

4. **Parallelize the two upstream requests per click.** `fetch_sunward_profile`
   issues the weather request and the air-quality request sequentially; they
   are independent endpoints. Run them concurrently to roughly halve click
   latency. AOD must still degrade gracefully to `None` on failure.

### Explicitly out of scope

- `overlay.py` caching machinery (staleness/grace/building) — load-bearing for
  API conservation; not worth the risk.
- Frontend — already lean.

## Constraints / success criteria

- All existing tests (`predictor/tests`, `app/tests`) stay green; new behavior
  (item 2 conditional, item 4 concurrency) gets a covering test.
- No change to forecast outputs for any input (items 1–3 are pure refactors;
  item 4 changes only request scheduling, not results).
- The running server still serves `/api/health`, `/api/forecast`,
  `/api/overlay/cn` correctly after the change.

## Data flow touched

`overlay._build` / `server._point_forecast` → `rules.score_snapshot` →
`features.derive` (items 1, 2); `fetch.OpenMeteoSource.fetch_sunward_profile`
(item 4); shared time helpers (item 3).
