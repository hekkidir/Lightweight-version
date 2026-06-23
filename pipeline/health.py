"""
health.py — data sanity checks for the built data dir.

check(data_dir) returns a list of human-readable problems ([] == healthy).
Used by `run.py check` (exit 1 on problems) and by CI / the /api/health route.
Catches the silent-wrong-data failures: missing files, dropped columns,
all-NaN columns, degenerate stage distribution.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from pipeline import schema
from pipeline.config import cfg

EXPECTED = [
    "prices.parquet", "metrics.parquet", "sectors.parquet",
    "rotation.parquet", "rotation_tail.parquet",
]


def coverage_gaps(prices: pd.DataFrame, lookback: int, min_frac: float) -> list[tuple]:
    """Recent trading days whose ticker coverage is below min_frac of the recent
    median — the signature of a throttled/partial download (e.g. 345 of 1079
    tickers). Settled bars only (a live-snapshot day is intentionally partial).
    Pure: no I/O. Returns [(date, count, median), ...] sorted by date."""
    if lookback <= 0 or prices.empty or "Date" not in prices.columns:
        return []
    df = prices
    if "Is_Synthetic" in df.columns:
        df = df[~df["Is_Synthetic"].fillna(False).astype(bool)]
    counts = df.groupby("Date")["Ticker"].nunique().sort_index()
    recent = counts.tail(lookback)
    if len(recent) < 3:
        return []
    median = float(recent.median())
    return [(d, int(c), int(median)) for d, c in recent.items()
            if c < median * min_frac]


def check(data_dir: Path) -> list[str]:
    problems: list[str] = []

    for name in EXPECTED:
        path = data_dir / name
        if not path.exists():
            problems.append(f"missing file: {name}")
            continue
        df = pd.read_parquet(path)
        if df.empty:
            problems.append(f"empty: {name}")
            continue

        miss = schema.missing_columns(name, df)
        if miss:
            problems.append(f"{name}: missing columns {miss}")

        # all-NaN check is scoped to the documented contract columns. A stray
        # extraneous all-NaN column (e.g. yfinance 'Adj Close') is cruft, not a
        # contract failure — download drops those at the source.
        for col in schema.SCHEMAS.get(name, []):
            if col in df.columns and df[col].isna().all():
                problems.append(f"{name}: required column '{col}' is entirely NaN")

    # prices coverage: a recent day with far fewer tickers than the norm is a
    # silent partial download — it force-exits held robots as 'data_missing' and
    # corrupts indicators. Flag it (ASCII-only: run.py prints these to cp1252).
    pp = data_dir / "prices.parquet"
    if pp.exists():
        try:
            pr = pd.read_parquet(pp, columns=["Date", "Ticker", "Is_Synthetic"])
        except (ValueError, KeyError):
            pr = pd.read_parquet(pp, columns=["Date", "Ticker"])
        for d, c, med in coverage_gaps(pr, cfg.download.backfill_lookback_days,
                                       cfg.download.backfill_min_frac):
            problems.append(f"prices: {d} has {c} tickers "
                            f"(recent median {med}) -- partial download?")

    # metrics-specific: a broken classifier shows up as a degenerate distribution
    mp = data_dir / "metrics.parquet"
    if mp.exists():
        m = pd.read_parquet(mp)
        if "Stage" in m.columns and len(m):
            if m["Stage"].nunique() <= 1:
                problems.append("metrics: stage distribution degenerate "
                                "(all tickers share one stage)")
            new_frac = (m["Stage"] == "New").mean()
            if new_frac > 0.5:
                problems.append(f"metrics: {new_frac:.0%} of tickers are 'New' "
                                "(insufficient price history?)")

    return problems
