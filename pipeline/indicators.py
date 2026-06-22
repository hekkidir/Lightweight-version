"""
indicators.py — compute technical indicators and classify stages.

run(cfg, data_dir) reads  data_dir/prices.parquet
                   writes data_dir/metrics.parquet

Each row in metrics.parquet is one ticker on the latest trading date.
"""
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline.config import Config

# ── Per-ticker indicator computation ──────────────────────────────────────────

def _compute_group(group: pd.DataFrame, cfg) -> pd.DataFrame:
    """Add all indicator columns to a single-ticker sorted DataFrame."""
    c = group["Close"]
    v = group["Volume"]

    group["change_pct"] = c.pct_change() * 100
    group["ema10"]      = c.ewm(span=10,  adjust=False).mean()
    group["ema20"]      = c.ewm(span=20,  adjust=False).mean()
    group["ema50"]      = c.ewm(span=50,  adjust=False).mean()
    group["ema200"]     = c.ewm(span=200, adjust=False).mean()
    group["ema50_slope"]= group["ema50"].pct_change(cfg.stages.slope_window)

    tr = pd.concat([
        group["High"] - group["Low"],
        (group["High"] - c.shift(1)).abs(),
        (group["Low"]  - c.shift(1)).abs(),
    ], axis=1).max(axis=1)
    group["atr"]     = tr.ewm(alpha=1/14, adjust=False).mean()
    group["atr_pct"] = (group["atr"] / c) * 100
    group["ext"]     = ((c / group["ema50"]) - 1) / (group["atr"] / c)

    delta = c.diff()
    gain  = delta.where(delta > 0, 0).ewm(span=14, adjust=False).mean()
    loss  = (-delta.where(delta < 0, 0)).ewm(span=14, adjust=False).mean()
    group["rsi"]      = 100 - (100 / (1 + gain / (loss + 1e-10)))
    group["rvol"]     = v / v.rolling(window=20).mean()
    group["rvol_avg"] = group["rvol"].rolling(window=cfg.stages.rvol_window,
                                               min_periods=1).mean()

    yr = group["Date"].dt.year.max()
    yr_start = group[group["Date"].dt.year == yr]
    fc = yr_start.iloc[0]["Close"] if not yr_start.empty else c.iloc[0]
    group["ytd"] = ((c - fc) / fc) * 100

    n = len(group)
    group["weekly"]  = ((c - c.shift(5))  / c.shift(5)  * 100) if n > 5  else 0.0
    group["monthly"] = ((c - c.shift(21)) / c.shift(21) * 100) if n > 21 else 0.0

    # Momentum returns (1m=21d, 3m=63d, 6m=126d) + daily dollar volume — inputs to
    # the robot gates (cross-sectional ranks of these are added in run()).
    group["ret_1m"]     = c.pct_change(21)
    group["ret_3m"]     = c.pct_change(63)
    group["ret_6m"]     = c.pct_change(126)
    group["dollar_vol"] = c * v

    return group


def add_cross_sectional_ranks(df: pd.DataFrame) -> pd.DataFrame:
    """Per-date percentile rank (0..1) of 1m/3m/6m returns across the universe.
    Shared by run() (today's bar -> metrics) and the robots stage (full history)."""
    for col in ("ret_1m", "ret_3m", "ret_6m"):
        df[f"{col}_rank"] = df.groupby("Date")[col].rank(pct=True)
    return df


# ── Robot-only money-flow features (not in metrics.parquet; used by pipeline/robots) ──
# Faithful ports of backtest/sv_build_features.py. RSI here is Wilder (alpha=1/14),
# matching the backtest's gates — distinct from the dashboard's ewm(span=14) rsi.

