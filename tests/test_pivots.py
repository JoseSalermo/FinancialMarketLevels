from __future__ import annotations

import pandas as pd

from financial_market_levels.analysis.pivots import daily_pivots, weekly_pivots


def test_daily_pivots_canonical_example() -> None:
    df = pd.DataFrame(
        {"Open": [95], "High": [110], "Low": [90], "Close": [100], "Volume": [1000]},
        index=pd.date_range("2026-01-02", periods=1),
    )
    p = daily_pivots(df)
    assert p is not None
    assert p["P"] == 100
    assert p["R1"] == 110
    assert p["R2"] == 120
    assert p["S1"] == 90
    assert p["S2"] == 80


def test_daily_pivots_uses_last_bar() -> None:
    df = pd.DataFrame(
        {
            "Open":   [50, 95],
            "High":   [55, 110],
            "Low":    [45, 90],
            "Close":  [50, 100],
            "Volume": [1000, 1000],
        },
        index=pd.date_range("2026-01-01", periods=2),
    )
    p = daily_pivots(df)
    assert p["P"] == 100  # uses second row, not first


def test_daily_pivots_empty_returns_none() -> None:
    assert daily_pivots(pd.DataFrame()) is None
    assert daily_pivots(None) is None


def _build_two_weeks() -> pd.DataFrame:
    # Week 1 (Jan 5-9, 2026, Mon-Fri): max H = 110, min L = 90, last C = 100
    week1_dates = pd.date_range("2026-01-05", periods=5, freq="B")
    week1 = pd.DataFrame(
        {
            "Open":   [95,  98, 102, 105, 100],
            "High":   [100, 105, 110, 108, 102],
            "Low":    [90,   93,  98,  95,  92],
            "Close":  [98,  102, 105, 100, 100],
            "Volume": [1000] * 5,
        },
        index=week1_dates,
    )
    # Week 2 (Jan 12-16, 2026): max H = 120, min L = 100, last C = 115
    week2_dates = pd.date_range("2026-01-12", periods=5, freq="B")
    week2 = pd.DataFrame(
        {
            "Open":   [101, 105, 110, 115, 113],
            "High":   [110, 115, 120, 118, 116],
            "Low":    [100, 103, 108, 110, 112],
            "Close":  [108, 112, 115, 116, 115],
            "Volume": [1000] * 5,
        },
        index=week2_dates,
    )
    return pd.concat([week1, week2])


def test_weekly_pivots_uses_prior_completed_week() -> None:
    df = _build_two_weeks()
    p = weekly_pivots(df, tz="America/New_York")
    assert p is not None
    # Week 1 HLC: H=110, L=90, C=100 → P=100, R1=110, S1=90, R2=120, S2=80
    assert p["P"] == 100
    assert p["R1"] == 110
    assert p["S1"] == 90
    assert p["R2"] == 120
    assert p["S2"] == 80


def test_weekly_pivots_returns_none_with_one_week() -> None:
    df = _build_two_weeks().iloc[:5]
    assert weekly_pivots(df) is None


def test_weekly_pivots_handles_tz_aware_index() -> None:
    df = _build_two_weeks()
    df.index = df.index.tz_localize("UTC")
    p = weekly_pivots(df, tz="America/New_York")
    assert p is not None
    assert p["P"] == 100


def test_weekly_pivots_empty_returns_none() -> None:
    assert weekly_pivots(pd.DataFrame()) is None
