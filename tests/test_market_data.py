from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd

from financial_market_levels.market_data import yahoo as yahoo_mod
from financial_market_levels.market_data.yahoo import fetch_history, get_company_name


def _fake_history(n_days: int = 200, tz: str = "America/New_York") -> pd.DataFrame:
    end = pd.Timestamp.now(tz=tz).normalize()
    idx = pd.date_range(end=end, periods=n_days, freq="B")
    return pd.DataFrame(
        {
            "Open": [100.0] * n_days,
            "High": [105.0] * n_days,
            "Low": [95.0] * n_days,
            "Close": [100.0] * n_days,
            "Volume": [1_000_000.0] * n_days,
            "Dividends": [0.0] * n_days,
            "Stock Splits": [0.0] * n_days,
        },
        index=idx,
    )


def test_fetch_history_uses_6mo_for_short_lookback() -> None:
    fake = _fake_history(150)
    with patch.object(yahoo_mod, "yf") as mock_yf:
        mock_yf.Ticker.return_value.history.return_value = fake
        fetch_history("AAPL", lookback_days=180)

    history_call = mock_yf.Ticker.return_value.history
    assert history_call.call_args.kwargs["period"] == "6mo"
    assert history_call.call_args.kwargs["interval"] == "1d"
    assert history_call.call_args.kwargs["actions"] is False


def test_fetch_history_uses_1y_for_long_lookback() -> None:
    fake = _fake_history(300)
    with patch.object(yahoo_mod, "yf") as mock_yf:
        mock_yf.Ticker.return_value.history.return_value = fake
        fetch_history("AAPL", lookback_days=365)

    assert mock_yf.Ticker.return_value.history.call_args.kwargs["period"] == "1y"


def test_fetch_history_drops_extra_columns() -> None:
    fake = _fake_history(100)
    with patch.object(yahoo_mod, "yf") as mock_yf:
        mock_yf.Ticker.return_value.history.return_value = fake
        out = fetch_history("AAPL", lookback_days=90)

    assert list(out.columns) == ["Open", "High", "Low", "Close", "Volume"]


def test_fetch_history_filters_by_lookback_window() -> None:
    fake = _fake_history(200)
    with patch.object(yahoo_mod, "yf") as mock_yf:
        mock_yf.Ticker.return_value.history.return_value = fake
        out = fetch_history("AAPL", lookback_days=30)

    # 30 calendar days ≈ ~22 business days; allow slack for boundary effects.
    assert len(out) <= 32


def test_fetch_history_returns_tz_aware_index() -> None:
    fake = _fake_history(60)
    with patch.object(yahoo_mod, "yf") as mock_yf:
        mock_yf.Ticker.return_value.history.return_value = fake
        out = fetch_history("AAPL", lookback_days=60, tz="America/New_York")

    assert out.index.tz is not None
    assert str(out.index.tz) == "America/New_York"


def test_fetch_history_empty_returns_empty() -> None:
    with patch.object(yahoo_mod, "yf") as mock_yf:
        mock_yf.Ticker.return_value.history.return_value = pd.DataFrame()
        out = fetch_history("ZZZZ", lookback_days=30)
    assert out.empty


def test_fetch_history_none_returns_empty() -> None:
    with patch.object(yahoo_mod, "yf") as mock_yf:
        mock_yf.Ticker.return_value.history.return_value = None
        out = fetch_history("ZZZZ", lookback_days=30)
    assert out.empty


def test_fetch_history_localizes_naive_index() -> None:
    n = 60
    naive_idx = pd.date_range(end=pd.Timestamp.now().normalize(), periods=n, freq="B")
    fake = pd.DataFrame(
        {
            "Open":  [100.0] * n,
            "High":  [105.0] * n,
            "Low":   [95.0] * n,
            "Close": [100.0] * n,
            "Volume": [1_000_000.0] * n,
        },
        index=naive_idx,
    )
    with patch.object(yahoo_mod, "yf") as mock_yf:
        mock_yf.Ticker.return_value.history.return_value = fake
        out = fetch_history("AAPL", lookback_days=60, tz="America/New_York")

    assert out.index.tz is not None
    assert str(out.index.tz) == "America/New_York"


def test_get_company_name_prefers_long_name() -> None:
    with patch.object(yahoo_mod, "yf") as mock_yf:
        mock_yf.Ticker.return_value.info = {"longName": "Apple Inc.", "shortName": "Apple"}
        assert get_company_name("AAPL") == "Apple Inc."


def test_get_company_name_falls_back_to_short_name() -> None:
    with patch.object(yahoo_mod, "yf") as mock_yf:
        mock_yf.Ticker.return_value.info = {"shortName": "Apple"}
        assert get_company_name("AAPL") == "Apple"


def test_get_company_name_returns_none_on_error() -> None:
    with patch.object(yahoo_mod, "yf") as mock_yf:
        mock_yf.Ticker.side_effect = RuntimeError("network down")
        assert get_company_name("AAPL") is None
