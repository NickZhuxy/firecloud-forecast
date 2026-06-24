#!/usr/bin/env bash
# loop.sh — overnight Ralph-style loop for Project Cloud Agent (火烧云 predictor).
#
# Loop Engineering: the loop prompts the agent; an EXTERNAL gate (verify.sh) decides "done".
# Context is fresh each iteration — durable state lives on disk (PROGRESS.md / TASKS.md / git).
set -euo pipefail

# ---- knobs (override via env) ----------------------------------------------
PROJECT_DIR="${PROJECT_DIR:-$HOME/projects/cloud-agent}"
PROMPT_FILE="${PROMPT_FILE:-PROMPT.md}"
VERIFY="${VERIFY:-./verify.sh}"
MODEL="${MODEL:-sonnet}"                  # sonnet = cheap per iter; bump to opus if it stalls
MAX_ITERS="${MAX_ITERS:-12}"              # hard ceiling on iterations
MAX_TURNS="${MAX_TURNS:-40}"             # cap agentic turns INSIDE one iteration
ITER_TIMEOUT="${ITER_TIMEOUT:-30m}"      # wall-clock kill switch per iteration
TIME_BUDGET_MIN="${TIME_BUDGET_MIN:-420}" # total budget in minutes (420 ≈ 7h overnight)

# Start TIGHT. Widen ALLOWED only when logs show the agent legitimately blocked.
ALLOWED="Read,Edit,Write,Glob,Grep,Bash(python3:*),Bash(python:*),Bash(pytest:*),Bash(ls:*),Bash(cat:*),Bash(mkdir:*),Bash(git add:*),Bash(git commit:*),Bash(git status:*),Bash(git diff:*),Bash(git checkout:*)"
DENIED="Bash(git push:*),Bash(git reset:*),Bash(git clean:*),Bash(rm:*),Bash(sudo:*),Bash(curl:*),Bash(wget:*)"
# ----------------------------------------------------------------------------

cd "$PROJECT_DIR"
command -v claude >/dev/null || { echo "FATAL: claude CLI not found"; exit 1; }
command -v git    >/dev/null || { echo "FATAL: git not found"; exit 1; }
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || { echo "FATAL: $PROJECT_DIR is not a git repo"; exit 1; }

RUN_ID="$(date +%Y%m%d-%H%M%S)"
LOG_DIR="logs/loop-$RUN_ID"; mkdir -p "$LOG_DIR"
START_EPOCH="$(date +%s)"
log() { echo "[$(date +%T)] $*" | tee -a "$LOG_DIR/run.log"; }

log "== Project Cloud Agent loop $RUN_ID =="
log "dir=$PROJECT_DIR model=$MODEL max_iters=$MAX_ITERS budget=${TIME_BUDGET_MIN}m"

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
    git add -A && git commit -q -m "loop[$i]: checkpoint (driver autocommit)" || true
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
log "                 git -C $PROJECT_DIR diff HEAD~$MAX_ITERS..HEAD   # inspect the night's work"
