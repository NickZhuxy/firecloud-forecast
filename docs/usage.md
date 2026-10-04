# Usage

China supports national and local products. New York City has an experimental
local pilot. Additional regions are planned.

## Installation

From the repository root, use `uv sync --frozen`. This installs the project and
development dependencies using the checked-in lockfile. Use
`uv sync --frozen --no-dev` for a runtime-only environment.

Run commands with `uv run firecloud` so the project environment is selected.
Alternatively, activate `.venv` before using the bare `firecloud` command.

GFS reading uses Herbie, xarray, cfgrib, and ecCodes; map rendering uses Cartopy,
GEOS, and PROJ. If native-library loading fails on macOS:

```bash
brew install eccodes geos proj
uv sync --frozen
```

The publishing workflow installs the locked runtime on Ubuntu. Other platforms
may require native packages appropriate to their Python distribution. Report the
OS, Python version, and complete error when installation fails.

## Select a source

| Source | Behavior |
| --- | --- |
| `auto` (default) | Try the remote feed; compute locally if a matching valid product is unavailable |
| `remote` | Fetch published products only; fail if unavailable |
| `local` | Download weather data as needed and compute locally |

A previously downloaded remote product can be reused while it remains valid.
Local cache presence is only a rough progress hint: additional forecast hours or
fields may still require downloads.

```bash
uv run firecloud --source remote --event sunset
uv run firecloud --source local --event sunrise
uv run firecloud --date 2026-09-15 --event sunset --source local
```

The explicit date is an example, not a guaranteed available forecast date. The CLI
default for China is the computer's current date. China products use event times across the China
domain, and remote-hit timestamps are labeled `UTC+08:00`, with the GFS UTC cycle
shown separately. Select `--date` explicitly when running outside China's timezone.

`--date` selects the local event day, not its UTC date. For example, a September
14 evening event in Los Angeles falls on September 15 in UTC; a September 14
morning event in Shanghai falls on September 13 in UTC. The computation currently
uses a longitude-based solar-day offset for the existing China profile. The New
York City pilot selects the civil calendar day in `America/New_York` explicitly.

## New York City pilot

Use `--region us-nyc --scope local` and signed coordinates. The default region is
`china`, which preserves the existing national and remote products.

```bash
uv run firecloud --region us-nyc --scope local --source local --event sunset \
  --lat 40.7128 --lon -74.0060 --radius 25 --resolution 0.1
```

The sample coordinates identify New York City, not a private address. Observer
centers must be within latitude 40.0–41.5 and longitude -75.0–-72.5. This bounded
pilot is not full U.S. coverage. Change the coordinates within this area to select
your location. Both sunrise and sunset use the same scoring path.

An omitted `--date` means today in `America/New_York`. An explicit date means
that local civil day. JSON metadata and the map show UTC and local event times;
daylight saving time is handled by the IANA timezone database. GFS forecast hours
are discrete and can differ from the exact event instant. Metadata reports both.
The selected Open-Meteo hourly times are also recorded when available.

There is no NYC remote feed. `--source remote` fails before contacting the China
feed. `--source auto` computes locally. NYC has no national product, and Himawari
satellite correction is unavailable; metadata records that limitation.

The pilot bounds apply only to observer centers. The shared GFS cube includes
every evaluation cell's complete 800 km sunward path, including Canadian and ocean
samples. The 25 km example evaluates 25 cells at 0.1° spacing; the underlying GFS
resolution remains 0.25°. The default 150 km grid has 945 cells at the sample
latitude and is much more expensive.

The default local pipeline uses GFS pressure profiles and Open-Meteo cloud cover,
humidity, and visibility. It does not provide terrain heights or per-column
aerosol fields. Its condition index is an uncalibrated heuristic, and this pilot
does not establish observed forecast skill. Outputs use
`output/us-nyc/YYYY-MM-DD/`.

The [archived NYC pilot case](../examples/new-york-sunset/README.md) records one real
run, its source times, zero-gate explanation, download measurements, and checksums.
Its offline verification requires no weather download and does not replay the model.

For forecasts without daily terminal commands, use the
[automatic local runner](automatic-forecasts.md). It schedules the existing local
generator, saves independent attempts, and maintains a latest-result file.
Photographs, observation sheets, and webcams are not prerequisites.

