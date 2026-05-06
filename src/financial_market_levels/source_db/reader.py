from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


class SourceDBError(RuntimeError):
    """Raised when the sibling FinancialMarketReport DB cannot satisfy a request."""


def connect_readonly(path: str | Path) -> sqlite3.Connection:
    """Open the sibling DB read-only. immutable=1 also bypasses locking,
    which lets us read while the sibling app may be writing."""
    db_path = Path(path)
    if not db_path.exists():
        raise SourceDBError(f"Source DB not found: {db_path}")
    uri = f"file:{db_path.resolve()}?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def get_latest_succeeded_run_id(conn: sqlite3.Connection) -> int | None:
    row = conn.execute(
        """
        SELECT id
        FROM report_runs
        WHERE status = 'succeeded'
        ORDER BY id DESC
        LIMIT 1
        """,
    ).fetchone()
    return int(row["id"]) if row is not None else None


def list_ticker_candidates(conn: sqlite3.Connection, *, run_id: int) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT symbol,
                   source,
                   price,
                   change_value,
                   changes_percentage,
                   volume,
                   company_name
            FROM ticker_candidates
            WHERE run_id = ?
            ORDER BY source, symbol
            """,
            (run_id,),
        )
    )


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def fetch_trending_tickers(
    source_db_path: str | Path,
    *,
    run_id: int | None = None,
) -> tuple[int, list[dict[str, Any]]]:
    """Resolve the source run (latest succeeded if `run_id` is None) and return
    its ticker candidates as plain dicts. Closes the connection before returning."""
    with connect_readonly(source_db_path) as conn:
        resolved_run_id = run_id if run_id is not None else get_latest_succeeded_run_id(conn)
        if resolved_run_id is None:
            raise SourceDBError(
                f"No succeeded report runs found in source DB: {source_db_path}"
            )

        if run_id is not None:
            exists = conn.execute(
                "SELECT 1 FROM report_runs WHERE id = ?", (run_id,)
            ).fetchone()
            if exists is None:
                raise SourceDBError(
                    f"run_id {run_id} not found in source DB: {source_db_path}"
                )

        rows = list_ticker_candidates(conn, run_id=resolved_run_id)
        return resolved_run_id, [_row_to_dict(row) for row in rows]
