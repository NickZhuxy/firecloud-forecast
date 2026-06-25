# Firecloud team loop v2 charter

This charter defines the autonomous team loop for `firecloud-forecast`.
It sits above individual GitHub issues and role prompts.

## Owner direction

Until the owner explicitly says the algorithm is successful enough, do **not**
turn the product into a website, hosted app, sharing platform, or polished public
application.

Acceptable product surface for now:

- local command-line startup flow;
- local generated PNG/JSON products;
- local research/diagnostic artifacts;
- GitHub issues, PRs, and project tracking for development.

Primary focus:

- algorithm quality;
- physics and meteorological correctness;
- data-source reliability;
- testable local workflows;
- visual products only insofar as they help inspect and communicate the algorithm.

## Team model

The loop is an autonomous development team, not one all-knowing agent.
Roles exchange artifacts, not chat context.

```text
Human / Owner
  -> Intake
  -> Sprint Planner
  -> Technical Planner
  -> Generator
  -> Evaluator
  -> Release Manager
```

Each role should start fresh. It may read only the artifacts and repository
state listed in its role prompt. It should not inherit the private reasoning or
conversation context of previous roles.

## Role boundaries

| Role | Main job | Must not do |
|---|---|---|
| Intake | Convert owner language into a non-technical brief | implementation plans, file names, dependencies |
| Sprint Planner | Manage GitHub issues/project/sprint from briefs | code changes, technical solution design |
| Technical Planner | Turn one issue into a bounded technical plan | code changes, PR/merge decisions |
| Generator | Implement exactly the technical plan | change the plan, push, PR, merge |
| Evaluator | Read-only adversarial review and verification | edit files, fix code, approve its own work |
| Release Manager | Push/PR/merge/update issues after gates pass | bypass failed gates, alter implementation |

## Authority model

The team is allowed to:

- create and update GitHub issues;
- organize sprint/project status;
- push branches;
- open pull requests;
- merge pull requests;
- close issues after merged work satisfies acceptance criteria.

Those powers belong to the appropriate roles only. In particular, the Generator
does not release its own work, and the Evaluator does not edit files.

## Hard stops

Stop for the owner instead of continuing when:

- a change would revive a website/app/product-hosting direction;
- a change would introduce a paid, private, credentialed, or license-unclear data source;
- an algorithmic assumption changes the meaning of the firecloud score;
- the deterministic verifier fails and the cause is not understood;
- GitHub release actions are requested but CI, review, or issue acceptance is ambiguous;
- a role needs context that was intentionally withheld from it.

## Verifier hierarchy

Final acceptance is never based only on an LLM's opinion.

Order of authority:

1. owner direction and hard stops;
2. deterministic checks (`pytest`, coverage gate, lint/type checks when configured);
3. repository protocols (`AGENTS.md`, `.agent-progress.md`, GitHub issues/project);
4. evaluator report;
5. generator's own summary.

## Cost and usefulness metric

Each run should record:

- iterations attempted;
- commits produced;
- commits accepted/merged;
- reverted or rejected attempts;
- verification runtime;
- coverage or quality delta where meaningful.

The useful metric is cost per accepted change, not number of loops run.
