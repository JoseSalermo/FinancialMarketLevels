from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from financial_market_levels.analysis.clustering import cluster_levels
from financial_market_levels.analysis.pivots import daily_pivots, weekly_pivots
from financial_market_levels.analysis.swings import find_swing_points


_LEVEL_COLUMNS = [
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


@dataclass(frozen=True)
class AnalysisSettings:
    lookback_days: int = 180
    swing_window: int = 5
    cluster_tolerance_pct: float = 0.5
    touch_tolerance_pct: float = 0.5
    proximity_pct: float = 10.0
    max_levels_per_ticker: int = 6
    include_pivot_daily: bool = True
    include_pivot_weekly: bool = True
    timezone: str = "America/New_York"


def _empty_levels_df() -> pd.DataFrame:
    return pd.DataFrame(columns=_LEVEL_COLUMNS)


def _count_touches(df: pd.DataFrame, level: float, tolerance_pct: float) -> int:
    tol = tolerance_pct / 100.0
    upper = level * (1 + tol)
    lower = level * (1 - tol)
    touched = (df["Low"] <= upper) & (df["High"] >= lower)
    return int(touched.sum())


def compute_levels(
    df: pd.DataFrame,
    last_close: float,
    settings: AnalysisSettings,
) -> pd.DataFrame:
    """Build the ranked S/R DataFrame for one ticker.

    Output columns match the `support_resistance_levels` table.
    """
    if df is None or df.empty or last_close <= 0:
        return _empty_levels_df()

    candidates: list[dict] = []

    swings = find_swing_points(df, window=settings.swing_window)
    clusters = cluster_levels(swings, tolerance_pct=settings.cluster_tolerance_pct)
    for _, c in clusters.iterrows():
        last_touch = c["last_touch_date"]
        candidates.append(
            {
                "level_value": float(c["level_value"]),
                "method": "swing",
                "pivot_role": None,
                "cluster_size": int(c["cluster_size"]),
                "last_touch_date": (
                    last_touch.isoformat()
                    if hasattr(last_touch, "isoformat")
                    else (str(last_touch) if last_touch is not None else None)
                ),
            }
        )

    if settings.include_pivot_daily:
        daily = daily_pivots(df)
        if daily is not None:
            for role, value in daily.items():
                candidates.append(
                    {
                        "level_value": float(value),
                        "method": "pivot_daily",
                        "pivot_role": role,
                        "cluster_size": 1,
                        "last_touch_date": None,
                    }
                )

    if settings.include_pivot_weekly:
        weekly = weekly_pivots(df, tz=settings.timezone)
        if weekly is not None:
            for role, value in weekly.items():
                candidates.append(
                    {
                        "level_value": float(value),
                        "method": "pivot_weekly",
                        "pivot_role": role,
                        "cluster_size": 1,
                        "last_touch_date": None,
                    }
                )

    if not candidates:
        return _empty_levels_df()

    cdf = pd.DataFrame(candidates)
    cdf["distance_abs"] = (cdf["level_value"] - last_close).abs()
    cdf["distance_pct"] = (cdf["level_value"] - last_close) / last_close * 100.0

    cdf = cdf[cdf["distance_pct"].abs() <= settings.proximity_pct].copy()
    if cdf.empty:
        return _empty_levels_df()

    cdf["touch_count"] = cdf["level_value"].apply(
        lambda lv: _count_touches(df, lv, settings.touch_tolerance_pct)
    )
    cdf["strength_score"] = cdf["touch_count"]

    cdf["level_type"] = [
        "resistance" if v > last_close else "support" for v in cdf["level_value"]
    ]

    cdf = cdf.sort_values(
        ["level_type", "distance_abs", "strength_score"],
        ascending=[True, True, False],
        kind="stable",
    ).reset_index(drop=True)

    cdf["rank_in_ticker"] = cdf.groupby("level_type").cumcount() + 1
    cdf = cdf[cdf["rank_in_ticker"] <= settings.max_levels_per_ticker].copy()

    return cdf[_LEVEL_COLUMNS].reset_index(drop=True)
