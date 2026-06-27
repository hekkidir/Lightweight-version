"""
robots.py — the 5 strategy "robots" (standalone port of the backtest engine).

Stage 2b: candidate gates. Builds a per-ticker feature frame for the last
settled bar (full volume), computes GICS sector rotation (reusing rotation.py),
the multi-factor + dashboard scores, the volume recipes (A7/G5/G6), and the A4
stage/sector gate — then the 5 robots' candidate pools.

Faithful ports of backtest/scripts/{axes.py, volume_axes.py, live_signals.py}.
RSI here is Wilder (rsi_wilder) to match the backtest's gates.

(Stage 2c adds the portfolio sim → holdings/trades/equity; 2d assembles robots.json.)
"""
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline import indicators
from pipeline.config import Config

LIQ_MIN_DV = 50e6
SCORE_FLOOR = 2.39
GUCLEN_QW = {"STRONG": 1.9, "WARMING": 1.6, "COOLING": 1.1, "WEAK": 1.0}
# Execution model. Defaults = the user's: free brokerage + same-bar (signal-day
# close) fills. Set COST_PER_SIDE=0.0015 + NEXT_OPEN_FILL=True to reproduce the
# backtest exactly (it uses 0.30% round-trip costs and T+1 open fills).
COST_PER_SIDE = 0.0
NEXT_OPEN_FILL = False

# Backtest stage thresholds (config.yaml) — the robots use THESE, not LW's dashboard
# config.ini (which differs: rsi_2b 60 vs 55, rvol_confirm 1.1/21 vs 1.5/5).
BT_STAGE = {"rsi_2a_floor": 45.0, "rsi_2b": 55.0, "rsi_2c": 73.0, "ext_2c": 5.0,
            "rsi_4a_ceil": 55.0, "rsi_4b": 38.0, "rsi_4c": 27.0, "ext_4c": -3.0,
            "rsi_1b_floor": 40.0, "rsi_3b_ceil": 50.0}
BT_RVOL_CONFIRM, BT_RVOL_WINDOW = 1.5, 5

# Sector tilts (GICS) applied to the score — from strategies.py A2_GICS_WEIGHTS /
# B_SECTOR_WEIGHTS. Default 1.0 for unlisted sectors.
A2_GICS_WEIGHTS = {"Technology": 1.4, "Financial Services": 0.7,
                   "Consumer Defensive": 0.7, "Communication Services": 0.7}
B_SECTOR_WEIGHTS = {"Technology": 1.4, "Healthcare": 1.4,
                    "Financial Services": 0.7, "Energy": 0.8}
SECTOR_TILT = {"A": A2_GICS_WEIGHTS, "AV": A2_GICS_WEIGHTS,
               "B": B_SECTOR_WEIGHTS, "D": B_SECTOR_WEIGHTS,
               "A-G-W3": A2_GICS_WEIGHTS, "A-SCORE-CLUST": A2_GICS_WEIGHTS,
               "B-GATE-W3": B_SECTOR_WEIGHTS}
EXCLUDE_SECTORS = {"B": {"Financial Services"}, "D": {"Financial Services"},
                   "B-GATE-W3": {"Financial Services"}}
SKIP_TRIM = {"A", "AV", "A-G-W3", "A-SCORE-CLUST"}   # SA family: let winners run
VSCREEN_REPLACE = {"D"}        # G5 replaces the H4 momentum gate (vs AND-gating it)

# Per-key overrides for experimental variants. Keys absent here use the default.
VC_COL      = {"A-G-W3": "vc_w3", "B-GATE-W3": "vc_w3"}   # vol-gate column
SCORE_EXTRA = {                                               # additive score term
    "A-SCORE-CLUST": lambda sub: 0.5 * _z(sub["vol_cluster_10"].fillna(0)),
}
# Robots that fill at next-day OPEN (T+1) instead of the global default. The 3
# experimental variants reproduce the backtest, which decides on the close and
# fills the following open.
NEXT_OPEN_KEYS = {"A-G-W3", "A-SCORE-CLUST", "B-GATE-W3"}

