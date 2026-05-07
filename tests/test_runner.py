from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from financial_market_levels import runner as runner_mod
from financial_market_levels.runner import LevelsRunResult, run_levels
from financial_market_levels.source_db.reader import SourceDBError
from financial_market_levels.storage.repository import (
    get_levels_run,
    list_levels_for_ticker,
    list_run_tickers,
)


SIBLING_SCHEMA = """
CREATE TABLE report_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    params_json TEXT NOT NULL,
    error_message TEXT,
    ticker_count INTEGER NOT NULL DEFAULT 0,
    email_sent INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE ticker_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    source TEXT,
    price REAL,
    change_value REAL,
    changes_percentage REAL,
    volume REAL,
    company_name TEXT,
    row_json TEXT NOT NULL
);
"""


def _make_source_db(path: Path, *, symbols: list[str], status: str = "succeeded") -> int:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(SIBLING_SCHEMA)
        cur = conn.execute(
            "INSERT INTO report_runs (started_at, status, params_json) VALUES (?, ?, '{}')",
            ("2026-05-06T10:00:00Z", status),
        )
        run_id = int(cur.lastrowid)
        for sym in symbols:
            conn.execute(
                """
                INSERT INTO ticker_candidates
                    (run_id, symbol, source, price, company_name, row_json)
                VALUES (?, ?, 'gainers', 100.0, ?, '{}')
                """,
                (run_id, sym, f"{sym} Corp"),
            )
        conn.commit()
        return run_id
    finally:
        conn.close()


def _make_config(tmp_path: Path, *, source_db: Path) -> Path:
    cfg = tmp_path / "c.yaml"
    cfg.write_text(
        f"analysis:\n"
        f"  lookback_days: 60\n"
        f"  timezone: America/New_York\n"
        f"source:\n"
        f"  source_db_path: {source_db}\n"
        f"  source_run_id: null\n",
        encoding="utf-8",
    )
    return cfg


def _ohlcv(n: int = 60, base: float = 100.0, tz: str = "America/New_York") -> pd.DataFrame:
    end = pd.Timestamp.now(tz=tz).normalize()
    idx = pd.date_range(end=end, periods=n, freq="B")
    return pd.DataFrame(
        {
            "Open":   [base + i * 0.1 for i in range(n)],
            "High":   [base + 1 + i * 0.1 for i in range(n)],
            "Low":    [base - 1 + i * 0.1 for i in range(n)],
            "Close":  [base + 0.5 + i * 0.1 for i in range(n)],
            "Volume": [1_000_000] * n,
        },
        index=idx,
    )


def test_run_levels_happy_path(tmp_path: Path) -> None:
    src = tmp_path / "fmr.sqlite3"
    _make_source_db(src, symbols=["AAA", "BBB"])
    cfg = _make_config(tmp_path, source_db=src)
    db = tmp_path / "fml.sqlite3"
    charts = tmp_path / "charts"

    fake_chart = tmp_path / "fake.png"
    fake_chart.write_bytes(b"png")

    with patch.object(runner_mod, "fetch_history", return_value=_ohlcv()), \
         patch.object(runner_mod, "save_levels_chart", return_value=fake_chart):
        result = run_levels(
            config_path=cfg,
            output_dir=charts,
            db_path=db,
            trigger="test",
        )

    assert isinstance(result, LevelsRunResult)
    assert result.ticker_count == 2
    assert result.levels_count >= 0  # depends on synthetic data hitting proximity filter

    run_row = get_levels_run(db, result.run_id)
    assert run_row is not None
    assert run_row["status"] == "succeeded"
    assert run_row["ticker_count"] == 2
    assert run_row["source_run_id"] is not None  # resolved from source DB

    tickers = list_run_tickers(db, run_id=result.run_id)
    assert sorted(t["symbol"] for t in tickers) == ["AAA", "BBB"]
    assert all(t["status"] == "ok" for t in tickers)
    assert all(t["bar_count"] > 0 for t in tickers)
    assert all(t["chart_path"] == str(fake_chart) for t in tickers)


def test_run_levels_no_data_records_status_no_data(tmp_path: Path) -> None:
    src = tmp_path / "fmr.sqlite3"
    _make_source_db(src, symbols=["XYZ"])
    cfg = _make_config(tmp_path, source_db=src)
    db = tmp_path / "fml.sqlite3"
    charts = tmp_path / "charts"

    with patch.object(runner_mod, "fetch_history", return_value=pd.DataFrame()), \
         patch.object(runner_mod, "save_levels_chart") as mock_chart:
        result = run_levels(
            config_path=cfg,
            output_dir=charts,
            db_path=db,
        )

    mock_chart.assert_not_called()
    tickers = list_run_tickers(db, run_id=result.run_id)
    assert len(tickers) == 1
    assert tickers[0]["status"] == "no_data"
    assert tickers[0]["bar_count"] == 0


