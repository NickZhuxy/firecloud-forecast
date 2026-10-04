# Product roadmap

Firecloud should help someone obtain a local sunrise or sunset forecast,
understand what the model says, and check whether the result arrived in time.
The current product is research software. Its condition index is an uncalibrated
heuristic; easier delivery does not establish forecast accuracy.

This roadmap sets priorities and acceptance criteria. It does not promise release
dates. The [issue tracker](https://github.com/NickZhuxy/firecloud-forecast/issues)
holds implementation tasks. The [project story](project-story.md) records completed
work and the evidence behind it.

## Current position

- China supports national and local maps. New York City supports an experimental
  local pilot with regional bounds and a civil-timezone date policy.
- Two archived forecast examples retain maps, source times and checksums. They
  demonstrate inspectable output, not observed forecast skill.
- The published `v0.1.0` release is the historical community research preview.
  Newer features in the source repository are not automatically part of that release.
- [Automatic local delivery](https://github.com/NickZhuxy/firecloud-forecast/pull/122)
  is under review. It preserves attempts, separates previews, and records failures
  and missed windows. A local Mac service depends on the host being awake, logged
  in and online.

## 1. Complete the daily local forecast experience

**User outcome:** a person can open one status page and understand whether the
configured event's forecast is waiting, available, failed or missed.

Acceptance criteria:

- Show the report's check time, the runner's last tick, and the local event date.
  A saved page must not imply that the service is currently healthy forever.
- Show planned requests, retries and expired windows in plain English. A result
  from an earlier date must remain distinct from the current event's state.
- Put the condition index, local event time and map before detailed provenance.
  Distinguish a valid zero index from unavailable or damaged output.
- Explain retained model diagnostics and missing inputs without inventing
  observations, sky colors, calibrated probabilities or a new scoring rule.
- Preserve original products and machine-readable records. Rendering or writing
  the status page must not discard a successful forecast.
- Require no daily command, personal photograph, observation sheet, manual label,
  webcam or AI service for normal forecast delivery.

The first operational review should examine scheduled completion, source timing,
missed windows and recovery. It is a delivery check, not an accuracy study.

## 2. Make a new user's first result easier to obtain

**User outcome:** a new contributor can inspect an example offline, then make one
bounded local forecast without navigating internal modules or guessing settings.

Acceptance criteria:

- Keep one clear installation route, an offline example and an explicit coverage
  description. Verify the instructions from a fresh environment.
- Provide a saved-result inspector that works with public examples as well as
  private results. Missing historical diagnostics must remain unknown.
- Keep service setup discoverable. Require an explicit location, execution
  environment and real preview before activation.
- State download sizes and runtimes as measured cases, including cache state.
  Do not turn one computer's measurements into universal promises.
- Keep private configurations, routine products and caches outside packages.
  Prepare a new preview release only after its source and package checks pass.

## 3. Offer delivery that does not depend on a personal laptop

**User outcome:** a person who chooses an always-on deployment can receive the
same dated forecast without keeping a laptop awake.

Before implementation, choose a host, delivery channel, supported location set,
resource budget and maintenance owner. Do not assume paid hosting, public location
disclosure or notifications to other people.

Acceptance criteria:

- Reuse the deterministic runner and its timing, retry and integrity contracts.
- Demonstrate a scheduled forecast through the actual deployment environment.
- Expose outages, freshness and failed delivery. Preserve source-valid times and
  original attempts; do not silently substitute a retrospective forecast.
- Measure storage, weather transfers and execution cost for the chosen workload.
- Verify any notification or public-feed behavior separately from generation.

Local notifications are a smaller optional improvement. Their delivery and
deduplication still need testing in the installed background environment.

## 4. Expand coverage through regional acceptance checks

**User outcome:** additional supported regions use the correct local event date,
weather domain, map and product identity.

Acceptance criteria:

- Test civil dates, daylight saving transitions and UTC rollover for each profile.
- Verify observer bounds and the complete sunward weather path separately.
- Retain regional source, correction and input-availability metadata.
- Add a documented forecast case with reproducible timing and artifact checks.
- Describe regional limitations explicitly. Coordinate support alone is not a
  claim that a region has been evaluated against observations.

New weather models and scoring changes require their own scientific and software
review. They are not prerequisites for improving the existing delivery experience.

## Deferred: webcam collection and machine-learning validation

The full collection and recognition pipeline is on hold. It should become a
separate project only if its source rights, image freshness, camera geometry,
label quality, cross-camera and seasonal performance, and operating budget can
be established. Forecast delivery must remain independent of that pipeline.

Independent evaluation remains a research goal. Passing regression tests,
viewing a few example maps, or producing automatic image labels does not meet it.
No personal photo collection or daily labeling work is assigned to users by this
roadmap. See [the scientific limits](../research/methodology.md#7-validation-priorities-and-limits).
