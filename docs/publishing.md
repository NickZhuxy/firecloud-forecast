# Static forecast publishing

The [precompute workflow](https://github.com/NickZhuxy/firecloud-forecast/blob/main/.github/workflows/precompute-pages.yml) runs local
forecast computation on a GitHub runner, then deploys a complete static snapshot
to GitHub Pages. It publishes data, images and a static map page from `web/`.
There is no server and no API.

## Setup

1. Enable GitHub Pages for the repository and select **GitHub Actions** as its source.
2. Put the workflow on the default branch.
3. Run **Precompute Firecloud products** from Actions to verify a full build.
4. Configure clients to use your deployment URL.

Forks do not run the expensive publishing job by default. To enable publishing in
a fork, set the repository Actions variable `FIRECLOUD_ENABLE_PUBLISHING` to `true`
and configure Pages. The original repository retains its existing schedule.

The workflow runs four times daily after GFS cycle release windows, and also on
relevant pushes to `main`. Its default products cover today and tomorrow in
`Asia/Shanghai`, for sunrise and sunset. Workflow inputs allow selecting dates,
number of days, and comma-separated `NAME:LAT:LON[:REGION]` local locations. The
default local products are Shanghai and New York City (`us-nyc`), each with a 150 km
radius and 0.1° grid spacing. New York products use the New York calendar date and
skip the satellite stage.

Each run asks Open-Meteo once per location and grid batch, and every product of the
run reads from those responses. The free tier counts each grid cell as one location,
so each extra local location adds about 837 × 4 locations per day.

Builds download weather data and can run for hours. Check the runner and Pages
limits for your account before enabling scheduled publishing. Availability depends
on upstream data and successful builds; there is no service-level guarantee.

## Local build

This command performs real downloads and computation:

```bash
uv run python -m predictor.precompute --days 2 --output _site \
  --location shanghai:31.23:121.47 \
  --location new-york:40.7128:-74.0060:us-nyc
cp -R web/. _site/
```

A build creates manifests under `products/latest/<date>/<event>.json` and immutable
artifacts under `products/runs/<algorithm-version>/<GFS-cycle>/...` within `_site`.
Local products for a location go under `.../<date>/<event>/points/<key>`. A pilot
region adds `regions/<region>/` before the date, for example
`products/latest/regions/us-nyc/<date>/<event>/points/<key>.json`.
`products/latest/index.json` lists the China manifests under `manifests` and the
pilot manifests under `regional`.

Every product also has a `*.grid.json` file (schema `firecloud-grid/1`). It holds the
grid, the index per cell, the map colours and outlines, and for local products the
gate score and the limiting gate per cell. The map page reads these files. Serve
`_site/` with any static server to open the page locally, for example
`python -m http.server -d _site`.
The workflow uses the commit SHA as the algorithm version. Each deployment replaces
the served snapshot; do not assume the static site is a permanent historical archive.

`_site/` stays outside Git. The workflow uploads it as a Pages artifact.

## Client configuration

The default feed is the maintainer's GitHub Pages deployment. Override it for a fork:

```bash
export FIRECLOUD_REMOTE_BASE_URL="https://YOUR-ACCOUNT.github.io/firecloud-forecast/"
uv run firecloud --source remote --event sunset
```

Clients validate freshness, product identity, and SHA-256 checksums. A valid cached
remote product may satisfy a request during a temporary outage. `--source remote`
never starts local forecast computation; `auto` can fall back to it.
