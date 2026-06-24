"""Leakage-free train/holdout split.

For a next-day forecast the only honest split is BY DATE and FORWARD IN TIME:
every row of a given calendar date goes entirely to one side, and the holdout is
the most recent dates. Splitting rows within a day leaks same-day weather; using
random dates leaks the future into training. Both are silent skill inflators, so
this module makes the date partition explicit and asserts it.
"""
from __future__ import annotations

import pandas as pd


def split_by_date(
    df: pd.DataFrame,
    holdout_frac: float = 0.2,
    holdout_dates: list | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split into ``(train, holdout)`` with no shared calendar date.

    The holdout is the latest ``holdout_frac`` of distinct dates (a forward-in-
    time split), unless an explicit ``holdout_dates`` set is given.
    """
    if "date" not in df.columns:
        raise ValueError("split_by_date requires a 'date' column")
    dates = pd.to_datetime(df["date"])
    unique_dates = sorted(dates.unique())
    if not unique_dates:
        return df.iloc[0:0].copy(), df.iloc[0:0].copy()

    if holdout_dates is not None:
        hold = {pd.Timestamp(d) for d in holdout_dates}
    else:
        if not 0.0 < holdout_frac < 1.0:
            raise ValueError("holdout_frac must be in (0, 1)")
        n_hold = max(1, round(len(unique_dates) * holdout_frac))
        hold = {pd.Timestamp(d) for d in unique_dates[-n_hold:]}

    is_hold = dates.isin(hold).to_numpy()
    train = df.loc[~is_hold].copy()
    holdout = df.loc[is_hold].copy()

    # The guarantee the rest of the harness relies on.
    overlap = set(pd.to_datetime(train["date"]).unique()) & set(
        pd.to_datetime(holdout["date"]).unique()
    )
    assert not overlap, f"date leakage between train and holdout: {overlap}"
    return train, holdout
