#!/usr/bin/env bash
# loop.sh — overnight Ralph-style loop for firecloud-forecast physics hardening.
#
# Loop Engineering: the loop prompts the agent; an EXTERNAL gate (verify.sh) decides "done".
# Context is fresh each iteration — durable state lives on disk (loop/PROGRESS.md,
# loop/TASKS.md, git). The agent hardens predictor/; it cannot fake the coverage gate.
set -euo pipefail

# ---- knobs (override via env) ----------------------------------------------
# PROJECT_DIR is the REPO ROOT (predictor/ lives there); the loop files live in loop/.
PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
PROMPT_FILE="${PROMPT_FILE:-loop/PROMPT.md}"
VERIFY="${VERIFY:-loop/verify.sh}"
MODEL="${MODEL:-sonnet}"                   # cheap per iter; bump to opus if it stalls
MAX_ITERS="${MAX_ITERS:-12}"               # hard ceiling on iterations
MAX_BUDGET_USD="${MAX_BUDGET_USD:-4}"      # cap API $ spend INSIDE one iteration
ITER_TIMEOUT="${ITER_TIMEOUT:-30m}"        # wall-clock kill switch per iteration
TIME_BUDGET_MIN="${TIME_BUDGET_MIN:-420}"  # total budget in minutes (420 ≈ 7h overnight)
export COV_FLOOR="${COV_FLOOR:-95.00}"     # source-coverage target verify.sh enforces

# Tool permissions live in loop/agent-settings.json (allow: Bash + file ops; deny:
# git push/reset/clean, rm, sudo, curl, wget). A settings FILE is honoured reliably
# under --permission-mode dontAsk; comma-joined --allowedTools strings are not, and
# silently leave Bash denied (the agent can edit files but can't run pytest or commit).
SETTINGS="${SETTINGS:-loop/agent-settings.json}"
# ----------------------------------------------------------------------------

cd "$PROJECT_DIR"
export UV_CACHE_DIR="${UV_CACHE_DIR:-$PROJECT_DIR/.uv-cache}"
command -v claude >/dev/null || { echo "FATAL: claude CLI not found"; exit 1; }
command -v git    >/dev/null || { echo "FATAL: git not found"; exit 1; }
command -v uv     >/dev/null || { echo "FATAL: uv not found (project uses uv)"; exit 1; }
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || { echo "FATAL: $PROJECT_DIR is not a git repo"; exit 1; }
if [ -n "$(git status --porcelain)" ]; then
  echo "FATAL: worktree is not clean before loop start; review/stash/commit first."
  git status --short
  exit 1
fi

hash_file() {
  if command -v shasum >/dev/null; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    sha256sum "$1" | awk '{print $1}'
  fi
}

protected_manifest() {
  for file in loop/PROMPT.md loop/verify.sh loop/coveragerc loop/loop.sh loop/agent-settings.json; do
    if [ ! -f "$file" ]; then
      echo "MISSING  $file"
    else
      echo "$(hash_file "$file")  $file"
    fi
  done
}

PROTECTED_BEFORE="$(protected_manifest)"

# Per-iteration wall-clock guard is optional (macOS ships no `timeout`); when no
# timeout binary exists, fall back to the --max-budget-usd cap. Plain string (not
# an array) so it word-splits to nothing under bash 3.2 + set -u.
TIMEOUT_BIN="$(command -v timeout || command -v gtimeout || true)"
TIMEOUT_PREFIX=""
[ -n "$TIMEOUT_BIN" ] && TIMEOUT_PREFIX="$TIMEOUT_BIN $ITER_TIMEOUT"

RUN_ID="$(date +%Y%m%d-%H%M%S)"
LOG_DIR="loop/logs/loop-$RUN_ID"; mkdir -p "$LOG_DIR"
START_EPOCH="$(date +%s)"
log() { echo "[$(date +%T)] $*" | tee -a "$LOG_DIR/run.log"; }

log "== firecloud-forecast hardening loop $RUN_ID =="
log "dir=$PROJECT_DIR model=$MODEL max_iters=$MAX_ITERS cov_floor=${COV_FLOOR}% budget=${TIME_BUDGET_MIN}m"
log "per-iteration guard: ${TIMEOUT_PREFIX:-(no timeout; --max-budget-usd \$$MAX_BUDGET_USD only)}"

for i in $(seq 1 "$MAX_ITERS"); do
  ELAPSED_MIN=$(( ( $(date +%s) - START_EPOCH ) / 60 ))
  if [ "$ELAPSED_MIN" -ge "$TIME_BUDGET_MIN" ]; then
    log "time budget reached (${ELAPSED_MIN}m) — stopping."; break
  fi
  log "--- iteration $i/$MAX_ITERS (elapsed ${ELAPSED_MIN}m) ---"

  # Fresh context every run; the prompt itself re-reads state from disk.
  # $TIMEOUT_PREFIX is "timeout 30m" when available, else empty (runs claude directly).
  set +e
  $TIMEOUT_PREFIX claude -p "$(cat "$PROMPT_FILE")" \
      --model "$MODEL" \
      --permission-mode dontAsk \
      --settings "$SETTINGS" \
      --max-budget-usd "$MAX_BUDGET_USD" \
      --output-format text \
      >"$LOG_DIR/iter-$i.log" 2>&1
  rc=$?
  set -e
  log "claude exit=$rc  (full log: $LOG_DIR/iter-$i.log)"

  PROTECTED_AFTER="$(protected_manifest)"
  if [ "$PROTECTED_AFTER" != "$PROTECTED_BEFORE" ]; then
    log "FATAL: protected loop guardrail files changed; refusing to autocommit."
    git status --short | tee -a "$LOG_DIR/run.log"
    exit 2
  fi

  # Safety net: never lose work — commit anything the agent left uncommitted.
  # Use porcelain (not `git diff`) so NEW untracked test files are caught too,
  # but only for the expected physics-hardening surface. This avoids accidentally
  # capturing local references, coverage artifacts, or unrelated user work.
  if [ -n "$(git status --porcelain)" ]; then
    unexpected="$(git status --porcelain -- . ':!loop/PROGRESS.md' ':!loop/TASKS.md' ':!predictor')"
    if [ -n "$unexpected" ]; then
      log "FATAL: unexpected paths changed; refusing to autocommit."
      echo "$unexpected" | tee -a "$LOG_DIR/run.log"
      exit 3
    fi
    git add loop/PROGRESS.md loop/TASKS.md predictor
    git commit -q -m "harden[$i]: checkpoint (driver autocommit)" || true
    log "driver autocommit."
  fi

  # External, un-fakeable success gate. The AGENT cannot trigger this.
  set +e
  bash "$VERIFY" | tee -a "$LOG_DIR/run.log"
  vrc=${PIPESTATUS[0]}
  set -e
  if [ "$vrc" -eq 0 ]; then
    log "✅ goal verified — stopping after iteration $i."; break
  fi
  log "goal not met yet — continuing."
done

log "== loop finished =="
log "Morning review:  git -C $PROJECT_DIR log --oneline | head -n $MAX_ITERS"
log "                 cat $PROJECT_DIR/loop/PROGRESS.md"
