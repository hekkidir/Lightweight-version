"""
rotation.py — compute RRG (Relative Rotation Graph) positions.

run(cfg, data_dir) reads  data_dir/prices.parquet + data_dir/metrics.parquet
                   writes data_dir/rotation.parquet       current X/Y per sector
                          data_dir/rotation_tail.parquet  historical trail points
"""
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline.config import Config

# ── Cohesion ───────────────────────────────────────────────────────────────────

def _cohesion_weight(c: float, cfg) -> float:
    """Soft outlier weight: 0 below min, linear ramp 0.5->1.0, full above threshold."""
    if c is None or np.isnan(c):
        return 0.0
    if c >= cfg.rotation.cohesion_full:
        return 1.0
    if c < cfg.rotation.cohesion_min:
        return 0.0
    span = cfg.rotation.cohesion_full - cfg.rotation.cohesion_min
    return 0.5 + 0.5 * (c - cfg.rotation.cohesion_min) / span if span > 0 else 1.0


def _cohesion_scores(log_returns: pd.DataFrame, ticker_sector: dict, cfg) -> dict:
    """Compute per-ticker cohesion (correlation with sector median) over last N days."""
    window  = log_returns.tail(cfg.rotation.cohesion_window)
    scores  = {}
    for _sector, tickers in _group_tickers(ticker_sector, window.columns).items():
        if len(tickers) < 2:
            for t in tickers: scores[t] = np.nan
            continue
        ret    = window[tickers].ffill().fillna(0)
        median = ret.median(axis=1).values
        if np.std(median) < 1e-10:
            for t in tickers: scores[t] = np.nan
            continue
        for t in tickers:
            r = ret[t].values
            scores[t] = float(np.corrcoef(r, median)[0, 1]) if np.std(r) > 1e-10 else np.nan
    return scores


def _group_tickers(ticker_sector: dict, available: pd.Index) -> dict:
    """sector -> [tickers present in available columns]."""
    from collections import defaultdict
    groups = defaultdict(list)
    for t, s in ticker_sector.items():
        if pd.notna(s) and t in available:
            groups[s].append(t)
    return groups


# ── Sector daily return series ─────────────────────────────────────────────────

def _sector_returns(log_returns: pd.DataFrame, ticker_sector: dict,
                    ticker_mcap: dict, cohesion: dict, cfg) -> dict:
    """sector -> pd.Series of cohesion+mcap-weighted daily log-returns."""
    series = {}
    for sector, tickers in _group_tickers(ticker_sector, log_returns.columns).items():
        if len(tickers) < 2:
            continue
        ret = log_returns[tickers].ffill().fillna(0)
        if len(tickers) >= cfg.rotation.min_tickers_cohesion:
            weights = np.array([
                _cohesion_weight(cohesion.get(t, np.nan), cfg)
                * np.sqrt(max(ticker_mcap.get(t, 1) or 1, 1))
                for t in tickers
            ])
            if weights.sum() < 1e-10:
                series[sector] = ret.median(axis=1)
            else:
                series[sector] = pd.Series(
                    (ret.values * weights).sum(axis=1) / weights.sum(),
                    index=ret.index)
        else:
            # Small sector: trimmed mean (drop top/bottom 10%)
            n    = len(tickers)
            trim = max(1, round(n * 0.10))
            series[sector] = ret.apply(
                lambda row, n=n, trim=trim: np.sort(row.values)[trim:n - trim].mean()
                if (n - 2 * trim) > 0 else row.mean(), axis=1)
    return series


# ── RRG axes ───────────────────────────────────────────────────────────────────

def _xy(rs: pd.Series, window_pos: int, window_mom: int):
    if len(rs) <= max(window_pos, window_mom):
        return np.nan, np.nan
    x = float(rs.iloc[-1] - rs.iloc[-1 - window_pos])
    y = float((rs.iloc[-1] - rs.iloc[-1 - window_mom]) / window_mom)
    return x, y


def _quadrant(x, y) -> str:
    if x >= 0 and y >= 0: return "STRONG"
    if x <  0 and y >  0: return "WARMING"
    if x <  0 and y <= 0: return "WEAK"
    return "COOLING"


# ── Main entry ─────────────────────────────────────────────────────────────────

