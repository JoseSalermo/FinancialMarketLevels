from __future__ import annotations

import argparse
import sys
from pathlib import Path


def cmd_init_db(args: argparse.Namespace) -> int:
    from financial_market_levels.storage.db import init_db

    db_path = init_db(args.db_path)
    print(f"Database initialized: {db_path}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    from financial_market_levels.runner import run_levels

    result = run_levels(
        config_path=args.config,
        output_dir=args.output_dir,
        db_path=args.db_path,
        source_db_path=args.source_db,
        source_run_id=args.source_run_id,
        trigger="cli",
    )
    print(f"Run ID: {result.run_id}")
    print(f"Source run ID: {result.source_run_id}")
    print(f"Tickers: {result.ticker_count}")
    print(f"Levels persisted: {result.levels_count}")
    return 0


def cmd_runs(args: argparse.Namespace) -> int:
    from financial_market_levels.storage.repository import list_levels_runs

    rows = list_levels_runs(args.db_path, limit=args.limit)
    if not rows:
        print("No levels runs recorded.")
        return 0

    for row in rows:
        print(
            f"#{row['id']} {row['status']} "
            f"started={row['started_at']} "
            f"finished={row['finished_at'] or '-'} "
            f"source_run={row['source_run_id'] or '-'} "
            f"tickers={row['ticker_count']} "
            f"levels={row['levels_count']}"
        )
        if row["error_message"]:
            print(f"  error={row['error_message']}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from financial_market_levels.web.app import run_dev_server

    run_dev_server(
        host=args.host,
        port=args.port,
        db_path=args.db_path,
        debug=args.debug,
    )
    return 0


def cmd_secrets_status(args: argparse.Namespace) -> int:
    from financial_market_levels.secrets import clear_secret_cache, secret_status, vault_error
    from financial_market_levels.vault import load_vault_config

    # MVP has no required secrets, but we still surface Vault wiring health.
    names: list[str] = []
    clear_secret_cache()
    config = load_vault_config()
    print(f"Vault configured: {config is not None}")
    for name, configured in secret_status(names).items():
        print(f"{name}: {'configured' if configured else 'missing'}")
    if vault_error():
        print(f"Vault error: {vault_error()}")
    return 0


def _path_or_none(value: str | None) -> Path | None:
    return Path(value) if value else None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="financial-market-levels",
        description="Support/resistance level finder for trending tickers.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init-db", help="Initialize the application's SQLite database.")
    p_init.add_argument("--db-path", type=_path_or_none, default=None)
    p_init.set_defaults(func=cmd_init_db)

    p_run = sub.add_parser("run", help="Run the levels pipeline against the latest sibling run.")
    p_run.add_argument("--config", type=_path_or_none, default=None, help="Path to YAML config.")
    p_run.add_argument("--db-path", type=_path_or_none, default=None)
    p_run.add_argument("--output-dir", type=_path_or_none, default=None, help="Charts output directory.")
    p_run.add_argument("--source-db", type=_path_or_none, default=None,
                       help="Path to FinancialMarketReport SQLite (read-only).")
    p_run.add_argument("--source-run-id", type=int, default=None,
                       help="Specific source run id (default: latest succeeded).")
    p_run.set_defaults(func=cmd_run)

    p_runs = sub.add_parser("runs", help="List recent levels runs.")
    p_runs.add_argument("--db-path", type=_path_or_none, default=None)
    p_runs.add_argument("--limit", type=int, default=10)
    p_runs.set_defaults(func=cmd_runs)

    p_serve = sub.add_parser("serve", help="Run the Flask web UI.")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8083)
    p_serve.add_argument("--db-path", type=_path_or_none, default=None)
    p_serve.add_argument("--debug", action="store_true")
    p_serve.set_defaults(func=cmd_serve)

    p_secrets = sub.add_parser("secrets-status", help="Show Vault/secrets resolution status.")
    p_secrets.set_defaults(func=cmd_secrets_status)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
