# Changelog

All notable changes to this project are recorded here
Format follows [Keep a Changelog](https://keepachangelog.com/); versions use [SemVer](https://semver.org/).

## [0.10.2] — 2026-06-24

### Fixed
- **Non-ASCII in `download.py` `print()` statements crashed downloads on the
  Windows cp1252 console.** The `⚠️`/`❌`/`—` characters in the miss/error/status
  prints raised `UnicodeEncodeError` — and the miss warning fires *exactly* on
  throttled days with missing tickers, aborting the 3-pass recovery on the days
  it exists to handle. Swapped for ASCII, per the repo's own print() convention.

### Added
- **Self-healing coverage backfill.** After the incremental fetch, `download.run`
  re-downloads any of the last `backfill_lookback_days` trading days whose ticker
  coverage drops below `backfill_min_frac` of the recent median (a throttled/
  partial day, e.g. 345 of 1079 tickers), adding only the missing bars. Scoped to
  the recent window so it never re-chases ancient, permanently-missing bars;
  detection is a cheap groupby and only fetches when a gap is found. New config
  knobs in `[download]`; disable with `backfill_lookback_days = 0`.
- **Coverage check in `health.py`** (`coverage_gaps`, reused by the backfill):
  `run.py check` now flags a recent day with anomalously low ticker coverage
  instead of passing silently on a partial download.

## [0.10.1] — 2026-06-23

### Fixed
- **Robots evaluated on the wrong bar after an end-of-day download.** `build_today`
  and `build_robots` skipped the last bar positionally (`all_dates[-2]` /
  `settled_offset=1`), assuming it was always a partial live snapshot. After a
  proper post-close download the latest bar is real and full-volume, so this
  over-skipped it — and across a market holiday (e.g. Juneteenth) the sim could
  land two trading days early and miss a Monday rebalance entirely. Now both read
  the `Is_Synthetic` flag that `download.py` already writes and evaluate on the
  last genuinely settled (non-synthetic) bar via `_last_settled_date`.

## [0.10.0] — 2026-06-22

Robots Phase 2 — the native standalone engine ships. The Robots tab now shows
**real** strategy signals computed from LW's own data (no backtest dependency).

### Added
- **`pipeline/robots.py`** — a faithful, standalone port of the backtest's 5
  robots: feature gates (multi-factor / dashboard / volume A7·G5·G6), GICS sector
  rotation, the `select_quant` selector per family, and a `run_backtest` port
  (weekly Monday rebalance, Phase-A trim / let-winners-run, exits E1/E20/E24/E33/
  E51/E56, C-axis sizing). Writes `data/robots.json`.
- New **`[5/5] Robots`** pipeline stage in `run.py` (skips if the GICS-map / SPY
  seeds are absent; only re-runs when prices change).
- Robot-only feature panel that mirrors the backtest exactly: percent `ext`, the
  backtest's EMA-alignment stage classifier (`_robot_stages`) with its own
  thresholds (`rsi_2b=55`, `rvol_confirm=1.5/5`) — LW's dashboard stages are
  untouched.

### Validation
- **LW reproduces the backtest** over 2022–2026 (total-return multiples, backtest
  cost+T+1 settings): A 21.6×/23.4×, B 81.8×/60.6×, C 34.3×/30.0×, D 8.7×/8.3×,
  AV 35.2×/33.4×. Stage agreement vs the backtest panel = 100%.

### Notes
- Execution model defaults to **free brokerage + same-bar (signal-day close)
  fills** (`COST_PER_SIDE=0`, `NEXT_OPEN_FILL=False`); set `0.0015` + `True` to
  reproduce the backtest exactly. Free/same-bar runs a bit higher (no cost drag,
  no T+1 gap): A 19.2× / B 83.3× / C 43.2× / D 16.2× / AV 29.7×.
- LW price history backfilled from the backtest's 5-year series (2021→2026).

## [0.9.1] — 2026-06-22

Robots Phase 2 — Stage 2a: feature panel.

### Added
- `indicators.py` now computes **`ret_1m/3m/6m`** (21/63/126d), **`dollar_vol`**,
  and their per-date **cross-sectional ranks** (`ret_*_rank`) — the inputs the
  robot gates need. These also enrich `metrics.parquet` / `/api/stocks`.
- `data/gics_map.csv` — Ticker→GICS sector seed (copied from the backtest; the
  one lookup that can't be computed). Tracked seed, like `tickers.csv`.

### Notes
- Verified against the backtest's `features_daily.parquet` on a common date:
  `ret_3m/6m`, `dollar_vol`, and the 3m/6m ranks correlate 0.98–0.99; `ret_1m`
  ~0.90 (most sensitive to recent-price/calendar drift between the two
  independent price panels — same formula). Robots consume LW's own features, so
  internal rank consistency is what the gates use.

## [0.9.0] — 2026-06-22

Robot tearsheet: trade tape with time filter + inline entry candidates.

### Changed
- The tearsheet's **"Kapanan işlemler"** is now **"İşlemler"** — the full trade
  tape (open **and** closed) with a **time filter** (1 Ay / 3 Ay / 6 Ay / 1 Yıl /
  Tümü; defaults to **1 Yıl**). Open trades show an "Açık" badge.
- Each trade shows its **entry-time candidate pool inline** (the names the robot
  weighed at the buy), as clickable chips — no expand needed.
- The candidate list is no longer a fixed 3 — the demo now surfaces more, and the
  contract was never capped (Phase 2 emits the full pool, like the signals HTML).

### Contract
- `trades` is the trailing tape: `exit_date` may be `null` (open); each trade may
  carry `entry_candidates: [{ ticker, score }]`. `robots.example.json` updated.

## [0.8.0] — 2026-06-22

Robot tearsheet modal + richer signal feed; robot pin = sectors.

### Added
- **Robot tearsheet modal** (`frontend/robot_modal.js`) — click a robot card's
  name: performance chart (robot vs **S&P 500** vs **Nasdaq 100**, rebased to 100)
  with a **drawdown** strip, full **stats**, a **monthly-returns heatmap**,
  **holdings sector allocation**, current holdings + candidates, a **closed-trade
  log**, and **last-rebalance** (added/dropped). Tickers open the stock modal.
- `robots.json` contract grows (all optional, UI degrades): dated `equity`,
  per-robot `benchmarks` (sp500/ndx), `trades` (closed), `rebalance`. Drawdown,
  the heatmap and sector allocation are derived client-side. `robots.example.json`
  updated.

### Changed
- Robot card button is now **"Sektörleri sabitle"** — pins the sectors of a
  robot's holdings **+** candidates onto the RRG (was "Holdingleri sabitle",
  which pinned individual tickers).
- A candidate's `reason` is now per-strategy (each robot shows its own logic),
  not one fixed string.

## [0.7.0] — 2026-06-22

Robots view (Phase 1 — UI + feed contract).

### Added
- **Robots tab** (top-bar `Panel | Robotlar` toggle) — one card per robot showing
  its current **holdings** and **next candidates**, each row joined to live
  `/api/stocks` for sector + stage; equity sparkline + stat chips per robot;
  ticker click opens the stock modal; "pin holdings" pushes a robot's holdings
  onto the RRG as pins. (`frontend/robots.js`)
- **`GET /api/robots`** — serves `data/robots.json` (holdings + candidates per
  robot); returns an empty payload (not 503) when the file is absent.
- `robots.example.json` documents the feed contract.

### Notes
- Phase 1 is the UI + contract; the 5 robots are A (SA-DEF), B (SB-B),
  C (SV-A7+floor), D (SB-HYB-G5-replace), AV (SA-HYB-G6). **Phase 2** will add a
  native LW pipeline stage that computes `robots.json` from LW's own data
  (stateful tracked portfolios), making the robots fully standalone — no
  dependency on the external backtest.

## [0.6.0] — 2026-06-21

Per-stock detail modal.

### Added
- **Stock detail modal** (`frontend/stock_modal.js`) — click any stock-table row:
  - Header (ticker · sector · stage with prev→ transition · close · day %).
  - **Stage timeline strip** — the stage for each of the last 20 days.
  - **Price & volume chart** — close + EMA10/20/50 with up/down volume bars.
  - **20-day range bar** — close between the 20-day low/high, % from the high.
  - **Current metrics grid** — close, day/week/month/YTD %, RSI, ATR%, Ext,
    RVOL, market cap, volume-confirmed.
  - **EMA structure panel** — % distance to EMA10/20/50/200 + alignment verdict.
  - **20-day table** — Date, Close, Chg%, RSI, ATR%, RVOL, Stage per bar.
  - **Sector quick-link** — pin this stock's sector across the dashboard.
- **`GET /api/stock/{ticker}?days=N`** — per-bar indicator series for one ticker,
  computed on demand from `prices.parquet` (reuses the pipeline's indicator +
  stage math; no storage change). Mounted under `/api` and `/api/v1`.

## [0.5.0] — 2026-06-21

Fullscreen RRG gains a wide canvas and an inspector panel.

### Added
- **Fullscreen RRG inspector panel** (`frontend/rrg_modal.js`):
  - **Sector detail card** — hover a dot (or follow the latest pin) for quadrant,
    RS/RM with a rotation arrow, ΔRS/ΔRM, strength score, weekly/monthly/YTD,
    breadth, avg RSI/RVOL, advancers-decliners, and the top-3 mover tickers.
  - **Quadrant legend** with live counts; click a quadrant to pin all its sectors.
  - **Rotation leaderboard** — top movers by velocity or momentum; click to pin.
  - **Display controls** — toggle tails, toggle all labels, tail-length slider (3–15).
- `drawRRG()` takes display opts (`showTails`, `showAllLabels`, `tailLen`).

### Changed
- The fullscreen map is now a wide rectangle filling the space beside the panel
  (was a centered square). Fullscreen logic moved out of `rrg.js` into
  `rrg_modal.js`; `rrg.js` keeps the inline map + shared drawing/hit-testing.

## [0.4.0] — 2026-06-21

Interactive RRG + a two-layer sector focus model (group + pins).

### Added
- **Interactive RRG**: hover a dot for a tooltip (sector, quadrant, RS/RM and
  ΔRS/ΔRM); click a dot to pin/unpin it. Works in the inline and fullscreen maps.
- **Pins** (spotlight) layer: clicking a sector row (or a dot) pins it without
  collapsing the active category. When any sector is pinned, the RRG highlights
  **only** the pinned dots (bold marker + name label) and dims the rest of the
  group; the Stocks table narrows to them too. Each pin shows as a 📌 chip in
  Active Filters.
- Sidebar **Tümünü Seç / Tümünü Temizle**: pin every sector currently listed
  (active category + search) / clear all pins.

### Changed
- **Focus model** is now two coexisting layers instead of mutually exclusive:
  a **category** = the active group (drives the RRG dimming, Aday Hisseler and the
  sidebar), and **pins** drill into it. The Stocks table follows pins when any are
  set, otherwise the whole category group. Picking a category clears pins.

## [0.3.0] — 2026-06-21

Selection/filter UX rebuilt from scratch; İvme panel removed.

### Added
- **Active Filters bar**: every active filter (focused sectors, category, stages,
  ranges, stock search) shows as a removable chip, with "Tümünü Temizle".
- Sector rows show a ✓ when in focus.

### Changed
- **Sector focus model** is now one concept with two inputs: a category chip is a
  single-select quick-pick (shown as one chip), and clicking a row is manual
  multi-select. They no longer silently intersect.
- **Layout**: RRG widened into a rectangle filling the freed space; the top row is
  now RRG | Aday Hisseler. The RRG canvas auto-sizes to its container.
- Reset moved from the top bar into the Active Filters bar.

### Removed
- İvme Matrisi panel (ΔY still drives Güçlenen / candidate ranking).

## [0.2.0] — 2026-06-20

Dashboard overhaul — filters, fixes, and a frontend test harness.

### Added
- Shared multi-select sector state linking all frames (A → B, C, D, E), with
  localStorage persistence and a Reset button.
- A (Sectors): category chips (Strong/Warming/Cooling/Weak/Güçlenen/Zayıflayan/
  🚀 En Hızlı/🚨 Kırılımlar) + sort by Strength_Score.
- C (İvme): sub-grouped matrix (STRONG/WEAK within accel/decel) + category filter.
- E (Stocks): collapsible filter bar — multi-select stage chips, min/max ranges
  (MCap, RSI, ATR%, Ext, RVOL, Performance), CSV export; removed the Vol box.
- D (Aday Hisseler): why-tag + score breakdown on hover; click → sector in E.
- B (RRG): fullscreen mode; comet-fade tails.
- A (Sectors): sector search box.
- Category filter is cross-frame: clicking a category in A/C dims the RRG and
  filters the table/candidates to those sectors (composes with manual selection).
- Headless-browser smoke test (Playwright) covering the whole dashboard.

### Fixed
- RRG quadrant bug: axes anchored at true 0,0 with a symmetric scale, so a dot's
  colour matches its visual quadrant (no more green dots in the cooling area).
- Static assets sent with Cache-Control: no-cache (no stale JS after a change).

### Changed
- Split the monolithic views.js into per-frame modules
  (utils/compute/sectors/rrg/ivme/candidates/table).
- Tuned Güçlenen quadrant weights (STRONG 1.7, WARMING 1.55) so STRONG/WARMING
  dominate the ranking less and more emerging sectors surface.
- RRG: category-focused sectors now show prominent comet tails (not just
  manually selected ones).

## [0.1.0] — 2026-06-18

First standalone version of the Lightweight screener.

### Added
- Pipeline: `download → indicators → sectors → rotation`, parquet storage.
- FastAPI server serving JSON (`/api/stocks|sectors|rotation|status`) + the frontend.
- Vanilla-JS dashboard: RRG chart, Ivme Matrisi, Aday Hisseler, stock table.
- Test harness: deterministic offline fixture, unit + golden + contract + health tests.
- `pipeline/schema.py` data contracts; `pipeline/health.py` + `run.py check`.
- `run.py --offline` mode; ruff + pyright config; `requirements.lock`.
- `CLAUDE.md` AI working guide (ground rules, file map, task recipes).

### Fixed
- Indicators: per-ticker latest-bar fallback so tickers missing today's live
  snapshot are analyzed on their last real bar instead of being dropped.
- Download: two-pass live-snapshot retry against rate-limiting; drop stray
  all-NaN columns at the source.
- Server: serialize NaN → null (was a 500 on `/api/stocks`).
