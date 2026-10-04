# Optional local forecast observations

Forecast generation does not require photographs, webcam images, or observation
labels. This guide describes an optional manual evaluation workflow for
contributors who choose to collect observations. It is not a required product
setup step. This observation workflow currently has no unattended runner or
webcam collector.

A webcam can replace personal photography in a separate automated evaluation
workflow once its location, view, timestamps, and supported access method are
verified. Compare those images with forecasts for the camera's actual location;
a nearby camera is not direct evidence of the sky at another viewpoint. Webcam
availability must not prevent the requested location's forecast from running.

Use one consistent viewpoint for a 2–4 week exploratory sunset pilot. Save the
prediction before observing the sky. Keep the scoring unchanged during this pilot.
The aim is to find delivery failures and recurring forecast problems, not to
calibrate the condition index or establish seasonal accuracy.

## Configure a viewpoint

Create `.local/observation-pilot/viewpoint.json`. This directory is ignored by Git.
Use your own location within the selected region's observer bounds. This public
example uses representative NYC coordinates:

```json
{
  "id": "my-viewpoint",
  "name": "My observation viewpoint",
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

The ID must be a safe directory name. The timezone must match the region profile.
The coordinates select the weather grid; they do not establish the camera height,
viewing direction, or visibility of the horizon. Record those separately. A 0.1°
evaluation grid does not increase the underlying GFS resolution of 0.25°.

## Plan the pilot

Install the project as described in the main README, then run:

```bash
uv run python -m predictor.observation_pilot plan \
  --start 2026-10-04 --days 28 --output .local/observation-pilot
```

The date is an example; choose the start of your pilot. The schedule records local
and UTC event times and the configured lead time, two hours in this example. Lead time is elapsed
time calculated in UTC, including across daylight saving transitions. The command
does not download weather or create an unattended scheduled task.

## Capture a forecast

At the planned time, run:

```bash
uv run python -m predictor.observation_pilot forecast
```

The default config is `.local/observation-pilot/viewpoint.json`. The default date
is today in its configured timezone. Add `--date YYYY-MM-DD` for another event
date. A local run can download substantial weather data; allow time for the first
download. The timestamp used to classify the lead is the request start time.

Every attempt has a separate directory under
`output/pilot/<viewpoint-id>/<date>/<attempt-id>/`. A successful attempt contains a
PNG, the original product JSON, and `attempt.json`. A failed forecast still saves
an attempt record for ordinary provider or renderer errors and exits with an error.
An initial `started` record is written before provider work. Interruption can leave
that record incomplete; disk failures can prevent persistence. Repeating a request
creates a new
attempt rather than replacing an earlier prediction.

The attempt records the request and event times, actual and intended lead,
timing status, actual completion time, source revision when available, runtime,
status, and product provenance. The product sidecar supplies source-valid times and the condition
components. Completion uses the wall clock; runtime uses a monotonic clock.
`product_available_before_event` requires successful completion before the event.
The source revision is a Git checkpoint only. `working_tree_not_verified` means
working-tree changes were not checked; the hash does not prove that the exact
executed files match a clean source tree. Installed packages outside a matching
source checkout have no recorded Git revision.

An early or late run remains in the log but is outside the planned lead window.
An after-event run is labeled separately. It cannot count as a forecast issued
before that observation. An initial setup run for a later day is a preview, and
should remain separate from the planned two-hour-lead sample.

## Record observations

Copy [the CSV template](templates/observation-log.csv) into your local pilot
directory. Keep a row for every scheduled event, including missed observations.
Record a successful attempt whose completion time precedes the observation's
`observed_at_local` timestamp. Request-based timing status alone does not establish
that the product was available then. Preserve additional
attempts without choosing a more favorable prediction after seeing the sky.

For this pilot, use a consistent window from 10 minutes before to 20 minutes after
sunset. Take timestamped photos from the same position and direction when possible.
Keep camera exposure and white balance consistent if you want to compare photos.
Record a changed viewpoint or obstructed sky rather than treating it as a model
failure automatically.

Use these `cloud_illumination` labels:

| Label | Meaning |
| --- | --- |
| `visible` | The observation shows colored illumination on clouds |
| `absent` | The sky was observed adequately and colored cloud illumination was absent |
| `uncertain` | The available view or image does not support a confident label |
| `not_observed` | The event occurred but no usable observation was collected |
| `not_recorded` | The row has not yet been completed; do not interpret it as absence |

Store ISO timestamps with UTC offsets, photo paths, camera position, direction,
horizon obstruction, and notes. The labels describe observations, not exact sky
color predictions or a calibrated probability. Do not infer unobserved cloud
height or fill in missing observations from the forecast itself.

## Review the sample

Count planned events, successful and failed requests, on-time attempts, usable
observations, and uncertain or missed observations. Compare the index and gate
components with the observation labels. Review both high-index misses and
low-index events that had illuminated clouds. Keep early, late, and after-event
runs identifiable.

Routine predictions and personal photographs stay in ignored local directories.
Public examples should be deliberately selected and reviewed, include successes
and failures, and use observations that the contributor has permission to share.
Describe view limitations and source timing. A few weeks at one viewpoint can
reveal collection problems and failure cases; they do not establish calibration,
regional skill, or seasonal reliability.
