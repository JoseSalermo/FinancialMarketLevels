from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pytest

from financial_market_levels.storage.db import connect
from financial_market_levels.storage.repository import (
    create_levels_run,
    delete_completed_levels_runs,
    delete_levels_run,
    finish_levels_run,
    get_levels_run,
    get_running_levels_run,
    get_settings,
    list_levels_for_ticker,
    list_levels_runs,
    list_run_tickers,
    record_run_ticker,
    replace_levels,
    save_settings_snapshot,
    update_settings,
    utc_now_iso,
)


def _levels_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _sample_levels(symbol_close: float = 100.0) -> pd.DataFrame:
    return _levels_df(
        [
            {
                "level_type": "support",
                "level_value": 95.0,
                "method": "swing",
                "pivot_role": None,
                "strength_score": 4,
                "touch_count": 4,
                "cluster_size": 3,
                "distance_pct": (95.0 - symbol_close) / symbol_close * 100,
                "distance_abs": abs(95.0 - symbol_close),
                "rank_in_ticker": 1,
                "last_touch_date": "2026-04-15",
            },
            {
                "level_type": "resistance",
                "level_value": 105.0,
                "method": "pivot_daily",
                "pivot_role": "R1",
                "strength_score": 2,
                "touch_count": 2,
                "cluster_size": 1,
                "distance_pct": (105.0 - symbol_close) / symbol_close * 100,
                "distance_abs": abs(105.0 - symbol_close),
                "rank_in_ticker": 1,
                "last_touch_date": None,
            },
        ]
    )


def test_create_and_finish_run(tmp_db: Path) -> None:
    run_id = create_levels_run(
        tmp_db,
        started_at=utc_now_iso(),
        params={"trigger": "test"},
        source_run_id=42,
        source_db_path="/source_data/fmr.sqlite3",
    )
    assert run_id == 1

    running = get_running_levels_run(tmp_db)
    assert running is not None
    assert running["id"] == run_id
    assert running["status"] == "running"

    finish_levels_run(
        tmp_db,
        run_id=run_id,
        status="succeeded",
        finished_at=utc_now_iso(),
        ticker_count=3,
        levels_count=12,
    )

    row = get_levels_run(tmp_db, run_id)
    assert row is not None
    assert row["status"] == "succeeded"
    assert row["ticker_count"] == 3
    assert row["levels_count"] == 12
    assert row["source_run_id"] == 42
    assert row["source_db_path"] == "/source_data/fmr.sqlite3"
    assert get_running_levels_run(tmp_db) is None


def test_settings_snapshot_flattens_nested_dataclass(tmp_db: Path) -> None:
    @dataclass
    class Analysis:
        lookback_days: int = 180
        proximity_pct: float = 10.0

    @dataclass
    class Source:
        source_db_path: str = "/source_data/fmr.sqlite3"
        source_run_id: int | None = None

    @dataclass
    class App:
        analysis: Analysis
        source: Source

    cfg = App(analysis=Analysis(), source=Source())
    save_settings_snapshot(tmp_db, settings=cfg, updated_at=utc_now_iso())

    settings = get_settings(tmp_db)
    assert settings["analysis.lookback_days"] == "180"
    assert settings["analysis.proximity_pct"] == "10.0"
    assert settings["source.source_db_path"] == '"/source_data/fmr.sqlite3"'
    assert settings["source.source_run_id"] == "null"


def test_update_settings_overrides_existing_keys(tmp_db: Path) -> None:
    update_settings(tmp_db, {"analysis.swing_window": 5})
    update_settings(tmp_db, {"analysis.swing_window": 7})
    assert get_settings(tmp_db)["analysis.swing_window"] == "7"


def test_save_settings_snapshot_rejects_non_mapping(tmp_db: Path) -> None:
    with pytest.raises(TypeError):
        save_settings_snapshot(tmp_db, settings=[1, 2, 3], updated_at=utc_now_iso())


def test_record_run_ticker_upserts(tmp_db: Path) -> None:
    run_id = create_levels_run(tmp_db, started_at=utc_now_iso(), params={})
    record_run_ticker(
        tmp_db,
        run_id=run_id,
        symbol="AAPL",
        company_name="Apple Inc.",
        last_price=180.5,
        bar_count=125,
        status="ok",
    )
    record_run_ticker(
        tmp_db,
        run_id=run_id,
        symbol="AAPL",
        company_name="Apple Inc.",
        last_price=181.0,
        bar_count=126,
        chart_path="/charts/1/AAPL.png",
        status="ok",
    )

    rows = list_run_tickers(tmp_db, run_id=run_id)
    assert len(rows) == 1
    assert rows[0]["last_price"] == 181.0
    assert rows[0]["chart_path"] == "/charts/1/AAPL.png"


