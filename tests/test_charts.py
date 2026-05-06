from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from financial_market_levels.reporting.charts import save_levels_chart


def _make_ohlcv(n: int = 60, tz: str = "America/New_York") -> pd.DataFrame:
    end = pd.Timestamp.now(tz=tz).normalize()
    idx = pd.date_range(end=end, periods=n, freq="B")
    return pd.DataFrame(
        {
            "Open":   [100.0 + i * 0.1 for i in range(n)],
            "High":   [101.0 + i * 0.1 for i in range(n)],
            "Low":    [99.0 + i * 0.1 for i in range(n)],
            "Close":  [100.5 + i * 0.1 for i in range(n)],
            "Volume": [1_000_000] * n,
        },
        index=idx,
    )


def _sample_levels() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "level_type": "support",
                "level_value": 100.0,
                "method": "swing",
                "pivot_role": None,
                "strength_score": 4,
                "touch_count": 4,
                "cluster_size": 3,
                "distance_pct": -2.0,
                "distance_abs": 2.0,
                "rank_in_ticker": 1,
                "last_touch_date": "2026-04-15",
            },
            {
                "level_type": "resistance",
                "level_value": 110.0,
                "method": "pivot_daily",
                "pivot_role": "R1",
                "strength_score": 2,
                "touch_count": 2,
                "cluster_size": 1,
                "distance_pct": 8.0,
                "distance_abs": 8.0,
                "rank_in_ticker": 1,
                "last_touch_date": None,
            },
        ]
    )


def test_save_levels_chart_creates_png(tmp_path: Path) -> None:
    df = _make_ohlcv()
    levels = _sample_levels()
    out = save_levels_chart("AAPL", df, levels, tmp_path)
    assert out.exists()
    assert out.parent == tmp_path
    assert out.name == "AAPL.png"
    assert out.stat().st_size > 1000


def test_save_levels_chart_works_without_levels(tmp_path: Path) -> None:
    df = _make_ohlcv()
    out = save_levels_chart("AAPL", df, pd.DataFrame(), tmp_path)
    assert out.exists()
    assert out.stat().st_size > 1000


def test_save_levels_chart_works_with_none_levels(tmp_path: Path) -> None:
    df = _make_ohlcv()
    out = save_levels_chart("AAPL", df, None, tmp_path)
    assert out.exists()


def test_save_levels_chart_empty_df_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="empty"):
        save_levels_chart("AAPL", pd.DataFrame(), pd.DataFrame(), tmp_path)


def test_save_levels_chart_localizes_naive_index(tmp_path: Path) -> None:
    n = 40
    naive_idx = pd.date_range(end=pd.Timestamp.now().normalize(), periods=n, freq="B")
    df = pd.DataFrame(
        {
            "Open":   [100.0 + i * 0.1 for i in range(n)],
            "High":   [101.0 + i * 0.1 for i in range(n)],
            "Low":    [99.0 + i * 0.1 for i in range(n)],
            "Close":  [100.5 + i * 0.1 for i in range(n)],
            "Volume": [1_000_000] * n,
        },
        index=naive_idx,
    )
    out = save_levels_chart("AAPL", df, _sample_levels(), tmp_path)
    assert out.exists()


def test_save_levels_chart_creates_output_dir(tmp_path: Path) -> None:
    df = _make_ohlcv()
    nested = tmp_path / "charts" / "run-7"
    out = save_levels_chart("AAPL", df, _sample_levels(), nested)
    assert nested.is_dir()
    assert out.exists()
