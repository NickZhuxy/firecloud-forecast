# Architecture

The public entry point is `predictor.cli:main`, installed as `firecloud`.
It plans national and optional local products for the requested date and events;
`--scope local` limits the plan to the requested location.
The default source policy tries published artifacts first, then computes locally.

## Package map

| Responsibility | Modules in `predictor/` |
| --- | --- |
| Input data and types | `gfs`, `fetch`, `profiles`, `satellite` |
| Vertical diagnosis | `normalize`, `thermo`, `clouds`, `stability`, `uncertainty` |
| Event and path geometry | `solar_event`, `sunset_grid`, `geometry`, `spatial`, `cross_section`, `ray_path` |
| Features and scoring | `features`, `illumination`, `rules`, `score`, `grid_score`, `sunward_section` |
| National computation | `national_field`, `national_physics`, `national_refine` |
| Local computation | `local_field`, `local_product` |
| Satellite experiments | `cloud_top`, `cloud_motion`, `nowcast` |
| Rendering and delivery | `national_product`, `sounding_plot`, `cross_section_plot`, `precompute`, `remote_product`, `cli` |

## Local computation flow

1. Select a GFS model cycle and forecast hours for the requested solar event.
2. Read surface/cover fields or pressure-level cubes as required.
3. Normalize profiles and diagnose cloud layers.
4. Derive the local canvas and sunward illumination features.
5. Evaluate the necessary-condition gates and quality modifiers.
6. Render maps and save JSON metadata.

National computation uses vectorized scoring and a sunward screen, with selective
pressure-cube ray-trace refinement. Local products evaluate detailed point physics
on a smaller grid using a shared cube and batched weather snapshots. Optional
satellite stages depend on suitable data and an eligible event-time window.

## Contracts to preserve

- `gate_modifier_parts` in `rules.py` defines the scalar combination. Vectorized
  `grid_score` must agree for equivalent inputs; parity tests use `1e-9` tolerance.
- An absent required canvas must not be compensated by favorable modifiers.
- GFS bounding boxes use `(lat_min, lat_max, lon_min, lon_max)`. Confirm ordering
  when adapting plotting or other geographic APIs.
- Sunrise and sunset share the event-parameterized pipeline; do not duplicate
  scoring logic by event.
- Keep network access at source boundaries. Unit tests use synthetic inputs and
  monkeypatched providers; real network checks carry the `integration` marker.
- Preserve product provenance and schema compatibility when changing JSON or
  remote manifests. Invalidate/version caches when their meaning changes.
- Historical `probability` names carry an uncalibrated condition index. A rename
  requires an explicit compatibility plan, not a silent scientific reinterpretation.

## Distribution boundaries

The wheel contains `predictor/` runtime modules; tests remain in the repository
and source distribution. The source distribution includes docs, tests, and
research sources and the small documented forecast example through an explicit
allowlist in `pyproject.toml`.
Downloads, routine local output, private references, internal plans, and generated HTML
are not distribution inputs. Keep `uv.lock` for reproducible contributor installs.
