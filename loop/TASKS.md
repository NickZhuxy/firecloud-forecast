# TASKS — most important first. The loop picks ONE per iteration and updates this file.

## BLOCKER — needs a human decision (no model iteration can move the metric until resolved)
- [ ] **Decide the label source + labelling rule** for "a good 火烧云 occurred at sunset
      (date D, site L) -> 1/0", AND confirm the pivot to a supervised *probability* model.
      This conflicts with the README stance (no personal training set; output is not a
      probability), so it must be an explicit, deliberate choice. Options to weigh:
      (a) professional/ground-truth observation logs, (b) a satellite-derived proxy label
      with a written rule, (c) human-rated archive. The agent must NOT invent labels or
      write data/holdout/ — that is the scoreboard.
- [ ] Once decided: populate `data/train.parquet` and `data/holdout/holdout.parquet`
      (schema in firecloud_ml/schema.py). Holdout = later dates only, frozen.

## Open (blocked on the decision above)
- [ ] Ingest base golden-hour features from the existing `predictor/` pipeline: low/mid/high
      cloud cover, RH profile by level (already produced by predictor.gfs / profiles).
- [ ] Add sun–cloud geometry feature (predictor.illumination / geometry give solar az/elev).
- [ ] Add a surface visibility / aerosol proxy feature.
- [ ] First real model iteration: fit the logistic baseline, record Brier/AUC vs base-rate,
      then try one motivated improvement (calibration / interactions / a stronger learner).

## Done
- [x] (iter 1) Minimal train+eval entrypoint writing reports/metrics.json — `python -m
      firecloud_ml`; abstains (exit 2, writes nothing) until a real dataset exists.
- [x] (iter 1) Leakage-free split BY DATE, forward in time — `firecloud_ml/split.py`
      (asserts no shared date between train and holdout).
- [x] (iter 1) >= 3 tests: (a) schema, (b) holdout-leakage guard, (c) metrics+model
      sanity — `loop/tests/`, 11 passing.
- [x] (iter 1) Hand-rolled Brier + ROC-AUC and a dependency-free logistic baseline.
