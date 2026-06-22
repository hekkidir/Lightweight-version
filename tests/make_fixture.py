"""
make_fixture.py — generate the deterministic test price dataset.

Run once to (re)create tests/fixtures/prices_sample.parquet. Seeded so the
output is byte-stable across machines: same seed -> same prices -> same golden
results. Re-run only when you intentionally want a new fixture shape.

    python tests/make_fixture.py
"""
from pathlib import Path

import numpy as np
import pandas as pd

FIXTURES = Path(__file__).parent / "fixtures"

N_DAYS   = 300                      # > 200 so ema200 + all windows are valid
SEED     = 42
SECTORS  = {
    "Software":   ["SOFA", "SOFB", "SOFC", "SOFD", "SOFE"],
    "Banks":      ["BNKA", "BNKB", "BNKC", "BNKD", "BNKE"],
    "Energy":     ["NRGA", "NRGB", "NRGC", "NRGD", "NRGE"],
    "Retail":     ["RTLA", "RTLB", "RTLC", "RTLD", "RTLE"],
    "Healthcare": ["HLTA", "HLTB", "HLTC", "HLTD", "HLTE"],
    "Industrial": ["INDA", "INDB", "INDC", "INDD", "INDE"],
}


def _series(rng: np.random.Generator) -> dict:
    """One ticker: GBM close with per-ticker drift/vol, plus OHLCV."""
    drift = rng.uniform(-0.0015, 0.0020)      # spread of up / flat / down trends
    vol   = rng.uniform(0.010, 0.030)
    start = rng.uniform(20, 200)

    shocks = rng.normal(drift, vol, N_DAYS)
    close  = start * np.exp(np.cumsum(shocks))

    intraday = np.abs(rng.normal(0, vol, N_DAYS)) * close
    high   = close + intraday * rng.uniform(0.3, 1.0, N_DAYS)
    low    = close - intraday * rng.uniform(0.3, 1.0, N_DAYS)
    open_  = low + (high - low) * rng.uniform(0, 1, N_DAYS)
    volume = rng.lognormal(13, 0.4, N_DAYS).round()
    return {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume}


def build() -> pd.DataFrame:
    rng   = np.random.default_rng(SEED)
    dates = pd.bdate_range(end="2025-12-31", periods=N_DAYS)
    rows  = []
    for sector, tickers in SECTORS.items():
        for t in tickers:
            s   = _series(rng)
            cap = float(rng.uniform(5e8, 5e11))   # spread of small -> mega cap
            df  = pd.DataFrame(s)
            df["Date"]       = dates
            df["Ticker"]     = t
            df["Sector"]     = sector
            df["Market_Cap"] = cap
            rows.append(df)
    out = pd.concat(rows, ignore_index=True)
    return out[["Date", "Ticker", "Open", "High", "Low", "Close",
                "Volume", "Sector", "Market_Cap"]]


if __name__ == "__main__":
    FIXTURES.mkdir(parents=True, exist_ok=True)
    df = build()
    path = FIXTURES / "prices_sample.parquet"
    df.to_parquet(path, index=False)
    print(f"Wrote {len(df)} rows ({df['Ticker'].nunique()} tickers x "
          f"{df['Date'].nunique()} days) -> {path}")