## Select products

| Scope | Behavior |
| --- | --- |
| `all` (default) | National maps, plus local maps when coordinates are supplied |
| `national` | National maps only; coordinates are rejected |
| `local` | Local maps only; both `--lat` and `--lon` are required |

Use `--scope local` for a location-focused forecast. This skips national maps and
their computation. Source selection still applies: `auto` tries matching published
local products before computing locally, and `remote` uses published products only.

```bash
uv run firecloud --scope local --lat 31.23 --lon 121.47 --event sunset --source remote
uv run firecloud --scope local --lat 31.2 --lon 121.5 --event sunset --source local
```

## Local detail

```bash
uv run firecloud --lat 31.23 --lon 121.47 --event sunset
uv run firecloud --lat 31.2 --lon 121.5 --radius 120 --resolution 0.2 --source local
```

With the default `--scope all`, coordinates add local maps alongside the national
maps. `--scope local` produces only the requested local maps. `--radius` is in km;
`--resolution` is grid spacing in degrees. Defaults are 150 km and 0.1°.
A shared GFS cube supports detailed physics at each local evaluation point.
This is not interpolation of the national score, but the input model still limits
independent spatial detail.

Remote local products must match published coordinates, radius, and resolution.
The repository's publishing workflow defaults to Shanghai at `31.23,121.47` with
the default grid. An arbitrary point will usually need local computation.

## Output and diagnostics

`--output PATH` changes the output root. Each date has its own directory, with
separate sunrise/sunset PNGs and JSON sidecars. Metadata carries source, model run,
solar event, event-time range, processing options, and performance information.
Inspect metadata before comparing products from different runs or methods.
See [how to read the maps](scientific-figures.md) for the index scale, missing
cells, map projection, and event-versus-model timing. New maps preserve computed
grid values; archived and downloaded products can retain an earlier map style.

## Saved-location workflow

After the [automatic runner](automatic-forecasts.md) is configured, use the same
configuration and output paths to read its current status:

```bash
uv run firecloud status --config .local/forecast-service/viewpoint.json --output output/forecasts
```

This command is read-only. It prints a readable report without starting weather
downloads or a scheduled run. Use `--format json` for scripts. The older
`python -m predictor.forecast_runner status` interface still defaults to JSON.
The service also saves a dated `status.md` page on each unlocked tick.

To make an extra forecast request, use:

```bash
uv run firecloud preview --config .local/forecast-service/viewpoint.json --output output/forecasts
```

An omitted preview date selects the location's current civil day.
Use `--date YYYY-MM-DD` to select another supported event day. A preview uses real weather
sources and saves separate attempt records. It does not satisfy the daily
scheduled slot. These commands do not infer a private service's paths; supply
its actual configuration and output directory.

## Advanced diagnostics

Useful flags:

- `--no-refine`: skip national Stage B refinement; local detail still uses cubes.
- `--no-satellite`: disable satellite correction.
- `--verbose`: show technical diagnostics and tracebacks.
- `--quiet`: suppress informational stage logs.
- `--help`: list all supported arguments.

Additional entry points:

```bash
uv run python -m predictor.gfs_smoke --lat 31.23 --lon 121.47
uv run python -m predictor.national_product --event sunset --output-dir products
```

Both commands may download real weather data. Sounding and cross-section plotting
functions are also available in the Python package for diagnostic work.

## Troubleshooting

**Remote product unavailable:** retry later, choose a published date/location,
or explicitly request `--source local`. A static feed does not compute requests
on demand.

**Slow first run:** GFS pressure cubes can be large. Watch the progress logs;
`--no-refine` reduces national work but does not disable local-point computation.
The terminal's runtime estimate is approximate and can be exceeded substantially.

**Weather-source errors:** the fetchers retry supported transient failures.
Persistent outages still fail. Re-running can reuse completed cached subsets.
Use `--verbose` when reporting a failure.

**Map-data download error:** first-time Cartopy rendering may need Natural Earth
assets. Check network access and the reported Cartopy cache location.

**Unexpected scientific result:** include date, event, coordinates, source mode,
JSON metadata, and the comparison observation. A high index is not a probability
or a guarantee of a visible event.