# Exact backtest configs (strategies.py): key, name, gate kind, D_n, volume screen,
# sizing (C-axis), exit string. All weekly-rebalanced.
ROBOTS = [
    ("A",             "Strategy A — SA-DEF",                      "sa", 5, None, "C2",  "E1+E51+E56"),
    ("A-G-W3",        "A-G-W3 — SA-DEF, 3-day vol gate",         "sa", 5, None, "C2",  "E1+E51+E56"),
    ("A-SCORE-CLUST", "A-SCORE-CLUST — SA-DEF, cluster score",   "sa", 5, None, "C2",  "E1+E51+E56"),
    ("B-GATE-W3",     "Strategy B — B-GATE-W3",                   "sb", 3, None, "C8a", "E1+E24+E33+EVP"),
    ("C",             "Volume C — SV-A7 +10% floor",              "sv", 5, "A7", "C8a", "E1+E24+E33+E20"),
    ("D",             "Volume D — SB-HYB-G5-replace",             "sb", 6, "G5", "C8a", "E1+E24+E33"),
    ("AV",            "AV — SA-HYB-G6",                           "sa", 5, "G6", "C2",  "E1+E51+E56"),
]


def _size(cands: pd.DataFrame, variant: str) -> pd.Series:
    """Position weights (C-axis). C2 = score-weighted; C8a = steep pyramid (1/rank)."""
    n = len(cands)
    if n == 0:
        return pd.Series(dtype=float)
    if variant == "C2":
        s = cands["score"].clip(lower=0)
        return s / s.sum() if s.sum() > 0 else pd.Series(1.0 / n, index=cands.index)
    raw = 1.0 / np.arange(1, n + 1, dtype=float)        # C8a: cands already score-desc
    return pd.Series(raw / raw.sum(), index=cands.index)


def _should_exit(pos: dict, row: pd.Series, exit_str: str) -> tuple[bool, str]:
    """Faithful port of backtest engine.should_exit for the codes the robots use:
    E1 stage-flip, E20 −10% floor, E24 3·ATR floor, E33 4·ATR trail after +20%,
    E51 −7% floor, E56 EMA20-lock after +10%, EVP value-area-low break (needs vp_val)."""
    px = row.get("Close", np.nan)
    if pd.isna(px):
        return False, ""   # hold through a NaN bar (backtest keeps the row, notna-guarded)
    toks = set(exit_str.split("+"))
    entry, hwm = pos["entry_price"], pos["hwm"]
    gain = (px / entry - 1) if entry else 0.0
    peak = (hwm / entry - 1) if entry else 0.0
    atr, ema20, stage = row.get("atr", np.nan), row.get("ema20", np.nan), row.get("stage", "Chop")
    if "E1" in toks and stage in ("3A", "3B", "4A", "4B", "4C"):
        return True, "stage_flip"
    if "E20" in toks and gain < -0.10:
        return True, "floor_10pct"
    if "E24" in toks and pd.notna(atr) and px < entry - 3.0 * atr:
        return True, "floor_3atr"
    if "E33" in toks and peak >= 0.20 and pd.notna(atr) and px < hwm - 4.0 * atr:
        return True, "trail_4atr"
    if "E51" in toks and gain < -0.07:
        return True, "floor_7pct"
    if "E56" in toks and peak >= 0.10 and pd.notna(ema20) and px < ema20:
        return True, "ema20_lock"
    if "EVP" in toks:
        vval = row.get("vp_val", np.nan)
        if pd.notna(vval) and px < vval:
            return True, "vp_below_val"
    return False, ""


# ── Panels (computed once; reused for today's candidates + the sim) ────────────

def _load_prices(data_dir: Path) -> pd.DataFrame:
    prices = pd.read_parquet(data_dir / "prices.parquet")
    if "Market Cap" in prices.columns:
        prices = (prices.drop(columns=["Market Cap"]) if "Market_Cap" in prices.columns
                  else prices.rename(columns={"Market Cap": "Market_Cap"}))
    prices["Date"] = pd.to_datetime(prices["Date"])
    return prices


def _last_settled_date(prices: pd.DataFrame) -> pd.Timestamp:
    """The most recent REAL settled bar — never a live/intraday snapshot.
    download.py tags pre/regular-session snapshot bars with Is_Synthetic=True;
    those carry the prior day's placeholder Volume, which would corrupt the
    volume gates (RVOL, dollar-vol, A7/G5/G6 recipes). So the robots always
    evaluate on the last NON-synthetic bar, not just the second-to-last row."""
    dates = prices["Date"]
    if "Is_Synthetic" in prices.columns:
        dates = prices.loc[~prices["Is_Synthetic"].fillna(False).astype(bool), "Date"]
    return pd.Timestamp(dates.max())


