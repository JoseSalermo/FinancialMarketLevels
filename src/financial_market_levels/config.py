"""Config dataclasses + YAML/SQLite override merging.

Phase 1+ will implement AnalysisSettings, SourceSettings, AppConfig,
load_config(), and apply_settings_overrides() — modeled on
/home/josej/Projects/FinancialMarketReport/src/financial_market_report/config.py.
"""
from __future__ import annotations

import os
from pathlib import Path


def _project_root() -> Path:
    env = os.environ.get("FINANCIAL_MARKET_LEVELS_HOME")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2]


PROJECT_ROOT = _project_root()
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "defaults.yaml"
