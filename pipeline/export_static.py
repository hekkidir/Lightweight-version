"""
export_static.py — export pipeline parquets as static JSON for GitHub Pages.

Usage:
    python pipeline/export_static.py [data_dir] [out_dir]

Defaults: data_dir=./data  out_dir=./frontend/data
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd


def _records(df: pd.DataFrame) -> list:
    return json.loads(df.to_json(orient="records"))


def _mtime(path: Path) -> str | None:
    return datetime.fromtimestamp(path.stat().st_mtime).isoformat() if path.exists() else None


def export(data_dir: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    def load(name: str) -> pd.DataFrame | None:
        p = data_dir / name
        return pd.read_parquet(p) if p.exists() else None

    df = load("metrics.parquet")
    if df is not None:
        (out_dir / "stocks.json").write_text(json.dumps(_records(df)), encoding="utf-8")
        print(f"  stocks.json  ({len(df)} rows)")

    df = load("sectors.parquet")
    if df is not None:
        (out_dir / "sectors.json").write_text(json.dumps(_records(df)), encoding="utf-8")
        print(f"  sectors.json ({len(df)} rows)")

    cur  = load("rotation.parquet")
    tail = load("rotation_tail.parquet")
    if cur is not None and tail is not None:
        (out_dir / "rotation.json").write_text(
            json.dumps({"current": _records(cur), "tails": _records(tail)}),
            encoding="utf-8",
        )
        print("  rotation.json")

    p = data_dir / "robots.json"
    if p.exists():
        (out_dir / "robots.json").write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
        print("  robots.json")

    status = {k: _mtime(data_dir / f"{k}.parquet")
              for k in ("prices", "metrics", "sectors", "rotation")}
    (out_dir / "status.json").write_text(json.dumps(status), encoding="utf-8")
    print("  status.json")


def export_stock_details(data_dir: Path, out_dir: Path, cfg, days: int = 20) -> None:
    from pipeline import indicators

    p = data_dir / "prices.parquet"
    if not p.exists():
        print("  stock/*.json skipped (prices.parquet not found)")
        return

    stock_dir = out_dir / "stock"
    stock_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_parquet(p)
    if "Market Cap" in df.columns:
        df = (df.drop(columns=["Market Cap"]) if "Market_Cap" in df.columns
              else df.rename(columns={"Market Cap": "Market_Cap"}))
    df["Date"] = pd.to_datetime(df["Date"])

    cols = ["Date", "Open", "High", "Low", "Close", "Volume", "change_pct",
            "rsi", "atr_pct", "ext", "rvol", "rvol_avg",
            "ema10", "ema20", "ema50", "ema200", "Stage", "Vol_Confirmed"]

    count = 0
    for ticker, group in df.groupby("Ticker"):
        g = indicators._compute_group(group.sort_values("Date").reset_index(drop=True), cfg)
        g["Stage"], _, g["Vol_Confirmed"] = indicators.classify_stages(g, cfg)
        tail = g[[c for c in cols if c in g.columns]].tail(days).copy()
        tail["Date"] = tail["Date"].dt.strftime("%Y-%m-%d")
        last = g.iloc[-1]
        has_mcap = "Market_Cap" in g.columns and pd.notna(last.get("Market_Cap"))
        payload = {
            "ticker": str(ticker).upper(),
            "sector": (str(last["Sector"]) if "Sector" in g.columns
                       and pd.notna(last.get("Sector")) else None),
            "market_cap": float(last["Market_Cap"]) if has_mcap else None,
            "bars": _records(tail),
        }
        (stock_dir / f"{str(ticker).upper()}.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )
        count += 1

    print(f"  stock/*.json ({count} tickers)")


if __name__ == "__main__":
    root     = Path(__file__).resolve().parent.parent
    data_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else root / "data"
    out_dir  = Path(sys.argv[2]) if len(sys.argv) > 2 else root / "frontend" / "data"

    export(data_dir, out_dir)

    from pipeline.config import load as load_cfg
    cfg = load_cfg(root / "config.ini")
    export_stock_details(data_dir, out_dir, cfg)

    print(f"Export complete -> {out_dir}")