def _robot_stages(g: pd.DataFrame, cfg: Config) -> pd.Series:
    """Exact port of backtest 02_compute_features.classify_stages (EMA-alignment +
    RSI/ext/slope), distinct from LW's regime-based classifier. Uses Wilder RSI +
    percent ext. Vectorised over the whole panel (element-wise)."""
    s = BT_STAGE
    c, e10, e20, e50 = g["Close"], g["ema10"], g["ema20"], g["ema50"]
    rsi, ext, slope = g["rsi_wilder"], g["ext"], g["ema50_slope"]
    up = (e10 > e20) & (e20 > e50)
    down = (e10 < e20) & (e20 < e50)
    side = ~up & ~down
    c2c = up & (c > e10) & (rsi >= s["rsi_2c"]) & (ext >= s["ext_2c"])
    c2b = up & (rsi >= s["rsi_2b"]) & ~c2c
    c2a = up & (rsi >= s["rsi_2a_floor"]) & ~c2b & ~c2c
    c4c = down & (c < e10) & (rsi <= s["rsi_4c"]) & (ext <= s["ext_4c"])
    c4b = down & (rsi <= s["rsi_4b"]) & ~c4c
    c4a = down & (rsi <= s["rsi_4a_ceil"]) & ~c4b & ~c4c
    c3b = side & (rsi <= s["rsi_3b_ceil"]) & (slope > 0)
    c3a = side & (c < e20) & (slope > 0) & ~c3b
    c1b = side & (rsi >= s["rsi_1b_floor"]) & (slope <= 0)
    c1a = side & (c > e20) & (slope <= 0) & ~c1b
    st = pd.Series("Chop", index=g.index, dtype=object)
    st = st.mask(c2c, "2C").mask(c2b, "2B").mask(c2a, "2A")
    st = st.mask(c4c, "4C").mask(c4b, "4B").mask(c4a, "4A")
    st = st.mask(c3b, "3B").mask(c3a, "3A")
    st = st.mask(c1b, "1B").mask(c1a, "1A")
    return st


def compute_full_panel(prices: pd.DataFrame, cfg: Config, gmap: dict) -> pd.DataFrame:
    """Per-(ticker,date) feature panel: indicators + ranks + money-flow + Wilder
    stages + GICS. Built once; sliced per date by _ft_for_day."""
    src = prices.sort_values(["Ticker", "Date"])
    panel = src.groupby("Ticker", group_keys=False).apply(lambda g: indicators._compute_group(g.copy(), cfg))
    panel["Ticker"] = src.loc[panel.index, "Ticker"]
    panel = indicators.add_cross_sectional_ranks(panel)
    panel = indicators.add_robot_features(panel)
    # Backtest-faithful ext for the robot stage: percent extension (C/ema50-1)*100,
    # NOT LW's ATR-normalized ext (the dashboard keeps its own). The stage thresholds
    # (ext_2c, ext_4c, healthy-2C ext<9) are calibrated for this percent form.
    panel["ext"] = (panel["Close"] / panel["ema50"].clip(lower=0.01) - 1) * 100
    # vol_confirmed — backtest formula: mean(vol, rvol_window) / mean(vol, 20) >= confirm.
    avg20 = panel.groupby("Ticker")["Volume"].transform(lambda x: x.rolling(20, min_periods=5).mean())
    rmean = panel.groupby("Ticker")["Volume"].transform(lambda x: x.rolling(BT_RVOL_WINDOW, min_periods=1).mean())
    panel["vol_confirmed"] = (rmean / avg20) >= BT_RVOL_CONFIRM
    panel["stage"] = _robot_stages(panel, cfg)
    panel["prev_stage"] = panel.groupby("Ticker")["stage"].shift(1).fillna("Chop")
    panel["GICS"] = panel["Ticker"].map(gmap)
    return panel


