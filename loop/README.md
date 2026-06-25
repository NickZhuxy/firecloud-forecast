# Firecloud loop workflows

This directory contains two related workflows.

## 1. Physics-hardening loop

The existing overnight hardening loop is:

- `loop/loop.sh`
- `loop/PROMPT.md`
- `loop/TASKS.md`
- `loop/PROGRESS.md`
- `loop/verify.sh`

It is a narrow local loop for improving `predictor/` physics robustness and
offline coverage. It does not push, open PRs, or manage GitHub.

## 2. Team loop v2

The team loop is the broader autonomous workflow described in
`loop/CHARTER.md`. It splits work across roles:

- `roles/intake.md`
- `roles/sprint_planner.md`
- `roles/technical_planner.md`
- `roles/generator.md`
- `roles/evaluator.md`
- `roles/release_manager.md`

Roles communicate through JSON artifacts validated against files in
`loop/schemas/`. They should not share chat context.

The local driver skeleton is `loop/run_team_issue.sh`. It starts a role-isolated
run from an owner brief and writes artifacts under `loop/runs/` (ignored by Git).

Example:

```bash
OWNER_INPUT=/path/to/owner-brief.md loop/run_team_issue.sh
```

By default, the driver stops after intake and technical planning. It does not
edit source code.

To let the Generator implement the technical plan locally:

```bash
RUN_GENERATOR=1 OWNER_INPUT=/path/to/owner-brief.md loop/run_team_issue.sh
```

The Generator may make local commits if authorized by the technical plan. It may
not push, open PRs, merge, or update GitHub project state.

To allow sprint planning through GitHub issues/projects:

```bash
ALLOW_GITHUB_PLANNING=1 OWNER_INPUT=/path/to/owner-brief.md loop/run_team_issue.sh
```

To allow final push/PR/merge after evaluator approval, opt in separately:

```bash
RUN_GENERATOR=1 ALLOW_RELEASE=1 OWNER_INPUT=/path/to/owner-brief.md loop/run_team_issue.sh
```

Release actions are intentionally separated from generation. A Generator may
commit locally, but only the Release Manager may push, open PRs, merge, and
close/update issues.

## Product stance

For now firecloud is algorithm-first. Do not build a website, app, sharing
platform, or hosted service until the owner explicitly says the algorithm is
successful enough.

Local CLI/product workflows are acceptable. The current product surface is a
local SunsetWx-style PNG+JSON generator.
