# National product visual revision — white map + orange/red firecloud candidates

Date: 2026-06-25

## Context

The satellite-cloud-overlay experiments were useful for visual exploration, but
the canonical local forecast product should return to an algorithm-first map:
no observed cloud texture, no dark satellite basemap, and no blue/green
probability ramp. The owner wants a clean white map where only firecloud
candidate areas are colored.

## Decision

- Render the canonical China product on a white basemap.
- Hide display probabilities below `0.50`; those areas are treated as
  "no useful firecloud signal" for the visual product and remain uncolored.
- Render visible candidate areas with an orange-to-red colormap only.
- Use saturated orange/red colors and a mostly opaque candidate layer; the
  low end of the color scale must not be near-white.
- Use a narrow `0.06` probability-width alpha feather at candidate edges to
  avoid dirty hard-threshold outlines without expanding the forecast footprint.
- Keep smoothing display-only; JSON metadata and scoring values remain the
  original algorithmic probabilities.
- Upsample the display field by `8×` before rendering. This reduces visible
  0.25° tile/block artifacts without claiming a higher-resolution forecast.
- Upgrade Natural Earth country context from `110m` to `10m`; keep provinces at
  `10m`.
- Use Shapely point-in-geometry masking when available so high-resolution
  polygon holes and rings are respected.

## Non-goals

- Do not change `score_grid`, rules, features, or any algorithmic probability.
- Do not present display upsampling as meteorological downscaling.
- Do not use Himawari/FY satellite cloud texture in this canonical product.
- Do not reintroduce a web/API app.

## Follow-up

The `0.50` display threshold is intentionally a product/display choice. It
should become a CLI option if we want to compare "strict" and "broad" forecast
editions without code changes.