def gics_panel(prices: pd.DataFrame, gmap: dict, spy: pd.DataFrame) -> pd.DataFrame:
    """Per-(sector,date) GICS rotation, ported from backtest/03_compute_sectors.py:
    equal-weight sector return, excess vs SPY, X=cum_excess_252, Y=cum_excess_20,
    strength=(0.5·rank(X)+0.5·rank(Y))·5 (per-sector temporal rank), ΔY=Y.diff(5)."""
    df = prices.copy()
    df["Sector"] = df["Ticker"].map(gmap)
    df = df[df["Sector"].notna() & (df["Sector"] != "Unknown")].sort_values(["Ticker", "Date"])
    df["ret"] = df.groupby("Ticker")["Close"].pct_change()
    agg = df.groupby(["Sector", "Date"], as_index=False)["ret"].mean().rename(columns={"ret": "daily_ret"})
    spy = spy.copy()
    spy["Date"] = pd.to_datetime(spy["Date"])
    spy["spy_ret"] = spy["Close"].pct_change()
    agg = agg.merge(spy[["Date", "spy_ret"]], on="Date", how="left")
    agg["excess"] = agg["daily_ret"] - agg["spy_ret"]
    out = []
    for _sec, g in agg.sort_values("Date").groupby("Sector"):
        g = g.copy()
        x = g["excess"].rolling(252, min_periods=60).sum() * 100
        y = g["excess"].rolling(20, min_periods=10).sum() * 100
        g["strength_score"] = (0.5 * x.rank(pct=True) + 0.5 * y.rank(pct=True)) * 5
        g["delta_Y"] = y.diff(5)
        g["quadrant"] = np.select(
            [(x >= 0) & (y >= 0), (x < 0) & (y > 0), (x < 0) & (y <= 0)],
            ["STRONG", "WARMING", "WEAK"], "COOLING")
        out.append(g[["Sector", "Date", "strength_score", "delta_Y", "quadrant"]])
    return pd.concat(out, ignore_index=True)


def _ft_for_day(panel: pd.DataFrame, gp: pd.DataFrame, day) -> pd.DataFrame:
    """Cross-section for one day (indexed by Ticker) with GICS strength/quadrant
    mapped on and the güçlenen set in .attrs."""
    ft = panel[panel["Date"] == day].dropna(subset=["GICS"]).set_index("Ticker").copy()
    gpd = gp[gp["Date"] == day].set_index("Sector")
    ft["gics_strength"] = ft["GICS"].map(gpd["strength_score"]).fillna(0.0)
    ft["gics_quadrant"] = ft["GICS"].map(gpd["quadrant"]).fillna("WEAK")
    ft.attrs["guclen"] = _guclen_sectors(gpd.reset_index())
    ft.attrs["day"] = pd.Timestamp(day)
    return ft


def build_today(cfg: Config, data_dir: Path) -> pd.DataFrame:
    """Feature frame for the last settled bar — the most recent non-synthetic bar
    (see _last_settled_date; live-snapshot bars carry placeholder volume that
    would corrupt the volume gates)."""
    prices = _load_prices(data_dir)
    gmap = pd.read_csv(data_dir / "gics_map.csv").set_index("Ticker")["GICS_Sector"].to_dict()
    spy = pd.read_parquet(data_dir / "spy.parquet")
    panel = compute_full_panel(prices, cfg, gmap)
    gp = gics_panel(prices, gmap, spy)
    return _ft_for_day(panel, gp, _last_settled_date(prices))


def _guclen_sectors(rot_df: pd.DataFrame, n: int = 12) -> set:
    """Top-N strengthening GICS sectors by quadrant-weighted ΔY."""
    d = rot_df.copy()
    d["qw"] = d["quadrant"].map(GUCLEN_QW).fillna(1.0)
    d["score"] = d.groupby("quadrant")["delta_Y"].rank(pct=True) * d["qw"]
    return set(d.sort_values("score", ascending=False).head(n)["Sector"])


# ── Scores ────────────────────────────────────────────────────────────────────

def _z(series: pd.Series) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce")
    sd = s.std(skipna=True)
    if not np.isfinite(sd) or sd < 1e-9:
        return pd.Series(0.0, index=s.index)
    return ((s - s.mean(skipna=True)) / sd).clip(-3, 3).fillna(0)


def _multifactor(ft: pd.DataFrame) -> pd.Series:
    return (_z(ft["ret_1m"]) + _z(ft["ret_3m"]) + _z(ft["ret_6m"])
            + 0.5 * _z(ft["rsi_wilder"] - 50) + 0.3 * (-_z(ft["atr_pct"]))
            + 0.5 * _z(ft["Close"] / ft["ema50"].clip(lower=0.01) - 1)
            + 0.7 * _z(ft["gics_strength"]))


def _dashboard(ft: pd.DataFrame, graded: bool) -> pd.Series:
    rsi_term = ((ft["rsi_wilder"] - 50) / 20).clip(lower=0)
    if graded:
        surge = ft["dollar_vol_surge"].fillna(0.0).clip(0.0, 2.0)
        vol_mult = 1.0 + 0.25 * (surge / 2.0)
    else:
        vol_mult = np.where(ft["vol_confirmed"], 1.25, 1.0)
    stage_mult = np.where(ft["stage"] == "2C", 0.7, 1.0)
    return ft["gics_strength"] * rsi_term * vol_mult * stage_mult


