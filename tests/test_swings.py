from __future__ import annotations

import pandas as pd

from financial_market_levels.analysis.swings import find_swing_points


def _make_df(highs: list[float], lows: list[float]) -> pd.DataFrame:
    n = len(highs)
    closes = [(h + l) / 2 for h, l in zip(highs, lows)]
    idx = pd.date_range("2026-01-05", periods=n, freq="B")
    return pd.DataFrame(
        {
            "Open": closes,
            "High": highs,
            "Low": lows,
            "Close": closes,
            "Volume": [1_000] * n,
        },
        index=idx,
    )


def test_known_peak_and_trough_recovered() -> None:
    # 11 bars, w=2 → swing candidates at indices 2..8
    # peak at i=6 (high=109), trough at i=5 (low=95)
    highs = [110, 108, 106, 104, 105, 107, 109, 107, 105, 103, 101]
    lows = [105, 103, 101, 99, 97, 95, 97, 99, 101, 103, 105]
    df = _make_df(highs, lows)

    swings = find_swing_points(df, window=2)
    high_swings = swings[swings["kind"] == "high"]
    low_swings = swings[swings["kind"] == "low"]

    assert len(high_swings) == 1
    assert high_swings.iloc[0]["price"] == 109
    assert high_swings.iloc[0]["date"] == df.index[6]

    assert len(low_swings) == 1
    assert low_swings.iloc[0]["price"] == 95
    assert low_swings.iloc[0]["date"] == df.index[5]


def test_flat_top_picks_rightmost() -> None:
    # Two adjacent equal highs at i=4 and i=5 (both 110); w=2.
    # The asymmetric loose-prior strict-next rule picks i=5.
    highs = [100, 102, 105, 108, 110, 110, 108, 105, 102, 100, 98]
    lows = [95, 97, 100, 103, 105, 105, 103, 100, 97, 95, 92]
    df = _make_df(highs, lows)

    swings = find_swing_points(df, window=2)
    high_swings = swings[swings["kind"] == "high"]

    assert len(high_swings) == 1
    assert high_swings.iloc[0]["price"] == 110
    assert high_swings.iloc[0]["date"] == df.index[5]


def test_flat_bottom_picks_rightmost() -> None:
    # Two adjacent equal lows at i=4 and i=5 (both 90); w=2.
    highs = [110, 108, 105, 102, 100, 100, 102, 105, 108, 110, 112]
    lows = [105, 102, 98, 95, 90, 90, 95, 98, 102, 105, 108]
    df = _make_df(highs, lows)

    swings = find_swing_points(df, window=2)
    low_swings = swings[swings["kind"] == "low"]

    assert len(low_swings) == 1
    assert low_swings.iloc[0]["price"] == 90
    assert low_swings.iloc[0]["date"] == df.index[5]


def test_short_input_returns_empty() -> None:
    df = _make_df([100, 101, 102], [95, 96, 97])
    out = find_swing_points(df, window=5)
    assert out.empty
    assert list(out.columns) == ["date", "price", "kind"]


def test_empty_input_returns_empty() -> None:
    df = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    out = find_swing_points(df, window=5)
    assert out.empty


def test_results_sorted_by_date() -> None:
    # 21 bars, w=3, multiple alternating peaks and troughs
    highs = [
        100, 102, 105, 108, 110, 108, 105,
        103, 102, 104, 107, 110, 113, 110,
        108, 105, 103, 106, 109, 112, 115,
    ]
    lows = [h - 5 for h in highs]
    df = _make_df(highs, lows)

    out = find_swing_points(df, window=3)
    assert not out.empty
    dates = out["date"].tolist()
    assert dates == sorted(dates)
