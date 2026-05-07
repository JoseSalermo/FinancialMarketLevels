from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from financial_market_levels.analysis.levels import AnalysisSettings


def _project_root() -> Path:
    configured = os.environ.get("FINANCIAL_MARKET_LEVELS_HOME")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


PROJECT_ROOT = _project_root()
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "defaults.yaml"


@dataclass(frozen=True)
class SourceSettings:
    source_db_path: str = "/source_data/financial_market_report.sqlite3"
    source_run_id: int | None = None


@dataclass(frozen=True)
class AppConfig:
    analysis: AnalysisSettings
    source: SourceSettings


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"Config file must contain a mapping: {path}")
    return data


def _section(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name, {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"Config section '{name}' must be a mapping")
    return value


def _decode_override_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _coerce_override_value(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(default, bool):
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)
    if isinstance(default, int) and not isinstance(default, bool):
        return int(value)
    if isinstance(default, float):
        return float(value)
    if isinstance(default, str):
        return str(value)
    return value


def _coerce_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped or stripped.lower() in {"null", "none"}:
            return None
        return int(stripped)
    return int(value)


def _normalize_source_settings(source: dict[str, Any]) -> dict[str, Any]:
    source["source_run_id"] = _coerce_optional_int(source.get("source_run_id"))
    source["source_db_path"] = str(source.get("source_db_path") or "")
    return source


def apply_settings_overrides(config: AppConfig, flat_settings: Mapping[str, Any]) -> AppConfig:
    analysis = asdict(config.analysis)
    source = asdict(config.source)
    sections = {"analysis": analysis, "source": source}

    for key, raw_value in flat_settings.items():
        section_name, separator, field_name = key.partition(".")
        if not separator:
            continue
        section = sections.get(section_name)
        if section is None or field_name not in section:
            continue

        value = _decode_override_value(raw_value)
        if section_name == "source" and field_name == "source_run_id":
            section[field_name] = _coerce_optional_int(value)
            continue
        section[field_name] = _coerce_override_value(value, section[field_name])

    source = _normalize_source_settings(source)

    return AppConfig(
        analysis=AnalysisSettings(**analysis),
        source=SourceSettings(**source),
    )


def load_config(path: str | Path | None = None) -> AppConfig:
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    data = _load_yaml(config_path)

    analysis = {**asdict(AnalysisSettings()), **_section(data, "analysis")}
    source = _normalize_source_settings(
        {**asdict(SourceSettings()), **_section(data, "source")}
    )

    return AppConfig(
        analysis=AnalysisSettings(**analysis),
        source=SourceSettings(**source),
    )