def _shared(ft: pd.DataFrame) -> pd.Series:
    return (ft["ret_1m_rank"].fillna(0) + ft["ret_3m_rank"].fillna(0)
            + ft["ret_6m_rank"].fillna(0) + ft["rvol_rank_univ"].fillna(0))


# ── Gates & recipes ───────────────────────────────────────────────────────────

def _healthy_2c(ft, require_vc=True, vc_col="vol_confirmed"):
    m = (ft["stage"] == "2C") & (ft["Close"] > ft["ema10"]) & (ft["ext"] < 9) & ft["prev_stage"].isin(["2B", "2C"])
    return (m & ft[vc_col]) if require_vc else m


def _a4_gate(ft):
    stage_ok = ft["stage"].isin(["2A", "2B"]) | _healthy_2c(ft)
    sec_ok = ft["gics_quadrant"].isin(["STRONG", "WARMING"]) | ft["GICS"].isin(ft.attrs["guclen"])
    return stage_ok & sec_ok


def _sw_gate(ft, vc_col="vol_confirmed"):
    # engine.select_quant's _stage_sector_mask with univ='SW' (the base robots'
    # default): STRONG/WARMING only — NO güçlenen (that's the live-display A4 gate).
    stage_ok = ft["stage"].isin(["2A", "2B"]) | _healthy_2c(ft, vc_col=vc_col)
    return stage_ok & ft["gics_quadrant"].isin(["STRONG", "WARMING"])


def _q_gate(ft):
    stage_ok = ft["stage"].isin(["2A", "2B"]) | _healthy_2c(ft, require_vc=False)
    return stage_ok & (ft["dollar_vol"] >= LIQ_MIN_DV)


def _recipe_mask(rid, ft):
    if rid == "A7": return ft["updown_vol_ratio20"] >= 2.0
    if rid == "G5": return (ft["mfi14"] >= 70) & (ft["ret_1m"] > 0)
    if rid == "G6": return (ft["cmf20"] > 0) & ft["obv_rising"]
    return pd.Series(True, index=ft.index)


# ── Candidate pools ───────────────────────────────────────────────────────────

# Faithful port of engine.select_quant per family (this is the PORTFOLIO selector,
# used for both holdings and the displayed candidates). Key differences vs the
# old display logic: SB applies a HARD H4 momentum gate (all 3 ret-ranks ≥0.9)
# unless a volume recipe replaces it; sector tilts + Financial-Services exclusion.
def _candidates_for(key, kind, vscreen, ft, n=15):
    vc = VC_COL.get(key, "vol_confirmed")

    if kind == "sv":                                       # C — pure volume recipe
        mask = _q_gate(ft) & _recipe_mask(vscreen, ft).fillna(False)
        sub = ft[mask].copy()
        if sub.empty:
            return sub
        sub["score"] = _shared(sub)
        sub["reason"] = f"{vscreen} hacim · skor " + sub["score"].round(2).astype(str)
        return sub.nlargest(n, "score")

    if kind == "sa":                                       # A, AV — multi-factor
        mask = _sw_gate(ft, vc_col=vc) & ft[vc] & (ft["dollar_vol"] >= LIQ_MIN_DV) & ft["atr_pct"].between(2, 12)
        if vscreen:
            mask = mask & _recipe_mask(vscreen, ft).fillna(False)
        sub = ft[mask].copy()
        if sub.empty:
            return sub
        sub["score"] = _multifactor(sub)
        if key in SCORE_EXTRA:
            sub["score"] = sub["score"] + SCORE_EXTRA[key](sub)
        tilt = SECTOR_TILT.get(key)
        if tilt:
            sub["score"] = sub["score"] * sub["GICS"].map(tilt).fillna(1.0)
        sub["reason"] = "z-skor " + sub["score"].round(2).astype(str) + " + sektör"
        return sub.nlargest(n, "score")

    # sb (B, D) — dashboard score, hard H4 gate (unless a recipe replaces it)
    mask = _sw_gate(ft, vc_col=vc) & ft[vc]
    if key not in VSCREEN_REPLACE:
        mask = mask & (ft["ret_1m_rank"] >= 0.9) & (ft["ret_3m_rank"] >= 0.9) & (ft["ret_6m_rank"] >= 0.9)
    if vscreen:
        mask = mask & _recipe_mask(vscreen, ft).fillna(False)
    excl = EXCLUDE_SECTORS.get(key)
    if excl:
        mask = mask & ~ft["GICS"].isin(excl)
    sub = ft[mask].copy()
    if sub.empty:
        return sub
    sub["score"] = _dashboard(sub, graded=True)
    sub = sub[sub["score"] >= SCORE_FLOOR]
    if sub.empty:
        return sub
    tilt = SECTOR_TILT.get(key)
    if tilt:
        sub["score"] = sub["score"] * sub["GICS"].map(tilt).fillna(1.0)
    sub["reason"] = "H4 · dashboard · skor " + sub["score"].round(2).astype(str)
    return sub.nlargest(n, "score")


