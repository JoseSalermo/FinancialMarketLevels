from __future__ import annotations

import numpy as np
import pandas as pd

from financial_market_levels.analysis.levels import AnalysisSettings, compute_levels


def _make_synthetic_df(n: int = 180, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    base = 100 + np.cumsum(rng.normal(0, 0.5, size=n))
    highs = base + np.abs(rng.normal(1, 0.3, size=n))
    lows = base - np.abs(rng.normal(1, 0.3, size=n))
    closes = base + rng.normal(0, 0.3, size=n)
    opens = closes + rng.normal(0, 0.3, size=n)
    idx = pd.date_range("2025-09-01", periods=n, freq="B")
    return pd.DataFrame(
        {"Open": opens, "High": highs, "Low": lows, "Close": closes, "Volume": [1_000_000] * n},
        index=idx,
    )


def test_compute_levels_end_to_end() -> None:
    df = _make_synthetic_df()
    last_close = float(df["Close"].iloc[-1])
    settings = AnalysisSettings()

    levels = compute_levels(df, last_close, settings)

    assert not levels.empty
    assert (levels["distance_pct"].abs() <= settings.proximity_pct).all()

    counts = levels.groupby("level_type").size()
    assert (counts <= settings.max_levels_per_ticker).all()

    for _, group in levels.groupby("level_type"):
        ranks = group["rank_in_ticker"].tolist()
        assert ranks == list(range(1, len(ranks) + 1))
        distances = group["distance_abs"].tolist()
        assert distances == sorted(distances)


def test_classification_against_last_close() -> None:
    df = _make_synthetic_df()
    last_close = float(df["Close"].iloc[-1])
    levels = compute_levels(df, last_close, AnalysisSettings())

    supports = levels[levels["level_type"] == "support"]
    resistances = levels[levels["level_type"] == "resistance"]
    assert (supports["level_value"] <= last_close).all()
    assert (resistances["level_value"] > last_close).all()


def test_pivot_toggles_off_excludes_pivots() -> None:
    df = _make_synthetic_df()
    last_close = float(df["Close"].iloc[-1])

    s_off = AnalysisSettings(include_pivot_daily=False, include_pivot_weekly=False)
    levels_off = compute_levels(df, last_close, s_off)
    if not levels_off.empty:
        assert set(levels_off["method"]) <= {"swing"}

    s_on = AnalysisSettings(include_pivot_daily=True, include_pivot_weekly=True)
    levels_on = compute_levels(df, last_close, s_on)
    methods_on = set(levels_on["method"])
    assert "swing" in methods_on or "pivot_daily" in methods_on or "pivot_weekly" in methods_on


def test_proximity_filter_narrow_vs_wide() -> None:
    df = _make_synthetic_df(seed=1)
    last_close = float(df["Close"].iloc[-1])

    narrow = compute_levels(df, last_close, AnalysisSettings(proximity_pct=1.0))
    wide = compute_levels(df, last_close, AnalysisSettings(proximity_pct=50.0))

    if not narrow.empty:
        assert (narrow["distance_pct"].abs() <= 1.0).all()
    assert len(wide) >= len(narrow)


def test_max_levels_per_ticker_respected() -> None:
    df = _make_synthetic_df(seed=7)
    last_close = float(df["Close"].iloc[-1])
    settings = AnalysisSettings(max_levels_per_ticker=2)

    levels = compute_levels(df, last_close, settings)
    counts = levels.groupby("level_type").size()
    assert (counts <= 2).all()


def test_strength_score_equals_touch_count() -> None:
    df = _make_synthetic_df()
    last_close = float(df["Close"].iloc[-1])
    levels = compute_levels(df, last_close, AnalysisSettings())
    assert (levels["strength_score"] == levels["touch_count"]).all()


def test_empty_df_returns_empty_levels() -> None:
    out = compute_levels(pd.DataFrame(), 100.0, AnalysisSettings())
    assert out.empty
    assert list(out.columns) == [
        "level_type",
        "level_value",
        "method",
        "pivot_role",
        "strength_score",
        "touch_count",
        "cluster_size",
        "distance_pct",
        "distance_abs",
        "rank_in_ticker",
        "last_touch_date",
    ]


def test_pivot_role_set_for_pivots_only() -> None:
    df = _make_synthetic_df()
    last_close = float(df["Close"].iloc[-1])
    levels = compute_levels(df, last_close, AnalysisSettings())

    swing_rows = levels[levels["method"] == "swing"]
    pivot_rows = levels[levels["method"].isin(["pivot_daily", "pivot_weekly"])]
    if not swing_rows.empty:
        assert swing_rows["pivot_role"].isna().all()
    if not pivot_rows.empty:
        assert pivot_rows["pivot_role"].isin(["P", "R1", "R2", "S1", "S2"]).all()
