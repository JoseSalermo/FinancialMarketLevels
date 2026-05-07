from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from financial_market_levels.storage.repository import (
    create_levels_run,
    finish_levels_run,
    get_levels_run,
    get_settings,
    list_levels_runs,
    record_run_ticker,
    replace_levels,
)
from financial_market_levels.web.app import create_app


@pytest.fixture
def app(tmp_path: Path):
    db_path = tmp_path / "app.sqlite3"
    charts_root = tmp_path / "charts"
    charts_root.mkdir()
    flask_app = create_app(db_path=db_path)
    flask_app.config["CHARTS_ROOT"] = charts_root
    return flask_app


def _seed_run(db_path: Path, *, status: str = "succeeded", started_at: str = "2026-05-06 10:00:00 EDT-0400") -> int:
    run_id = create_levels_run(db_path, started_at=started_at, params={})
    if status != "running":
        finish_levels_run(
            db_path,
            run_id=run_id,
            status=status,
            finished_at="2026-05-06 10:01:00 EDT-0400",
        )
    return run_id


def test_healthz_returns_ok(app) -> None:
    response = app.test_client().get("/healthz")
    assert response.status_code == 200
    assert response.json == {"ok": True}


def test_dashboard_renders_when_empty(app) -> None:
    response = app.test_client().get("/")
    assert response.status_code == 200
    assert b"No runs recorded" in response.data


def test_runs_page_lists_runs(app) -> None:
    db = Path(app.config["DB_PATH"])
    run_id = _seed_run(db)
    response = app.test_client().get("/runs")
    assert response.status_code == 200
    assert f"#{run_id}".encode() in response.data
    assert b"succeeded" in response.data


def test_run_detail_shows_tickers(app) -> None:
    db = Path(app.config["DB_PATH"])
    run_id = _seed_run(db)
    record_run_ticker(
        db,
        run_id=run_id,
        symbol="AAA",
        company_name="Aaa Inc",
        last_price=123.45,
        last_bar_date="2026-05-05",
        bar_count=120,
        chart_path="/tmp/AAA.png",
        status="ok",
    )
    response = app.test_client().get(f"/runs/{run_id}")
    assert response.status_code == 200
    assert b"AAA" in response.data
    assert b"Aaa Inc" in response.data


def test_run_detail_404s_for_unknown_run(app) -> None:
    response = app.test_client().get("/runs/999")
    assert response.status_code == 404


def test_ticker_detail_renders_levels(app) -> None:
    db = Path(app.config["DB_PATH"])
    run_id = _seed_run(db)
    record_run_ticker(
        db,
        run_id=run_id,
        symbol="AAA",
        last_price=100.0,
        last_bar_date="2026-05-05",
        bar_count=120,
        chart_path="/tmp/AAA.png",
        status="ok",
    )
    levels_df = pd.DataFrame([
        {
            "level_type": "support",
            "level_value": 95.0,
            "method": "swing",
            "pivot_role": None,
            "strength_score": 4,
            "touch_count": 4,
            "cluster_size": 3,
            "distance_pct": -5.0,
            "distance_abs": 5.0,
            "rank_in_ticker": 1,
            "last_touch_date": "2026-04-01",
        },
    ])
    replace_levels(db, run_id=run_id, symbol="AAA", rows=levels_df)

    response = app.test_client().get(f"/runs/{run_id}/AAA")
    assert response.status_code == 200
    assert b"support" in response.data
    assert b"95.00" in response.data
    assert b"swing" in response.data


def test_ticker_detail_404s_for_unknown_symbol(app) -> None:
    db = Path(app.config["DB_PATH"])
    run_id = _seed_run(db)
    response = app.test_client().get(f"/runs/{run_id}/ZZZ")
    assert response.status_code == 404


def test_chart_asset_serves_png(app) -> None:
    db = Path(app.config["DB_PATH"])
    run_id = _seed_run(db)
    chart_dir = app.config["CHARTS_ROOT"] / str(run_id)
    chart_dir.mkdir()
    (chart_dir / "AAA.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")

    response = app.test_client().get(f"/charts/{run_id}/AAA.png")
    assert response.status_code == 200
    assert response.data.startswith(b"\x89PNG")


