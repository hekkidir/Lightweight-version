"""Tests for the data health check."""
from datetime import date, timedelta

import pandas as pd

from pipeline.health import check, coverage_gaps


def test_built_data_is_healthy(built_data):
    assert check(built_data) == []


def test_empty_dir_reports_missing_files(tmp_path):
    problems = check(tmp_path)
    assert any("missing file" in p for p in problems)


# ── coverage_gaps (partial-download detection) ──────────────────────────────────

def _panel(coverage_by_day, synthetic_by_day=None):
    """Build a Date/Ticker/Is_Synthetic frame from {day_index: n_tickers}."""
    base, rows = date(2026, 1, 1), []
    for i, n in coverage_by_day.items():
        for t in range(n):
            rows.append({"Date": base + timedelta(days=i),
                         "Ticker": f"T{t}", "Is_Synthetic": False})
    for i, n in (synthetic_by_day or {}).items():
        for t in range(n):
            rows.append({"Date": base + timedelta(days=i),
                         "Ticker": f"T{t}", "Is_Synthetic": True})
    return pd.DataFrame(rows)


def test_coverage_gaps_flags_partial_day():
    cov = {i: 100 for i in range(9)}
    cov[9] = 30                                   # one throttled day
    gaps = coverage_gaps(_panel(cov), lookback=15, min_frac=0.97)
    assert len(gaps) == 1
    d, c, med = gaps[0]
    assert (c, med) == (30, 100)


def test_coverage_gaps_clean_when_full():
    assert coverage_gaps(_panel({i: 100 for i in range(10)}), 15, 0.97) == []


def test_coverage_gaps_ignores_synthetic_partial_day():
    # the latest day is a partial LIVE snapshot (synthetic), not a real gap
    panel = _panel({i: 100 for i in range(9)}, synthetic_by_day={9: 20})
    assert coverage_gaps(panel, 15, 0.97) == []


def test_coverage_gaps_disabled_with_zero_lookback():
    cov = {i: 100 for i in range(9)}
    cov[9] = 10
    assert coverage_gaps(_panel(cov), lookback=0, min_frac=0.97) == []