def test_replace_levels_scoped_per_symbol(tmp_db: Path) -> None:
    run_id = create_levels_run(tmp_db, started_at=utc_now_iso(), params={})
    replace_levels(tmp_db, run_id=run_id, symbol="AAPL", rows=_sample_levels(180.0))
    replace_levels(tmp_db, run_id=run_id, symbol="MSFT", rows=_sample_levels(400.0))

    aapl = list_levels_for_ticker(tmp_db, run_id=run_id, symbol="AAPL")
    msft = list_levels_for_ticker(tmp_db, run_id=run_id, symbol="MSFT")
    assert len(aapl) == 2 and len(msft) == 2

    new_aapl = _sample_levels(180.0).iloc[[0]].copy()
    inserted = replace_levels(tmp_db, run_id=run_id, symbol="AAPL", rows=new_aapl)
    assert inserted == 1

    aapl_after = list_levels_for_ticker(tmp_db, run_id=run_id, symbol="AAPL")
    msft_after = list_levels_for_ticker(tmp_db, run_id=run_id, symbol="MSFT")
    assert len(aapl_after) == 1
    assert len(msft_after) == 2


def test_replace_levels_with_empty_df_clears(tmp_db: Path) -> None:
    run_id = create_levels_run(tmp_db, started_at=utc_now_iso(), params={})
    replace_levels(tmp_db, run_id=run_id, symbol="AAPL", rows=_sample_levels(180.0))
    inserted = replace_levels(tmp_db, run_id=run_id, symbol="AAPL", rows=pd.DataFrame())
    assert inserted == 0
    assert list_levels_for_ticker(tmp_db, run_id=run_id, symbol="AAPL") == []


def test_list_levels_runs_orders_desc(tmp_db: Path) -> None:
    a = create_levels_run(tmp_db, started_at=utc_now_iso(), params={})
    b = create_levels_run(tmp_db, started_at=utc_now_iso(), params={})
    rows = list_levels_runs(tmp_db, limit=10)
    assert [r["id"] for r in rows] == [b, a]


def test_delete_levels_run_blocks_running(tmp_db: Path) -> None:
    run_id = create_levels_run(tmp_db, started_at=utc_now_iso(), params={})
    assert delete_levels_run(tmp_db, run_id=run_id) is False

    finish_levels_run(
        tmp_db, run_id=run_id, status="failed", finished_at=utc_now_iso(), error_message="boom"
    )
    assert delete_levels_run(tmp_db, run_id=run_id) is True
    assert get_levels_run(tmp_db, run_id) is None


def test_delete_completed_runs_keeps_running(tmp_db: Path) -> None:
    a = create_levels_run(tmp_db, started_at=utc_now_iso(), params={})
    finish_levels_run(tmp_db, run_id=a, status="succeeded", finished_at=utc_now_iso())
    create_levels_run(tmp_db, started_at=utc_now_iso(), params={})

    removed = delete_completed_levels_runs(tmp_db)
    assert removed == 1
    rows = list_levels_runs(tmp_db, limit=10)
    assert len(rows) == 1
    assert rows[0]["status"] == "running"


def test_cascade_delete_removes_children(tmp_db: Path) -> None:
    run_id = create_levels_run(tmp_db, started_at=utc_now_iso(), params={})
    record_run_ticker(tmp_db, run_id=run_id, symbol="AAPL", status="ok")
    replace_levels(tmp_db, run_id=run_id, symbol="AAPL", rows=_sample_levels(180.0))
    finish_levels_run(tmp_db, run_id=run_id, status="succeeded", finished_at=utc_now_iso())

    assert delete_levels_run(tmp_db, run_id=run_id) is True

    with connect(tmp_db) as conn:
        ticker_rows = conn.execute(
            "SELECT COUNT(*) AS n FROM levels_run_tickers WHERE run_id = ?", (run_id,)
        ).fetchone()
        level_rows = conn.execute(
            "SELECT COUNT(*) AS n FROM support_resistance_levels WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    assert ticker_rows["n"] == 0
    assert level_rows["n"] == 0


def test_init_db_creates_expected_tables(tmp_db: Path) -> None:
    with sqlite3.connect(tmp_db) as conn:
        names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
            )
        }
    assert {
        "settings",
        "levels_runs",
        "levels_run_tickers",
        "support_resistance_levels",
    }.issubset(names)
