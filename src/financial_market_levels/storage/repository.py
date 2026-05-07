from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from financial_market_levels.storage.db import connect, init_db


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _json_default(value: Any) -> str | int | float | bool | None:
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def to_json(value: Any) -> str:
    if is_dataclass(value):
        value = asdict(value)
    return json.dumps(value, default=_json_default, sort_keys=True)


def get_settings(db_path: str | Path | None) -> dict[str, str]:
    init_db(db_path)
    with connect(db_path) as conn:
        return {
            row["key"]: row["value"]
            for row in conn.execute("SELECT key, value FROM settings ORDER BY key")
        }


def update_settings(db_path: str | Path | None, values: dict[str, Any]) -> None:
    init_db(db_path)
    updated_at = utc_now_iso()
    with connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO settings (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            [(key, to_json(value), updated_at) for key, value in values.items()],
        )


def save_settings_snapshot(db_path: str | Path | None, *, settings: Any, updated_at: str) -> None:
    init_db(db_path)
    values = asdict(settings) if is_dataclass(settings) else settings
    if not isinstance(values, dict):
        raise TypeError("settings must be a dataclass or mapping")

    flattened: list[tuple[str, str, str]] = []

    def visit(prefix: str, value: Any) -> None:
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                child_prefix = f"{prefix}.{child_key}" if prefix else str(child_key)
                visit(child_prefix, child_value)
            return
        flattened.append((prefix, to_json(value), updated_at))

    visit("", values)

    with connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO settings (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            flattened,
        )


def create_levels_run(
    db_path: str | Path | None,
    *,
    started_at: str,
    params: Any,
    source_run_id: int | None = None,
    source_db_path: str | Path | None = None,
) -> int:
    init_db(db_path)
    with connect(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO levels_runs (
                started_at, status, params_json, source_run_id, source_db_path
            )
            VALUES (?, 'running', ?, ?, ?)
            """,
            (
                started_at,
                to_json(params),
                source_run_id,
                str(source_db_path) if source_db_path is not None else None,
            ),
        )
        return int(cursor.lastrowid)


def set_levels_run_source(
    db_path: str | Path | None,
    *,
    run_id: int,
    source_run_id: int | None,
) -> None:
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE levels_runs SET source_run_id = ? WHERE id = ?",
            (source_run_id, run_id),
        )


def reap_orphaned_running_runs(db_path: str | Path | None) -> int:
    """Mark any rows still status='running' as 'failed'. Used at app startup
    so a container restart mid-run doesn't leave stale rows that block the
    Run Now button forever. Returns the number of rows updated."""
    init_db(db_path)
    finished_at = utc_now_iso()
    with connect(db_path) as conn:
        cursor = conn.execute(
            """
            UPDATE levels_runs
            SET status = 'failed',
                finished_at = ?,
                error_message = ?
            WHERE status = 'running'
            """,
            (finished_at, "Container or process restarted while run was in progress."),
        )
        return int(cursor.rowcount or 0)


def finish_levels_run(
    db_path: str | Path | None,
    *,
    run_id: int,
    status: str,
    finished_at: str,
    ticker_count: int = 0,
    levels_count: int = 0,
    error_message: str | None = None,
) -> None:
    with connect(db_path) as conn:
        conn.execute(
            """
            UPDATE levels_runs
            SET finished_at = ?,
                status = ?,
                error_message = ?,
                ticker_count = ?,
                levels_count = ?
            WHERE id = ?
            """,
            (finished_at, status, error_message, ticker_count, levels_count, run_id),
        )


def record_run_ticker(
    db_path: str | Path | None,
    *,
    run_id: int,
    symbol: str,
    company_name: str | None = None,
    last_price: float | None = None,
    last_bar_date: str | None = None,
    bar_count: int = 0,
    chart_path: str | Path | None = None,
    status: str,
    error_message: str | None = None,
) -> None:
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO levels_run_tickers (
                run_id, symbol, company_name, last_price, last_bar_date,
                bar_count, chart_path, status, error_message
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id, symbol) DO UPDATE SET
                company_name  = excluded.company_name,
                last_price    = excluded.last_price,
                last_bar_date = excluded.last_bar_date,
                bar_count     = excluded.bar_count,
                chart_path    = excluded.chart_path,
                status        = excluded.status,
                error_message = excluded.error_message
            """,
            (
                run_id,
                symbol,
                company_name,
                last_price,
                last_bar_date,
                bar_count,
                str(chart_path) if chart_path is not None else None,
                status,
                error_message,
            ),
        )