def test_run_levels_per_ticker_error_isolates(tmp_path: Path) -> None:
    src = tmp_path / "fmr.sqlite3"
    _make_source_db(src, symbols=["AAA", "BBB"])
    cfg = _make_config(tmp_path, source_db=src)
    db = tmp_path / "fml.sqlite3"
    charts = tmp_path / "charts"

    fake_chart = tmp_path / "ok.png"
    fake_chart.write_bytes(b"png")

    def history_side_effect(symbol: str, **_kw) -> pd.DataFrame:
        if symbol == "AAA":
            raise RuntimeError("yfinance exploded")
        return _ohlcv()

    with patch.object(runner_mod, "fetch_history", side_effect=history_side_effect), \
         patch.object(runner_mod, "save_levels_chart", return_value=fake_chart):
        result = run_levels(
            config_path=cfg,
            output_dir=charts,
            db_path=db,
        )

    run_row = get_levels_run(db, result.run_id)
    assert run_row["status"] == "succeeded"

    tickers = {t["symbol"]: t for t in list_run_tickers(db, run_id=result.run_id)}
    assert tickers["AAA"]["status"] == "error"
    assert "yfinance exploded" in (tickers["AAA"]["error_message"] or "")
    assert tickers["BBB"]["status"] == "ok"


def test_run_levels_top_level_failure_marks_run_failed(tmp_path: Path) -> None:
    src = tmp_path / "fmr.sqlite3"
    # Status='running' means no succeeded run → SourceDBError
    _make_source_db(src, symbols=["AAA"], status="running")
    cfg = _make_config(tmp_path, source_db=src)
    db = tmp_path / "fml.sqlite3"
    charts = tmp_path / "charts"

    with pytest.raises(SourceDBError):
        run_levels(config_path=cfg, output_dir=charts, db_path=db)

    # Find the (failed) run by scanning the table
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT status, error_message FROM levels_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert row["status"] == "failed"
    assert "SourceDBError" in (row["error_message"] or "")


def test_run_levels_explicit_source_run_id_overrides_setting(tmp_path: Path) -> None:
    src = tmp_path / "fmr.sqlite3"
    source_run = _make_source_db(src, symbols=["AAA"])
    cfg = _make_config(tmp_path, source_db=src)
    db = tmp_path / "fml.sqlite3"
    charts = tmp_path / "charts"

    fake_chart = tmp_path / "ok.png"
    fake_chart.write_bytes(b"png")

    with patch.object(runner_mod, "fetch_history", return_value=_ohlcv()), \
         patch.object(runner_mod, "save_levels_chart", return_value=fake_chart):
        result = run_levels(
            config_path=cfg,
            output_dir=charts,
            db_path=db,
            source_run_id=source_run,
        )

    assert result.source_run_id == source_run
    run_row = get_levels_run(db, result.run_id)
    assert run_row["source_run_id"] == source_run


def test_run_levels_persists_levels_rows(tmp_path: Path) -> None:
    """Smoke check that compute_levels output makes it into support_resistance_levels."""
    src = tmp_path / "fmr.sqlite3"
    _make_source_db(src, symbols=["AAA"])
    cfg = _make_config(tmp_path, source_db=src)
    db = tmp_path / "fml.sqlite3"
    charts = tmp_path / "charts"

    fake_chart = tmp_path / "ok.png"
    fake_chart.write_bytes(b"png")

    # 180 bars of synthetic data so swings + pivots can fire
    df = _ohlcv(n=180)
    with patch.object(runner_mod, "fetch_history", return_value=df), \
         patch.object(runner_mod, "save_levels_chart", return_value=fake_chart):
        result = run_levels(
            config_path=cfg,
            output_dir=charts,
            db_path=db,
        )

    rows = list_levels_for_ticker(db, run_id=result.run_id, symbol="AAA")
    # Even if no swings cluster within proximity, daily/weekly pivots may add rows.
    # Either way, the count we recorded on the run must equal what's persisted.
    assert result.levels_count == len(rows)


def test_run_levels_creates_charts_dir(tmp_path: Path) -> None:
    src = tmp_path / "fmr.sqlite3"
    _make_source_db(src, symbols=["AAA"])
    cfg = _make_config(tmp_path, source_db=src)
    db = tmp_path / "fml.sqlite3"
    charts = tmp_path / "nested" / "charts"

    fake_chart = tmp_path / "ok.png"
    fake_chart.write_bytes(b"png")

    with patch.object(runner_mod, "fetch_history", return_value=_ohlcv()), \
         patch.object(runner_mod, "save_levels_chart", return_value=fake_chart):
        result = run_levels(
            config_path=cfg,
            output_dir=charts,
            db_path=db,
        )

    expected = charts / str(result.run_id)
    assert expected.is_dir()
