"""
app.py — FastAPI server. Serves dashboard data as JSON and the frontend.

Routes (also available under /api/v1/* for explicit versioning):
    GET /                 -> frontend/index.html
    GET /api/status       -> last pipeline run timestamps
    GET /api/stocks       -> all stock metrics (metrics.parquet)
    GET /api/stock/{tkr}  -> last-N-bar indicator series for one ticker (on demand)
    GET /api/sectors      -> sector summary (sectors.parquet)
    GET /api/robots       -> robot signals (holdings + candidates) from data/robots.json (optional)
    GET /api/rotation     -> RRG current positions + tails
    GET /api/health       -> data sanity (200 ok / 503 unhealthy) — never auth-gated

Deployment knobs come from pipeline.config.runtime (env): CORS origins, bearer
auth token, host/port. See .env.example.
"""
import json
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from pipeline import health, indicators
from pipeline.config import load, runtime


def _require_auth(authorization: str | None = Header(default=None)):
    """No-op unless SCREENER_AUTH_TOKEN is set; then require a matching bearer."""
    token = runtime.auth_token
    if token and authorization != f"Bearer {token}":
        raise HTTPException(status_code=401, detail="Unauthorized")


def create_app(data_dir: Path) -> FastAPI:
    # Frontend + VERSION live with the source, not next to the data dir — on a
    # server the data dir is often a mounted volume somewhere else entirely.
    project_root = Path(__file__).resolve().parent.parent
    frontend = project_root / "frontend"
    version  = ((project_root / "VERSION").read_text().strip()
                if (project_root / "VERSION").exists() else "0")
    cfg = load(project_root / "config.ini")   # for on-demand per-stock indicators

    app = FastAPI(title="Screener API", version=version)

    if runtime.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=runtime.cors_origins,
                           allow_methods=["GET"], allow_headers=["*"])

    # Always revalidate static assets so a changed JS/CSS file is never served
    # from a stale browser cache (it still 304s when unchanged — cheap).
    @app.middleware("http")
    async def _no_stale_static(request, call_next):
        resp = await call_next(request)
        if request.url.path.startswith("/static"):
            resp.headers["Cache-Control"] = "no-cache"
        return resp

    app.mount("/static", StaticFiles(directory=str(frontend)), name="static")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _load(filename: str) -> pd.DataFrame:
        path = data_dir / filename
        if not path.exists():
            raise HTTPException(
                status_code=503,
                detail=f"{filename} not found — run 'python run.py pipeline' first.")
        return pd.read_parquet(path)

    def _records(df: pd.DataFrame) -> list:
        # to_json converts NaN/Inf to null natively; json.loads yields plain dicts.
        return json.loads(df.to_json(orient="records"))

    def _mtime_str(filename: str) -> str | None:
        p = data_dir / filename
        if not p.exists():
            return None
        from datetime import datetime
        return datetime.fromtimestamp(p.stat().st_mtime).isoformat()

    # ── Frontend ──────────────────────────────────────────────────────────────

    @app.get("/", include_in_schema=False)
    def index():
        html = frontend / "index.html"
        if not html.exists():
            raise HTTPException(404, "Frontend not built yet.")
        return FileResponse(str(html))

    # ── Health (never auth-gated, so uptime monitors can reach it) ─────────────

    def health_route():
        problems = health.check(data_dir)
        return JSONResponse(
            {"status": "ok" if not problems else "unhealthy", "problems": problems},
            status_code=200 if not problems else 503)

    app.add_api_route("/api/health",    health_route, methods=["GET"])
    app.add_api_route("/api/v1/health", health_route, methods=["GET"])

    # ── Data API (auth-gated; mounted at both /api and /api/v1) ────────────────

    api = APIRouter(dependencies=[Depends(_require_auth)])

    @api.get("/status")
    def status():
        return {k: _mtime_str(f"{k}.parquet")
                for k in ("prices", "metrics", "sectors", "rotation")}

    @api.get("/stocks")
    def stocks():
        return JSONResponse(_records(_load("metrics.parquet")))

    @api.get("/sectors")
    def sectors_route():
        return JSONResponse(_records(_load("sectors.parquet")))

    @api.get("/robots")
    def robots_route():
        """Robot signals (holdings + candidates per robot) from data/robots.json.
        Optional file: returns an empty payload (not 503) when it's absent, so the
        Robots tab shows an empty state instead of erroring."""
        p = data_dir / "robots.json"
        if not p.exists():
            return JSONResponse({"generated_at": None, "robots": []})
        try:
            return JSONResponse(json.loads(p.read_text(encoding="utf-8")))
        except (ValueError, OSError) as e:
            raise HTTPException(503, f"robots.json unreadable: {e}") from e

    @api.get("/stock/{ticker}")
    def stock_detail(ticker: str, days: int = 20):
        """Per-bar indicator series for one ticker (last `days` bars), computed
        on demand from prices.parquet — the same math the pipeline uses."""
        df = _load("prices.parquet")
        if "Market Cap" in df.columns:
            df = (df.drop(columns=["Market Cap"]) if "Market_Cap" in df.columns
                  else df.rename(columns={"Market Cap": "Market_Cap"}))
        sym = ticker.upper()
        df = df[df["Ticker"].astype(str).str.upper() == sym].copy()
        if df.empty:
            raise HTTPException(404, f"No price history for {ticker!r}.")
        df["Date"] = pd.to_datetime(df["Date"])
        g = indicators._compute_group(df.sort_values("Date").reset_index(drop=True), cfg)
        g["Stage"], _, g["Vol_Confirmed"] = indicators.classify_stages(g, cfg)

        cols = ["Date", "Open", "High", "Low", "Close", "Volume", "change_pct",
                "rsi", "atr_pct", "ext", "rvol", "rvol_avg",
                "ema10", "ema20", "ema50", "ema200", "Stage", "Vol_Confirmed"]
        tail = g[[c for c in cols if c in g.columns]].tail(days).copy()
        tail["Date"] = tail["Date"].dt.strftime("%Y-%m-%d")
        last = g.iloc[-1]
        has_mcap = "Market_Cap" in g.columns and pd.notna(last["Market_Cap"])
        return JSONResponse({
            "ticker": sym,
            "sector": last["Sector"] if "Sector" in g.columns and pd.notna(last["Sector"]) else None,
            "market_cap": float(last["Market_Cap"]) if has_mcap else None,
            "bars": _records(tail),
        })

    @api.get("/rotation")
    def rotation_route():
        return JSONResponse({
            "current": _records(_load("rotation.parquet")),
            "tails":   _records(_load("rotation_tail.parquet")),
        })

    app.include_router(api, prefix="/api")
    app.include_router(api, prefix="/api/v1")
    return app
