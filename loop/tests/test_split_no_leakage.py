"""(b) holdout-leakage guard."""
import pandas as pd

from firecloud_ml.split import split_by_date


def test_no_date_appears_in_both_sides(make_frame):
    df = make_frame(n_dates=20, rows_per_date=6)
    train, holdout = split_by_date(df, holdout_frac=0.25)

    train_dates = set(pd.to_datetime(train["date"]).unique())
    holdout_dates = set(pd.to_datetime(holdout["date"]).unique())
    assert train_dates and holdout_dates
    assert train_dates.isdisjoint(holdout_dates)
    # No rows lost, none duplicated.
    assert len(train) + len(holdout) == len(df)


def test_holdout_is_the_most_recent_dates(make_frame):
    df = make_frame(n_dates=10, rows_per_date=4)
    train, holdout = split_by_date(df, holdout_frac=0.3)
    # Forward-in-time: every holdout date is later than every train date.
    assert pd.to_datetime(holdout["date"]).min() > pd.to_datetime(train["date"]).max()


def test_explicit_holdout_dates_are_honoured(make_frame):
    df = make_frame(n_dates=5, rows_per_date=3)
    held = [pd.to_datetime(df["date"]).max()]
    train, holdout = split_by_date(df, holdout_dates=held)
    assert set(pd.to_datetime(holdout["date"]).unique()) == set(held)
    assert pd.to_datetime(held[0]) not in set(pd.to_datetime(train["date"]).unique())