def candidates(cfg: Config, data_dir: Path, n=15) -> dict:
    """{key: candidate DataFrame} for all robots, on the last settled bar."""
    ft = build_today(cfg, data_dir)
    return {r[0]: _candidates_for(r[0], r[2], r[4], ft, n) for r in ROBOTS}


# ── Portfolio simulation ──────────────────────────────────────────────────────

def _close_trade(trades, t, p, exit_date, exit_px, reason):
    epx = p["entry_price"]
    ret = (exit_px / epx - 1) * 100 if (pd.notna(exit_px) and epx) else 0.0
    trades.append({"ticker": t, "entry_date": p["entry_date"].strftime("%Y-%m-%d"),
                   "exit_date": exit_date.strftime("%Y-%m-%d"), "return_pct": round(ret, 1),
                   "days_held": (exit_date - p["entry_date"]).days, "exit_reason": reason,
                   "entry_candidates": p["entry_cands"]})


def _mtm(cash, positions, closes, last_px=None):
    """Mark-to-market. A held position whose ticker has no bar today is valued at
    its last-known close (then entry price) instead of vanishing — mirrors the
    backtest, which keeps no-data days as NaN rows and holds the position through."""
    tot = cash
    for t, p in positions.items():
        px = closes.get(t, np.nan)
        if pd.isna(px) and last_px is not None:
            px = last_px.get(t, np.nan)
        if pd.isna(px):
            px = p["entry_price"]
        tot += p["shares"] * px
    return tot


