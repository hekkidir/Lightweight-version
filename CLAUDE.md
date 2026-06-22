# Screener (Lightweight) — AI working guide

A standalone US-equity stage + rotation screener. Pipeline builds parquet files;
a FastAPI server serves them as JSON; a vanilla-JS frontend renders the dashboard.

---

## Ground rules — read first

1. **Ask before structural change.** New files, moving logic between stages,
   changing a parquet schema, or altering the pipeline shape → propose first and
   wait for "go". In-place bug fixes don't need asking.
2. **No workaround solutions.** Fix the root cause. If the proper fix is large,
   **stop and surface it** — never paper over it with a band-aid.
3. **Test every change.** Run `python -m pytest` and report the result. Never
   claim "done" without a green run.
4. **Build incrementally.** One concern per change; small and reviewable; no
   hidden coupling. Prefer the simplest thing that works over the clever thing.
5. **Touch the minimum.** Don't refactor, rename, or reformat code you weren't
   asked to change.
6. **No new dependencies without asking.** Lightweight is a hard value here.
7. **Report honestly.** If a test fails, a step was skipped, or you're unsure —
   say so plainly.

---

## Verify a change (the one command)

```
python -m pytest          # full suite, offline  ← run after every change
python run.py check       # validate the built data dir (exit 1 on problems)
python run.py pipeline --offline   # rebuild stages 2-4 from existing data, no network
```

Frontend changes are covered by a headless-browser smoke test
(`tests/test_frontend.py`, Playwright) that loads the real dashboard and fails on
any JS error. It runs as part of `pytest`; it skips cleanly if Playwright isn't
installed (`pip install playwright && python -m playwright install chromium`).

If you change pipeline math **on purpose** and a golden test fails, regenerate the
expected snapshot — but only after confirming the new numbers are correct:

```
python tests/update_golden.py
```

---

## Architecture (5 lines)

- Flow: **download → indicators → sectors → rotation**, each writing a parquet in `data/`.
- `run()` in each stage is a thin I/O shell; all logic lives in **pure functions** (testable directly).
- Config is a **typed singleton** — `from pipeline.config import cfg`; never hardcode a threshold.
- `pipeline/schema.py` is the **single source of truth** for every parquet's columns.
- Server reads parquets → JSON; frontend fetches `/api/*` and renders. No build step.

---

## File map

