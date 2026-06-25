#!/usr/bin/env bash
# Role-isolated firecloud team loop driver.
#
# Default mode is safe planning only:
#   OWNER_INPUT=/path/to/brief.md loop/run_team_issue.sh
#
# Opt in to stronger capabilities:
#   ALLOW_GITHUB_PLANNING=1  create/update issues/project in sprint planning
#   RUN_GENERATOR=1          let the generator edit/commit local code
#   ALLOW_RELEASE=1          let release manager push/PR/merge after evaluator pass
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
OWNER_INPUT="${OWNER_INPUT:-}"
RUN_ID="${RUN_ID:-$(date +%Y%m%d-%H%M%S)}"
RUN_DIR="${RUN_DIR:-$PROJECT_DIR/loop/runs/team-$RUN_ID}"

MODEL_INTAKE="${MODEL_INTAKE:-sonnet}"
MODEL_SPRINT="${MODEL_SPRINT:-sonnet}"
MODEL_TECHNICAL="${MODEL_TECHNICAL:-sonnet}"
MODEL_GENERATOR="${MODEL_GENERATOR:-sonnet}"
MODEL_EVALUATOR="${MODEL_EVALUATOR:-sonnet}"
MODEL_RELEASE="${MODEL_RELEASE:-sonnet}"

ALLOW_GITHUB_PLANNING="${ALLOW_GITHUB_PLANNING:-0}"
RUN_GENERATOR="${RUN_GENERATOR:-0}"
ALLOW_RELEASE="${ALLOW_RELEASE:-0}"
MAX_BUDGET_USD="${MAX_BUDGET_USD:-4}"

cd "$PROJECT_DIR"
export UV_CACHE_DIR="${UV_CACHE_DIR:-$PROJECT_DIR/.uv-cache}"

usage() {
  echo "usage: OWNER_INPUT=/path/to/brief.md loop/run_team_issue.sh"
}

if [ -z "$OWNER_INPUT" ] || [ ! -f "$OWNER_INPUT" ]; then
  usage
  exit 64
fi

command -v claude >/dev/null || { echo "FATAL: claude CLI not found"; exit 1; }
command -v git >/dev/null || { echo "FATAL: git not found"; exit 1; }
command -v python3 >/dev/null || { echo "FATAL: python3 not found"; exit 1; }
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || {
  echo "FATAL: $PROJECT_DIR is not a git repo"
  exit 1
}

if [ -n "$(git status --porcelain)" ]; then
  echo "FATAL: worktree is not clean before team loop start; review/stash/commit first."
  git status --short
  exit 1
fi

mkdir -p "$RUN_DIR"
cp "$OWNER_INPUT" "$RUN_DIR/00-owner-input.md"

log() {
  echo "[$(date +%T)] $*" | tee -a "$RUN_DIR/run.log"
}

schema_check() {
  schema="$1"
  artifact="$2"
  python3 - "$schema" "$artifact" <<'PY'
import json
import sys

try:
    import jsonschema
except ImportError:
    print(
        "FATAL: Python package 'jsonschema' is required to validate loop artifacts.",
        file=sys.stderr,
    )
    raise SystemExit(2)

schema_path, artifact_path = sys.argv[1:3]
with open(schema_path, "r", encoding="utf-8") as f:
    schema = json.load(f)
with open(artifact_path, "r", encoding="utf-8") as f:
    artifact = json.load(f)

jsonschema.Draft202012Validator.check_schema(schema)
validator = jsonschema.Draft202012Validator(schema)
errors = sorted(validator.iter_errors(artifact), key=lambda e: list(e.path))
if errors:
    print(f"FATAL: {artifact_path} does not match {schema_path}", file=sys.stderr)
    for error in errors[:10]:
        path = ".".join(str(p) for p in error.path) or "<root>"
        print(f"- {path}: {error.message}", file=sys.stderr)
    raise SystemExit(1)
PY
}

eval_release_gate() {
  eval_report="$1"
  python3 - "$eval_report" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as f:
    report = json.load(f)

status = report.get("status")
product_status = report.get("product_direction_check", {}).get("status")
if status == "pass" and product_status == "pass":
    raise SystemExit(0)

print(
    "FATAL: release gate blocked; evaluator status="
    f"{status!r}, product_direction_check.status={product_status!r}",
    file=sys.stderr,
)
raise SystemExit(1)
PY
}

