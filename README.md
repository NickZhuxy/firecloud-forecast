# Firecloud Forecast

**Explainable sunrise and sunset glow forecasts.**

Firecloud combines public weather forecasts, cloud-layer diagnosis, and sunward
illumination geometry to produce national and local maps with traceable metadata.
Its output is a **condition index from 0 to 1**, not a calibrated probability:
`0.8` does not mean an 80% chance of a colorful sky.

This is research software. It provides a Python package and command-line tools;
precomputed maps can be distributed through a static GitHub Pages feed.

**Current coverage:** China is the first supported region. Coverage will expand
to additional regions in future releases.

## Quick start

Requires Python 3.11 or newer and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/NickZhuxy/firecloud-forecast.git
cd firecloud-forecast
uv sync --frozen
uv run firecloud --help
uv run firecloud --source remote --event sunset
```

The last command downloads a published map if one is available. It fails with
an explanation if the feed is unavailable or stale, without starting a local
weather-data download. The public feed is best-effort and may have coverage gaps.

For local computation:

```bash
uv run firecloud --source local --event sunset
```

The first local run downloads GFS subsets and Cartopy map data. Downloads can be
large, and full refinement can take tens of minutes or longer. On macOS, if
native GRIB or mapping libraries are missing, install `eccodes`, `geos`, and
`proj` with Homebrew. See [usage and troubleshooting](docs/usage.md).

## What it does

- Produces national sunrise/sunset maps and optional detailed local maps.
- Reads GFS 0.25° forecasts and diagnoses cloud base, top, phase, and opacity.
- Evaluates the sunward path out to 800 km, including cloud and aerosol obstruction.
- Combines necessary conditions and quality modifiers into an explainable index.
- Saves PNG maps and JSON provenance, timing, and algorithm metadata.
- Supports remote downloads with checksum verification and valid-cache fallback.

```bash
uv run firecloud                          # Today, both events; remote first
uv run firecloud --event sunrise          # One event
uv run firecloud --lat 31.23 --lon 121.47  # Add local products around Shanghai
uv run firecloud --source local --no-refine --event sunset
```

`--source auto` is the default. If remote products are missing, invalid, or do not
match the requested grid, it falls back to local computation. Use `--source remote`
when you only want published products. Local products default to a 150 km radius
and 0.1° evaluation grid; this finer sampling does **not** increase the resolution
of the underlying GFS model.

Outputs are grouped by date:

```text
output/YYYY-MM-DD/
├── national-sunrise.png
├── national-sunrise.json
├── national-sunset.png
├── national-sunset.json
└── point-31.23_121.47-sunset.png   # Plus JSON, when coordinates are supplied
```

## Documentation

| Guide | Contents |
| --- | --- |
| [Usage](docs/usage.md) | Installation, CLI options, output interpretation, troubleshooting |
| [Architecture](docs/architecture.md) | Data flow, package map, contributor invariants |
| [Methodology](research/methodology.md) | Implemented assumptions, scoring, scientific limitations |
| [Static publishing](docs/publishing.md) | Precomputation and GitHub Pages setup |
| [Contributing](CONTRIBUTING.md) | Development setup, tests, and pull requests |
| [Research](research/README.md) | Experiments and the historical paper |

## Repository layout

```text
predictor/              Forecast package and command-line entry points
  tests/                Synthetic, regression, and opt-in network tests
docs/                   User and developer guides
research/
  experiments/          Reproducible research scripts
  paper/                Historical LaTeX case study and figure sources
  methodology.md        Current implementation guide
.github/                Test/publishing workflows and contribution templates
```

Downloaded data, generated forecasts, private reference documents, and personal
planning archives stay outside version control. The lockfile and small paper
figures remain tracked for reproducibility. Internal implementation diaries have
been replaced by focused public guides; their originals remain in Git history.

## Scientific status

The score is an uncalibrated heuristic. Cloud boundaries, aerosol structure,
terrain, and event timing are uncertain at model resolution. Offline regression
and physical-consistency tests check software behavior; they do not establish
real-world forecast skill. Satellite-related modules are experimental and their
availability must be checked in product metadata. This is not a full spectral
radiative-transfer model, and it does not predict exact sky colors.

Some Python fields retain historical names such as `probability` for compatibility;
interpret them as condition indices. The legacy `label_zh` localization field is
also retained, while public documentation and command-line output use English.

## Contributing and next steps

Bug reports, reproducible forecast cases, documentation improvements, and
independent validation are welcome. Start with [CONTRIBUTING.md](CONTRIBUTING.md)
and the [issue tracker](https://github.com/NickZhuxy/firecloud-forecast/issues).
Planning lives on the [project board](https://github.com/users/NickZhuxy/projects/2).

The most useful next steps are an independent validation dataset, a small gallery
of verified forecast examples, and a versioned release with clear data provenance.
Algorithm changes should be evaluated separately from repository maintenance.

## License

Licensed under the [MIT License](LICENSE).
Weather data, maps, and third-party references have their own terms; see
[data sources](docs/data-sources.md).
