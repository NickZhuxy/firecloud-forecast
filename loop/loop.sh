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
MAX_TURNS="${MAX_TURNS:-50}"               # cap agentic turns INSIDE one iteration
ITER_TIMEOUT="${ITER_TIMEOUT:-30m}"        # wall-clock kill switch per iteration
TIME_BUDGET_MIN="${TIME_BUDGET_MIN:-420}"  # total budget in minutes (420 ≈ 7h overnight)
export COV_FLOOR="${COV_FLOOR:-95}"        # source-coverage target verify.sh enforces

# Tight allowlist: the project's real commands. Widen only when logs show a true block.
ALLOWED="Read,Edit,Write,Glob,Grep,Bash(uv run pytest:*),Bash(uv run python:*),Bash(uv run:*),Bash(ls:*),Bash(cat:*),Bash(mkdir:*),Bash(git add:*),Bash(git commit:*),Bash(git status:*),Bash(git diff:*),Bash(git checkout:*),Bash(git log:*)"
DENIED="Bash(git push:*),Bash(git reset:*),Bash(git clean:*),Bash(rm:*),Bash(sudo:*),Bash(curl:*),Bash(wget:*)"
# ----------------------------------------------------------------------------

cd "$PROJECT_DIR"
command -v claude >/dev/null || { echo "FATAL: claude CLI not found"; exit 1; }
command -v git    >/dev/null || { echo "FATAL: git not found"; exit 1; }
command -v uv     >/dev/null || { echo "FATAL: uv not found (project uses uv)"; exit 1; }
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || { echo "FATAL: $PROJECT_DIR is not a git repo"; exit 1; }

RUN_ID="$(date +%Y%m%d-%H%M%S)"
LOG_DIR="loop/logs/loop-$RUN_ID"; mkdir -p "$LOG_DIR"
START_EPOCH="$(date +%s)"
log() { echo "[$(date +%T)] $*" | tee -a "$LOG_DIR/run.log"; }

log "== firecloud-forecast hardening loop $RUN_ID =="
log "dir=$PROJECT_DIR model=$MODEL max_iters=$MAX_ITERS cov_floor=${COV_FLOOR}% budget=${TIME_BUDGET_MIN}m"

for i in $(seq 1 "$MAX_ITERS"); do
  ELAPSED_MIN=$(( ( $(date +%s) - START_EPOCH ) / 60 ))
  if [ "$ELAPSED_MIN" -ge "$TIME_BUDGET_MIN" ]; then
    log "time budget reached (${ELAPSED_MIN}m) — stopping."; break
  fi
  log "--- iteration $i/$MAX_ITERS (elapsed ${ELAPSED_MIN}m) ---"

  # Fresh context every run; the prompt itself re-reads state from disk.
  set +e
  timeout "$ITER_TIMEOUT" claude -p "$(cat "$PROMPT_FILE")" \
      --model "$MODEL" \
      --permission-mode dontAsk \
      --allowedTools "$ALLOWED" \
      --disallowedTools "$DENIED" \
      --max-turns "$MAX_TURNS" \
      --output-format text \
      >"$LOG_DIR/iter-$i.log" 2>&1
  rc=$?
  set -e
  log "claude exit=$rc  (full log: $LOG_DIR/iter-$i.log)"

  # Safety net: never lose work — commit anything the agent left uncommitted.
  if ! git diff --quiet || ! git diff --cached --quiet; then
    git add -A && git commit -q -m "harden[$i]: checkpoint (driver autocommit)" || true
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