def _simulate(rcfg, by_date, panel, gp, dates) -> dict:
    """Faithful port of engine.run_backtest for the 5 robots: decide on today's
    close, FILL AT NEXT-DAY OPEN (T+1) with costs; weekly Monday rebalance with
    Phase-A trim (skipped for let-winners-run) + Phase-B cash-capped buys."""
    key, name, kind, d_n, vscreen, sizing, exit_str = rcfg
    skip_trim = key in SKIP_TRIM
    next_open = NEXT_OPEN_FILL or key in NEXT_OPEN_KEYS   # per-robot T+1 fill
    cash, positions, equity, trades, rebal = 1.0, {}, [], [], None
    last_closes = pd.Series(dtype=float)
    last_px: dict = {}        # ticker -> last known close, for holding through data gaps

    def _fill(t, ndf, closes, fallback):
        if next_open and ndf is not None and t in ndf.index:
            px = ndf.loc[t, "Open"]
            if pd.notna(px):
                return px
        return closes.get(t, fallback)

    for i, d in enumerate(dates):
        ftd = by_date.get(d)
        if ftd is None:
            continue
        closes = ftd["Close"]
        last_closes = closes
        nd = dates[i + 1] if i + 1 < len(dates) else None
        ndf = by_date.get(nd) if nd is not None else None
        fdate = nd if (next_open and nd is not None) else d

        # 1. Exits: decide on today's close, execute at next-day open (T+1).
        # A held ticker absent today is HELD THROUGH the gap (frozen at last close),
        # not force-exited — matches the backtest, whose panel keeps no-data days as
        # NaN rows so the position stays in the index and rides the gap out.
        to_exit = []
        for t, p in positions.items():
            if t not in ftd.index:
                continue
            row = ftd.loc[t]
            px = row.get("Close", np.nan)
            if pd.notna(px):
                last_px[t] = float(px)
                if px > p["hwm"]:
                    p["hwm"] = px
            ex, reason = _should_exit(p, row, exit_str)
            if ex:
                to_exit.append((t, reason))
        for t, reason in to_exit:
            fp = _fill(t, ndf, closes, last_px.get(t, positions[t]["entry_price"]))
            cash += positions[t]["shares"] * fp * (1 - COST_PER_SIDE)
            _close_trade(trades, t, positions[t], fdate, fp, reason)
            del positions[t]

        # 2. Weekly (Monday) rebalance.
        if d.weekday() == 0:
            ft = _ft_for_day(panel, gp, d)
            cands = _candidates_for(key, kind, vscreen, ft, n=d_n)
            if len(cands):
                weights = _size(cands, sizing)
                cur_eq = _mtm(cash, positions, closes, last_px)
                target = {t: float(weights.get(t, 0)) * cur_eq for t in cands.index}
                tset = set(target)
                cand_list = [{"ticker": tt, "score": round(float(cands.loc[tt, "score"]), 2)}
                             for tt in list(cands.index)[:8]]
                added, dropped = [], []

                for t in list(positions):                      # rotate out names off the list
                    if t not in tset:
                        fp = _fill(t, ndf, closes, positions[t]["entry_price"])
                        cash += positions[t]["shares"] * fp * (1 - COST_PER_SIDE)
                        _close_trade(trades, t, positions[t], fdate, fp, "rebalance")
                        del positions[t]
                        dropped.append(t)

                if not skip_trim:                              # Phase A: trim overweight to target
                    for t in list(positions):
                        if t not in target:
                            continue
                        fp = _fill(t, ndf, closes, np.nan)
                        if pd.isna(fp):
                            continue
                        delta = target[t] - positions[t]["shares"] * fp
                        if delta >= -cur_eq * 0.005:
                            continue
                        sell = min(abs(delta) / (fp * (1 - COST_PER_SIDE)), positions[t]["shares"])
                        cash += sell * fp * (1 - COST_PER_SIDE)
                        positions[t]["shares"] -= sell
                        if positions[t]["shares"] < 1e-9:
                            del positions[t]

                for t in cands.index:                          # Phase B: buys (cash-capped)
                    fp = _fill(t, ndf, closes, np.nan)
                    if pd.isna(fp) or fp <= 0:
                        continue
                    if t in positions:
                        delta = target[t] - positions[t]["shares"] * fp
                        if delta <= cur_eq * 0.005:
                            continue
                        delta = min(delta, cash * 0.99)
                        if delta <= 0:
                            continue
                        positions[t]["shares"] += delta / (fp * (1 + COST_PER_SIDE))
                        cash -= delta
                    else:
                        cap = min(target[t], cash * 0.99)
                        if cap <= 0:
                            continue
                        positions[t] = dict(shares=cap / (fp * (1 + COST_PER_SIDE)),
                                            entry_price=fp, entry_date=fdate, hwm=fp, entry_cands=cand_list)
                        cash -= cap
                        added.append(t)
                rebal = {"date": d.strftime("%Y-%m-%d"), "added": added, "dropped": dropped}

        # 3. Mark to market at today's close.
        equity.append({"date": d.strftime("%Y-%m-%d"),
                       "value": round(_mtm(cash, positions, closes, last_px), 6)})

    return _finalize(rcfg, positions, trades, equity, rebal, dates[-1], last_closes, last_px)


def _finalize(rcfg, positions, trades, equity, rebal, last_date, last_closes, last_px=None) -> dict:
    key, name = rcfg[0], rcfg[1]
    last_px = last_px or {}
    e0 = equity[0]["value"] if equity else 1.0
    eq = [{"date": e["date"], "value": round(e["value"] / e0 * 100, 2)} for e in equity]

    def _last(t, p):
        v = last_px.get(t, last_closes.get(t, np.nan))
        return v if pd.notna(v) else p["entry_price"]

    final_val = sum(p["shares"] * _last(t, p) for t, p in positions.items()) or 1.0
    holdings = []
    for t, p in positions.items():
        px = _last(t, p)
        holdings.append({"ticker": t, "weight": round(p["shares"] * px / final_val, 2),
                         "entry_date": p["entry_date"].strftime("%Y-%m-%d"),
                         "return_pct": round((px / p["entry_price"] - 1) * 100, 1),
                         "days_held": (last_date - p["entry_date"]).days})
        trades.append({"ticker": t, "entry_date": p["entry_date"].strftime("%Y-%m-%d"),
                       "exit_date": None, "return_pct": round((px / p["entry_price"] - 1) * 100, 1),
                       "days_held": (last_date - p["entry_date"]).days, "exit_reason": "",
                       "entry_candidates": p["entry_cands"]})

    vals = np.array([e["value"] for e in equity]) if equity else np.array([1.0])
    rets = np.diff(vals) / vals[:-1] if len(vals) > 1 else np.array([0.0])
    peak = np.maximum.accumulate(vals)
    closed = [t for t in trades if t["exit_date"] is not None]
    stats = {
        "return_pct": round((vals[-1] / vals[0] - 1) * 100, 1),
        "cagr": round(((vals[-1] / vals[0]) ** (252 / len(vals)) - 1) * 100, 1) if len(vals) > 5 else 0.0,
        "max_dd": round((vals / peak - 1).min() * 100, 1),
        "sharpe": round(rets.mean() / rets.std() * np.sqrt(252), 2) if rets.std() > 1e-9 else 0.0,
        "win_rate": round(100 * np.mean([t["return_pct"] > 0 for t in closed])) if closed else 0,
        "n_trades": len(trades),
    }
    return {"name": name, "key": key, "inception": eq[0]["date"] if eq else None,
            "stats": stats, "equity": eq, "holdings": holdings, "trades": trades,
            "rebalance": rebal}


