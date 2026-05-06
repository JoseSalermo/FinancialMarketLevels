from __future__ import annotations

import pandas as pd


_EMPTY = pd.DataFrame(columns=["level_value", "cluster_size", "last_touch_date"])


def cluster_levels(swings_df: pd.DataFrame, *, tolerance_pct: float = 0.5) -> pd.DataFrame:
    """Greedy single-pass clustering of swing prices.

    Sort prices ascending, start a cluster, and absorb each next price while
    its distance from the running-mean anchor is within `tolerance_pct`.
    """
    if swings_df is None or swings_df.empty:
        return _EMPTY.copy()

    tol = tolerance_pct / 100.0
    sorted_df = swings_df.sort_values("price", kind="stable").reset_index(drop=True)

    clusters: list[dict] = []
    prices: list[float] = []
    dates: list = []

    def flush() -> None:
        if not prices:
            return
        anchor = sum(prices) / len(prices)
        clusters.append(
            {
                "level_value": float(anchor),
                "cluster_size": len(prices),
                "last_touch_date": max(dates),
            }
        )

    for _, row in sorted_df.iterrows():
        price = float(row["price"])
        date = row["date"]
        if not prices:
            prices.append(price)
            dates.append(date)
            continue
        anchor = sum(prices) / len(prices)
        if anchor > 0 and (price - anchor) / anchor <= tol:
            prices.append(price)
            dates.append(date)
        else:
            flush()
            prices = [price]
            dates = [date]
    flush()

    if not clusters:
        return _EMPTY.copy()
    return pd.DataFrame(clusters)