def test_chart_asset_rejects_nested_paths(app) -> None:
    response = app.test_client().get("/charts/1/nested/AAA.png")
    # Flask routes /charts/<int:run_id>/<filename> won't even match a path with a slash
    # but werkzeug may 404. Either way it must NOT 200.
    assert response.status_code == 404


def test_chart_asset_rejects_traversal_attempt(app) -> None:
    db = Path(app.config["DB_PATH"])
    run_id = _seed_run(db)
    response = app.test_client().get(f"/charts/{run_id}/..%2Fsecret.png")
    assert response.status_code == 404


def test_chart_asset_404s_when_file_missing(app) -> None:
    db = Path(app.config["DB_PATH"])
    run_id = _seed_run(db)
    response = app.test_client().get(f"/charts/{run_id}/missing.png")
    assert response.status_code == 404


def test_settings_page_renders_defaults(app) -> None:
    response = app.test_client().get("/settings")
    assert response.status_code == 200
    assert b"Lookback Days" in response.data
    assert b"Swing Window" in response.data
    assert b"Source DB Path" in response.data


def test_settings_post_persists_values(app) -> None:
    db = Path(app.config["DB_PATH"])
    response = app.test_client().post(
        "/settings",
        data={
            "analysis.lookback_days": "240",
            "analysis.swing_window": "7",
            "analysis.cluster_tolerance_pct": "0.75",
            "analysis.touch_tolerance_pct": "0.5",
            "analysis.proximity_pct": "12.5",
            "analysis.max_levels_per_ticker": "8",
            "analysis.include_pivot_daily": "on",
            # include_pivot_weekly intentionally omitted -> unchecked
            "analysis.timezone": "America/Toronto",
            "source.source_db_path": "/tmp/fmr.sqlite3",
            "source.source_run_id": "",
        },
    )
    assert response.status_code == 302
    stored = get_settings(db)
    assert json.loads(stored["analysis.lookback_days"]) == 240
    assert json.loads(stored["analysis.swing_window"]) == 7
    assert json.loads(stored["analysis.cluster_tolerance_pct"]) == 0.75
    assert json.loads(stored["analysis.proximity_pct"]) == 12.5
    assert json.loads(stored["analysis.max_levels_per_ticker"]) == 8
    assert json.loads(stored["analysis.include_pivot_daily"]) is True
    assert json.loads(stored["analysis.include_pivot_weekly"]) is False
    assert json.loads(stored["analysis.timezone"]) == "America/Toronto"
    assert json.loads(stored["source.source_db_path"]) == "/tmp/fmr.sqlite3"
    assert json.loads(stored["source.source_run_id"]) is None


def test_settings_post_parses_explicit_run_id(app) -> None:
    db = Path(app.config["DB_PATH"])
    response = app.test_client().post(
        "/settings",
        data={
            "analysis.lookback_days": "180",
            "source.source_run_id": "42",
        },
    )
    assert response.status_code == 302
    stored = get_settings(db)
    assert json.loads(stored["source.source_run_id"]) == 42


def test_delete_run_removes_completed_run(app) -> None:
    db = Path(app.config["DB_PATH"])
    run_id = _seed_run(db, status="failed")
    response = app.test_client().post(f"/runs/{run_id}/delete")
    assert response.status_code == 302
    assert get_levels_run(db, run_id) is None


def test_delete_run_keeps_running_run(app) -> None:
    db = Path(app.config["DB_PATH"])
    run_id = _seed_run(db, status="running")
    response = app.test_client().post(f"/runs/{run_id}/delete")
    assert response.status_code == 302
    assert get_levels_run(db, run_id) is not None


def test_clear_runs_removes_completed_keeps_running(app) -> None:
    db = Path(app.config["DB_PATH"])
    completed_id = _seed_run(db)
    running_id = _seed_run(db, status="running", started_at="2026-05-06 10:05:00 EDT-0400")

    response = app.test_client().post("/runs/clear")
    assert response.status_code == 302
    rows = list_levels_runs(db, limit=10)
    assert [row["id"] for row in rows] == [running_id]


