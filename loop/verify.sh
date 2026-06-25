#!/usr/bin/env bash
# verify.sh — EXTERNAL, un-fakeable success gate for the overnight physics-hardening loop.
# Exit 0 = goal met (loop stops). Non-zero = keep hardening.
# The agent is forbidden from editing this file; only the driver runs it.
#
# "Done" = the OFFLINE physics suite is green AND predictor/ source coverage clears
# the floor. You cannot raise real coverage without exercising real code paths, and
# you cannot stay green while weakening behaviour — so the gate cannot be faked.
set -uo pipefail
cd "$(dirname "$0")/.."            # repo root — predictor/ lives here

COV_FLOOR="${COV_FLOOR:-95.00}"   # source-coverage target; ratchet up as hardening proceeds
export UV_CACHE_DIR="${UV_CACHE_DIR:-$(pwd)/.uv-cache}"
mkdir -p "$UV_CACHE_DIR"

# Offline only (integration/network tests excluded — validation is offline by design).
PYTHONPATH=. uv run pytest -m "not integration" -q \
    --cov=predictor --cov-config=loop/coveragerc \
    --cov-fail-under="$COV_FLOOR"
rc=$?

if [ "$rc" -eq 0 ]; then
  echo "verify: offline suite green AND predictor/ coverage >= ${COV_FLOOR}% -> PASS"
  exit 0
fi
echo "verify: NOT done (suite red or coverage < ${COV_FLOOR}%) -> keep hardening"
exit 1
