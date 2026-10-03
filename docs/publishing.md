# Static forecast publishing

The [precompute workflow](https://github.com/NickZhuxy/firecloud-forecast/blob/main/.github/workflows/precompute-pages.yml) runs local
forecast computation on a GitHub runner, then deploys a complete static snapshot
to GitHub Pages. It publishes data and images, not an interactive application or API.

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
number of days, and comma-separated `NAME:LAT:LON` local locations. Shanghai is
the default local product, with 150 km radius and 0.1° grid spacing.

Builds download weather data and can run for hours. Check the runner and Pages
limits for your account before enabling scheduled publishing. Availability depends
on upstream data and successful builds; there is no service-level guarantee.

## Local build

This command performs real downloads and computation:

```bash
uv run python -m predictor.precompute --days 2 --output _site \
  --location shanghai:31.23:121.47
```

A build creates manifests under `products/latest/<date>/<event>.json` and immutable
artifacts under `products/runs/<algorithm-version>/<GFS-cycle>/...` within `_site`.
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
