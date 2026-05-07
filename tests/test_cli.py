from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from financial_market_levels import cli as cli_mod
from financial_market_levels.runner import LevelsRunResult


def test_init_db_creates_tables(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    db = tmp_path / "fml.sqlite3"
    rc = cli_mod.main(["init-db", "--db-path", str(db)])
    captured = capsys.readouterr()
    assert rc == 0
    assert db.exists()
    assert "Database initialized" in captured.out


def test_run_invokes_run_levels(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    fake_result = LevelsRunResult(run_id=7, ticker_count=3, levels_count=12, source_run_id=42)
    with patch.object(cli_mod, "main") as _:
        pass  # ensure module fully imported

    with patch("financial_market_levels.runner.run_levels", return_value=fake_result) as mock_run:
        rc = cli_mod.main([
            "run",
            "--config", str(tmp_path / "c.yaml"),
            "--db-path", str(tmp_path / "fml.sqlite3"),
            "--source-db", str(tmp_path / "fmr.sqlite3"),
            "--source-run-id", "42",
        ])

    assert rc == 0
    captured = capsys.readouterr()
    assert "Run ID: 7" in captured.out
    assert "Tickers: 3" in captured.out
    assert "Levels persisted: 12" in captured.out

    assert mock_run.called
    kwargs = mock_run.call_args.kwargs
    assert kwargs["source_run_id"] == 42
    assert kwargs["trigger"] == "cli"
    assert kwargs["config_path"] == tmp_path / "c.yaml"


def test_runs_lists_recorded_runs(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    db = tmp_path / "fml.sqlite3"
    cli_mod.main(["init-db", "--db-path", str(db)])

    from financial_market_levels.storage.repository import create_levels_run, finish_levels_run
    run_id = create_levels_run(db, started_at="2026-05-06 10:00:00", params={})
    finish_levels_run(
        db,
        run_id=run_id,
        status="succeeded",
        finished_at="2026-05-06 10:01:00",
        ticker_count=2,
        levels_count=5,
    )

    rc = cli_mod.main(["runs", "--db-path", str(db)])
    captured = capsys.readouterr()
    assert rc == 0
    assert f"#{run_id}" in captured.out
    assert "succeeded" in captured.out
    assert "tickers=2" in captured.out
    assert "levels=5" in captured.out


def test_runs_empty_db(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    db = tmp_path / "fml.sqlite3"
    rc = cli_mod.main(["runs", "--db-path", str(db)])
    captured = capsys.readouterr()
    assert rc == 0
    assert "No levels runs recorded" in captured.out


def test_secrets_status_runs_without_vault(capsys: pytest.CaptureFixture) -> None:
    rc = cli_mod.main(["secrets-status"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "Vault configured" in captured.out


def test_serve_invokes_run_dev_server() -> None:
    with patch("financial_market_levels.web.app.run_dev_server") as mock_serve:
        rc = cli_mod.main(["serve", "--host", "0.0.0.0", "--port", "9999"])
    assert rc == 0
    assert mock_serve.called
    kwargs = mock_serve.call_args.kwargs
    assert kwargs["host"] == "0.0.0.0"
    assert kwargs["port"] == 9999
    assert kwargs["debug"] is False


def test_unknown_command_errors(capsys: pytest.CaptureFixture) -> None:
    with pytest.raises(SystemExit):
        cli_mod.main(["bogus"])


def test_build_parser_has_all_subcommands() -> None:
    parser = cli_mod.build_parser()
    # Walk subparsers
    subactions = [a for a in parser._actions if a.__class__.__name__ == "_SubParsersAction"]
    assert subactions, "no subparsers registered"
    names = set(subactions[0].choices.keys())
    assert {"init-db", "run", "runs", "serve", "secrets-status"}.issubset(names)
