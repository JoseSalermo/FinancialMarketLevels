from __future__ import annotations

import csv
import io
import json
import threading
from pathlib import Path
from typing import Any

from flask import (
    Flask,
    Response,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)

from financial_market_levels.config import (
    DEFAULT_CONFIG_PATH,
    PROJECT_ROOT,
    apply_settings_overrides,
    load_config,
)
from financial_market_levels.runner import run_levels
from financial_market_levels.secrets import clear_secret_cache, secret_status, vault_error
from financial_market_levels.source_db.reader import source_db_status
from financial_market_levels.storage.db import DEFAULT_DB_PATH, init_db
from financial_market_levels.storage.repository import (
    delete_completed_levels_runs,
    delete_levels_run,
    get_levels_run,
    get_running_levels_run,
    get_settings,
    list_levels_for_run,
    list_levels_for_ticker,
    list_levels_runs,
    list_run_tickers,
    update_settings,
)
from financial_market_levels.vault import load_vault_config


SETTING_FIELDS = [
    ("analysis.lookback_days", "Lookback Days", "number"),
    ("analysis.swing_window", "Swing Window", "number"),
    ("analysis.cluster_tolerance_pct", "Cluster Tolerance %", "number"),
    ("analysis.touch_tolerance_pct", "Touch Tolerance %", "number"),
    ("analysis.proximity_pct", "Proximity %", "number"),
    ("analysis.max_levels_per_ticker", "Max Levels per Ticker", "number"),
    ("analysis.include_pivot_daily", "Include Daily Pivots", "checkbox"),
    ("analysis.include_pivot_weekly", "Include Weekly Pivots", "checkbox"),
    ("analysis.timezone", "Timezone", "text"),
    ("source.source_db_path", "Source DB Path", "text"),
    ("source.source_run_id", "Source Run ID (blank=latest)", "text"),
]


def _decode_setting(value: str | None) -> Any:
    if value is None:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _field_value(settings: dict[str, str], key: str, fallback: Any) -> Any:
    return _decode_setting(settings.get(key)) if key in settings else fallback


def _default_settings_map() -> dict[str, Any]:
    config = load_config(DEFAULT_CONFIG_PATH)
    return {
        "analysis.lookback_days": config.analysis.lookback_days,
        "analysis.swing_window": config.analysis.swing_window,
        "analysis.cluster_tolerance_pct": config.analysis.cluster_tolerance_pct,
        "analysis.touch_tolerance_pct": config.analysis.touch_tolerance_pct,
        "analysis.proximity_pct": config.analysis.proximity_pct,
        "analysis.max_levels_per_ticker": config.analysis.max_levels_per_ticker,
        "analysis.include_pivot_daily": config.analysis.include_pivot_daily,
        "analysis.include_pivot_weekly": config.analysis.include_pivot_weekly,
        "analysis.timezone": config.analysis.timezone,
        "source.source_db_path": config.source.source_db_path,
        "source.source_run_id": config.source.source_run_id if config.source.source_run_id is not None else "",
    }


def _charts_root() -> Path:
    return PROJECT_ROOT / "charts"


_LEVEL_CSV_COLUMNS = [
    "level_type",
    "level_value",
    "method",
    "pivot_role",
    "strength_score",
    "touch_count",
    "cluster_size",
    "distance_pct",
    "distance_abs",
    "rank_in_ticker",
    "last_touch_date",
]


