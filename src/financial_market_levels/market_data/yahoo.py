from __future__ import annotations

import pandas as pd
import yfinance as yf


def fetch_history(
    symbol: str,
    *,
    lookback_days: int = 180,
    tz: str = "America/New_York",
) -> pd.DataFrame:
    """Return daily OHLCV for `symbol` covering the last `lookback_days`.

    Returns an empty DataFrame on no-data; callers should record `status='no_data'`
    rather than raising.
    """
    period = "6mo" if lookback_days <= 190 else "1y"
    df = yf.Ticker(symbol).history(period=period, interval="1d", actions=False)
    if df is None or df.empty:
        return pd.DataFrame()

    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    if df.index.tz is None:
        df.index = df.index.tz_localize(tz)
    else:
        df.index = df.index.tz_convert(tz)

    cutoff = pd.Timestamp.now(tz=tz) - pd.Timedelta(days=lookback_days)
    return df.loc[df.index >= cutoff]


def get_company_name(symbol: str) -> str | None:
    try:
        info = yf.Ticker(symbol).info
    except Exception:
        return None
    return info.get("longName") or info.get("shortName")
