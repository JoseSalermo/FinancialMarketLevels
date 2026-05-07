from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import pytest
import yaml

from financial_market_levels.config import (
    AppConfig,
    SourceSettings,
    apply_settings_overrides,
    load_config,
)
from financial_market_levels.analysis.levels import AnalysisSettings


def _write_yaml(path: Path, data: dict) -> Path:
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_load_config_uses_defaults_for_missing_keys(tmp_path: Path) -> None:
    cfg = _write_yaml(tmp_path / "c.yaml", {})
    config = load_config(cfg)

    assert isinstance(config, AppConfig)
    assert config.analysis == AnalysisSettings()
    assert config.source == SourceSettings()


def test_load_config_overrides_yaml_values(tmp_path: Path) -> None:
    cfg = _write_yaml(
        tmp_path / "c.yaml",
        {
            "analysis": {
                "lookback_days": 200,
                "swing_window": 7,
                "include_pivot_weekly": False,
                "timezone": "America/Toronto",
            },
            "source": {
                "source_db_path": "/data/fmr.sqlite3",
                "source_run_id": 42,
            },
        },
    )
    config = load_config(cfg)
    assert config.analysis.lookback_days == 200
    assert config.analysis.swing_window == 7
    assert config.analysis.include_pivot_weekly is False
    assert config.analysis.timezone == "America/Toronto"
    assert config.source.source_db_path == "/data/fmr.sqlite3"
    assert config.source.source_run_id == 42


def test_load_config_normalizes_null_run_id_string(tmp_path: Path) -> None:
    cfg = _write_yaml(
        tmp_path / "c.yaml",
        {"source": {"source_run_id": "null"}},
    )
    config = load_config(cfg)
    assert config.source.source_run_id is None


def test_load_config_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nope.yaml")


def test_load_config_non_mapping_raises(tmp_path: Path) -> None:
    bad = tmp_path / "c.yaml"
    bad.write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(ValueError, match="mapping"):
        load_config(bad)


def test_apply_settings_overrides_merges_strings(tmp_path: Path) -> None:
    base = AppConfig(analysis=AnalysisSettings(), source=SourceSettings())
    out = apply_settings_overrides(
        base,
        {
            "analysis.lookback_days": "365",
            "analysis.touch_tolerance_pct": "0.75",
            "analysis.include_pivot_daily": "false",
            "source.source_run_id": "7",
        },
    )
    assert out.analysis.lookback_days == 365
    assert out.analysis.touch_tolerance_pct == 0.75
    assert out.analysis.include_pivot_daily is False
    assert out.source.source_run_id == 7


def test_apply_settings_overrides_decodes_json_value() -> None:
    base = AppConfig(analysis=AnalysisSettings(), source=SourceSettings())
    out = apply_settings_overrides(base, {"analysis.max_levels_per_ticker": "8"})
    assert out.analysis.max_levels_per_ticker == 8


def test_apply_settings_overrides_unknown_keys_ignored() -> None:
    base = AppConfig(analysis=AnalysisSettings(), source=SourceSettings())
    out = apply_settings_overrides(
        base,
        {
            "totally.bogus": "x",
            "analysis.not_a_field": "y",
            "analysis.lookback_days": "150",
        },
    )
    assert out.analysis.lookback_days == 150
    # Other defaults untouched
    assert out.analysis.swing_window == AnalysisSettings().swing_window


def test_apply_settings_overrides_clears_run_id_with_null_string() -> None:
    base = AppConfig(
        analysis=AnalysisSettings(),
        source=SourceSettings(source_run_id=99),
    )
    out = apply_settings_overrides(base, {"source.source_run_id": "null"})
    assert out.source.source_run_id is None


def test_apply_settings_overrides_returns_new_instance() -> None:
    base = AppConfig(analysis=AnalysisSettings(), source=SourceSettings())
    out = apply_settings_overrides(base, {"analysis.lookback_days": "300"})
    assert out is not base
    assert asdict(base.analysis)["lookback_days"] == AnalysisSettings().lookback_days