def test_run_now_spawns_thread(app) -> None:
    with patch("financial_market_levels.web.app.run_levels") as mock_run:
        # Use threading.Thread.start synchronously by patching the Thread class.
        from financial_market_levels.web import app as app_mod
        captured = {}

        class _SyncThread:
            def __init__(self, *, target, daemon):
                captured["target"] = target

            def start(self):
                captured["target"]()

        with patch.object(app_mod.threading, "Thread", _SyncThread):
            response = app.test_client().post("/runs")
        assert response.status_code == 302
        assert mock_run.called


def test_run_now_blocks_when_already_running(app) -> None:
    db = Path(app.config["DB_PATH"])
    _seed_run(db, status="running")
    with patch("financial_market_levels.web.app.run_levels") as mock_run:
        response = app.test_client().post("/runs")
    assert response.status_code == 302
    assert not mock_run.called


def test_secrets_page_renders(app) -> None:
    response = app.test_client().get("/secrets")
    assert response.status_code == 200
    assert b"Vault Configured" in response.data


def test_dashboard_shows_source_db_panel_unreachable(app) -> None:
    # Default source path will not exist in the test environment
    response = app.test_client().get("/")
    assert response.status_code == 200
    assert b"Source Database" in response.data
    # Either reachable badge is present (if path happens to exist locally) or unreachable+error.
    assert b"Reachable" in response.data


def test_dashboard_source_panel_reachable(app, tmp_path: Path) -> None:
    # Build a real sibling-shaped DB so the panel reports reachable.
    src = tmp_path / "fmr.sqlite3"
    import sqlite3 as _s
    schema = """
        CREATE TABLE report_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL,
            finished_at TEXT, status TEXT NOT NULL, params_json TEXT NOT NULL, error_message TEXT,
            ticker_count INTEGER NOT NULL DEFAULT 0, email_sent INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE ticker_candidates (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER NOT NULL,
            symbol TEXT NOT NULL, source TEXT, price REAL, change_value REAL, changes_percentage REAL,
            volume REAL, company_name TEXT, row_json TEXT NOT NULL);
    """
    conn = _s.connect(src)
    conn.executescript(schema)
    cur = conn.execute(
        "INSERT INTO report_runs (started_at, status, params_json) VALUES ('x', 'succeeded', '{}')"
    )
    rid = cur.lastrowid
    conn.execute(
        "INSERT INTO ticker_candidates (run_id, symbol, row_json) VALUES (?, 'AAPL', '{}')",
        (rid,),
    )
    conn.commit()
    conn.close()

    # Point the app's stored settings at this DB
    from financial_market_levels.storage.repository import update_settings as _us
    _us(app.config["DB_PATH"], {"source.source_db_path": str(src)})

    response = app.test_client().get("/")
    body = response.data.decode()
    assert response.status_code == 200
    assert "Source Database" in body
    assert ">yes<" in body  # reachable badge
    # Latest FMR run id is shown
    assert f">{rid}<" in body


def test_ticker_detail_filter_chips_render(app) -> None:
    db = Path(app.config["DB_PATH"])
    run_id = _seed_run(db)
    record_run_ticker(
        db, run_id=run_id, symbol="AAA", last_price=100.0, last_bar_date="2026-05-05",
        bar_count=120, chart_path="/tmp/AAA.png", status="ok",
    )
    levels = pd.DataFrame([
        {"level_type": "support", "level_value": 95.0, "method": "swing", "pivot_role": None,
         "strength_score": 4, "touch_count": 4, "cluster_size": 3,
         "distance_pct": -5.0, "distance_abs": 5.0, "rank_in_ticker": 1, "last_touch_date": None},
        {"level_type": "resistance", "level_value": 105.0, "method": "swing", "pivot_role": None,
         "strength_score": 2, "touch_count": 2, "cluster_size": 1,
         "distance_pct": 5.0, "distance_abs": 5.0, "rank_in_ticker": 1, "last_touch_date": None},
    ])
    replace_levels(db, run_id=run_id, symbol="AAA", rows=levels)

    response = app.test_client().get(f"/runs/{run_id}/AAA")
    body = response.data.decode()
    assert "All (2)" in body
    assert "Support (1)" in body
    assert "Resistance (1)" in body
    assert "95.00" in body and "105.00" in body


