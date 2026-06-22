"""
Contract / drift tests — the executable doc-sync mechanism.

If a pipeline stage changes its output columns without updating pipeline/schema.py
(or vice versa), these fail. That keeps code and the documented contract in sync
automatically instead of relying on anyone to remember.
"""
from pathlib import Path

import pandas as pd

from pipeline import schema
from pipeline.config import load

ROOT = Path(__file__).parent.parent


def test_config_loads_and_is_typed():
    cfg = load(ROOT / "config.ini")
    assert isinstance(cfg.stages.rvol_window, int)
    assert isinstance(cfg.stages.max_stale_bars, int)
    assert isinstance(cfg.rotation.tail_length, int)
    assert cfg.stages.breadth_stages  # non-empty list


def test_metrics_matches_schema(built_data):
    df = pd.read_parquet(built_data / "metrics.parquet")
    assert schema.missing_columns("metrics.parquet", df) == []


def test_sectors_matches_schema(built_data):
    df = pd.read_parquet(built_data / "sectors.parquet")
    assert schema.missing_columns("sectors.parquet", df) == []


def test_rotation_matches_schema(built_data):
    rot  = pd.read_parquet(built_data / "rotation.parquet")
    tail = pd.read_parquet(built_data / "rotation_tail.parquet")
    assert schema.missing_columns("rotation.parquet", rot) == []
    assert schema.missing_columns("rotation_tail.parquet", tail) == []
