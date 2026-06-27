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

    print(f"Export complete -> {out_dir}")


if __name__ == "__main__":
    root     = Path(__file__).resolve().parent.parent
    data_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else root / "data"
    out_dir  = Path(sys.argv[2]) if len(sys.argv) > 2 else root / "frontend" / "data"
    export(data_dir, out_dir)
