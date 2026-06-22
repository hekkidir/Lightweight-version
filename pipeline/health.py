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

EXPECTED = [
    "prices.parquet", "metrics.parquet", "sectors.parquet",
    "rotation.parquet", "rotation_tail.parquet",
]


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
