from __future__ import annotations

import sqlite3
from pathlib import Path

from financial_market_levels.config import PROJECT_ROOT


DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "financial_market_levels.sqlite3"


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS levels_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
    params_json TEXT NOT NULL,
    error_message TEXT,
    source_run_id INTEGER,
    source_db_path TEXT,
    ticker_count INTEGER NOT NULL DEFAULT 0,
    levels_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS levels_run_tickers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES levels_runs(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    company_name TEXT,
    last_price REAL,
    last_bar_date TEXT,
    bar_count INTEGER NOT NULL DEFAULT 0,
    chart_path TEXT,
    status TEXT NOT NULL CHECK (status IN ('ok', 'no_data', 'error')),
    error_message TEXT,
    UNIQUE (run_id, symbol)
);

CREATE TABLE IF NOT EXISTS support_resistance_levels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES levels_runs(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    level_type TEXT NOT NULL CHECK (level_type IN ('support', 'resistance')),
    level_value REAL NOT NULL,
    method TEXT NOT NULL CHECK (method IN ('swing', 'pivot_daily', 'pivot_weekly')),
    pivot_role TEXT,
    strength_score INTEGER NOT NULL DEFAULT 0,
    touch_count INTEGER NOT NULL DEFAULT 0,
    cluster_size INTEGER NOT NULL DEFAULT 1,
    distance_pct REAL NOT NULL,
    distance_abs REAL NOT NULL,
    rank_in_ticker INTEGER NOT NULL,
    last_touch_date TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sr_run_symbol ON support_resistance_levels(run_id, symbol);
CREATE INDEX IF NOT EXISTS idx_sr_run_type   ON support_resistance_levels(run_id, level_type);
CREATE INDEX IF NOT EXISTS idx_lrt_run       ON levels_run_tickers(run_id);
"""


def resolve_db_path(path: str | Path | None = None) -> Path:
    return Path(path) if path else DEFAULT_DB_PATH


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    db_path = resolve_db_path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(path: str | Path | None = None) -> Path:
    db_path = resolve_db_path(path)
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
    return db_path