def test_ticker_detail_filter_support_only(app) -> None:
    db = Path(app.config["DB_PATH"])
    run_id = _seed_run(db)
    record_run_ticker(
        db, run_id=run_id, symbol="AAA", last_price=100.0, status="ok",
    )
    levels = pd.DataFrame([
        {"level_type": "support", "level_value": 95.0, "method": "swing", "pivot_role": None,
         "strength_score": 4, "touch_count": 4, "cluster_size": 3,
         "distance_pct": -5.0, "distance_abs": 5.0, "rank_in_ticker": 1, "last_touch_date": None},
        {"level_type": "resistance", "level_value": 105.0, "method": "swing", "pivot_role": None,
         "strength_score": 2, "touch_count": 2, "cluster_size": 1,
         "distance_pct": 5.0, "distance_abs": 5.0, "rank_in_ticker": 1, "last_touch_date": None},
    ])
    replace_levels(db, run_id=run_id, symbol="AAA", rows=levels)

    response = app.test_client().get(f"/runs/{run_id}/AAA?type=support")
    body = response.data.decode()
    assert "95.00" in body
    assert "105.00" not in body


def test_ticker_detail_filter_invalid_type_falls_back_to_all(app) -> None:
    db = Path(app.config["DB_PATH"])
    run_id = _seed_run(db)
    record_run_ticker(db, run_id=run_id, symbol="AAA", last_price=100.0, status="ok")
    response = app.test_client().get(f"/runs/{run_id}/AAA?type=garbage")
    assert response.status_code == 200


def test_run_levels_csv_downloads(app) -> None:
    db = Path(app.config["DB_PATH"])
    run_id = _seed_run(db)
    record_run_ticker(db, run_id=run_id, symbol="AAA", last_price=100.0, status="ok")
    levels = pd.DataFrame([
        {"level_type": "support", "level_value": 95.0, "method": "swing", "pivot_role": None,
         "strength_score": 4, "touch_count": 4, "cluster_size": 3,
         "distance_pct": -5.0, "distance_abs": 5.0, "rank_in_ticker": 1, "last_touch_date": None},
    ])
    replace_levels(db, run_id=run_id, symbol="AAA", rows=levels)

    response = app.test_client().get(f"/runs/{run_id}/levels.csv")
    assert response.status_code == 200
    assert response.mimetype == "text/csv"
    assert f'filename="run_{run_id}_levels.csv"' in response.headers["Content-Disposition"]
    body = response.data.decode()
    header, *rows = [line for line in body.splitlines() if line]
    assert header.split(",")[0] == "symbol"
    assert any(line.startswith("AAA,support,95.0,") for line in rows)


def test_ticker_levels_csv_downloads(app) -> None:
    db = Path(app.config["DB_PATH"])
    run_id = _seed_run(db)
    record_run_ticker(db, run_id=run_id, symbol="AAA", last_price=100.0, status="ok")
    levels = pd.DataFrame([
        {"level_type": "support", "level_value": 95.0, "method": "swing", "pivot_role": None,
         "strength_score": 4, "touch_count": 4, "cluster_size": 3,
         "distance_pct": -5.0, "distance_abs": 5.0, "rank_in_ticker": 1, "last_touch_date": None},
    ])
    replace_levels(db, run_id=run_id, symbol="AAA", rows=levels)

    response = app.test_client().get(f"/runs/{run_id}/AAA/levels.csv")
    assert response.status_code == 200
    body = response.data.decode()
    header, *rows = [line for line in body.splitlines() if line]
    # Per-ticker CSV does not include the symbol column
    assert header.split(",")[0] == "level_type"
    assert any(line.startswith("support,95.0,") for line in rows)


def test_run_levels_csv_404_for_unknown_run(app) -> None:
    response = app.test_client().get("/runs/9999/levels.csv")
    assert response.status_code == 404


def test_ticker_levels_csv_404_for_unknown_symbol(app) -> None:
    db = Path(app.config["DB_PATH"])
    run_id = _seed_run(db)
    response = app.test_client().get(f"/runs/{run_id}/ZZZ/levels.csv")
    assert response.status_code == 404
