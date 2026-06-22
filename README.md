# Screener (Lightweight)

A standalone US-equity **stage + rotation** screener. A small Python pipeline
builds parquet files; a FastAPI server serves them as JSON; a vanilla-JS
dashboard renders sectors, an RRG rotation chart, candidate stocks, and a
filterable stock table.

> Working on the code (human or AI)? Read **[CLAUDE.md](CLAUDE.md)** first —
> ground rules, file map, and the one command to verify a change.

---

## Quickstart

```bash
pip install -r requirements.txt      # exact pinned versions

python run.py bootstrap              # cold-start: build data/ from tickers.csv (first run, slow)
python run.py all                   # refresh data, then serve at http://localhost:8000
```

Day to day:

```bash
python run.py pipeline              # refresh data (skips stages already up to date)
python run.py serve                 # serve the dashboard
python run.py check                 # validate the built data (exit 1 on problems)
```

## Architecture

```
tickers.csv ─▶ download ─▶ indicators ─▶ sectors ─▶ rotation ─▶ data/*.parquet
                                                                     │
                                            server/app.py (FastAPI) ─┘ ─▶ /api/* JSON
                                                                     │
                                                       frontend/ (fetch + render)
```

- Each stage writes a parquet in `data/`; `run.py` skips stages whose inputs are unchanged.
- `pipeline/config.py` is a typed config singleton; all knobs live in `config.ini`.
- `pipeline/schema.py` is the single source of truth for parquet columns.

## Commands

| Command | Does |
|---------|------|
| `python run.py bootstrap` | Build the whole `data/` dir from `tickers.csv` (full history download) |
| `python run.py pipeline` | Refresh data (skip up-to-date stages) |
| `python run.py pipeline --force` | Rebuild all stages |
| `python run.py pipeline --offline` | Rebuild stages 2–4 from existing data, no network |
| `python run.py serve` | Start the API + dashboard |
| `python run.py all` | Pipeline then serve |
| `python run.py check` | Validate the built data |

## Development

```bash
pip install -e ".[dev]"
python -m pytest        # 21 tests, offline, ~2s
python -m ruff check .  # lint
```

## Configuration

All settings are in **[config.ini](config.ini)** (stage thresholds, rotation
windows, download options). Environment variables override them at runtime — see
**[.env.example](.env.example)**.

## Deployment

See **[DEPLOY.md](DEPLOY.md)** for Docker, scheduling, and server notes.

## License

Proprietary — see [LICENSE](LICENSE).
