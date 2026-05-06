from __future__ import annotations

import pandas as pd

from financial_market_levels.analysis.clustering import cluster_levels


def _swings(*items: tuple[str, float]) -> pd.DataFrame:
    return pd.DataFrame(
        [{"date": pd.Timestamp(d), "price": p, "kind": "high"} for d, p in items]
    )


def test_three_points_within_tolerance_merge() -> None:
    # 100 → anchor 100
    # 100.4: (100.4-100)/100 = 0.4% <= 0.5% → joins, anchor 100.2
    # 100.6: (100.6-100.2)/100.2 ≈ 0.40% <= 0.5% → joins
    swings = _swings(
        ("2026-01-01", 100.0),
        ("2026-01-02", 100.4),
        ("2026-01-03", 100.6),
    )
    out = cluster_levels(swings, tolerance_pct=0.5)
    assert len(out) == 1
    assert out.iloc[0]["cluster_size"] == 3
    expected_anchor = (100.0 + 100.4 + 100.6) / 3
    assert abs(out.iloc[0]["level_value"] - expected_anchor) < 1e-9
    assert out.iloc[0]["last_touch_date"] == pd.Timestamp("2026-01-03")


def test_far_point_starts_new_cluster() -> None:
    # 100 → anchor 100. 100.4 joins → anchor 100.2.
    # 101.0: (101 - 100.2)/100.2 ≈ 0.80% > 0.5% → new cluster.
    swings = _swings(
        ("2026-01-01", 100.0),
        ("2026-01-02", 100.4),
        ("2026-01-03", 101.0),
    )
    out = cluster_levels(swings, tolerance_pct=0.5).sort_values("level_value").reset_index(drop=True)
    assert len(out) == 2
    assert out.iloc[0]["cluster_size"] == 2
    assert out.iloc[1]["cluster_size"] == 1
    assert out.iloc[1]["level_value"] == 101.0


def test_unsorted_input_is_handled() -> None:
    swings = _swings(
        ("2026-01-03", 101.0),
        ("2026-01-01", 100.0),
        ("2026-01-02", 100.4),
    )
    out = cluster_levels(swings, tolerance_pct=0.5).sort_values("level_value").reset_index(drop=True)
    assert len(out) == 2
    assert out.iloc[0]["cluster_size"] == 2


def test_empty_input_returns_empty() -> None:
    out = cluster_levels(pd.DataFrame(columns=["date", "price", "kind"]), tolerance_pct=0.5)
    assert out.empty
    assert list(out.columns) == ["level_value", "cluster_size", "last_touch_date"]


def test_last_touch_is_max_date_in_cluster() -> None:
    swings = _swings(
        ("2026-01-05", 100.0),
        ("2026-01-01", 100.3),
        ("2026-01-10", 100.4),
    )
    out = cluster_levels(swings, tolerance_pct=0.5)
    assert len(out) == 1
    assert out.iloc[0]["last_touch_date"] == pd.Timestamp("2026-01-10")


def test_distant_points_form_separate_clusters() -> None:
    swings = _swings(
        ("2026-01-01", 50.0),
        ("2026-01-02", 75.0),
        ("2026-01-03", 100.0),
    )
    out = cluster_levels(swings, tolerance_pct=0.5)
    assert len(out) == 3
    assert (out["cluster_size"] == 1).all()
