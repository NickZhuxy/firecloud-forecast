# Historical CONUS case study

This paper explores the early gate × modifier architecture using NOAA HRRR and
an Olympic Peninsula case. It documents the project's starting point, not the
current GFS product architecture or independently validated forecast skill.

- `paper.tex`: manuscript source.
- `references.bib`: bibliography.
- `figures/*.py`: figure-generation scripts.
- `figures/*.png`: checked-in figures for offline paper compilation.
- `paper.pdf`: generated output, ignored by Git.

With a LaTeX installation providing `pdflatex` and `bibtex`:

```bash
cd research/paper
make
```

`make clean` removes the compiled paper and LaTeX intermediates. The figure PNGs
are intentionally retained so compiling the manuscript does not require rerunning
historical network queries. Figure regeneration may require network access and
historical data that are no longer available through the original endpoints.

For current behavior, use the root README, `research/methodology.md`, and the
implementation in `predictor/`. The manuscript is a project research artifact,
not a claim of peer review or publication.
