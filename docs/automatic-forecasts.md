# Automatic local forecasts

The automatic runner saves a local forecast near the configured lead time before
sunrise or sunset. It uses the existing weather sources, scoring and renderer.
Photographs, observation sheets, webcam images and AI services are not required.

Delivery is local: a latest-result summary links to the original map, metadata
and attempt record. This does not create an API, public feed, or email service.
The condition index remains an uncalibrated heuristic.

## 1. Save the location

Install the project environment with `uv sync --frozen` first. Create an ignored
configuration such as `.local/forecast-service/viewpoint.json`:

```json
{
  "id": "my-viewpoint",
  "name": "My forecast location",
  "region": "us-nyc",
  "timezone": "America/New_York",
  "latitude": 40.7128,
  "longitude": -74.0060,
  "solar_event": "sunset",
  "radius_km": 25,
  "resolution_deg": 0.1,
  "lead_minutes": 120,
  "lead_tolerance_minutes": 15
}
```

The example coordinates identify the public NYC city center. Use a location within
the selected region's bounds. The ID is a safe directory name. The timezone must
match the region profile. Keep the configuration and generated forecasts out of
Git and release archives.

## 2. Check a real preview

Check a real forecast and its delivery before loading a background job. A preview
is an extra request for a specified event date. It uses separate latest files and
does not satisfy that date's scheduled slot. Do not treat an early setup preview
as a forecast issued at the intended lead time.

Previewing uses real weather sources and can download substantial data. Planning
and status inspection do not request weather. The installer does not load a
LaunchAgent merely by writing its configuration.

Request an extra preview for a chosen local event date:

```bash
uv run firecloud preview \
  --config .local/forecast-service/viewpoint.json --date 2026-10-04 \
  --output output/forecasts
```

The date is an example. The command reports the attempt record's path.
After success, open `<output>/previews/<site-id>/preview_latest.md` for links to
the map, metadata and attempt. Inspect them before activating the service.
See [how to read the maps](scientific-figures.md).
A separate manual tick is not needed for setup; the service checks when loaded.

## 3. Prepare and activate the macOS service

First verify the real preview. Use absolute service paths. This example prepares
the source-checkout environment; a pinned runtime is preferable for a durable
installation:

```bash
uv run python -m predictor.forecast_service install \
  --config "$PWD/.local/forecast-service/viewpoint.json" \
  --output "$PWD/output/forecasts" --start 2026-10-04 \
  --python "$PWD/.venv/bin/python" --dry-run
```

The dry run prints the plist and activation/status/removal commands without
writing the job. Remove `--dry-run` to prepare its plist and log directories.
Then run the printed `activate` command. Inspect the printed `status` command and
actual service logs to confirm the launched interpreter can read the config and
write state. A successful plist preparation alone does not verify execution.

The service checks every five minutes and once when loaded. Its request tolerance
must be at least five minutes; the example uses fifteen minutes. `--module-path` and
`--working-directory` select a pinned installed package and separate operational
data directory. The working directory must not shadow that package with another
`predictor` directory. Stop the job with the printed `deactivate` command before
removing its plist or replacing its runtime. Existing different jobs are not
silently overwritten.

## 4. Read the status

Open `<output>/<site-id>/status.md`, or run:

```bash
uv run firecloud status \
  --config .local/forecast-service/viewpoint.json --output output/forecasts
```

Use the same configuration and output paths as the installed service. A private
installation may use absolute paths outside the repository. These commands do
not discover private installations automatically.

`status` reads saved records without requesting weather or starting a scheduled
run. It prints a readable report by default; add `--format json` for scripts.
The module interface `python -m predictor.forecast_runner status` keeps its JSON
default. The page is a dated snapshot; check its time and the last tick before
assuming that the service is current.

Each unlocked command-line tick also writes `<output>/<site-id>/status.md`.
This is a dated status snapshot, separate from the canonical `latest.md` forecast
and original attempts. It shows the runner's last tick, the event's recorded
state, request and event times, and any verified scheduled result. Its check time
is explicit: a page saved yesterday does not establish today's service health.
An expired pending window is identified even if the runner has not recorded the
miss yet. A setup preview does not become the scheduled forecast.

Where retained, the report explains model diagnostics and input availability.
These are model results, not observed sky conditions. Missing diagnostics remain
unknown. Detailed weather-valid times stay separate from the exact event time.
If report rendering or writing fails, the command preserves the forecast result
and logs the report error; a later tick can try again.