| File | What it does |
|------|--------------|
| `run.py` | Orchestrator: `pipeline` / `serve` / `all` / `check`; skip logic; `--force` `--offline` |
| `config.ini` | All tunable settings (thresholds, windows, rotation knobs) |
| `pipeline/config.py` | Typed config singleton; `load()` reads `config.ini` → `cfg.stages.*`, `cfg.rotation.*` |
| `pipeline/download.py` | yfinance OHLCV + market cap; 3-pass recovery; pre/regular live snapshot → `prices.parquet` |
| `pipeline/indicators.py` | Per-ticker EMA/RSI/ATR/RVOL + `classify_stages()`; per-ticker latest bar → `metrics.parquet` |
| `pipeline/sectors.py` | sqrt-mcap-weighted sector aggregation → `sectors.parquet` |
| `pipeline/rotation.py` | RRG: cohesion + weighted sector returns → X/Y/quadrant → `rotation.parquet` + `rotation_tail.parquet`; `compute_rotation()` reusable |
| `pipeline/robots.py` | Standalone port of the 5 backtest robots: gates + GICS rotation + `select_quant` + `run_backtest` sim → `data/robots.json`. Needs `gics_map.csv` + `spy.parquet` seeds |
| `pipeline/schema.py` | Required columns per parquet — the data contract |
| `pipeline/health.py` | Data sanity checks (`check()`), used by `run.py check` + `/api/health` |
| `pipeline/log.py` | Structured stdout logging (`setup()`); level via `SCREENER_LOG_LEVEL` |
| `pipeline/notify.py` | Best-effort failure webhook (`alert()`), stdlib only |
| `server/app.py` | FastAPI: frontend + `/api/{stocks,stock/{tkr},sectors,robots,rotation,status,health}` (+ `/api/v1`) |
| `server/asgi.py` | Production ASGI entrypoint (`uvicorn server.asgi:app`) |
| `frontend/index.html` | Dashboard shell (empty containers JS fills) |
| `frontend/data.js` | API fetch calls |
| `frontend/utils.js` | Shared DOM + formatting helpers (no state) |
| `frontend/compute.js` | Pure rotation math: trail/ΔY maps + category sets |
| `frontend/sectors.js` | A frame: category chips + sector list (`visibleSectors`) |
| `frontend/rrg.js` | B frame: RRG canvas drawing (`drawRRG`), hit-testing, inline map + tooltip |
| `frontend/rrg_modal.js` | Fullscreen RRG: wide canvas + inspector panel (detail/legend/leaderboard/controls) |
| `frontend/candidates.js` | D frame: Aday Hisseler (STRONG/WARMING + Güçlenen) |
| `frontend/table.js` | E frame: stock table, filter bar, CSV export |
| `frontend/stock_modal.js` | Per-stock modal: 20-day chart/strip/range/metrics/EMA/table (uses `/api/stock/{tkr}`) |
| `frontend/robots.js` | Robots view: card per robot (holdings + candidates), live-joined; uses `/api/robots` |
| `frontend/robot_modal.js` | Robot tearsheet: perf vs SP500/NDX, drawdown, heatmap, sector alloc, trade log, rebalance |
| `frontend/app.js` | State, two-layer focus model (group/pins), event wiring |
| `frontend/app.css` | Dark theme |
| `tests/` | Fixture generator + unit + golden + contract + health tests |

---

## Conventions (technical — things an AI gets wrong without being told)

- **ASCII-only in `print()`** — the Windows console is cp1252; `→ ≥ ✓ —` crash it.
- **pandas 3 groupby key:** after `groupby(...).apply(...)`, the key is dropped —
  restore with `df["Ticker"] = df_orig.loc[df.index, "Ticker"]`.
- **Column name is `Market_Cap`** (underscore), never `Market Cap`.
- **NaN must serialize as `null`** in the API — use `to_json` (plain `to_dict` raises on NaN).
- **Files stay under ~200 lines.**
- **No hardcoded thresholds** — add to `config.ini` + the dataclass + `load()` in `config.py`.
- **UI strings are Turkish; code and comments are English.**

---

## When you change X, update Y (doc-sync — mostly enforced by tests)

- Change a stage's **output columns** → update `pipeline/schema.py`
  *(the contract test fails otherwise).*
- Add/rename a **config key** → `config.ini` + the dataclass + `load()` in `config.py`.
- Change **pipeline math on purpose** → `python tests/update_golden.py` after confirming.
- Add a **dependency** → ask first; then pin in `requirements.lock` + `pyproject.toml`.
- Ship a **behavior/feature change** → bump `VERSION` + add a `CHANGELOG.md` entry.

---

## Task recipes

- **Add an indicator:** compute it in `_compute_group` (`indicators.py`) → add the column
  to the `cols` list in `indicators.run` → add it to `schema.METRICS` → `pytest` → `update_golden`.
- **Add a config knob:** `config.ini` → field on the dataclass + a `get()` line in `config.py`
  `load()` → use via `cfg.*` → `pytest`.
- **Add an API field:** make sure it's in the relevant parquet + `schema.py`; the server serves
  all columns automatically.
- **Change a stage threshold:** edit `config.ini` only — no code change.

---

## Docs (open on demand, not loaded every session)

- `README.md` — quickstart + commands
- `DEPLOY.md` — Docker, scheduling, server settings, repo separation
- `FORMULAS.md` — plain-English formula for every indicator
- `CHANGELOG.md` — version history
- `.env.example` — deployment env vars

---

## Boundaries

This project is **standalone**. Never import from or depend on anything outside this
folder. It must stand up from `data/tickers.csv` + code alone (`python run.py pipeline`).
