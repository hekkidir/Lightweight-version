"""Tests for download helpers — the self-healing coverage backfill (offline)."""
from datetime import date, timedelta

import pandas as pd

from pipeline import download
from pipeline.config import load

BASE = date(2026, 1, 1)
COLS = ["Open", "High", "Low", "Close", "Volume"]


def _bar(d, t, **extra):
    row = {"Date": d, "Ticker": t, **{c: 1.0 for c in COLS}}
    row.update(extra)
    return row


def test_backfill_fills_throttled_day(monkeypatch):
    """A recent day with only 10/50 tickers gets the 40 missing bars backfilled,
    with Sector/Market_Cap/Is_Synthetic restored — without re-fetching everything."""
    cfg = load()
    tickers = [f"T{t}" for t in range(50)]
    rows = [_bar(BASE + timedelta(days=i), t, Sector="X", Market_Cap=1.0,
                 Is_Synthetic=False)
            for i in range(9) for t in tickers]
    rows += [_bar(BASE + timedelta(days=9), t, Sector="X", Market_Cap=1.0,
                  Is_Synthetic=False) for t in tickers[:10]]   # throttled day
    combined = pd.DataFrame(rows)

    def fake_fetch(missing, _cfg, start=None, period=None):
        return pd.DataFrame([_bar(BASE + timedelta(days=9), t) for t in missing])
    monkeypatch.setattr(download, "download_prices", fake_fetch)

    out, n = download._backfill_recent_gaps(
        combined, tickers, cfg, {t: "X" for t in tickers}, {t: 1.0 for t in tickers})

    day9 = out[out["Date"] == BASE + timedelta(days=9)]
    assert n == 40
    assert day9["Ticker"].nunique() == 50          # day repaired to full coverage
    assert not day9["Is_Synthetic"].any()          # backfilled bars are real
    assert day9["Sector"].eq("X").all()            # metadata restored


def test_backfill_noop_when_full(monkeypatch):
    cfg = load()
    tickers = [f"T{t}" for t in range(50)]
    combined = pd.DataFrame(
        [_bar(BASE + timedelta(days=i), t, Sector="X", Market_Cap=1.0,
              Is_Synthetic=False)
         for i in range(10) for t in tickers])

    def fail_fetch(*a, **k):
        raise AssertionError("download_prices must not be called when coverage is full")
    monkeypatch.setattr(download, "download_prices", fail_fetch)

    out, n = download._backfill_recent_gaps(
        combined, tickers, cfg, {t: "X" for t in tickers}, {t: 1.0 for t in tickers})
    assert n == 0 and len(out) == len(combined)
