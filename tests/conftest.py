from __future__ import annotations

from pathlib import Path

import pytest

from financial_market_levels.storage.db import init_db


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "fml.sqlite3"
    init_db(db_path)
    return db_path
