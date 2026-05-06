# FinancialMarketLevels

Support/resistance level finder for the trending tickers produced by
[FinancialMarketReport](https://github.com/JoseSalermo/FinancialMarketReport).

## What it does

1. Reads the latest list of trending tickers directly from FinancialMarketReport's
   SQLite database (read-only).
2. Fetches ~6 months of daily OHLCV per ticker via `yfinance`.
3. Computes nearby support/resistance levels using:
   - **Swing-point clustering** — local highs/lows over a rolling window, then
     clustered by price tolerance.
   - **Classic pivot points** — daily and weekly P/R1/R2/S1/S2 from the prior
     period's H/L/C.
4. Filters to levels within ±10% of current price, scores them by touch count,
   ranks them by proximity.
5. Presents results in a Flask web UI with annotated candlestick charts.

No scheduler, no email — manual "Refresh" only.

## Local development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
financial-market-levels --help
financial-market-levels init-db
financial-market-levels serve --port 8083
```

## Docker

```bash
cp .env.example .env
docker compose up -d
# UI at http://localhost:8083
```

The container expects the sibling FinancialMarketReport data directory mounted
read-only at `/app/source_data`. See `docker-compose.yml`.

## Layout

- `src/financial_market_levels/analysis/` — swing detection, clustering, pivots
- `src/financial_market_levels/market_data/yahoo.py` — yfinance wrapper
- `src/financial_market_levels/source_db/reader.py` — read-only sibling DB adapter
- `src/financial_market_levels/storage/` — own SQLite schema + repository
- `src/financial_market_levels/runner.py` — pipeline orchestrator
- `src/financial_market_levels/web/` — Flask UI
- `tests/` — pytest with synthetic OHLCV fixtures