def _rebase(series: pd.Series, dates: list) -> list:
    s = series.reindex(pd.to_datetime(dates)).ffill()
    base = s.iloc[0] if len(s) and pd.notna(s.iloc[0]) else None
    if not base:
        return []
    return [{"date": d, "value": round(float(v) / base * 100, 2)} for d, v in zip(dates, s.values) if pd.notna(v)]


def build_robots(cfg: Config, data_dir: Path, lookback_days: int = 504) -> dict:
    """Full robots payload: simulate all 5 → holdings/trades/equity/stats, today's
    candidates, and the SPY benchmark rebased to each robot's inception."""
    from datetime import datetime
    prices = _load_prices(data_dir)
    gmap = pd.read_csv(data_dir / "gics_map.csv").set_index("Ticker")["GICS_Sector"].to_dict()
    spy = pd.read_parquet(data_dir / "spy.parquet")
    spy_s = spy.set_index(pd.to_datetime(spy["Date"]))["Close"]

    panel = compute_full_panel(prices, cfg, gmap)
    gp = gics_panel(prices, gmap, spy)
    all_dates = sorted(panel["Date"].unique())
    end = _last_settled_date(prices)                          # last non-synthetic bar
    sim_dates = [d for d in all_dates[252:] if d <= end][-lookback_days:]
    # Volume-profile value-area-low for the vp exit (EVP) — only needed over the sim
    # window; robots whose exit_str lacks EVP ignore the column, so they're unaffected.
    if sim_dates and any("EVP" in r[6] for r in ROBOTS):
        panel = indicators.add_vp_val(panel, since=sim_dates[0])
    by_date = {d: g.set_index("Ticker") for d, g in panel.groupby("Date")}
    today_ft = _ft_for_day(panel, gp, end)

    robots = []
    for rcfg in ROBOTS:
        out = _simulate(rcfg, by_date, panel, gp, sim_dates)
        cands = _candidates_for(rcfg[0], rcfg[2], rcfg[4], today_ft, n=15)
        out["candidates"] = [{"ticker": t, "score": round(float(cands.loc[t, "score"]), 2),
                              "reason": str(cands.loc[t, "reason"])} for t in cands.index]
        out["benchmarks"] = {"sp500": _rebase(spy_s, [e["date"] for e in out["equity"]])}
        robots.append(out)
    return {"generated_at": datetime.now().isoformat(timespec="seconds"), "robots": robots}


def run(cfg: Config, data_dir: Path) -> None:
    """Pipeline stage: simulate the robots and write data/robots.json.
    Skips gracefully if the GICS-map / SPY seeds aren't present."""
    import json
    if not (data_dir / "gics_map.csv").exists() or not (data_dir / "spy.parquet").exists():
        print("[robots] gics_map.csv or spy.parquet missing — skipping (no robots.json).")
        return
    print(f"[robots] Simulating {len(ROBOTS)} robots (this is the slow stage)...")
    payload = build_robots(cfg, data_dir, lookback_days=2000)
    (data_dir / "robots.json").write_text(json.dumps(payload), encoding="utf-8")
    n_h = sum(len(r["holdings"]) for r in payload["robots"])
    print(f"[robots] {len(payload['robots'])} robots, {n_h} holdings -> robots.json")


if __name__ == "__main__":  # quick sim sanity check
    from pipeline.config import load
    _cfg = load(Path(__file__).parent.parent / "config.ini")
    _out = build_robots(_cfg, Path(__file__).parent.parent / "data")
    for _r in _out["robots"]:
        _s = _r["stats"]
        print(f"{_r['key']:3} ret {_s['return_pct']:+6.1f}% cagr {_s['cagr']:+5.1f}% "
              f"dd {_s['max_dd']:+5.1f}% sharpe {_s['sharpe']:+.2f} | "
              f"{len(_r['holdings'])} holds, {_s['n_trades']} trades, "
              f"hold: {', '.join(h['ticker'] for h in _r['holdings'][:5])}")