def _csv_response(rows: list, *, filename: str, include_symbol: bool) -> Response:
    columns = (["symbol"] if include_symbol else []) + _LEVEL_CSV_COLUMNS
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(columns)
    for row in rows:
        writer.writerow([row[c] for c in columns])
    response = Response(buf.getvalue(), mimetype="text/csv")
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def create_app(*, db_path: str | Path | None = None) -> Flask:
    app = Flask(__name__)
    app.secret_key = "local-dev-change-me"
    app.config["DB_PATH"] = str(db_path or DEFAULT_DB_PATH)
    app.config["CHARTS_ROOT"] = _charts_root()
    init_db(app.config["DB_PATH"])

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.get("/")
    def dashboard():
        latest_runs = list_levels_runs(app.config["DB_PATH"], limit=1)
        latest_run = latest_runs[0] if latest_runs else None
        running_run = get_running_levels_run(app.config["DB_PATH"])
        recent_runs = list_levels_runs(app.config["DB_PATH"], limit=5)

        config = apply_settings_overrides(
            load_config(DEFAULT_CONFIG_PATH),
            get_settings(app.config["DB_PATH"]),
        )
        source_status = source_db_status(config.source.source_db_path)

        return render_template(
            "dashboard.html",
            latest_run=latest_run,
            recent_runs=recent_runs,
            running_run=running_run,
            source_status=source_status,
        )

    @app.get("/runs")
    def runs():
        rows = list_levels_runs(app.config["DB_PATH"], limit=50)
        return render_template("runs.html", runs=rows)

    @app.post("/runs")
    def run_now():
        running_run = get_running_levels_run(app.config["DB_PATH"])
        if running_run is not None:
            flash(f"Run #{running_run['id']} is already running.")
            return redirect(url_for("runs"))

        db_path = app.config["DB_PATH"]
        charts_root = str(app.config["CHARTS_ROOT"])

        def target() -> None:
            try:
                run_levels(db_path=db_path, output_dir=charts_root, trigger="web")
            except Exception:
                app.logger.exception("Manual levels run failed")

        threading.Thread(target=target, daemon=True).start()
        flash("Levels run started. Refresh to see progress.")
        return redirect(url_for("runs"))

    @app.post("/runs/<int:run_id>/delete")
    def delete_run(run_id: int):
        run = get_levels_run(app.config["DB_PATH"], run_id)
        if run is None:
            abort(404)
        if run["status"] == "running":
            flash(f"Run #{run_id} is still running and cannot be removed.")
            return redirect(url_for("runs"))

        deleted = delete_levels_run(app.config["DB_PATH"], run_id=run_id)
        if deleted:
            flash(f"Run #{run_id} removed from history. Generated charts were left on disk.")
        else:
            flash(f"Run #{run_id} could not be removed.")
        return redirect(url_for("runs"))

    @app.post("/runs/clear")
    def clear_runs():
        removed_count = delete_completed_levels_runs(app.config["DB_PATH"])
        flash(
            f"Removed {removed_count} completed run"
            f"{'' if removed_count == 1 else 's'} from history."
        )
        return redirect(url_for("runs"))

    @app.get("/runs/<int:run_id>")
    def run_detail(run_id: int):
        run = get_levels_run(app.config["DB_PATH"], run_id)
        if run is None:
            abort(404)
        tickers = list_run_tickers(app.config["DB_PATH"], run_id=run_id)
        return render_template("run_detail.html", run=run, tickers=tickers)

    @app.get("/runs/<int:run_id>/<symbol>")
    def ticker_detail(run_id: int, symbol: str):
        run = get_levels_run(app.config["DB_PATH"], run_id)
        if run is None:
            abort(404)
        symbol_norm = symbol.strip().upper()
        tickers = {t["symbol"]: t for t in list_run_tickers(app.config["DB_PATH"], run_id=run_id)}
        ticker = tickers.get(symbol_norm)
        if ticker is None:
            abort(404)

        type_filter = (request.args.get("type") or "all").strip().lower()
        if type_filter not in {"all", "support", "resistance"}:
            type_filter = "all"

        all_levels = list_levels_for_ticker(
            app.config["DB_PATH"], run_id=run_id, symbol=symbol_norm
        )
        if type_filter == "all":
            levels = all_levels
        else:
            levels = [r for r in all_levels if r["level_type"] == type_filter]

        counts = {
            "all": len(all_levels),
            "support": sum(1 for r in all_levels if r["level_type"] == "support"),
            "resistance": sum(1 for r in all_levels if r["level_type"] == "resistance"),
        }

        return render_template(
            "ticker_detail.html",
            run=run,
            ticker=ticker,
            levels=levels,
            symbol=symbol_norm,
            type_filter=type_filter,
            counts=counts,
        )

    @app.get("/runs/<int:run_id>/levels.csv")
    def run_levels_csv(run_id: int):
        run = get_levels_run(app.config["DB_PATH"], run_id)
        if run is None:
            abort(404)
        rows = list_levels_for_run(app.config["DB_PATH"], run_id=run_id)
        return _csv_response(rows, filename=f"run_{run_id}_levels.csv", include_symbol=True)

    @app.get("/runs/<int:run_id>/<symbol>/levels.csv")
    def ticker_levels_csv(run_id: int, symbol: str):
        run = get_levels_run(app.config["DB_PATH"], run_id)
        if run is None:
            abort(404)
        symbol_norm = symbol.strip().upper()
        tickers = {t["symbol"]: t for t in list_run_tickers(app.config["DB_PATH"], run_id=run_id)}
        if symbol_norm not in tickers:
            abort(404)
        rows = list_levels_for_ticker(
            app.config["DB_PATH"], run_id=run_id, symbol=symbol_norm
        )
        return _csv_response(
            rows,
            filename=f"run_{run_id}_{symbol_norm}_levels.csv",
            include_symbol=False,
        )

    @app.get("/charts/<int:run_id>/<filename>")
    def chart_asset(run_id: int, filename: str):
        # Reject any path component that includes separators, and resolve to a
        # tightly scoped per-run directory.
        requested = Path(filename)
        if requested.name != filename:
            abort(404)

        chart_dir = (app.config["CHARTS_ROOT"] / str(run_id)).resolve()
        target = (chart_dir / filename).resolve()
        try:
            target.relative_to(chart_dir)
        except ValueError:
            abort(404)
        if not target.is_file():
            abort(404)

        return send_from_directory(chart_dir, filename)

    @app.get("/settings")
    def settings():
        stored = get_settings(app.config["DB_PATH"])
        defaults = _default_settings_map()
        fields = [
            {
                "key": key,
                "label": label,
                "type": field_type,
                "value": _field_value(stored, key, defaults.get(key)),
            }
            for key, label, field_type in SETTING_FIELDS
        ]
        return render_template("settings.html", fields=fields)

    @app.post("/settings")
    def update_settings_view():
        defaults = _default_settings_map()
        values: dict[str, Any] = {}
        for key, _label, field_type in SETTING_FIELDS:
            if field_type == "checkbox":
                values[key] = key in request.form
            elif key in request.form:
                raw = request.form[key].strip()
                default = defaults.get(key)
                if key == "source.source_run_id":
                    values[key] = int(raw) if raw else None
                elif isinstance(default, bool):
                    values[key] = raw.lower() in {"1", "true", "yes", "on"}
                elif isinstance(default, int):
                    values[key] = int(raw)
                elif isinstance(default, float):
                    values[key] = float(raw)
                else:
                    values[key] = raw
        update_settings(app.config["DB_PATH"], values)
        flash("Settings saved. Future runs against this database will use these values.")
        return redirect(url_for("settings"))

    @app.get("/secrets")
    def secrets():
        clear_secret_cache()
        # MVP has no required secrets but the panel exists for parity.
        names: list[str] = []
        return render_template(
            "secrets.html",
            vault_configured=load_vault_config() is not None,
            statuses=secret_status(names),
            vault_error=vault_error(),
        )

    return app


def run_dev_server(
    *,
    host: str,
    port: int,
    db_path: str | Path | None = None,
    debug: bool = False,
) -> None:
    app = create_app(db_path=db_path)
    app.run(host=host, port=port, debug=debug, use_reloader=False)
