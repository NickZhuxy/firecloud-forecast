# `loop/data/` — the dataset contract (NOT yet satisfied)

The overnight loop scores a model on a **frozen labelled holdout**. That data does
not exist yet, and this harness will not invent it. To make the loop runnable,
drop in two files with the schema in `firecloud_ml/schema.py`:

```
loop/data/train.parquet            # past dates — model fits on these
loop/data/holdout/holdout.parquet  # the frozen scoreboard — later dates only
```

Required columns (one row per location × date, at the sunset golden hour):

| column | meaning |
|---|---|
| `date` | calendar date (drives the leakage-free split) |
| `location_id` | site key |
| `cloud_low_pct` / `cloud_mid_pct` / `cloud_high_pct` | étage cloud cover, 0–100 |
| `rh_850_pct` / `rh_700_pct` / `rh_500_pct` | relative humidity profile, 0–100 |
| `visibility_km` | surface visibility / aerosol proxy |
| `sun_elevation_deg` / `sun_azimuth_deg` | sun–cloud geometry at sunset |
| `label` | **1 = a good 火烧云 occurred, 0 = not** — the supervised target |

## The open question (only a human can answer)

`label` is the blocker. The project's README explicitly says it does **not** plan
to accumulate a personal-observation training set, and does **not** treat its
output as a statistical probability. A supervised Brier/AUC goal needs a label
source and a labelling rule. See `../PROGRESS.md`. Until that is decided and the
two files above exist, `python -m firecloud_ml` exits without writing metrics, and
`verify.sh` stays red. **Rules:** the agent never writes `data/holdout/`; it is the
scoreboard.
