from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import mplfinance as mpf
import pandas as pd


_SUPPORT_COLOR = "#16a34a"
_RESISTANCE_COLOR = "#dc2626"


def _make_style() -> Any:
    mc = mpf.make_marketcolors(
        up=_SUPPORT_COLOR,
        down=_RESISTANCE_COLOR,
        wick="inherit",
        edge="inherit",
        volume="in",
    )
    return mpf.make_mpf_style(
        base_mpf_style="yahoo",
        marketcolors=mc,
        gridstyle=":",
        gridcolor="#999999",
    )


def _format_volume_axis(ax) -> None:
    ax.yaxis.set_major_formatter(
        mticker.FuncFormatter(lambda x, _p: f"{x / 1_000_000:.1f}M")
    )


def _build_hlines(levels_df: pd.DataFrame) -> dict[str, Any]:
    return {
        "hlines": [float(v) for v in levels_df["level_value"]],
        "colors": [
            _SUPPORT_COLOR if t == "support" else _RESISTANCE_COLOR
            for t in levels_df["level_type"]
        ],
        "linestyle": "--",
        "linewidths": [
            min(2.4, 0.6 + 0.2 * float(s))
            for s in levels_df["strength_score"]
        ],
        "alpha": 0.85,
    }


def _annotate_levels(ax, last_x, levels_df: pd.DataFrame) -> None:
    for _, row in levels_df.iterrows():
        color = _SUPPORT_COLOR if row["level_type"] == "support" else _RESISTANCE_COLOR
        ax.annotate(
            f"{float(row['level_value']):.2f}",
            xy=(last_x, float(row["level_value"])),
            xytext=(45, 0),
            textcoords="offset points",
            va="center",
            fontsize=7,
            color=color,
            bbox={"boxstyle": "round,pad=0.15", "fc": "white", "ec": "none", "alpha": 0.7},
        )


def save_levels_chart(
    symbol: str,
    df: pd.DataFrame,
    levels_df: pd.DataFrame | None,
    output_dir: str | Path,
    *,
    tz: str = "America/New_York",
) -> Path:
    """Render a daily candlestick chart for `symbol` with S/R hlines overlaid.

    Returns the absolute path of the saved PNG. Raises ValueError if `df` is empty.
    """
    if df is None or df.empty:
        raise ValueError(f"Cannot render chart for {symbol}: empty OHLCV DataFrame")

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{symbol}.png"

    chart_df = df.copy()
    if chart_df.index.tz is None:
        chart_df.index = chart_df.index.tz_localize(tz)
    else:
        chart_df.index = chart_df.index.tz_convert(tz)

    style = _make_style()
    base_kwargs: dict[str, Any] = {
        "type": "candle",
        "style": style,
        "volume": True,
        "figsize": (12, 6),
        "title": f"{symbol} - Daily ({len(chart_df)} bars)",
        "ylabel": "Price ($)",
        "ylabel_lower": "Vol (M)",
        "returnfig": True,
        "tight_layout": True,
        "xrotation": 0,
        "savefig": {"fname": str(out_path), "dpi": 160, "pad_inches": 0.1},
    }

    extra_kwargs: dict[str, Any] = {}
    has_levels = levels_df is not None and not levels_df.empty
    if has_levels:
        extra_kwargs["hlines"] = _build_hlines(levels_df)

    fig, axes = mpf.plot(chart_df, **base_kwargs, **extra_kwargs)
    try:
        main_ax = axes[0] if isinstance(axes, (list, tuple)) else axes
        last_px = float(chart_df["Close"].iloc[-1])
        last_x = chart_df.index[-1]
        main_ax.annotate(
            f"{last_px:.2f}",
            xy=(last_x, last_px),
            xytext=(10, 0),
            textcoords="offset points",
            va="center",
            fontsize=9,
            bbox={"boxstyle": "round,pad=0.2", "fc": "white", "alpha": 0.7},
        )
        if has_levels:
            _annotate_levels(main_ax, last_x, levels_df)
        if isinstance(axes, (list, tuple)) and len(axes) >= 3:
            _format_volume_axis(axes[2])
        fig.savefig(out_path, dpi=160, pad_inches=0.1)
    finally:
        plt.close(fig)

    return out_path
