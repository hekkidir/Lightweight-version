"""
download.py — fetch OHLCV prices and market cap from yfinance.

run(cfg, data_dir) writes:
    data_dir/prices.parquet   full price history for all tickers
    data_dir/mcap.parquet     market cap cache with TTL
"""
import contextlib
import csv as _csv
import io
import logging
import random
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from datetime import time as dtime
from pathlib import Path

import pandas as pd
import yfinance as yf

from pipeline import schema
from pipeline.config import Config, runtime
from pipeline.health import coverage_gaps

# Suppress yfinance's direct-print "possibly delisted" and "N Failed downloads"
# messages — false positives from rate-limiting, not real delistings.
# We do our own per-chunk miss detection and report it cleanly.
logging.getLogger("yfinance").setLevel(logging.ERROR)


# ── US Market Holiday Calendar (NYSE) ─────────────────────────────────────────
# Hardcoded — no extra dependency. Add new years as they get published.
# Source: nyse.com/markets/hours-calendars
US_MARKET_HOLIDAYS = {
    # 2025
    date(2025, 1, 1),   date(2025, 1, 20),  date(2025, 2, 17),
    date(2025, 4, 18),  date(2025, 5, 26),  date(2025, 6, 19),
    date(2025, 7, 4),   date(2025, 9, 1),   date(2025, 11, 27),
    date(2025, 12, 25),
    # 2026
    date(2026, 1, 1),   date(2026, 1, 19),  date(2026, 2, 16),
    date(2026, 4, 3),   date(2026, 5, 25),  date(2026, 6, 19),
    date(2026, 7, 3),   date(2026, 9, 7),   date(2026, 11, 26),
    date(2026, 12, 25),
    # 2027
    date(2027, 1, 1),   date(2027, 1, 18),  date(2027, 2, 15),
    date(2027, 3, 26),  date(2027, 5, 31),  date(2027, 6, 18),
    date(2027, 7, 5),   date(2027, 9, 6),   date(2027, 11, 25),
    date(2027, 12, 24),
    # 2028
    date(2028, 1, 17),  date(2028, 2, 21),  date(2028, 4, 14),
    date(2028, 5, 29),  date(2028, 6, 19),  date(2028, 7, 4),
    date(2028, 9, 4),   date(2028, 11, 23), date(2028, 12, 25),
}

_PRE_MARKET_START = dtime(4, 0)
_PRE_MARKET_END   = dtime(9, 30)
_REGULAR_END      = dtime(16, 0)
_AFTER_HOURS_END  = dtime(20, 0)


