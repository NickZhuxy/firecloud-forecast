# Research

This directory connects physical assumptions to reproducible implementation work.
Start with [methodology.md](methodology.md), which describes the current algorithm
and its limitations in English.

- `experiments/nationalization_spike.py`: offline synthetic comparison of national
  approximations against detailed point calculations. This is a software/physics
  benchmark, not observed forecast accuracy.
- `experiments/live_refine_validation.py`: real-data refinement validation; requires
  network access and can download substantial GFS data.
- `paper/`: historical CONUS/HRRR case study, LaTeX source, bibliography, and figures.
  Its domain and implementation predate the current product pipeline.

Run the offline experiment from the repository root:

```bash
uv run python research/experiments/nationalization_spike.py
```

Historical theory drafts and implementation plans have been consolidated into the
public methodology and architecture guides. Their complete originals remain in
Git history; the maintainer's checkout also keeps ignored local copies. This is an
editorial consolidation, not a sentence-by-sentence translation of old drafts.
Old issue IDs in code comments identify provenance, not outstanding work.

For new research, record the hypothesis, source, applicable domain, uncertainty,
and a test that could disprove it. Use independent public observations or datasets
for validation. Do not describe the condition index as a calibrated probability.
Private reference PDFs and downloaded data are intentionally excluded from Git.
