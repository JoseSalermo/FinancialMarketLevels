from __future__ import annotations

import argparse
import sys


def cmd_init_db(args: argparse.Namespace) -> int:
    raise NotImplementedError("init-db will be implemented in Phase 1 (storage)")


def cmd_run(args: argparse.Namespace) -> int:
    raise NotImplementedError("run will be implemented in Phase 5 (runner)")


def cmd_runs(args: argparse.Namespace) -> int:
    raise NotImplementedError("runs will be implemented in Phase 1 (storage)")


def cmd_serve(args: argparse.Namespace) -> int:
    raise NotImplementedError("serve will be implemented in Phase 6 (web)")


def cmd_secrets_status(args: argparse.Namespace) -> int:
    raise NotImplementedError("secrets-status will be implemented in Phase 6")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="financial-market-levels",
        description="Support/resistance level finder for trending tickers.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init-db", help="Initialize the application's SQLite database.")
    p_init.add_argument("--db-path", help="Override default DB path.")
    p_init.set_defaults(func=cmd_init_db)

    p_run = sub.add_parser("run", help="Run the levels pipeline against the latest sibling run.")
    p_run.add_argument("--config", help="Path to YAML config.")
    p_run.add_argument("--db-path", help="Override default DB path.")
    p_run.add_argument("--source-db", help="Path to FinancialMarketReport SQLite (read-only).")
    p_run.add_argument("--source-run-id", type=int, help="Specific source run id (default: latest succeeded).")
    p_run.set_defaults(func=cmd_run)

    p_runs = sub.add_parser("runs", help="List recent levels runs.")
    p_runs.add_argument("--db-path", help="Override default DB path.")
    p_runs.add_argument("--limit", type=int, default=10)
    p_runs.set_defaults(func=cmd_runs)

    p_serve = sub.add_parser("serve", help="Run the Flask web UI.")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8083)
    p_serve.add_argument("--db-path", help="Override default DB path.")
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
