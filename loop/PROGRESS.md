# PROGRESS — Firecloud Forecast physics-hardening loop
# Append-only, newest at the bottom. The loop reads this FIRST every iteration.
# This is the agent's only long-term memory between context resets.

## Mission
Harden the physics of `predictor/` (robustness, physical correctness, offline test coverage).
External gate (verify.sh): offline suite green AND predictor/ source coverage ≥ COV_FLOOR
(95.00%, measured with two-decimal precision).
No ML, no labelled data, no probability calibration — this project validates with offline
physics scenarios + public-data cross-checks (see repo README).

## Baseline — 2026-06-25 (loop repurposed)
- offline suite: 279 passed (`PYTHONPATH=. uv run pytest -m "not integration" -q`).
- predictor/ SOURCE coverage (coveragerc scope, excl tests & gfs_smoke): ~92%.  Floor = 95%.
- weakest source modules: national_product (~77%), gfs (~91%), national_field (~88%),
  sunset_grid (~83%), rules / features / profiles / clouds / cross_section (~90–95%).
- PIVOT NOTE: this loop was first set up for a supervised next-day *probability* model on a
  frozen labelled holdout. That goal had no data and no label source and contradicted the
  project's documented "no training set / not a probability" stance, so per the owner's
  decision (2026-06-25) it was dropped and the harness re-centered on hardening the existing
  physics. The earlier ML scaffold (firecloud_ml/, its tests, data contract) was removed.

## Log

### 2026-06-25  iter 2
hardened: polar/midnight-sun fallback + all error branches in `sunset_grid.py`.
Added 17 tests to `predictor/tests/test_sunset_grid.py` covering:
- `_axis()` raises on empty / 2-D / non-finite inputs (lines 20, 22).
- `_inclusive_axis()` raises on zero / negative / NaN step (line 28).
- `_sunset_timestamp()` polar fallback: at 80°N on 2026-06-22 (midnight sun) astral
  raises ValueError; fallback returns `midnight UTC + (18h − lon/15h)` — three tests
  pin the exact values for lon=0° (18:00 UTC) and lon=120°E (10:00 UTC) and verify
  that `sunset_utc_grid` over a polar domain yields non-NaT output (lines 44-51).
- `hourly_valid_times()` raises on empty and NaT-containing arrays (line 95).
- `nearest_valid_time_indices()` raises on empty/NaT sunsets, empty valid_times,
  and non-increasing valid_times (lines 112, 114, 128).
