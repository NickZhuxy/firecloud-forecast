"""(a) data-schema test."""
import numpy as np
import pytest

from firecloud_ml.schema import REQUIRED_COLUMNS, SchemaError, validate


def test_valid_frame_is_typed(make_frame):
    out = validate(make_frame(n_dates=3, rows_per_date=4))
    assert list(REQUIRED_COLUMNS)  # sanity
    assert np.issubdtype(out["date"].dtype, np.datetime64)
    assert out["label"].dtype == int
    assert set(out["label"].unique()).issubset({0, 1})


def test_missing_column_is_rejected(make_frame):
    df = make_frame(n_dates=2, rows_per_date=2).drop(columns=["rh_700_pct"])
    with pytest.raises(SchemaError, match="missing required columns"):
        validate(df)


def test_non_numeric_feature_is_rejected(make_frame):
    df = make_frame(n_dates=2, rows_per_date=2)
    # pandas 3 won't store a string in a float column; widen to object first so
    # the bad value actually reaches validate().
    df["visibility_km"] = df["visibility_km"].astype(object)
    df.loc[0, "visibility_km"] = "fog"
    with pytest.raises(SchemaError, match="visibility_km"):
        validate(df)


def test_label_outside_zero_one_is_rejected(make_frame):
    df = make_frame(n_dates=2, rows_per_date=2)
    df.loc[0, "label"] = 2
    with pytest.raises(SchemaError, match="label"):
        validate(df)