def compute_rotation(prices: pd.DataFrame, ticker_sector: dict, ticker_mcap: dict,
                     ticker_vc: dict, cfg: Config) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Pure RRG computation: (rotation_df, tail_df) for the given ticker→sector map.
    Reused by run() (custom sectors → the dashboard) and the robots stage (GICS)."""
    r   = cfg.rotation
    need = r.cohesion_window + r.window_position + r.window_momentum + r.tail_length + 5
    price_pivot = (prices.pivot(index="Date", columns="Ticker", values="Close")
                         .tail(need + 1))
    log_returns = np.log(price_pivot / price_pivot.shift(1)).iloc[1:]
    print(f"[rotation] {len(log_returns)} days x {log_returns.shape[1]} tickers")

    cohesion = _cohesion_scores(log_returns, ticker_sector, cfg)
    sec_ret  = _sector_returns(log_returns, ticker_sector, ticker_mcap, cohesion, cfg)

    bench = pd.DataFrame(sec_ret).mean(axis=1)   # equal-weight benchmark

    # RS series: cumulative (sector - benchmark), optionally EMA-smoothed
    rs_map = {}
    for sector, daily in sec_ret.items():
        rs = (daily.cumsum() - bench.cumsum())
        if r.ema_smooth > 1:
            rs = rs.ewm(span=r.ema_smooth, adjust=False).mean()
        rs_map[sector] = rs

    # Current X/Y + tails
    rot_rows, tail_rows = [], []
    for sector, rs in rs_map.items():
        x_now, y_now = _xy(rs, r.window_position, r.window_momentum)
        if np.isnan(x_now):
            continue

        sec_df  = pd.DataFrame(sec_ret)[sector] if sector in pd.DataFrame(sec_ret) else None
        sec_ret_w  = float(pd.DataFrame(sec_ret)[sector].iloc[-r.window_position:].sum()) if sec_df is not None else 0.0
        bench_ret_w= float(bench.iloc[-r.window_position:].sum())

        tickers_s = [t for t, s in ticker_sector.items() if s == sector]
        vc_pct = round(100 * sum(1 for t in tickers_s if ticker_vc.get(t, False)) / len(tickers_s), 1) if tickers_s else 0.0

        rot_rows.append({"Sector": sector, "X_raw": x_now, "Y_raw": y_now,
                         "Sector_Return_Window": sec_ret_w,
                         "Benchmark_Return_Window": bench_ret_w,
                         "Excess_Return": sec_ret_w - bench_ret_w,
                         "Tickers": len(tickers_s),
                         "Vol_Confirmed_Pct": vc_pct})

        for offset in range(r.tail_length, 0, -1):
            if len(rs) <= offset + max(r.window_position, r.window_momentum):
                continue
            x_o, y_o = _xy(rs.iloc[:len(rs) - offset], r.window_position, r.window_momentum)
            if not np.isnan(x_o):
                tail_rows.append({"Sector": sector, "Day_Offset": -offset,
                                  "X_raw": x_o, "Y_raw": y_o})

    rot_df  = pd.DataFrame(rot_rows)
    tail_df = pd.DataFrame(tail_rows)

    # Z-score normalise (same scale for dots and tails)
    x_mean, x_std = rot_df["X_raw"].mean(), rot_df["X_raw"].std()
    y_mean, y_std = rot_df["Y_raw"].mean(), rot_df["Y_raw"].std()
    x_std = x_std if x_std > 1e-10 else 1.0
    y_std = y_std if y_std > 1e-10 else 1.0

    rot_df["X"]  = ((rot_df["X_raw"]  - x_mean) / x_std).round(3)
    rot_df["Y"]  = ((rot_df["Y_raw"]  - y_mean) / y_std).round(3)
    rot_df["Quadrant"]       = rot_df.apply(lambda r: _quadrant(r["X"], r["Y"]), axis=1)
    rot_df["Strength_Score"] = np.sqrt(rot_df["X"]**2 + rot_df["Y"]**2).round(3)
    rot_df["Sector_Return_Window"]    = (rot_df["Sector_Return_Window"]    * 100).round(2)
    rot_df["Benchmark_Return_Window"] = (rot_df["Benchmark_Return_Window"] * 100).round(2)
    rot_df["Excess_Return"]           = (rot_df["Excess_Return"]           * 100).round(2)

    if not tail_df.empty:
        tail_df["X"] = ((tail_df["X_raw"] - x_mean) / x_std).round(3)
        tail_df["Y"] = ((tail_df["Y_raw"] - y_mean) / y_std).round(3)

    q_order = {"STRONG": 0, "WARMING": 1, "COOLING": 2, "WEAK": 3}
    rot_df  = (rot_df.assign(_q=rot_df["Quadrant"].map(q_order))
                     .sort_values(["_q", "Strength_Score"], ascending=[True, False])
                     .drop(columns="_q")
                     .reset_index(drop=True))
    return rot_df, tail_df


def run(cfg: Config, data_dir: Path) -> None:
    prices_file  = data_dir / "prices.parquet"
    metrics_file = data_dir / "metrics.parquet"
    rot_file     = data_dir / "rotation.parquet"
    tail_file    = data_dir / "rotation_tail.parquet"

    print("[rotation] Loading data...")
    prices  = pd.read_parquet(prices_file)
    metrics = pd.read_parquet(metrics_file)
    prices["Date"] = pd.to_datetime(prices["Date"])

    ticker_sector = dict(zip(metrics["Ticker"], metrics["Sector"]))
    ticker_mcap   = dict(zip(metrics["Ticker"], metrics["Market_Cap"].fillna(1)))
    ticker_vc     = dict(zip(metrics["Ticker"], metrics["Vol_Confirmed"].fillna(False)))

    rot_df, tail_df = compute_rotation(prices, ticker_sector, ticker_mcap, ticker_vc, cfg)

    rot_df.to_parquet(rot_file,  index=False)
    tail_df.to_parquet(tail_file, index=False)
    print(f"[rotation] {len(rot_df)} sectors, {len(tail_df)} tail points saved")
