#!/usr/bin/env bash
# verify.sh — EXTERNAL, un-fakeable success gate for the overnight loop.
# Exit 0 = goal met (loop stops). Non-zero = keep looping.
# The agent is forbidden from editing this file; only the driver runs it.
set -uo pipefail
cd "$(dirname "$0")"

# 1) Tests must pass.
if ! pytest -q >/dev/null 2>&1; then
  echo "verify: tests FAILING"; exit 1
fi

# 2) Metrics on the frozen holdout must clear both thresholds.
METRICS="reports/metrics.json"
[ -f "$METRICS" ] || { echo "verify: no metrics.json yet"; exit 1; }

python3 - "$METRICS" <<'PY'
import json, sys
m = json.load(open(sys.argv[1]))
brier = float(m.get("brier", 1.0))   # lower is better
auc   = float(m.get("auc",   0.0))   # higher is better
ok = (brier <= 0.15) and (auc >= 0.80)
print(f"verify: brier={brier:.4f} auc={auc:.4f} -> {'PASS' if ok else 'FAIL'}")
sys.exit(0 if ok else 1)
PY
