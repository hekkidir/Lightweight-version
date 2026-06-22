"""
conftest.py — shared pytest fixtures.

`cfg`        — Config loaded from the real config.ini (so tests track prod config).
`built_data` — a temp data dir with the pipeline run end-to-end on the frozen
               fixture (indicators -> sectors -> rotation), no network, <1s.
"""
import shutil
from pathlib import Path

import pytest

ROOT     = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def cfg():
    from pipeline.config import load
    return load(ROOT / "config.ini")


@pytest.fixture(scope="session")
def built_data(tmp_path_factory, cfg):
    from pipeline import indicators, rotation, sectors
    d = tmp_path_factory.mktemp("data")
    shutil.copy(FIXTURES / "prices_sample.parquet", d / "prices.parquet")
    indicators.run(cfg, d)
    sectors.run(cfg, d)
    rotation.run(cfg, d)
    return d
