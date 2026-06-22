"""Unit tests for the stage classifier (pure function, no I/O)."""
import numpy as np
import pandas as pd

from pipeline.indicators import classify_stages


def _row(**kw):
    base = dict(ema50_slope=0.0, Close=100.0, ema10=100.0, ema20=100.0,
                ema50=100.0, ema200=100.0, rsi=50.0, ext=0.0, rvol_avg=1.0)
    base.update(kw)
    return base


def _df(*rows):
    return pd.DataFrame(list(rows))


def test_strict_uptrend_healthy_rsi_is_2b(cfg):
    df = _df(_row(ema50_slope=0.05, Close=110, ema10=108, ema20=105,
                  ema50=102, ema200=100, rsi=62, ext=2))
    stage, regime, _ = classify_stages(df, cfg)
    assert regime.iloc[0] == 2
    assert stage.iloc[0] == "2B"


def test_overextended_extreme_rsi_is_2c(cfg):
    df = _df(_row(ema50_slope=0.05, Close=140, ema10=130, ema20=120,
                  ema50=110, ema200=100, rsi=80, ext=7))
    stage, _, _ = classify_stages(df, cfg)
    assert stage.iloc[0] == "2C"


def test_incomplete_history_is_new(cfg):
    df = _df(_row(ema50_slope=np.nan))
    stage, regime, _ = classify_stages(df, cfg)
    assert stage.iloc[0] == "New"
    assert regime.iloc[0] == 0


def test_vol_confirmed_rounding_edge(cfg):
    # raw 1.0994 < 1.1 but rounds to 1.10 -> must confirm (the bug we fixed).
    _, _, vc = classify_stages(_df(_row(rvol_avg=1.0994)), cfg)
    assert bool(vc.iloc[0]) is True

    _, _, vc = classify_stages(_df(_row(rvol_avg=1.04)), cfg)
    assert bool(vc.iloc[0]) is False
