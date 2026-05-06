from __future__ import annotations

from typing import Mapping

import pandas as pd


def _pivot_levels(high: float, low: float, close: float) -> dict[str, float]:
    p = (high + low + close) / 3.0
    rng = high - low
    return {
        "P": float(p),
        "R1": float(2 * p - low),
        "R2": float(p + rng),
        "S1": float(2 * p - high),
        "S2": float(p - rng),
    }


def daily_pivots(df: pd.DataFrame) -> Mapping[str, float] | None:
    """Compute classic pivots from the most recent completed daily bar."""
    if df is None or df.empty:
        return None
    last = df.iloc[-1]
    return _pivot_levels(float(last["High"]), float(last["Low"]), float(last["Close"]))


def weekly_pivots(
    df: pd.DataFrame,
    *,
    tz: str = "America/New_York",
) -> Mapping[str, float] | None:
    """Resample to W-FRI in `tz`, then take the prior completed week (row -2).

    Row -1 is treated as the in-progress week even when the data ends on a
    Friday — using -2 keeps pivots stable across mid-week reruns.
    """
    if df is None or df.empty:
        return None

    tz_df = df.copy()
    if tz_df.index.tz is None:
        tz_df.index = tz_df.index.tz_localize(tz)
    else:
        tz_df.index = tz_df.index.tz_convert(tz)

    weekly = (
        tz_df.resample("W-FRI")
        .agg({"High": "max", "Low": "min", "Close": "last"})
        .dropna()
    )
    if len(weekly) < 2:
        return None

    prior = weekly.iloc[-2]
    return _pivot_levels(float(prior["High"]), float(prior["Low"]), float(prior["Close"]))
