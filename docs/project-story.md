# From a forecast prototype to an explainable research product

Firecloud's development history records a series of concrete questions: what does
a favorable score mean, which clouds can be illuminated, how can a detailed
calculation scale to a map, and how can someone obtain a result without managing
weather downloads? The first tracked design dates to May 20, 2026. This page
follows decisions documented in commits and research cases. The examples
distinguish software checks from observed forecast evaluation.

## 1. A working forecast exposed the first engineering problems

**May 20–21, 2026.** The initial prototype connected NOAA HRRR weather data to
small scoring rules and a map notebook. Moving from one point to a regional grid
made repeated GRIB parsing costly and exposed a geographic detail: distances in
latitude and longitude degrees need a latitude correction. Dataset caching and
a `cos(latitude)` correction followed the first use of the map.

The lesson was practical: a weather-data interface needs to handle geographic
coordinates and reuse expensive reads, not just return the requested variables.

Evidence: [initial source adapter](https://github.com/NickZhuxy/firecloud-forecast/commit/0b27a46),
[first-use bug finding](https://github.com/NickZhuxy/firecloud-forecast/commit/1ccdea3),
[cache and coordinate correction](https://github.com/NickZhuxy/firecloud-forecast/commit/c2dfc6c).

## 2. A favorable average could conceal a missing cloud canvas

**May–June 2026.** In the historical Olympic Peninsula case, the project's own
weighted-average baseline returned an index around 0.63 despite zero
model-reported mid- and high-cloud coverage. Favorable values for other inputs
could outweigh a missing necessary component. The replacement separated
necessary-condition gates from quality modifiers: a zero-valued gate with
positive weight forces the combined index to zero.

This is evidence of a design correction. The case has no independent observation
establishing what the sky actually looked like, so it cannot demonstrate better
real-world accuracy or superiority to another service.

Evidence: [historical case and figures](../research/paper/README.md),
[gate × modifier implementation, June 7](https://github.com/NickZhuxy/firecloud-forecast/commit/cb2225e),
[current scoring assumptions](../research/methodology.md).

## 3. Clouds over the observer are only part of the problem

**June–July 2026.** The calculation grew from bulk cloud-cover rules into diagnosed
layers, a selected cloud canvas, and a section toward the sun. The implemented
path extends up to 800 km and checks cloud, terrain, and aerosol obstruction.
Later changes distinguished aerosol effects on the incoming illumination path
from effects on local viewing conditions.

That added complexity created an obligation to explain the assumptions and keep
the scalar and map calculations consistent. Physical invariance and parity tests
help protect those software properties; they do not replace observed forecast
evaluation.

Evidence: [aerosol-role separation](https://github.com/NickZhuxy/firecloud-forecast/commit/bdccaaf),
[terrain obstruction](https://github.com/NickZhuxy/firecloud-forecast/commit/42ff5d4),
[current geometry](../research/methodology.md#4-geometry-aerosol-and-the-sunward-path),
[architecture contracts](architecture.md#contracts-to-preserve),
[physical invariance tests](../predictor/tests/test_metamorphic_physics.py).

## 4. Obtaining a forecast became a product problem

**July–August 2026.** Detailed computation requires substantial weather data.
Development added resumable downloads, progress messages, precomputed products,
checksum verification, and a remote delivery path. Subsequent work hardened
weather requests against transient failures.

The lesson was that a forecast also needs a usable delivery system. Available
precomputed products let users retrieve a result without performing the full
local calculation. A remote feed still needs freshness checks and explicit
failure behavior.

Evidence: [remote delivery and resumable downloads](https://github.com/NickZhuxy/firecloud-forecast/commit/a0dd635),
[local-detail delivery](https://github.com/NickZhuxy/firecloud-forecast/commit/ff90379),
[retry hardening](https://github.com/NickZhuxy/firecloud-forecast/commit/c61d87e),
[publishing guide](publishing.md).

## 5. Clear claims and correct dates are part of regional readiness

**September 2026.** Public documentation moved to English, the repository adopted
the MIT License, and distribution rules separated source from downloads and local
execution files. A local-date bug was also corrected: a September 14 sunset in
Los Angeles must not resolve to September 13 locally just because the event lies
on a different UTC date.

The event helper then selected by longitude-based local solar day. This addressed
the documented rollover problem; it was not a full civil-timezone lookup. China
was the first supported product region. Extending coverage also needed
regional maps, delivery conventions, source checks, and evaluation.

Evidence: [community foundation and event-date correction](https://github.com/NickZhuxy/firecloud-forecast/commit/4e3174e),
[date semantics](usage.md), [event-date regression tests](../predictor/tests/test_solar_event.py).

## 6. Regional delivery needs more than accepting coordinates

**October 2026.** The New York City pilot added an explicit region profile, local
map bounds, and an `America/New_York` civil-date policy, including daylight saving
time. Its complete sunward weather domain is separate from the allowed observer
bounds. The pilot uses the existing GFS calculation and records that satellite
correction is unavailable for this region. A public archived case separates the
exact sunset instant from the weather model's selected forecast hour.

The next delivery change is under review: a deterministic unattended runner with
bounded retries, interruption recovery, separate previews and verified original
artifacts. Its local service records missed windows when the host is unavailable.
It requires no personal photographs or daily observation sheet. A readable status
snapshot makes waiting, failed and stale results visible without treating saved
files as proof of current service health.

The lesson is that a regional forecast needs a correct local date, an inspectable
weather domain, honest source timing, and a usable delivery path. Those software
properties still do not establish accuracy against the observed sky.

Evidence: [merged New York City pilot](https://github.com/NickZhuxy/firecloud-forecast/commit/e432b22),
[archived New York City case](../examples/new-york-sunset/README.md),
[automatic delivery under review](https://github.com/NickZhuxy/firecloud-forecast/pull/122),
[delivery guide](automatic-forecasts.md), [product priorities](roadmap.md).

## What remains open

Firecloud now has an inspectable implementation, tests, reproducible research
scripts, and traceable product metadata. Its condition index remains an
uncalibrated heuristic. The next research question is how well it corresponds to
independently observed cloud-glow conditions across places, seasons, and forecast
lead times.

Useful contributions include reproducible forecast cases, clearly licensed
reference observations, regional acceptance checks, and explanations of a
forecast that failed. See [Contributing](../CONTRIBUTING.md) and
[the current methodology](../research/methodology.md#7-validation-priorities-and-limits).