def replace_levels(
    db_path: str | Path | None,
    *,
    run_id: int,
    symbol: str,
    rows: pd.DataFrame | None,
) -> int:
    created_at = utc_now_iso()
    with connect(db_path) as conn:
        conn.execute(
            "DELETE FROM support_resistance_levels WHERE run_id = ? AND symbol = ?",
            (run_id, symbol),
        )
        if rows is None or rows.empty:
            return 0

        payload = []
        for row in rows.to_dict(orient="records"):
            payload.append(
                (
                    run_id,
                    symbol,
                    row["level_type"],
                    float(row["level_value"]),
                    row["method"],
                    row.get("pivot_role"),
                    int(row.get("strength_score", 0) or 0),
                    int(row.get("touch_count", 0) or 0),
                    int(row.get("cluster_size", 1) or 1),
                    float(row["distance_pct"]),
                    float(row["distance_abs"]),
                    int(row["rank_in_ticker"]),
                    row.get("last_touch_date"),
                    created_at,
                )
            )
        conn.executemany(
            """
            INSERT INTO support_resistance_levels (
                run_id, symbol, level_type, level_value, method, pivot_role,
                strength_score, touch_count, cluster_size,
                distance_pct, distance_abs, rank_in_ticker,
                last_touch_date, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            payload,
        )
        return len(payload)


def list_levels_runs(db_path: str | Path | None, *, limit: int = 25) -> list[sqlite3.Row]:
    init_db(db_path)
    with connect(db_path) as conn:
        return list(
            conn.execute(
                """
                SELECT id,
                       started_at,
                       finished_at,
                       status,
                       source_run_id,
                       source_db_path,
                       ticker_count,
                       levels_count,
                       error_message
                FROM levels_runs
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            )
        )


def get_levels_run(db_path: str | Path | None, run_id: int) -> sqlite3.Row | None:
    init_db(db_path)
    with connect(db_path) as conn:
        return conn.execute(
            """
            SELECT id,
                   started_at,
                   finished_at,
                   status,
                   params_json,
                   error_message,
                   source_run_id,
                   source_db_path,
                   ticker_count,
                   levels_count
            FROM levels_runs
            WHERE id = ?
            """,
            (run_id,),
        ).fetchone()


def get_running_levels_run(db_path: str | Path | None) -> sqlite3.Row | None:
    init_db(db_path)
    with connect(db_path) as conn:
        return conn.execute(
            """
            SELECT id,
                   started_at,
                   status,
                   params_json
            FROM levels_runs
            WHERE status = 'running'
            ORDER BY id DESC
            LIMIT 1
            """,
        ).fetchone()


def list_run_tickers(db_path: str | Path | None, *, run_id: int) -> list[sqlite3.Row]:
    init_db(db_path)
    with connect(db_path) as conn:
        return list(
            conn.execute(
                """
                SELECT symbol,
                       company_name,
                       last_price,
                       last_bar_date,
                       bar_count,
                       chart_path,
                       status,
                       error_message
                FROM levels_run_tickers
                WHERE run_id = ?
                ORDER BY symbol
                """,
                (run_id,),
            )
        )


def list_levels_for_ticker(
    db_path: str | Path | None,
    *,
    run_id: int,
    symbol: str,
) -> list[sqlite3.Row]:
    init_db(db_path)
    with connect(db_path) as conn:
        return list(
            conn.execute(
                """
                SELECT level_type,
                       level_value,
                       method,
                       pivot_role,
                       strength_score,
                       touch_count,
                       cluster_size,
                       distance_pct,
                       distance_abs,
                       rank_in_ticker,
                       last_touch_date
                FROM support_resistance_levels
                WHERE run_id = ? AND symbol = ?
                ORDER BY level_type, rank_in_ticker
                """,
                (run_id, symbol),
            )
        )


def list_levels_for_run(
    db_path: str | Path | None,
    *,
    run_id: int,
) -> list[sqlite3.Row]:
    init_db(db_path)
    with connect(db_path) as conn:
        return list(
            conn.execute(
                """
                SELECT symbol,
                       level_type,
                       level_value,
                       method,
                       pivot_role,
                       strength_score,
                       touch_count,
                       cluster_size,
                       distance_pct,
                       distance_abs,
                       rank_in_ticker,
                       last_touch_date
                FROM support_resistance_levels
                WHERE run_id = ?
                ORDER BY symbol, level_type, rank_in_ticker
                """,
                (run_id,),
            )
        )


def delete_levels_run(db_path: str | Path | None, *, run_id: int) -> bool:
    init_db(db_path)
    with connect(db_path) as conn:
        cursor = conn.execute(
            """
            DELETE FROM levels_runs
            WHERE id = ?
              AND status != 'running'
            """,
            (run_id,),
        )
        return cursor.rowcount > 0


def delete_completed_levels_runs(db_path: str | Path | None) -> int:
    init_db(db_path)
    with connect(db_path) as conn:
        cursor = conn.execute(
            """
            DELETE FROM levels_runs
            WHERE status != 'running'
            """,
        )
        return cursor.rowcount
