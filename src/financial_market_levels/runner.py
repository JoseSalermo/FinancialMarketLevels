from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from financial_market_levels.analysis.levels import compute_levels
from financial_market_levels.config import (
    PROJECT_ROOT,
    AppConfig,
    apply_settings_overrides,
    load_config,
)
from financial_market_levels.market_data.yahoo import fetch_history
from financial_market_levels.reporting.charts import save_levels_chart
from financial_market_levels.source_db.reader import fetch_trending_tickers
from financial_market_levels.storage.repository import (
    create_levels_run,
    finish_levels_run,
    get_settings,
    record_run_ticker,
    replace_levels,
    save_settings_snapshot,
    set_levels_run_source,
)


@dataclass(frozen=True)
class LevelsRunResult:
    run_id: int
    ticker_count: int
    levels_count: int
    source_run_id: int | None


def _charts_root(output_dir: str | Path | None = None) -> Path:
    return Path(output_dir) if output_dir else PROJECT_ROOT / "charts"


def _resolve_source_db_path(
    config: AppConfig,
    source_db_path: str | Path | None,
) -> Path:
    raw = source_db_path if source_db_path is not None else config.source.source_db_path
    if not raw:
        raise ValueError("Source DB path is not configured.")
    return Path(raw)


def _resolve_source_run_id(config: AppConfig, source_run_id: int | None) -> int | None:
    if source_run_id is not None:
        return source_run_id
    return config.source.source_run_id


def _now(tz: str) -> datetime:
    return datetime.now(ZoneInfo(tz))


def _fmt(now: datetime) -> str:
    return now.strftime("%Y-%m-%d %H:%M:%S %Z%z")


def run_levels(
    *,
    config_path: str | Path | None = None,
    output_dir: str | Path | None = None,
    db_path: str | Path | None = None,
    source_db_path: str | Path | None = None,
    source_run_id: int | None = None,
    trigger: str = "cli",
) -> LevelsRunResult:
    config: AppConfig = load_config(config_path)
    if db_path is not None:
        config = apply_settings_overrides(config, get_settings(db_path))
    analysis = config.analysis

    timezone = analysis.timezone
    now = _now(timezone)
    generated_at = _fmt(now)

    resolved_source_path = _resolve_source_db_path(config, source_db_path)
    requested_source_run_id = _resolve_source_run_id(config, source_run_id)

    params: dict[str, Any] = {
        "config": asdict(config),
        "runtime": {
            "config_path": str(config_path) if config_path else None,
            "output_dir": str(output_dir) if output_dir else None,
            "db_path": str(db_path) if db_path else None,
            "source_db_path": str(resolved_source_path),
            "source_run_id": requested_source_run_id,
            "trigger": trigger,
        },
    }

    save_settings_snapshot(db_path, settings=config, updated_at=generated_at)
    run_id = create_levels_run(
        db_path,
        started_at=generated_at,
        params=params,
        source_run_id=requested_source_run_id,
        source_db_path=str(resolved_source_path),
    )

    charts_root = _charts_root(output_dir) / str(run_id)
    charts_root.mkdir(parents=True, exist_ok=True)

    ticker_count = 0
    levels_count = 0
    resolved_source_run_id: int | None = requested_source_run_id

    try:
        resolved_source_run_id, candidates = fetch_trending_tickers(
            resolved_source_path,
            run_id=requested_source_run_id,
        )
        if resolved_source_run_id != requested_source_run_id:
            set_levels_run_source(
                db_path,
                run_id=run_id,
                source_run_id=resolved_source_run_id,
            )

        seen: set[str] = set()
        for candidate in candidates:
            symbol_raw = candidate.get("symbol")
            if not symbol_raw:
                continue
            symbol = str(symbol_raw).strip().upper()
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)

            company_name = candidate.get("company_name")
            ticker_count += 1

            try:
                df = fetch_history(
                    symbol,
                    lookback_days=analysis.lookback_days,
                    tz=timezone,
                )
                if df is None or df.empty:
                    record_run_ticker(
                        db_path,
                        run_id=run_id,
                        symbol=symbol,
                        company_name=company_name,
                        status="no_data",
                    )
                    continue

                last_bar = df.iloc[-1]
                last_close = float(last_bar["Close"])
                last_bar_date = df.index[-1]
                last_bar_iso = (
                    last_bar_date.isoformat()
                    if hasattr(last_bar_date, "isoformat")
                    else str(last_bar_date)
                )

                levels_df = compute_levels(df, last_close, analysis)
                inserted = replace_levels(
                    db_path,
                    run_id=run_id,
                    symbol=symbol,
                    rows=levels_df,
                )
                levels_count += inserted

                chart_path = save_levels_chart(
                    symbol,
                    df,
                    levels_df if not levels_df.empty else None,
                    charts_root,
                    tz=timezone,
                )

                record_run_ticker(
                    db_path,
                    run_id=run_id,
                    symbol=symbol,
                    company_name=company_name,
                    last_price=last_close,
                    last_bar_date=last_bar_iso,
                    bar_count=int(len(df)),
                    chart_path=chart_path,
                    status="ok",
                )
            except Exception as exc:
                record_run_ticker(
                    db_path,
                    run_id=run_id,
                    symbol=symbol,
                    company_name=company_name,
                    status="error",
                    error_message=f"{exc.__class__.__name__}: {exc}",
                )

        finish_levels_run(
            db_path,
            run_id=run_id,
            status="succeeded",
            finished_at=_fmt(_now(timezone)),
            ticker_count=ticker_count,
            levels_count=levels_count,
        )
    except Exception as exc:
        finish_levels_run(
            db_path,
            run_id=run_id,
            status="failed",
            finished_at=_fmt(_now(timezone)),
            ticker_count=ticker_count,
            levels_count=levels_count,
            error_message=f"{exc.__class__.__name__}: {exc}",
        )
        raise

    return LevelsRunResult(
        run_id=run_id,
        ticker_count=ticker_count,
        levels_count=levels_count,
        source_run_id=resolved_source_run_id,
    )
