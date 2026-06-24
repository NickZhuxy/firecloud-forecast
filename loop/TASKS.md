# TASKS — physics-hardening backlog, most important first.
# The loop picks ONE per iteration, writes a failing offline test, fixes the code, commits.
# All tests live in predictor/tests/ and must run offline (no network).

## Physical invariants (pin laws the code must ALWAYS obey)
- [ ] Condition scores stay in [0, 1] over a fuzz of valid-but-random Features/profiles
      (rules.py, features.py, score.py). No NaN, no out-of-range, no exception.
- [ ] Diagnosed cloud geometry is physical: top ≥ base ≥ surface, all finite, for every
      diagnosed layer across a battery of synthetic soundings (clouds.py, cloud_top.py).
- [ ] Sunward path/cross-section: distances strictly increasing and within 0–800 km;
      sample points monotone along the true sunset azimuth (cross_section.py, spatial.py).
- [ ] Determinism: identical input → identical output (extend the existing 1e-9 equivalence
      theme into a property-style test over scoring + diagnosis).
- [ ] National grid: every cell score ∈ [0,1] or NaN where masked; no exception over a
      synthetic AtmosphericCube/SurfaceGrid (grid_score.py, national_field.py).

## Edge cases (degrade safely, never crash / emit unphysical values)
- [x] Polar / no-sunset day: high summer latitude where the sun never sets — illumination
      and the scorer must handle it gracefully (illumination.py, sunset_grid.py).
      DONE iter 2: _sunset_timestamp fallback pinned, sunset_utc_grid tested end-to-end.
- [ ] Longitude conventions: 0–360 vs ±180 and the antimeridian seam (profiles nearest-lon,
      sunset_grid.py, spatial.py).
- [ ] Degenerate profiles: empty / single-level / all-NaN column through normalize.py →
      clouds.py → cloud_top.py must fall back safely, not raise.
- [ ] Extremes: 0% clear-sky and 100% overcast pushed through the full scorer.
- [ ] Strong temperature inversion sounding through cloud diagnosis + cloud-top retrieval.

## Coverage gaps to close with MEANINGFUL tests (current weak modules)
- [ ] national_product.py (~77%, 45 missed) — exercise the pure plotting/metadata helpers offline.
- [ ] gfs.py (~91%, 24 missed) — cycle-fallback / missing-level / error branches (mock the loader; no net).
- [x] national_field.py (~88% → 100%) — DONE iter 3: all 13 missed lines covered by 11 new tests.
- [ ] sunset_grid.py: line 33 is unreachable defensive code — skip.
- [ ] profiles.py (~90%, 9 missed), rules.py (~94%, 11 missed), features.py (~93%, 10 missed),
      clouds.py (~95%, 6 missed), cross_section.py (~92%, 4 missed) — close reachable branches.

## Target
- [ ] predictor/ source coverage ≥ 95% (verify.sh floor) with all of the above green.
      Ratchet the floor (COV_FLOOR) upward in future runs once reached.

## Done
<!-- move finished items here with the iteration number that closed them -->