run_role() {
  role_name="$1"
  role_prompt="$2"
  settings="$3"
  model="$4"
  output="$5"
  schema="$6"
  shift 6

  prompt_file="$RUN_DIR/.prompt-$role_name.md"
  {
    echo "# Firecloud team loop role invocation"
    echo
    echo "This is a fresh, role-isolated invocation. Use only the role instructions and artifacts included below."
    echo "Do not assume access to prior chat context."
    echo
    echo "## Role instructions"
    cat "$role_prompt"
    echo
    echo "## Included artifacts"
    for artifact in "$@"; do
      echo
      echo "### $artifact"
      cat "$artifact"
    done
  } > "$prompt_file"

  log "role=$role_name model=$model output=$output"
  claude -p "$(cat "$prompt_file")" \
    --model "$model" \
    --permission-mode dontAsk \
    --settings "$settings" \
    --max-budget-usd "$MAX_BUDGET_USD" \
    --output-format text \
    > "$output"
  schema_check "$schema" "$output"
}

run_role \
  "intake" \
  "loop/roles/intake.md" \
  "loop/team-settings/intake.json" \
  "$MODEL_INTAKE" \
  "$RUN_DIR/01-owner-brief.json" \
  "loop/schemas/owner_brief.schema.json" \
  "loop/CHARTER.md" \
  "$RUN_DIR/00-owner-input.md"

if [ "$ALLOW_GITHUB_PLANNING" = "1" ]; then
  run_role \
    "sprint-planner" \
    "loop/roles/sprint_planner.md" \
    "loop/team-settings/sprint-planner.json" \
    "$MODEL_SPRINT" \
    "$RUN_DIR/02-sprint-plan.json" \
    "loop/schemas/sprint_plan.schema.json" \
    "loop/CHARTER.md" \
    "$RUN_DIR/01-owner-brief.json"
else
  log "skipping sprint planner; set ALLOW_GITHUB_PLANNING=1 to allow issue/project planning"
fi

technical_inputs=("loop/CHARTER.md" "$RUN_DIR/01-owner-brief.json")
if [ -f "$RUN_DIR/02-sprint-plan.json" ]; then
  technical_inputs+=("$RUN_DIR/02-sprint-plan.json")
fi

run_role \
  "technical-planner" \
  "loop/roles/technical_planner.md" \
  "loop/team-settings/technical-planner.json" \
  "$MODEL_TECHNICAL" \
  "$RUN_DIR/03-tech-plan.json" \
  "loop/schemas/tech_plan.schema.json" \
  "${technical_inputs[@]}"

if [ "$RUN_GENERATOR" != "1" ]; then
  log "stopping after planning; set RUN_GENERATOR=1 to allow implementation"
  echo "$RUN_DIR"
  exit 0
fi

run_role \
  "generator" \
  "loop/roles/generator.md" \
  "loop/team-settings/generator.json" \
  "$MODEL_GENERATOR" \
  "$RUN_DIR/04-generator-report.json" \
  "loop/schemas/generator_report.schema.json" \
  "loop/CHARTER.md" \
  "$RUN_DIR/03-tech-plan.json"

run_role \
  "evaluator" \
  "loop/roles/evaluator.md" \
  "loop/team-settings/evaluator.json" \
  "$MODEL_EVALUATOR" \
  "$RUN_DIR/05-eval-report.json" \
  "loop/schemas/eval_report.schema.json" \
  "loop/CHARTER.md" \
  "$RUN_DIR/01-owner-brief.json" \
  "$RUN_DIR/03-tech-plan.json" \
  "$RUN_DIR/04-generator-report.json"

if [ "$ALLOW_RELEASE" != "1" ]; then
  log "skipping release manager; set ALLOW_RELEASE=1 to allow push/PR/merge"
  echo "$RUN_DIR"
  exit 0
fi

eval_release_gate "$RUN_DIR/05-eval-report.json"

run_role \
  "release-manager" \
  "loop/roles/release_manager.md" \
  "loop/team-settings/release-manager.json" \
  "$MODEL_RELEASE" \
  "$RUN_DIR/06-release-report.json" \
  "loop/schemas/release_report.schema.json" \
  "loop/CHARTER.md" \
  "$RUN_DIR/01-owner-brief.json" \
  "$RUN_DIR/03-tech-plan.json" \
  "$RUN_DIR/04-generator-report.json" \
  "$RUN_DIR/05-eval-report.json"

log "team loop completed"
echo "$RUN_DIR"