def _robot_group(g: pd.DataFrame) -> pd.DataFrame:
    c, h, l, v = g["Close"], g["High"], g["Low"], g["Volume"]
    dc = c.diff()
    obv = (np.sign(dc).fillna(0) * v).cumsum()
    g["obv_rising"] = obv > obv.shift(20)

    hl = (h - l).replace(0, np.nan)
    mfv = (((c - l) - (h - c)) / hl * v).fillna(0)            # money-flow volume
    g["cmf20"] = mfv.rolling(20, min_periods=10).sum() / v.rolling(20, min_periods=10).sum()

    tp = (h + l + c) / 3.0
    rmf, tpc = tp * v, tp.diff()
    pos = rmf.where(tpc > 0, 0.0).rolling(14, min_periods=7).sum()
    neg = rmf.where(tpc < 0, 0.0).rolling(14, min_periods=7).sum()
    g["mfi14"] = 100 - (100 / (1 + pos / neg.replace(0, np.nan)))

    dvol = g["dollar_vol"].astype(float)
    dvol20 = dvol.rolling(20, min_periods=10).mean()
    g["dollar_vol_surge"] = (dvol - dvol20) / dvol.rolling(20, min_periods=10).std().replace(0, np.nan)

    up = v.where(dc > 0, 0.0).rolling(20, min_periods=10).sum()
    dn = v.where(dc < 0, 0.0).rolling(20, min_periods=10).sum()
    g["updown_vol_ratio20"] = up / dn.replace(0, np.nan)

    up_w = dc.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    dn_w = (-dc.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    g["rsi_wilder"] = 100 - (100 / (1 + up_w / dn_w.replace(0, np.nan)))
    return g


def add_robot_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add money-flow + Wilder-RSI features (per ticker) and rvol_rank_univ
    (cross-sectional). Expects dollar_vol + rvol already present (from _compute_group)."""
    src = df.sort_values(["Ticker", "Date"])
    out = src.groupby("Ticker", group_keys=False).apply(_robot_group)
    out["Ticker"] = src.loc[out.index, "Ticker"]      # pandas 3: restore dropped key
    out["rvol_rank_univ"] = out.groupby("Date")["rvol"].rank(pct=True)
    return out


# ── Stage classifier (vectorized, two-axis stair-step) ────────────────────────

def classify_stages(df: pd.DataFrame, cfg) -> tuple:
    """
    Returns (stage, regime, vol_confirmed) as three Series aligned to df.index.

    Regime axis  — EMA50 slope: 1=basing, 2=advancing, 3=topping, 4=declining
    Phase  axis  — EMA alignment + RSI + extension thresholds from cfg.stages
    Vol_Confirmed — rvol_avg (rounded to 2dp) >= rvol_confirm
    """
    s = cfg.stages
    slope    = df["ema50_slope"]
    c        = df["Close"]
    ema10    = df["ema10"]
    ema20    = df["ema20"]
    ema50    = df["ema50"]
    above200 = c > df["ema200"]
    rsi      = df["rsi"]
    ext      = df["ext"]
    rvol_avg = df["rvol_avg"]

    rising  = slope >  s.slope_threshold
    falling = slope < -s.slope_threshold
    flat    = slope.abs() <= s.slope_threshold

    regime = pd.Series(0, index=df.index, dtype=int)
    regime[rising  &  above200] = 2
    regime[falling & ~above200] = 4
    regime[flat    & ~above200] = 1
    regime[flat    &  above200] = 3
    regime[rising  & ~above200] = 2   # early breakout
    regime[falling &  above200] = 3   # early rollover

    ema_loose_up  = (ema10 > ema20) & (ema10 > ema50)
    ema_strict_up = (ema10 > ema20) & (ema20 > ema50)
    ema_loose_dn  = (ema10 < ema20) & (ema10 < ema50)
    ema_strict_dn = (ema10 < ema20) & (ema20 < ema50)

    stage = pd.Series("Chop", index=df.index)
    m2 = regime == 2
    stage[m2 & ema_strict_up & (rsi >= s.rsi_2c) & (ext >= s.ext_2c)] = "2C"
    stage[m2 & ema_strict_up & (stage == "Chop") & (rsi >= s.rsi_2b)] = "2B"
    stage[m2 & ema_loose_up  & (stage == "Chop") & (rsi >= s.rsi_2a_floor)] = "2A"

    m4 = regime == 4
    stage[m4 & ema_strict_dn & ((rsi <= s.rsi_4c) | (ext <= s.ext_4c))] = "4C"
    stage[m4 & ema_strict_dn & (stage == "Chop") & (rsi <= s.rsi_4b)] = "4B"
    stage[m4 & ema_loose_dn  & (stage == "Chop") & (rsi <= s.rsi_4a_ceil)] = "4A"

    m1 = regime == 1
    stage[m1 & ((ema10 > ema20) | (c > ema50)) & (rsi >= s.rsi_1b_floor)] = "1B"
    stage[m1 & (stage == "Chop")] = "1A"

    m3 = regime == 3
    stage[m3 & ((ema10 < ema20) | (c < ema50)) & (rsi <= s.rsi_3b_ceil)] = "3B"
    stage[m3 & (stage == "Chop")] = "3A"

    incomplete = slope.isna() | df["ema200"].isna()
    stage[incomplete] = "New"
    regime[incomplete] = 0

    vol_confirmed = (rvol_avg.round(2) >= s.rvol_confirm).fillna(False)
    return stage, regime, vol_confirmed


# ── Main entry ─────────────────────────────────────────────────────────────────

def run(cfg: Config, data_dir: Path) -> None:
    prices_file  = data_dir / "prices.parquet"
    metrics_file = data_dir / "metrics.parquet"

    print("[indicators] Loading prices...")
    df = pd.read_parquet(prices_file)
    if "Market Cap" in df.columns:
        if "Market_Cap" in df.columns:
            df = df.drop(columns=["Market Cap"])
        else:
            df = df.rename(columns={"Market Cap": "Market_Cap"})
    df["Date"] = pd.to_datetime(df["Date"])

    print("[indicators] Computing indicators per ticker...")
    df_orig = df.sort_values(["Ticker", "Date"]).copy()
    df = df_orig.groupby("Ticker", group_keys=False).apply(lambda g: _compute_group(g.copy(), cfg))
    # pandas 3: groupby key excluded from apply result — restore from original index
    df["Ticker"] = df_orig.loc[df.index, "Ticker"]
    df = add_cross_sectional_ranks(df)   # ranks need the whole cross-section per date

    all_dates   = sorted(df["Date"].unique())
    latest_date = all_dates[-1]

    # Per-ticker latest bar (not the single global latest date). A ticker that
    # missed today's live snapshot falls back to its most recent real bar
    # instead of vanishing. Tickers whose last bar is older than max_stale_bars
    # trading days (likely delisted) are dropped so we never show weeks-old data.
    fresh_dates = set(all_dates[-(cfg.stages.max_stale_bars + 1):])
    last_idx    = df.groupby("Ticker")["Date"].idxmax()
    today_df    = df.loc[last_idx.values]
    today_df    = today_df[today_df["Date"].isin(fresh_dates)].copy()

    n_today    = int((today_df["Date"] == latest_date).sum())
    n_fallback = len(today_df) - n_today
    print(f"[indicators] Classifying {len(today_df)} tickers "
          f"({n_today} on {pd.Timestamp(latest_date).date()}, "
          f"{n_fallback} on a prior bar)...")
    today_df["Stage"], today_df["Regime"], today_df["Vol_Confirmed"] = classify_stages(today_df, cfg)

    # Previous bar per ticker (the row right before each ticker's latest) drives
    # the stage-transition arrows. Computed per ticker so fallback tickers still
    # compare against their own prior session, not a mismatched global date.
    prior     = df.drop(index=last_idx.values)
    prev_df   = prior.loc[prior.groupby("Ticker")["Date"].idxmax().values] if len(prior) else prior
    if len(prev_df):
        prev_stage, _, _       = classify_stages(prev_df, cfg)
        prev_lookup            = prev_df.assign(Prev_Stage=prev_stage).set_index("Ticker")["Prev_Stage"]
        today_df["Prev_Stage"] = today_df["Ticker"].map(prev_lookup).fillna("")
    else:
        today_df["Prev_Stage"] = ""

    dist = today_df["Stage"].value_counts().to_dict()
    vc   = int(today_df["Vol_Confirmed"].sum())
    print(f"[indicators] Distribution: {dist}")
    print(f"[indicators] Vol_Confirmed: {vc}/{len(today_df)} "
          f"(rvol_avg>={cfg.stages.rvol_confirm} over {cfg.stages.rvol_window}d)")

    cols = ["Ticker", "Sector", "Market_Cap", "Close", "change_pct",
            "Stage", "Prev_Stage", "Regime", "Vol_Confirmed",
            "ytd", "weekly", "monthly", "atr_pct", "ext", "rsi", "rvol", "rvol_avg",
            "ema10", "ema20", "ema50", "ema200", "ema50_slope",
            "ret_1m", "ret_3m", "ret_6m", "ret_1m_rank", "ret_3m_rank", "ret_6m_rank", "dollar_vol"]
    out = today_df[[c for c in cols if c in today_df.columns]].copy()

    for col in ["change_pct", "ytd", "weekly", "monthly", "atr_pct", "ext", "rvol", "rvol_avg"]:
        if col in out.columns:
            out[col] = out[col].round(2)
    for col in ["rsi"]:
        if col in out.columns:
            out[col] = out[col].round(1)
    for col in ["ret_1m", "ret_3m", "ret_6m", "ret_1m_rank", "ret_3m_rank", "ret_6m_rank"]:
        if col in out.columns:
            out[col] = out[col].round(4)
    if "dollar_vol" in out.columns:
        out["dollar_vol"] = out["dollar_vol"].round(0)

    out.to_parquet(metrics_file, index=False)
    print(f"[indicators] {len(out)} rows saved -> {metrics_file.name}")
