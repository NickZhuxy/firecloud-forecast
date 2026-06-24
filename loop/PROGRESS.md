# PROGRESS — Project Cloud Agent (火烧云 predictor)
# Append-only, newest at the bottom. The loop reads this FIRST every iteration.
# This is the agent's only long-term memory between context resets.

## Baseline
- best Brier: UNMEASURED on real data (no labelled holdout exists — see iter 1)
- best AUC:   UNMEASURED on real data
- notes: cold start. Goal = Brier <= 0.15 AND AUC >= 0.80 on data/holdout/. BLOCKED: the
  holdout and a label source do not exist; the harness will not fabricate them.

## Log
<!-- iteration entries appended below, newest at the bottom. -->

### 2026-06-25  iter 1 — bootstrap harness; BLOCKED on data/labels (a human decision)
read first: PROGRESS (cold start), TASKS (all open), reports/metrics.json (absent).

investigated the repo for any dataset / label source:
  - NO `data/holdout/`, NO training data, NO `reports/`, NO label column anywhere.
  - `research/observations/` is empty; no tabular data files in the repo.
  - README (line ~82) is explicit: 「项目不规划依靠个人长期观察积累训练集」 and 「不把当前条件
    指数描述为统计概率」. `research/README.md` repeats it. The project deliberately has no
    labelled training set and does not treat its output as a calibrated probability.

=> TWO blockers, both needing a human:
  1. HARD DATA BLOCKER. A supervised Brier/AUC goal needs labelled examples
     ("was there a good 火烧云 at sunset on date D, site L?"). There is no such data and
     no label source. The PROMPT forbids the agent from writing data/holdout/ (it is the
     scoreboard); inventing labels would be fake skill. So no metric can move yet.
  2. DIRECTION CONFLICT. The supervised-probability goal contradicts the documented
     project stance (no training set, output is not a probability). Needs an explicit
     human go/no-go on this pivot before pouring effort into a learned model.

decision (per the PROMPT's own guardrails: "goal mis-specified / blocked -> write it down,
make the smallest safe progress, and stop; never move the goalposts or fake completion"):
  - did NOT create data/holdout/, did NOT write a passing reports/metrics.json, did NOT edit
    verify.sh / loop.sh / PROMPT.md.
  - smallest safe progress = stood up the label-AGNOSTIC foundation the loop needs, so the
    moment real data exists the loop runs end-to-end:
      firecloud_ml/schema.py    row contract (étage cloud cover, RH profile, visibility,
                                sun–cloud geometry, label) + validate()
      firecloud_ml/split.py     leakage-free FORWARD-IN-TIME split by date (asserts no shared
                                date between train and holdout)
      firecloud_ml/metrics.py   hand-rolled Brier + ROC-AUC (tie-averaged ranks; no sklearn)
      firecloud_ml/model.py     tiny dependency-free logistic baseline + base-rate null model
      firecloud_ml/pipeline.py  train_and_evaluate (pure) + run() that writes metrics.json
                                ONLY from a real dataset, else raises DatasetMissing
      firecloud_ml/__main__.py  `python -m firecloud_ml` — abstains (exit 2, writes nothing)
                                when data is absent
      tests/ (3 required)       schema, holdout-leakage guard, metrics+model sanity — 11 pass
    verified: 11/11 tests pass; entrypoint abstains with no data; reports/ holds no
    metrics.json; verify.sh stays honestly RED. Plumbing sanity on SYNTHETIC (not holdout)
    data: the baseline recovers a planted signal (auc≈0.98, brier≈0.05), confirming the
    harness can learn when given labels — this is NOT a real-data result and is not recorded
    as one.

metric delta: none (no real data by design).

runtime note for the driver: verify.sh calls bare `pytest` / `python3`. In this repo pytest
lives in the uv venv (`.venv/bin/pytest`), and bare `pytest` is not on PATH — so verify.sh's
test gate currently fails for "pytest not found", not a real test failure. Activate `.venv`
(or put pytest+pandas+numpy on PATH) before running the loop. System `python3` already has
pandas/numpy, so `python3 -m firecloud_ml` works.

next (all require the human decision above first):
  - DECIDE the label source + labelling rule, and confirm the supervised-probability pivot.
  - then: ingest real features via the existing predictor/ pipeline; populate data/train +
    data/holdout; only then do model iterations move Brier/AUC.
STOP here — looping without data/labels would be flailing, which the PROMPT forbids.
