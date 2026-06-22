"""
sectors.py — aggregate per-stock metrics into sector-level summary.

run(cfg, data_dir) reads  data_dir/metrics.parquet
                   writes data_dir/sectors.parquet
"""
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline.config import Config


def _sqrt_mcap_weighted_mean(group: pd.DataFrame, col: str) -> float:
    mask = group[col].notna()
    if not mask.any():
        return 0.0
    w = group.loc[mask, "sqrt_mcap"]
    v = group.loc[mask, col]
    return float((v * w).sum() / w.sum())


def _top_movers(group: pd.DataFrame, sector_weekly: float) -> str:
    """Top 3 stocks by sqrt_mcap-weighted weekly contribution."""
    g = group.copy()
    w_sum = g["sqrt_mcap"].sum()
    if w_sum <= 0:
        return ""
    g["contrib"] = g["weekly"] * (g["sqrt_mcap"] / w_sum)
    ascending = sector_weekly < 0
    top = g.sort_values("contrib", ascending=ascending).head(3)
    parts = [f"{r['Ticker']} ({r['weekly']:+.1f}%)"
             for _, r in top.iterrows() if pd.notna(r["weekly"])]
    return ", ".join(parts)


def run(cfg: Config, data_dir: Path) -> None:
    metrics_file = data_dir / "metrics.parquet"
    sectors_file = data_dir / "sectors.parquet"

    print("[sectors] Loading metrics...")
    df = pd.read_parquet(metrics_file)
    df["sqrt_mcap"] = np.sqrt(df["Market_Cap"].fillna(1).clip(lower=1))

    rows = []
    for sector, group in df.groupby("Sector"):
        if pd.isna(sector):
            continue
        w_weekly = _sqrt_mcap_weighted_mean(group, "weekly")
        advances = (group["change_pct"] > 0).sum()
        declines = (group["change_pct"] < 0).sum()
        breadth  = (group["Stage"].isin(cfg.stages.breadth_stages).sum() / len(group)) * 100

        rows.append({
            "Sector":      sector,
            "Ticker_Count":len(group),
            "Breadth_Pct": round(breadth, 1),
            "AD":          f"{advances}/{declines}",
            "Daily":       round(_sqrt_mcap_weighted_mean(group, "change_pct"), 2),
            "Weekly":      round(w_weekly, 2),
            "Monthly":     round(_sqrt_mcap_weighted_mean(group, "monthly"), 2),
            "YTD":         round(_sqrt_mcap_weighted_mean(group, "ytd"), 2),
            "Avg_RSI":     round(_sqrt_mcap_weighted_mean(group, "rsi"), 1),
            "Avg_RVOL":    round(_sqrt_mcap_weighted_mean(group, "rvol"), 2),
            "Top3":        _top_movers(group, w_weekly),
        })

    out = pd.DataFrame(rows).sort_values("Sector").reset_index(drop=True)
    out.to_parquet(sectors_file, index=False)
    print(f"[sectors] {len(out)} sectors saved -> {sectors_file.name}")