## Schedule and timing

The planned request is the event time minus `lead_minutes`, calculated in UTC.
The event date belongs to the location's civil timezone, including daylight
saving time. A periodic tick starts no earlier than the planned request and no
later than the end of the configured tolerance. It does not start a new forecast
after that window to make a missed run appear successful.

Each retry uses its real request time to select available weather. Request and
completion times are recorded separately. A request in the planned window does
not prove that the product was available before the event. Source-valid times can
differ from the exact event instant; the original product metadata records them.

The default policy permits at most three attempts, with at least five minutes
between a failed attempt's completion and its next request. Retries must still
fit the request window. Provider work can take longer than five minutes, so the
number of available retries can be smaller than the configured maximum.

A process lock prevents concurrent ticks for the same site. Persistent slots
retain success, failure and interruption state. A successful scheduled slot is
not captured again. The forecast configuration is fingerprinted; a conflicting
configuration must not silently replace an existing event's record.

## Weather cache and disk space

GFS downloads use `research/data/cache/gfs` relative to the working directory.
Choose a separate service data directory so this cache is separate from a source
checkout and the pinned package. The runner checks for at least 1 GB of free disk
space before starting provider work; low space becomes a recorded failure.

For a dedicated service cache, opt in to retention with
`--cache-root ABSOLUTE_SERVICE_DATA/research/data/cache/gfs --cache-retention-days 14`.
The same flags are accepted by the runner and installer. The path must match the
default cache under the working directory. Old regular cache files are removed
under the site lock. Symlink paths are rejected. Retention is disabled unless
explicitly configured; do not enable it for a shared or manually maintained cache.
Original forecasts, metadata and attempts are not cache-pruning inputs.

## Local host requirements

A macOS user LaunchAgent runs while the user is logged in. It requires an awake
computer, network access, a working Python environment and readable local files.
Calendar-based launches coalesce after sleep; they do not wake the Mac. When the
runner resumes after a missed request window, it records the miss rather than
generating a retrospective forecast. Past dates since the configured start remain
represented in the state.

The local setup is not an always-on service. Do not assume that closing a laptop
or disconnecting it will still produce forecasts. An always-on host is a separate
deployment choice; it can reuse the same deterministic tick without an AI agent.
See [Apple's LaunchAgent guide](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html)
and the installed `launchd.plist` manual for host behaviour.

macOS privacy controls can block background access to Desktop folders even when
interactive commands work. Verify an actual launch in the installed environment.
An operational runtime and normalized config can reside in
`~/Library/Application Support/Firecloud Forecast/` when Desktop access is not
available. Never work around this by weakening system permissions.

Use absolute paths in service configuration. A pinned installed package avoids
silently changing the running code when a source checkout changes branches.
Keep its package hash and source revision in a local deployment record. Installed
packages may have no Git revision in individual attempt metadata; the deployment
record then identifies the deployed code. A recorded checkout revision does not
assert a clean working tree.

## Delivery and failures

The latest-result files are pointers and summaries. They do not replace original
attempts or weather provenance. Preview delivery is kept separate from scheduled
delivery. Check the target date and completion time before using a latest result;
an older successful result is not evidence of a new forecast.

Keep unsuccessful attempts and missed slots. An interrupted attempt can leave a
started record. Recovery must preserve it and check whether completion occurred
before retrying. Artifact integrity and delivery failures are distinct from a
weather-generation failure. No successful forecast should be invented from a
missing, incomplete or damaged artifact.

The service writes operational logs locally. Inspect them if execution fails,
and confirm access after changing Python, moving files, or replacing a package.
No images or model outputs are automatically published. This workflow does not
establish real-world forecast accuracy.

## Operator commands

Planning does not request weather. From the repository root, inspect the next
seven event times:

```bash
uv run python -m predictor.forecast_runner plan \
  --config .local/forecast-service/viewpoint.json --days 7
```

For a deliberate manual scheduler check, use the installed start date, output
path, and retry settings:

```bash
uv run python -m predictor.forecast_runner tick \
  --config .local/forecast-service/viewpoint.json --start 2026-10-04 \
  --output output/forecasts
```

A tick can request real weather when a slot is due. Normal service operation
already performs these checks; this is not a daily user task.
