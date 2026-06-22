"""
run.py -- pipeline orchestrator and server launcher.

Usage:
    python run.py pipeline           run all pipeline stages (skip if up to date)
    python run.py pipeline --force   run all stages regardless of freshness
    python run.py pipeline --offline run stages 2-4 on existing data (no network)
    python run.py bootstrap          cold start: build data/ from tickers.csv
    python run.py serve              start the API + frontend server
    python run.py all                pipeline then serve
    python run.py all --force        force pipeline then serve
    python run.py check              validate the built data (exit 1 on problems)
"""
import os
import sys
from pathlib import Path

ROOT   = Path(__file__).parent
CONFIG = ROOT / "config.ini"
# Data dir is env-overridable for server deploys (mounted volume); defaults to ./data.
DATA_DIR = (Path(os.environ["SCREENER_DATA_DIR"])
            if os.environ.get("SCREENER_DATA_DIR") else ROOT / "data")

sys.path.insert(0, str(ROOT))


# ── Freshness check ────────────────────────────────────────────────────────────

def _mtime(path: Path) -> float:
    return path.stat().st_mtime if path.exists() else 0.0


def _needs_run(output: Path, *inputs: Path) -> bool:
    """True if output is missing or older than any input."""
    if not output.exists():
        return True
    out_t = _mtime(output)
    return any(_mtime(p) > out_t for p in inputs)


# ── Pipeline ───────────────────────────────────────────────────────────────────

def run_pipeline(force: bool = False, offline: bool = False) -> None:
    from pipeline import download, indicators, robots, rotation, sectors
    from pipeline.config import cfg

    prices_file  = DATA_DIR / "prices.parquet"
    metrics_file = DATA_DIR / "metrics.parquet"
    sectors_file = DATA_DIR / "sectors.parquet"
    rot_file     = DATA_DIR / "rotation.parquet"
    tail_file    = DATA_DIR / "rotation_tail.parquet"
    tickers_file = DATA_DIR / "tickers.csv"

    print("\n" + "=" * 50)
    print("  SCREENER PIPELINE" + ("  (offline)" if offline else ""))
    print("=" * 50)

    # Stage 1 -- Download (skipped entirely in offline mode)
    if offline:
        print("\n[1/4] Download -- offline mode, skipped")
        force = True   # force stages 2-4 to rebuild from the existing prices
    elif force or _needs_run(prices_file, tickers_file, CONFIG):
        print("\n[1/4] Download")
        download.run(cfg, DATA_DIR)
    else:
        print("\n[1/4] Download -- up to date, skipped")

    # Stage 2 -- Indicators + stages
    if force or _needs_run(metrics_file, prices_file, CONFIG):
        print("\n[2/4] Indicators & Stages")
        indicators.run(cfg, DATA_DIR)
    else:
        print("\n[2/4] Indicators -- up to date, skipped")

    # Stage 3 -- Sector aggregation
    if force or _needs_run(sectors_file, metrics_file, CONFIG):
        print("\n[3/4] Sectors")
        sectors.run(cfg, DATA_DIR)
    else:
        print("\n[3/4] Sectors -- up to date, skipped")

    # Stage 4 -- RRG rotation
    if force or _needs_run(rot_file, metrics_file, prices_file, CONFIG) \
             or _needs_run(tail_file, metrics_file, prices_file, CONFIG):
        print("\n[4/5] Rotation (RRG)")
        rotation.run(cfg, DATA_DIR)
    else:
        print("\n[4/5] Rotation -- up to date, skipped")

    # Stage 5 -- Robots (strategy portfolios -> robots.json)
    robots_file = DATA_DIR / "robots.json"
    if force or _needs_run(robots_file, prices_file, CONFIG):
        print("\n[5/5] Robots")
        robots.run(cfg, DATA_DIR)
    else:
        print("\n[5/5] Robots -- up to date, skipped")

    print("\nPipeline complete.\n")


# ── Server ─────────────────────────────────────────────────────────────────────

def run_server() -> None:
    import uvicorn

    from pipeline.config import runtime
    from server.app import create_app
    app = create_app(DATA_DIR)
    # 0.0.0.0 is a bind address (all interfaces) — not reachable in a browser.
    # Show a clickable host instead.
    display_host = "localhost" if runtime.host in ("0.0.0.0", "") else runtime.host
    print(f"\nServer running at http://{display_host}:{runtime.port}")
    print(f"Open the dashboard at  http://{display_host}:{runtime.port}\n")
    uvicorn.run(app, host=runtime.host, port=runtime.port)


# ── Bootstrap ────────────────────────────────────────────────────────────────────

def run_bootstrap() -> None:
    """Cold start: build the whole data dir from tickers.csv (full history)."""
    print("[bootstrap] Building data dir from scratch (full history download)...")
    print("[bootstrap] For a complete re-download, delete data/prices.parquet first.\n")
    run_pipeline(force=True)
    run_check()


# ── Health check ─────────────────────────────────────────────────────────────────

def run_check() -> None:
    from pipeline.health import check
    problems = check(DATA_DIR)
    if not problems:
        print("[check] OK -- all parquets present, schema valid, data sane.")
        return
    print(f"[check] {len(problems)} problem(s):")
    for p in problems:
        print(f"  - {p}")
    sys.exit(1)


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from pipeline.config import runtime
    from pipeline.log import setup as setup_logging
    setup_logging(runtime.log_level)

    args    = sys.argv[1:]
    force   = "--force" in args
    offline = "--offline" in args
    cmd     = next((a for a in args if not a.startswith("--")), "help")

    try:
        if cmd == "pipeline":
            run_pipeline(force, offline)
        elif cmd == "bootstrap":
            run_bootstrap()
        elif cmd == "serve":
            run_server()
        elif cmd == "all":
            run_pipeline(force, offline)
            run_server()
        elif cmd == "check":
            run_check()
        else:
            print(__doc__)
    except Exception as exc:  # noqa: BLE001 — top-level guard: log, alert, re-raise
        import logging

        from pipeline import notify
        logging.getLogger("run").exception("command '%s' failed", cmd)
        notify.alert(f"Screener '{cmd}' failed: {exc}", runtime.alert_webhook)
        raise
