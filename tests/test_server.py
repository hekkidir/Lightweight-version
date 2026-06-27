"""
Server contract tests — the API returns the exact fields the frontend reads
(derived from frontend/views.js). If a pipeline change drops one of these, the
dashboard would silently break; this fails instead.
"""
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT     = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures"

STOCK_FIELDS  = {"Ticker", "Sector", "Stage", "Close", "ext", "rsi", "Vol_Confirmed"}
SECTOR_FIELDS = {"Sector", "Breadth_Pct", "Weekly"}
ROT_FIELDS    = {"Sector", "Quadrant", "X", "Y", "Strength_Score"}


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    from pipeline import indicators, rotation, sectors
    from pipeline.config import load
    from server.app import create_app

    cfg  = load(ROOT / "config.ini")
    base = tmp_path_factory.mktemp("app")
    data = base / "data"
    data.mkdir()
    (base / "frontend").mkdir()
    (base / "frontend" / "index.html").write_text("<html></html>")
    (base / "VERSION").write_text("test")
    shutil.copy(FIXTURES / "prices_sample.parquet", data / "prices.parquet")
    shutil.copy(FIXTURES / "robots_sample.json", data / "robots.json")
    indicators.run(cfg, data)
    sectors.run(cfg, data)
    rotation.run(cfg, data)

    return TestClient(create_app(data))


def test_stocks_has_frontend_fields(client):
    rows = client.get("/api/stocks").json()
    assert rows and STOCK_FIELDS <= set(rows[0])


def test_sectors_has_frontend_fields(client):
    rows = client.get("/api/sectors").json()
    assert rows and SECTOR_FIELDS <= set(rows[0])


def test_rotation_has_frontend_fields(client):
    data = client.get("/api/rotation").json()
    assert "current" in data and "tails" in data
    assert ROT_FIELDS <= set(data["current"][0])


def test_stock_detail_endpoint(client):
    tkr = client.get("/api/stocks").json()[0]["Ticker"]
    data = client.get(f"/api/stock/{tkr}").json()
    assert data["ticker"] == tkr.upper()
    bars = data["bars"]
    assert bars and len(bars) <= 20
    assert {"Date", "Close", "rsi", "atr_pct", "ext", "rvol_avg", "Stage"} <= set(bars[-1])


def test_stock_detail_unknown_404(client):
    assert client.get("/api/stock/NOPE_NOT_A_TICKER").status_code == 404


def test_health_endpoint_ok(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_robots_endpoint(client):
    from pipeline.robots import ROBOTS
    data = client.get("/api/robots").json()
    assert len(data["robots"]) == len(ROBOTS)
    r0 = data["robots"][0]
    assert {"name", "key", "holdings", "candidates"} <= set(r0)


def test_robots_missing_is_empty(tmp_path):
    from server.app import create_app
    empty = tmp_path / "data"
    empty.mkdir()
    c = TestClient(create_app(empty))
    data = c.get("/api/robots").json()
    assert data["robots"] == [] and data["generated_at"] is None


def test_v1_alias_works(client):
    assert client.get("/api/v1/stocks").status_code == 200


def test_static_is_revalidated(client):
    # no-cache prevents stale JS being served after a frontend change.
    # Frontend assets are served from root (matching GitHub Pages), not /static.
    r = client.get("/app.js")
    assert r.status_code == 200
    assert "no-cache" in r.headers.get("cache-control", "")