Line 33 in `_inclusive_axis()` is unreachable defensive code (insert when first value
doesn't align with lo) — skipped; will not be covered by normal usage.
cov 92% → 93% (1957 stmts, 146 missed). suite green (296 passed, 5 deselected).
sunset_grid.py now at 98% (only line 33 unreachable).
next: close the 13-line gap in national_field.py (lines 59, 61, 75, 77, 121, 123,
  126, 143, 163, 183-187, 196) — many are trivial error-branch tests requiring no GFS
  mock; tackle them as the next atomic step.
need 48 more lines to reach 95% floor.

### 2026-06-25  iter 3
hardened: all 13 missed lines in `national_field.py` (88% → 100%).
Added 11 tests to `predictor/tests/test_national_field.py` covering:
- `_range_axis()` inverted range (line 59 fallback to [start]) and non-aligned end (line 61 appends end).
  Note: `_range_axis(30.0, 20.0)` hits BOTH lines 59 and 61 since after the [start] fallback,
  end=20.0 is not close to start=30.0, so end is also appended → result is [30.0, 20.0].
- `_active_sunsets()` raises when domain_mask returns wrong shape (line 75) and when domain_mask
  excludes all cells (line 77) — both exercised via build_national_field with mock masks.
- `build_national_field()` input validation: datetime→date coercion (line 121), TypeError on
  non-date input (line 123), ValueError on inverted bbox lat_min>lat_max (line 126).
- `fetch_surface_grids` batch API path (line 143): source with that method gets one batch call
  instead of N individual `fetch_surface_grid` calls.
- Coarse bbox miss assertion (line 163): monkeypatched sunset_utc_grid returns wider range on
  second call → required_times ⊄ valid_times → ValueError raised.
- `download_bytes` summation branch (lines 183-187): grids with download_bytes=500 → field
  reports correct totals (500*n and 500*(n-1)).
- tracemalloc already tracing (line 196): start tracemalloc before call → trace=False → peak_mem_mb=NaN.
cov 93% → 93% (1957 stmts, 146→133 missed). suite green (307 passed, 5 deselected).
national_field.py now at 100%.
still need 35 more lines to reach 95% floor.
next highest-leverage: national_product.py (45 missed, 77%) or gfs.py (24 missed, 91%).

### 2026-06-25  iter 4
hardened: 22 reachable missed lines in `national_product.py` (77% → 88%).
Added 13 tests to `predictor/tests/test_national_product.py` covering:
- `_geom_to_path()` degenerate interior ring < 3 pts (line 61: `continue` skips it)
  and all-degenerate polygon (line 67: `ValueError("country geometry contains no polygon rings")`).
  Tested via `_RingStub`/`_PolyStub` stubs since shapely enforces min 3 exterior pts.
- `_draw_polygon_boundary()` early return (line 73) when geometry is not Polygon/MultiPolygon
  (e.g. a shapely Point).
- `_line_parts()` generator: LineString branch (lines 87-88) and MultiLineString recursive
  branch (lines 89-91).
- `_draw_admin_lines()` inner loop body (lines 96-99): called with a real LineString,
  verifying one line is plotted to the axes.
- `_initialized_label()` no-match branch (line 133): non-GFS source label → "unknown".
- `_utc()` naive-datetime branch (line 143): attaches UTC tzinfo before conversion.
- `plot_sunsetwx_product()` surrounding loop body (line 174): context with one surrounding
  polygon → loop body executes, figure still has 2 axes.
- `save_product()` dpi validation (line 305): dpi ≤ 0 → `ValueError`.
- `_intersects()` pure function (lines 335-337): True for overlapping bounds, False for disjoint.
- `_parse_date()` error branch (lines 401-402): non-ISO string → `ArgumentTypeError`.
- `_positive_int()` error branch (line 408): zero/negative → `ArgumentTypeError`.
The remaining 23 missed lines in national_product.py are all in `load_map_context()`
(lines 342-372) which calls `cartopy.io.shapereader.natural_earth()` — a disk/network fetch.
That function is not exercised offline and the existing integration-exclusion keeps it
out of the gate. Mark those as permanently skipped offline.
cov 93% → 94% (1957 stmts, 133→111 missed). suite green (320 passed, 5 deselected).
national_product.py 77% → 88% (23 missed, all in load_map_context).
still need 13 more lines to reach 95% floor.
next: profiles.py (9 missed: lines 103-112, a contiguous block) + cross_section.py
(4 missed: lines 43, 71, 85, 91) — together 13 lines exactly at the floor.

### 2026-06-25  iter 5
hardened: profiles.py (lines 103-112) + cross_section.py (lines 43, 71, 85, 91) — 13 lines.
Added 5 tests:
- `test_normalized_profile_to_dict_is_json_friendly` (test_profiles.py): exercises
  NormalizedProfile.to_dict() — arrays → list, datetimes → ISO string (lines 103-112).
- `test_even_heights_count_less_than_2_returns_single_zero` (test_cross_section.py):
  even_heights(count=0/1) returns [0.0] (line 43).
- `test_build_cross_section_raises_on_length_mismatch` (test_cross_section.py):
  mismatched profiles/layers_per_point/samples raises ValueError (line 71).
- `test_empty_profile_column_is_fully_masked` (test_cross_section.py):
  profile with geometric_height_m=[] → col_heights.size == 0 → continue (line 85).
- `test_profile_span_entirely_outside_heights_is_masked` (test_cross_section.py):
  all requested heights above profile top → valid.any() is False → continue (line 91).
cov 94% → 95% (1957 stmts, 111→98 missed). suite green (325 passed, 5 deselected).
profiles.py 90% → 100%; cross_section.py 92% → 100%.
COV_FLOOR OF 95% REACHED. Verify.sh external gate should now pass.
Remaining missed lines (98 total): gfs.py 24, national_product.py 23 (load_map_context, offline-permanent skip),
features.py 10, rules.py 11, clouds.py 6, cross_section_plot.py 3, sounding_plot.py 4,
fetch.py 10, geometry.py 2, spatial.py 2, sunset_grid.py 1 (line 33 unreachable), others 2.
next: headroom — push to 96%+ by covering reachable branches in rules.py (11 missed),
features.py (10 missed), clouds.py (6 missed). Or wait for external verify to confirm gate passes.

### 2026-06-25  guardrail patch
hardened: loop harness safety before publishing the overnight workflow.
- Root `.gitignore` now ignores `reference/`, coverage artifacts, `htmlcov/`, and project-local
  `.uv-cache/` so `git add` cannot accidentally capture visual references or coverage output.
- `verify.sh` and `loop.sh` default to project-local `UV_CACHE_DIR=.uv-cache`, avoiding
  environment/user-cache failures.
- `coveragerc` now reports two-decimal coverage and the default floor is 95.00, so 94.99 no
  longer passes by display rounding.
- `loop.sh` refuses to start on a dirty worktree, hashes protected loop guardrail files
  (`PROMPT.md`, `verify.sh`, `coveragerc`, `loop.sh`, `agent-settings.json`), and refuses to
  autocommit if they change during an agent iteration.
- Driver autocommit is now whitelisted to `loop/PROGRESS.md`, `loop/TASKS.md`, and `predictor/`
  instead of broad `git add -A`.
- Prompt now requires reading `AGENTS.md` / `.agent-progress.md` and claiming loop work before
  edits.
Added one meaningful grid-score test for the "missing visibility and AOD" clean-air fallback,
raising strict coverage above the 95.00 floor instead of relying on rounding.

### 2026-06-25  team loop v2 charter
hardened: expanded the loop from a narrow physics-hardening runner into a role-isolated
firecloud team workflow.
- Added `loop/CHARTER.md` with the owner direction: algorithm-first; no website/app/hosted
  product until the owner explicitly agrees the algorithm is successful; local CLI and local
  PNG/JSON products are acceptable.
- Added `loop/roles/` prompts for Intake, Sprint Planner, Technical Planner, Generator,
  Evaluator, and Release Manager. Roles pass artifacts, not chat context.
- Added `loop/schemas/` JSON contracts for owner briefs, sprint plans, technical plans,
  generator reports, evaluator reports, and release reports.
- Added `loop/team-settings/` permission profiles: Generator cannot push/PR/merge; Evaluator
  is read-only; Release Manager may publish after gates pass.
- Added `loop/run_team_issue.sh`, a safe local driver that defaults to planning only and
  requires explicit opt-in for implementation (`RUN_GENERATOR=1`), GitHub planning
  (`ALLOW_GITHUB_PLANNING=1`), and release actions (`ALLOW_RELEASE=1`).
Validation: shell syntax and JSON syntax checks passed for the new driver, schemas, and
role settings.

### 2026-06-25  PR #49 self-review fixes
review finding: the first team-loop driver only checked artifact JSON syntax, not schema
contracts; and `ALLOW_RELEASE=1` would invoke the Release Manager even if the evaluator
reported failure.
fix:
- `run_team_issue.sh` now validates each role artifact against the matching JSON schema via
  `jsonschema.Draft202012Validator`.
- The driver now hard-blocks release unless evaluator `status == "pass"` and
  `product_direction_check.status == "pass"`.
- Non-generator roles now explicitly deny local `git add`, `git commit`, `git checkout`,
  `git switch`, and `git restore` in their role settings. Release Manager still owns
  publishing, but not local implementation edits.
next validation: run shell syntax, JSON syntax, targeted fake-driver gate tests, and
`bash loop/verify.sh`.
