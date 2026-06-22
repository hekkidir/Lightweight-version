"""
schema.py — data contracts for every parquet the pipeline produces.

Single source of truth for column names. Imported by:
  - run.py check            (health check)
  - tests/test_contracts.py (drift detection: code vs schema vs config)
  - server/app.py           (frontend field contract)

When a stage's output columns change, change them HERE too — the contract
test fails loudly if code and schema drift apart.
"""
from __future__ import annotations

import pandas as pd

# ── Required columns per parquet ──────────────────────────────────────────────

PRICES = [
    "Date", "Ticker", "Open", "High", "Low", "Close", "Volume",
    "Sector", "Market_Cap",
]

METRICS = [
    "Ticker", "Sector", "Market_Cap", "Close", "change_pct",
    "Stage", "Prev_Stage", "Regime", "Vol_Confirmed",
    "ytd", "weekly", "monthly", "atr_pct", "ext", "rsi", "rvol", "rvol_avg",
    "ema10", "ema20", "ema50", "ema200", "ema50_slope",
    # momentum + dollar-volume features (robot gate inputs; also enrich the dashboard)
    "ret_1m", "ret_3m", "ret_6m", "ret_1m_rank", "ret_3m_rank", "ret_6m_rank", "dollar_vol",
]

SECTORS = [
    "Sector", "Ticker_Count", "Breadth_Pct", "AD",
    "Daily", "Weekly", "Monthly", "YTD", "Avg_RSI", "Avg_RVOL", "Top3",
]

ROTATION = [
    "Sector", "X_raw", "Y_raw",
    "Sector_Return_Window", "Benchmark_Return_Window", "Excess_Return",
    "Tickers", "Vol_Confirmed_Pct", "X", "Y", "Quadrant", "Strength_Score",
]

ROTATION_TAIL = ["Sector", "Day_Offset", "X_raw", "Y_raw", "X", "Y"]

# filename -> required columns
SCHEMAS: dict[str, list[str]] = {
    "prices.parquet":        PRICES,
    "metrics.parquet":       METRICS,
    "sectors.parquet":       SECTORS,
    "rotation.parquet":      ROTATION,
    "rotation_tail.parquet": ROTATION_TAIL,
}


def missing_columns(name: str, df: pd.DataFrame) -> list[str]:
    """Required columns that are absent from df (empty list == contract met)."""
    return [c for c in SCHEMAS.get(name, []) if c not in df.columns]
