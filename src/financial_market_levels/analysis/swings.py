from __future__ import annotations

import pandas as pd


_EMPTY = pd.DataFrame(columns=["date", "price", "kind"])


def find_swing_points(df: pd.DataFrame, *, window: int = 5) -> pd.DataFrame:
    """Return one row per detected swing high/low.

    A bar i is a swing high if High[i] >= max(High[i-w..i-1]) and High[i] >
    max(High[i+1..i+w]). The asymmetric loose-prior / strict-next rule means
    the rightmost bar of a flat top is the swing — equivalent rule for lows.
    """
    if df is None or df.empty or window < 1:
        return _EMPTY.copy()
    if len(df) < 2 * window + 1:
        return _EMPTY.copy()

    high = df["High"]
    low = df["Low"]

    prior_max = high.shift(1).rolling(window).max()
    next_max = high.shift(-window).rolling(window).max()
    is_swing_high = (high >= prior_max) & (high > next_max)

    prior_min = low.shift(1).rolling(window).min()
    next_min = low.shift(-window).rolling(window).min()
    is_swing_low = (low <= prior_min) & (low < next_min)

    rows: list[tuple] = []
    for ts, val in high[is_swing_high.fillna(False)].items():
        rows.append((ts, float(val), "high"))
    for ts, val in low[is_swing_low.fillna(False)].items():
        rows.append((ts, float(val), "low"))

    if not rows:
        return _EMPTY.copy()

    out = pd.DataFrame(rows, columns=["date", "price", "kind"])
    return out.sort_values("date", kind="stable").reset_index(drop=True)