def _et_now():
    """Return current US/Eastern datetime (tz-aware), or None if zoneinfo unavailable."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        return None


def last_market_day(d: date) -> date:
    """Most recent NYSE trading day on or before d. Skips weekends + holidays."""
    while d.weekday() >= 5 or d in US_MARKET_HOLIDAYS:
        d -= timedelta(days=1)
    return d


def us_market_session() -> str:
    """Return current US market session: 'pre', 'regular', 'after', or 'closed'.
    Weekends and NYSE holidays always return 'closed'."""
    et = _et_now()
    if et is None:
        return 'closed'
    if et.weekday() >= 5 or et.date() in US_MARKET_HOLIDAYS:
        return 'closed'
    t = et.time()
    if _PRE_MARKET_START <= t < _PRE_MARKET_END:
        return 'pre'
    if _PRE_MARKET_END   <= t < _REGULAR_END:
        return 'regular'
    if _REGULAR_END      <= t < _AFTER_HOURS_END:
        return 'after'
    return 'closed'


# ── Ticker list ────────────────────────────────────────────────────────────────

def load_tickers(tickers_file: Path) -> pd.DataFrame:
    """Load tickers.csv -> DataFrame[Ticker, Sector].
    Auto-repairs rows mangled by Excel quoting (sectors with commas in name)."""
    df = pd.read_csv(tickers_file, encoding="utf-8-sig")
    bad = df["Ticker"].str.contains(",", na=False)
    if bad.any():
        for idx, row in df[bad].iterrows():
            try:
                parts = next(_csv.reader([row["Ticker"]]))
                if len(parts) >= 3:
                    df.at[idx, "Ticker"]   = parts[0].strip()
                    df.at[idx, "Company"]  = parts[1].strip()
                    df.at[idx, "Industry"] = parts[2].strip()
            except Exception:
                pass
        df.to_csv(tickers_file, index=False, encoding="utf-8-sig")
    return df


# ── Market cap ─────────────────────────────────────────────────────────────────

def _fetch_one_mcap(ticker: str):
    time.sleep(random.uniform(0.2, 0.5))
    try:
        return ticker, yf.Ticker(ticker).fast_info.market_cap
    except Exception:
        return ticker, None


def refresh_mcap(tickers: list[str], mcap_file: Path, cfg: Config) -> dict:
    """Return {ticker: mcap}. Uses cache; re-fetches all if stale."""
    cache, cache_age = {}, 9999
    if mcap_file.exists():
        try:
            df = pd.read_parquet(mcap_file)
            cache_age = (date.today() - pd.to_datetime(df["last_updated"]).dt.date.max()).days
            cache = dict(zip(df["Ticker"], df["market_cap"]))
        except Exception:
            pass

    if cache_age >= cfg.data.mcap_refresh_days:
        targets = tickers
        print(f"  MCap: refreshing all {len(targets)} tickers (cache {cache_age}d old)")
    else:
        targets = [t for t in tickers if t not in cache]
        if targets:
            print(f"  MCap: fetching {len(targets)} new tickers")

    if targets:
        with ThreadPoolExecutor(max_workers=5) as ex:
            cache.update(dict(ex.map(_fetch_one_mcap, targets)))
        rows = [{"Ticker": t, "market_cap": v, "last_updated": date.today()}
                for t, v in cache.items()]
        pd.DataFrame(rows).to_parquet(mcap_file, index=False)
    return cache


# ── Price download ─────────────────────────────────────────────────────────────

def _one_pass(tickers, start, period, chunk_size, sleep_range):
    parts = []
    start_str = start.strftime("%Y-%m-%d") if start else None
    for i in range(0, len(tickers), chunk_size):
        chunk = tickers[i:i + chunk_size]
        print(f"  Batch {i + len(chunk)}/{len(tickers)}...", end="", flush=True)
        try:
            # Redirect stdout+stderr: yfinance batch downloader uses direct print()
            # for "possibly delisted" and "N Failed downloads" — false positives
            # caused by rate-limiting. We do our own miss detection below.
            _sink = io.StringIO()
            with contextlib.redirect_stdout(_sink), contextlib.redirect_stderr(_sink):
                raw = yf.download(chunk, start=start_str,
                                  period=period if not start_str else None,
                                  progress=False, group_by="ticker",
                                  timeout=30, auto_adjust=True)

            # Detect column structure at runtime: newer yfinance returns MultiIndex
            # columns even for single-ticker batches when group_by="ticker" is set,
            # so len(chunk)==1 is not a reliable signal.
            chunk_df = pd.DataFrame()
            if not raw.empty:
                if isinstance(raw.columns, pd.MultiIndex):
                    chunk_df = (raw.stack(level=0, future_stack=True)
                                   .rename_axis(["Date", "Ticker"])
                                   .reset_index())
                else:
                    chunk_df = raw.reset_index()
                    chunk_df["Ticker"] = chunk[0]
                # Drop NaN-Close rows immediately: when a batch fails for some
                # tickers, yfinance still returns a placeholder row with all-NaN
                # prices. Keeping them would save bad data to parquet and cause
                # the miss detector to report those tickers as present when they
                # have no valid data.
                if "Close" in chunk_df.columns:
                    chunk_df = chunk_df.dropna(subset=["Close"])

            # Per-chunk miss reporting: show ticker names, not just a count
            if chunk_df.empty:
                chunk_misses = list(chunk)
            else:
                got = set(chunk_df["Ticker"].unique())
                chunk_misses = [t for t in chunk if t not in got]

            if chunk_misses:
                miss_str = ", ".join(chunk_misses[:6]) + (
                    f" (+{len(chunk_misses) - 6})" if len(chunk_misses) > 6 else ""
                )
                print(f" ! no data: {miss_str}")
            else:
                print()  # clean newline

            if not chunk_df.empty:
                parts.append(chunk_df)
        except Exception as e:
            print(f" x error: {str(e)[:80]}")
        time.sleep(random.uniform(*sleep_range))
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def _backfill_recent_gaps(combined: pd.DataFrame, all_tickers: list, cfg: Config,
                          ticker_sector: dict, mcap: dict) -> tuple:
    """Self-heal partial download days: re-fetch any recent trading day whose
    ticker coverage is below par (see health.coverage_gaps) and add ONLY the
    bars that are missing. Bounded to the recent window so it never re-chases
    ancient gaps; one targeted fetch per run. Returns (combined, n_added)."""
    gaps = coverage_gaps(combined, cfg.download.backfill_lookback_days,
                         cfg.download.backfill_min_frac)
    if not gaps:
        return combined, 0
    gap_days = {d for d, _c, _m in gaps}
    earliest, median = min(gap_days), gaps[0][2]
    present = {d: set(combined.loc[combined["Date"] == d, "Ticker"]) for d in gap_days}
    universe = set(all_tickers)
    missing = sorted({t for d in gap_days for t in (universe - present[d])})
    worst = min(c for _d, c, _m in gaps)
    print(f"[download] Coverage gap on {len(gap_days)} recent day(s) "
          f"(worst {worst}/{median} tickers); backfilling {len(missing)} tickers "
          f"from {earliest}...")
    fetched = download_prices(missing, cfg, start=earliest)
    if fetched.empty:
        return combined, 0
    fetched["Date"] = pd.to_datetime(fetched["Date"]).dt.date
    fetched = fetched[fetched["Date"].isin(gap_days)]
    exist_keys = set(zip(combined["Ticker"], combined["Date"]))
    new = fetched[[k not in exist_keys
                   for k in zip(fetched["Ticker"], fetched["Date"])]].copy()
    if new.empty:
        return combined, 0
    new["Sector"]       = new["Ticker"].map(ticker_sector)
    new["Market_Cap"]   = new["Ticker"].map(mcap)
    new["Is_Synthetic"] = False
    combined = pd.concat([combined, new], ignore_index=True)
    print(f"[download] Backfilled {len(new)} missing bars "
          f"({new['Ticker'].nunique()} tickers, {new['Date'].nunique()} days).")
    return combined, len(new)


def _missing(tickers, result):
    # Use Close dropna: a ticker with all-NaN Close rows is effectively missing.
    # (NaN rows are filtered inside _one_pass, but this is a robust fallback.)
    if result.empty or "Ticker" not in result.columns:
        return list(tickers)
    got = set(result.dropna(subset=["Close"])["Ticker"].dropna().unique())
    return [t for t in tickers if t not in got]


def download_prices(tickers: list[str], cfg: Config,
                    start: date = None, period: str = None) -> pd.DataFrame:
    """3-pass recovery: full speed -> slower -> one-by-one for stragglers."""
    chunk = cfg.download.chunk_size
    r1 = _one_pass(tickers, start, period, chunk, (1.5, 3.0))
    m1 = _missing(tickers, r1)
    if not m1:
        return r1
    print(f"  Pass 2: {len(m1)} missing, retrying...")
    r2 = _one_pass(m1, start, period, 10, (5.0, 8.0))
    m2 = _missing(m1, r2)
    if not m2:
        return pd.concat([r1, r2], ignore_index=True)
    print(f"  Pass 3: {len(m2)} still missing, one-by-one...")
    r3 = _one_pass(m2, start, period, 1, (2.0, 4.0))
    remaining = _missing(m2, r3)
    if remaining:
        print(f"  Warning: {len(remaining)} tickers returned no data - cache rows preserved.")
    return pd.concat([r1, r2, r3], ignore_index=True)


# ── Helpers ────────────────────────────────────────────────────────────────────

def latest_published_bar() -> date:
    """Most recent finalized yfinance daily bar.
    Published only after the 16:00 ET regular-session close. Skips weekends+holidays."""
    et = _et_now()
    if et is not None:
        if et.weekday() < 5 and et.date() not in US_MARKET_HOLIDAYS \
                and et.time() >= _REGULAR_END:
            d = et.date()
        else:
            d = et.date() - timedelta(days=1)
    else:
        d = date.today() - timedelta(days=1)
    return last_market_day(d)


# ── Live snapshot ──────────────────────────────────────────────────────────────

def _fetch_live_price(ticker: str, sleep_range=(0.05, 0.15)):
    """Latest intraday/pre-market price from 1-minute history with prepost=True.
    More reliable than fast_info.last_price during extended hours — that often
    returns the stale regular-session close for thinly-traded tickers."""
    time.sleep(random.uniform(*sleep_range))
    try:
        hist = yf.Ticker(ticker).history(
            period="1d", interval="1m", prepost=True, auto_adjust=True
        )
        if hist.empty:
            return ticker, None
        valid = hist["Close"].dropna()
        return ticker, float(valid.iloc[-1]) if not valid.empty else None
    except Exception:
        return ticker, None


def _snapshot_pass(tickers, max_workers, sleep_range) -> dict:
    """One concurrent pass of live-price fetches. Returns {ticker: price>0}."""
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        results = list(ex.map(lambda t: _fetch_live_price(t, sleep_range), tickers))
    return {t: p for t, p in results if p is not None and p > 0}


def fetch_live_snapshot(tickers: list[str]) -> dict:
    """Two-pass live-price snapshot. Pass 1 is fast; pass 2 retries the misses
    gently (fewer workers, longer sleep) so transient rate-limiting — common
    right after a large bar download — doesn't starve the snapshot. Tickers that
    still miss are genuinely untraded (e.g. no pre-market prints) and fall back
    to their last real bar downstream in indicators."""
    prices = _snapshot_pass(tickers, max_workers=10, sleep_range=(0.05, 0.15))
    misses = [t for t in tickers if t not in prices]
    if misses:
        print(f"  Pass 2: retrying {len(misses)} misses (gentler, may be throttled)...")
        prices.update(_snapshot_pass(misses, max_workers=4, sleep_range=(0.4, 0.8)))
    return prices


# ── Main entry ─────────────────────────────────────────────────────────────────

def run(cfg: Config, data_dir: Path) -> None:
    tickers_file = data_dir / "tickers.csv"
    prices_file  = data_dir / "prices.parquet"
    mcap_file    = data_dir / "mcap.parquet"

    ticker_df     = load_tickers(tickers_file)
    ticker_sector = dict(zip(ticker_df["Ticker"], ticker_df["Industry"]))
    all_tickers   = sorted(ticker_df["Ticker"].dropna().unique())
    print(f"[download] {len(all_tickers)} tickers loaded")

    mcap = refresh_mcap(all_tickers, mcap_file, cfg)

    existing = pd.DataFrame()
    if prices_file.exists():
        existing = pd.read_parquet(prices_file)
        existing["Date"] = pd.to_datetime(existing["Date"]).dt.date

    existing_set = set(existing["Ticker"].unique()) if not existing.empty else set()
    new_tickers  = [t for t in all_tickers if t not in existing_set]
    last_date    = existing["Date"].max() if not existing.empty else None

    # ── Session + download decision ────────────────────────────────────────────
    # Three orthogonal concerns (mirrors main version):
    #   BAR DOWNLOAD  — cache state vs latest_published_bar()
    #   LIVE SNAPSHOT — pre + regular sessions only
    #   RECOVERY      — 3-pass retry on every batch download
    market_session   = us_market_session()
    target_bar       = latest_published_bar()
    do_live_snapshot = market_session in ('pre', 'regular') and runtime.live_snapshot

    # Synthetic-bar detection: if the last cached row is synthetic (left from a
    # prior pre/regular run) and a real bar is now available, re-fetch to replace.
    synthetic_detected = False
    if last_date is not None and not existing.empty and "Is_Synthetic" in existing.columns:
        latest_rows = existing[existing["Date"] == last_date]
        if not latest_rows.empty and latest_rows["Is_Synthetic"].fillna(False).any():
            synthetic_detected = True

    # Five-case decision for bar download:
    #   (a) no cache            → new_tickers handles full history; no incremental
    #   (b) cache < target_bar  → incremental fetch from last_date+1
    #   (c) cache == target AND synthetic → refetch that day (replace synth with real)
    #   (d) cache == target AND real      → skip
    #   (e) cache > target (synthetic for today, pre/regular) → skip; live snapshot refreshes it
    update_tickers = [t for t in all_tickers if t in existing_set]
    fetch_start    = None
    skip_reason    = None

    if last_date is None:
        update_tickers = []
        fetch_start    = None
        skip_reason    = 'no cache yet'
    elif last_date < target_bar:
        fetch_start = last_date + timedelta(days=1)
    elif last_date == target_bar and synthetic_detected:
        fetch_start = last_date  # refetch this day to replace synthetic with real
    else:
        update_tickers = []
        fetch_start    = None
        skip_reason    = 'cache current'

    if market_session != 'closed':
        labels = {'pre': 'pre-market', 'regular': 'regular hours', 'after': 'after-hours'}
        print(f"[download] US market active ({labels[market_session]}).")

    if synthetic_detected and fetch_start is not None:
        print(f"[download] Synthetic bar for {last_date} detected - re-fetching as real bar.")

    if skip_reason == 'cache current':
        print(f"[download] Prices up to date ({last_date}). Bar download skipped.")

    hist_period = f"{cfg.data.history_years}y"
    parts = []

    if new_tickers:
        print(f"[download] {len(new_tickers)} new tickers - fetching {hist_period} history...")
        parts.append(download_prices(new_tickers, cfg, period=hist_period))

    if update_tickers and fetch_start is not None:
        print(f"[download] Incremental update from {fetch_start} for {len(update_tickers)} tickers...")
        parts.append(download_prices(update_tickers, cfg, start=fetch_start))

    if not parts and existing.empty:
        print("[download] Nothing to save.")
        return

    combined = pd.concat([existing] + parts, ignore_index=True) if parts else existing
    combined["Date"] = pd.to_datetime(combined["Date"]).dt.date
    combined = combined.drop_duplicates(subset=["Ticker", "Date"], keep="last")
    combined["Sector"]     = combined["Ticker"].map(ticker_sector)
    combined["Market_Cap"] = combined["Ticker"].map(mcap)
    combined = (combined[combined["Ticker"].isin(set(all_tickers))]
                .reset_index(drop=True))

    # Self-heal recent coverage gaps (throttled/partial download days) before the
    # live snapshot, so downstream stages never see a half-empty trading day.
    combined, _ = _backfill_recent_gaps(combined, all_tickers, cfg, ticker_sector, mcap)

    # ── Live snapshot (pre-market + regular hours only) ────────────────────────
    # Append or refresh a synthetic bar whose Close reflects the current intraday
    # price. Uses 1-minute history with prepost=True — more reliable than
    # fast_info.last_price during extended hours, which often returns the stale
    # regular-session close for thinly-traded tickers.
    # Volume is NOT taken from the 1m bar: pre-market volume is a tiny fraction
    # of regular-session volume and would tank RVOL to ~0.05 (false signal).
    # The synthetic bar inherits the previous day's Volume instead.
    live_overrides = 0
    live_synthetic = 0
    if do_live_snapshot:
        print(f"[download] {market_session}-market live snapshot ({len(all_tickers)} tickers)...")
        live_prices = fetch_live_snapshot(all_tickers)
        print(f"  {len(live_prices)} / {len(all_tickers)} live prices received.")

        et       = _et_now()
        today_et = et.date() if et is not None else date.today()

        # Update existing today rows in-place (Close/High/Low; Volume left untouched)
        today_mask = (combined["Date"] == today_et) & combined["Ticker"].isin(live_prices)
        if today_mask.any():
            idx = combined.index[today_mask]
            lp  = combined.loc[idx, "Ticker"].map(live_prices)
            combined.loc[idx, "Close"] = lp
            combined.loc[idx, "High"]  = combined.loc[idx, "High"].combine(lp, max)
            combined.loc[idx, "Low"]   = combined.loc[idx, "Low"].combine(lp, min)
            if "Is_Synthetic" not in combined.columns:
                combined["Is_Synthetic"] = False
            combined.loc[idx, "Is_Synthetic"] = True
            live_overrides = int(today_mask.sum())

        # Append synthetic rows for tickers that have no today row yet
        tickers_with_today = set(combined.loc[today_mask, "Ticker"]) if today_mask.any() else set()
        tickers_needing    = [t for t in live_prices if t not in tickers_with_today]
        if tickers_needing:
            last_rows      = combined.sort_values("Date").groupby("Ticker").tail(1)
            last_close_map = dict(zip(last_rows["Ticker"], last_rows["Close"]))
            last_vol_map   = dict(zip(last_rows["Ticker"], last_rows["Volume"]))
            synth_rows = []
            for t in tickers_needing:
                lp = live_prices[t]
                lc = last_close_map.get(t)
                if lc is None or pd.isna(lc):
                    continue
                synth_rows.append({
                    "Date":         today_et,
                    "Ticker":       t,
                    "Open":         lc,           # gap reference — synthetic
                    "High":         max(lc, lp),
                    "Low":          min(lc, lp),
                    "Close":        lp,
                    "Volume":       last_vol_map.get(t),  # previous day's vol — keeps RVOL stable
                    "Sector":       ticker_sector.get(t),
                    "Market_Cap":   mcap.get(t),
                    "Is_Synthetic": True,
                })
            if synth_rows:
                combined = pd.concat([combined, pd.DataFrame(synth_rows)], ignore_index=True)
                live_synthetic = len(synth_rows)

        if live_overrides or live_synthetic:
            print(f"[download] Live: {live_overrides} bars updated, "
                  f"{live_synthetic} synthetic bars added (Date={today_et}).")
        else:
            print("[download] Live snapshot: no updates applied.")

    # Ensure Is_Synthetic column exists and defaults to False for un-tagged rows
    if "Is_Synthetic" not in combined.columns:
        combined["Is_Synthetic"] = False
    combined["Is_Synthetic"] = combined["Is_Synthetic"].fillna(False).astype(bool)

    # Drop extraneous all-NaN columns (e.g. yfinance's 'Adj Close' under
    # auto_adjust) — keep only real, non-empty columns. Never drop a documented
    # PRICES column even if empty, so the health check can flag it instead.
    junk = [col for col in combined.columns
            if col not in schema.PRICES and combined[col].isna().all()]
    if junk:
        combined = combined.drop(columns=junk)

    combined = combined.sort_values(["Ticker", "Date"]).reset_index(drop=True)
    combined.to_parquet(prices_file, index=False)
    print(f"[download] {len(combined):,} rows saved -> {prices_file.name}")
