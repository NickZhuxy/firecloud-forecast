# Methodology and scientific status

This guide describes the implementation in `predictor/`. It consolidates the
historical research drafts without treating their proposed features or old audits
as current behavior. The code and its regression tests define the exact numerical
implementation; this document explains how the pieces fit together.

## 1. What the index means

A cloud-glow event requires a cloud canvas and an illumination path. Favorable
humidity cannot compensate for a missing canvas. The predictor therefore separates
necessary-condition gates from quality modifiers:

```text
G = product(s_i ** (w_i / sum_gate_weights))
M = sum(w_j * s_j) / sum_modifier_weights
condition_index = G * M
```

A zero-valued gate with positive weight forces the composite to zero. Missing
components are omitted; when a component group is empty its value is one. Thus a
score based on fewer inputs is not equivalent evidence to a fully diagnosed score.

The standard configuration in `rules.py` uses:

| Component | Role | Weight |
| --- | --- | ---: |
| Mid/high cloud presence | Gate | 2.0 |
| Low-cloud obstruction | Gate | 2.0 |
| Solar angle | Gate | 1.5 |
| Sunward illumination, when available | Gate | 2.5 |
| Local aerosol perception (`clean_air`) | Modifier | 1.5 |
| Humidity | Modifier | 1.0 |
| Cloud altitude preference | Modifier | 1.0 |
| Cloud-cover sweet spot | Modifier | 1.5 |
| Boundary confidence, when available | Modifier | 1.0 |

These are heuristic weights, not fitted likelihoods. The historical field name
`probability` remains in Python and some metadata for compatibility; the quantity
is an uncalibrated condition index. Local aerosol perception is now a modifier,
although older drafts described it as a clean-air gate. Path aerosol obstruction
still affects illumination separately.

## 2. Cloud diagnosis and stability

`normalize.py` and `thermo.py` convert model profiles to consistent temperature,
humidity, pressure, and geometric-height arrays. `clouds.py` prefers liquid/ice
condensate as cloud evidence; if condensate is unavailable, it uses RH at reduced
confidence. It interpolates threshold crossings and merges nearby cloud layers.

Default assumptions include a condensate threshold of `1e-6 kg/kg`, an RH fallback
threshold of 90%, and a 300 m merge gap. These are configurable diagnosis choices.
The low/mid/high tier boundaries in code are 2 km and 6 km; they are classification
conventions, not universal cloud-altitude limits across all climates.

For condensate-supported layers, cloud optical depth is estimated from water path:

```text
WP = integral(rho_air * q dz)
tau = 1.5 * WP / (rho_condensate * effective_radius)
opacity = (1 - exp(-tau)) * confidence
```

Liquid and ice contributions use different densities and assumed effective radii.
If optical depth cannot be derived, a thickness/phase proxy is used. Finite model
levels, assumed particle sizes, and missing condensate limit this estimate.

Virga can extend the effective blocking base downward for cold, optically
substantial layers above contiguous humid air. Defaults include a base temperature
at or below 263.15 K, optical depth at least 1, sub-base RH at least 60%, and a
maximum extension of 1,500 m. The original cloud base still determines the tier.
These fall-streak rules are empirical proxies, not a precipitation microphysics model.

`stability.py` lifts a surface parcel dry-adiabatically to the lifting condensation
level and moist-adiabatically above it. The first contiguous region where the
parcel is warmer than the environment determines an unstable depth. Default
thresholds distinguish mediocris at 400 m and congestus at 2,000 m; a 500 m band
around the congestus threshold is marked marginal. This approximate regime
classification is not a full convective forecast. Congestus handling carries lower
confidence and calls for recent observations.

## 3. Canvas selection

`illumination.select_canvas` gives eligible mid/high layers precedence. Low cloud
can compete only if no eligible elevated deck is present. Candidates are ranked by:

```text
canvas_score = cover * substance * height * extent
```

Cover can disqualify a deck; substance, height, and boundary extent have floors so
that a thin but real layer remains a possible canvas. Ties favor the higher base.
Missing auxiliary cover/boundary information is treated neutrally. Selection uses
both the diagnosed layers and, when supplied, consistent tier-cover information.

Underlying decks attenuate the selected canvas through the product of their
transmittances. Confidence weights opacity, which means uncertain cloud evidence
softens a veto; it does not establish a statistical confidence interval.

## 4. Geometry, aerosol, and the sunward path

The model uses a curvature-aware parabolic approximation in a vertical sunward
section. With distances and heights in km and Earth radius `R = 6371 km`:

