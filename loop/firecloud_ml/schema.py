"""Row schema for one (location, date) golden-hour example.

A deliberately small, explicit contract so the leakage guard, the split, and the
eval harness all agree on what a row is. Features mirror the project's physical
drivers (étage cloud cover, an RH profile, surface visibility / aerosol proxy,
sun–cloud geometry at sunset). ``label`` is the supervised target a real dataset
would have to provide; the project does not yet have one.
"""
from __future__ import annotations

import pandas as pd

# Physical drivers, all per (location, date) at the sunset golden hour.
FEATURE_COLUMNS: list[str] = [
    "cloud_low_pct",       # GFS low-étage cloud cover (0–100)
    "cloud_mid_pct",       # mid-étage cover (0–100)
    "cloud_high_pct",      # high-étage cover (0–100)
    "rh_850_pct",          # relative humidity at 850 hPa (0–100)
    "rh_700_pct",          # 700 hPa
    "rh_500_pct",          # 500 hPa
    "visibility_km",       # surface visibility / aerosol proxy
    "sun_elevation_deg",   # solar elevation at sunset (≈0, negative below horizon)
    "sun_azimuth_deg",     # solar azimuth at sunset (0–360)
]
# Identity columns: ``date`` drives the leakage-free split; ``location_id`` keys a site.
ID_COLUMNS: list[str] = ["date", "location_id"]
LABEL_COLUMN: str = "label"   # 1 = a good 火烧云 occurred, 0 = not
REQUIRED_COLUMNS: list[str] = ID_COLUMNS + FEATURE_COLUMNS + [LABEL_COLUMN]


class SchemaError(ValueError):
    """Raised when a frame does not satisfy the example schema."""


def validate(df: pd.DataFrame) -> pd.DataFrame:
    """Return a typed copy of ``df`` or raise :class:`SchemaError`.

    Guarantees for downstream code: every required column present, ``date`` is a
    real datetime, every feature is finite numeric, and ``label`` is strictly
    0/1 with no gaps.
    """
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise SchemaError(f"missing required columns: {missing}")

    out = df.copy()
    try:
        out["date"] = pd.to_datetime(out["date"])
    except (ValueError, TypeError) as exc:
        raise SchemaError(f"'date' is not parseable as datetime: {exc}") from exc

    for col in FEATURE_COLUMNS:
        coerced = pd.to_numeric(out[col], errors="coerce")
        if coerced.isna().any():
            raise SchemaError(f"feature '{col}' has non-numeric or missing values")
        out[col] = coerced.astype(float)

    label = pd.to_numeric(out[LABEL_COLUMN], errors="coerce")
    if label.isna().any():
        raise SchemaError("'label' has missing or non-numeric values")
    if not set(label.unique()).issubset({0, 1}):
        raise SchemaError(f"'label' must be 0/1, got {sorted(label.unique())}")
    out[LABEL_COLUMN] = label.astype(int)
    return out
