from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from financial_market_levels.source_db.reader import (
    SourceDBError,
    connect_readonly,
    fetch_trending_tickers,
    get_latest_succeeded_run_id,
    list_ticker_candidates,
)


# Mirrors the relevant subset of FinancialMarketReport's schema. Kept inline
# rather than imported so this test does not depend on the sibling package.
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


def _seed_run(conn: sqlite3.Connection, *, status: str, started_at: str) -> int:
    cur = conn.execute(
        "INSERT INTO report_runs (started_at, status, params_json) VALUES (?, ?, '{}')",
        (started_at, status),
    )
    return int(cur.lastrowid)


def _seed_candidate(conn: sqlite3.Connection, *, run_id: int, symbol: str, source: str) -> None:
    conn.execute(
        """
        INSERT INTO ticker_candidates (run_id, symbol, source, price, company_name, row_json)
        VALUES (?, ?, ?, ?, ?, '{}')
        """,
        (run_id, symbol, source, 100.0, f"{symbol} Corp"),
    )


@pytest.fixture
def sibling_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "fmr.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SIBLING_SCHEMA)
    return db_path


def test_connect_readonly_rejects_writes(sibling_db: Path) -> None:
    with connect_readonly(sibling_db) as conn:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("INSERT INTO report_runs (started_at, status, params_json) VALUES ('x', 'running', '{}')")


def test_connect_readonly_missing_path_raises(tmp_path: Path) -> None:
    with pytest.raises(SourceDBError):
        connect_readonly(tmp_path / "does-not-exist.sqlite3")


def test_get_latest_succeeded_skips_running_and_failed(sibling_db: Path) -> None:
    with sqlite3.connect(sibling_db) as conn:
        _seed_run(conn, status="succeeded", started_at="2026-04-01T00:00:00Z")
        _seed_run(conn, status="failed",    started_at="2026-04-02T00:00:00Z")
        latest_succeeded = _seed_run(conn, status="succeeded", started_at="2026-04-03T00:00:00Z")
        _seed_run(conn, status="running",   started_at="2026-04-04T00:00:00Z")

    with connect_readonly(sibling_db) as conn:
        assert get_latest_succeeded_run_id(conn) == latest_succeeded


def test_get_latest_succeeded_none_when_empty(sibling_db: Path) -> None:
    with connect_readonly(sibling_db) as conn:
        assert get_latest_succeeded_run_id(conn) is None


def test_list_ticker_candidates_orders_by_source_then_symbol(sibling_db: Path) -> None:
    with sqlite3.connect(sibling_db) as conn:
        run_id = _seed_run(conn, status="succeeded", started_at="2026-04-01T00:00:00Z")
        _seed_candidate(conn, run_id=run_id, symbol="MSFT", source="actives")
        _seed_candidate(conn, run_id=run_id, symbol="AAPL", source="actives")
        _seed_candidate(conn, run_id=run_id, symbol="NVDA", source="gainers")

    with connect_readonly(sibling_db) as conn:
        rows = list_ticker_candidates(conn, run_id=run_id)
    assert [(r["source"], r["symbol"]) for r in rows] == [
        ("actives", "AAPL"),
        ("actives", "MSFT"),
        ("gainers", "NVDA"),
    ]


def test_fetch_trending_tickers_uses_latest_when_run_id_none(sibling_db: Path) -> None:
    with sqlite3.connect(sibling_db) as conn:
        old = _seed_run(conn, status="succeeded", started_at="2026-04-01T00:00:00Z")
        _seed_candidate(conn, run_id=old, symbol="OLD", source="actives")
        new = _seed_run(conn, status="succeeded", started_at="2026-04-02T00:00:00Z")
        _seed_candidate(conn, run_id=new, symbol="NEW", source="actives")

    run_id, tickers = fetch_trending_tickers(sibling_db)
    assert run_id == new
    assert [t["symbol"] for t in tickers] == ["NEW"]


def test_fetch_trending_tickers_explicit_run_id_overrides_latest(sibling_db: Path) -> None:
    with sqlite3.connect(sibling_db) as conn:
        old = _seed_run(conn, status="succeeded", started_at="2026-04-01T00:00:00Z")
        _seed_candidate(conn, run_id=old, symbol="OLD", source="actives")
        new = _seed_run(conn, status="succeeded", started_at="2026-04-02T00:00:00Z")
        _seed_candidate(conn, run_id=new, symbol="NEW", source="actives")

    run_id, tickers = fetch_trending_tickers(sibling_db, run_id=old)
    assert run_id == old
    assert [t["symbol"] for t in tickers] == ["OLD"]


def test_fetch_trending_tickers_unknown_run_id_raises(sibling_db: Path) -> None:
    with sqlite3.connect(sibling_db) as conn:
        _seed_run(conn, status="succeeded", started_at="2026-04-01T00:00:00Z")

    with pytest.raises(SourceDBError, match="run_id 9999"):
        fetch_trending_tickers(sibling_db, run_id=9999)


def test_fetch_trending_tickers_no_succeeded_runs_raises(sibling_db: Path) -> None:
    with sqlite3.connect(sibling_db) as conn:
        _seed_run(conn, status="failed", started_at="2026-04-01T00:00:00Z")

    with pytest.raises(SourceDBError, match="No succeeded"):
        fetch_trending_tickers(sibling_db)


def test_fetch_trending_tickers_missing_db_raises(tmp_path: Path) -> None:
    with pytest.raises(SourceDBError, match="Source DB not found"):
        fetch_trending_tickers(tmp_path / "missing.sqlite3")


def test_fetch_trending_tickers_returns_plain_dicts(sibling_db: Path) -> None:
    with sqlite3.connect(sibling_db) as conn:
        run_id = _seed_run(conn, status="succeeded", started_at="2026-04-01T00:00:00Z")
        _seed_candidate(conn, run_id=run_id, symbol="AAPL", source="actives")

    _, tickers = fetch_trending_tickers(sibling_db)
    assert isinstance(tickers, list)
    assert isinstance(tickers[0], dict)
    assert tickers[0]["symbol"] == "AAPL"
    assert tickers[0]["company_name"] == "AAPL Corp"
    assert "price" in tickers[0]