```text
h(l) ~= (l - l0)^2 / (2 * R)
maximum_reach = 2 * sqrt(2 * R * effective_cloud_base)
viewing_angle ~= h / l - l / (2 * R)    # radians, for a distant target
```

The section extends up to 800 km toward the event's solar azimuth. `ray_path.py`
tests cloud, terrain, and aerosol obstruction along candidate rays. Opaque
obstructions veto a path; semi-transparent crossed clouds attenuate surviving
illumination with `product(1 - opacity)`. This discrete approximation is not
continuous spectral radiative transfer. Grazing path length and unresolved cloud
structure introduce uncertainty.

The aerosol model approximates an exponential vertical extinction profile. With
AOD and scale height `H`, the near-surface extinction is approximately `AOD / H`.
The equivalent opaque-ground height follows:

```text
h_x = H * ln(beta_0 / beta_x)
effective_cloud_base = max(0, cloud_base - h_x)
```

Threshold handling and clipping are implemented in `geometry.py`. The extinction
threshold is `0.02 km^-1`. A scale-height sweep over 0.5–4 km expresses sensitivity
to uncertain aerosol vertical structure. Per-column path checks preserve where
upstream aerosol occurs instead of reducing the entire transect to a single mean.
This threshold-based obstruction surrogate is not a resolved optical-depth integral
along every ray.

Relative humidity increases effective aerosol extinction through a bounded
hygroscopic-growth factor:

```text
g(RH) = ((1 - RH_reference) / (1 - RH)) ** 0.6
RH_reference = 0.60; RH is capped at 0.90
```

The factor is one for unknown RH or RH at/below the reference. Local perception and
path obstruction use their relevant aerosol inputs separately. These aerosol
assumptions need independent validation, particularly during fog or unusual events.

Terrain is evaluated in the same geometric frame as the cloud and aerosol path;
coarse model terrain cannot resolve a nearby building or small ridge.

## 5. Timing and motion

`solar_event.py` parameterizes sunrise and sunset in one pipeline. `sunset_grid.py`
resolves event times across the domain and selects forecast hours from a common
model cycle. Polar-edge fallbacks and finite model timesteps limit timing accuracy.
Cloud boundaries can be advected toward the event time using winds at cloud height;
this does not predict cloud growth, decay, or convection.

Duration estimates use local overhead geometry and viewing elevation. The current
representative terminator speed is the mean of a latitude-scaled geometric speed
and an empirical `20 km/min` reference. It is a rough duration assumption and does
not enter the condition score. Treat minute-level duration estimates cautiously.

## 6. National, local, and satellite products

National computation combines a vectorized field and a 1-D sunward screen with
selective 2-D ray-trace refinement. Local maps use detailed point scoring on a
shared pressure cube rather than interpolation of national scores. National
screening and refinement budgets trade fidelity for computation; a coarse or
unrefined cell should not be interpreted as equally resolved local physics.

Satellite modules support cloud-top and motion-related experiments. A correction
requires suitable observations and event timing; inspect metadata to determine
what actually ran. Satellite availability should not be inferred simply from the
presence of the code or an enabled option.

The offline experiment in `experiments/nationalization_spike.py` compares
approximations against a detailed synthetic reference. Agreement with that reference
measures approximation error, not observed forecast accuracy. Historical benchmark
numbers should be regenerated before being used for current performance claims.

## 7. Validation priorities and limits

The current test suite protects gate semantics, scalar/vector agreement, synthetic
cloud/path cases, metamorphic properties, and product delivery contracts. It does
not answer how often users will see a colorful sky at a given score.

High-value follow-up work includes:

1. An independently sourced, versioned set of observed events and non-events, with
   a defined target and geographic/seasonal coverage.
2. Held-out evaluation separated by event/time block, with reliability and failure
   analysis before any probability claim.
3. Sensitivity checks for cloud thresholds, aerosol scale height, and coarse/fine
   refinement choices.
4. Reproducible runtime and download-volume measurements for representative runs.
5. Validation of satellite corrections against observations, including cases where
   corrections reduce skill.

Exact color prediction, full multiple scattering, and inter-cloud secondary
illumination are outside the current implementation. Do not infer these capabilities
from the paper's background discussion of atmospheric optics.

## 8. Research provenance

The historical manuscript and bibliography remain in `paper/`. They include
background references on cloud classification, atmospheric optics, and solar
geometry. Original theory drafts and implementation audits remain in Git history.
Some empirical geometry and threshold choices were inspired by a privately held
practical forecasting manual; that source is not redistributed. Such provenance
is distinct from independent verification or peer review of this model.
