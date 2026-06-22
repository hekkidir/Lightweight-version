"""
config.py — typed settings loader.

All pipeline files import the module-level singleton:
    from pipeline.config import cfg

Access: cfg.stages.rsi_2b, cfg.rotation.tail_length, etc.
Re-load at any time: cfg = config.load(path)
"""
from __future__ import annotations

import configparser
import os
from dataclasses import dataclass
from pathlib import Path

ROOT        = Path(__file__).parent.parent
DATA_DIR    = ROOT / "data"
CONFIG_FILE = ROOT / "config.ini"


@dataclass
class DataConfig:
    history_years:     int
    mcap_refresh_days: int


@dataclass
class StageConfig:
    slope_threshold: float
    slope_window:    int
    rsi_2a_floor:    float
    rsi_2b:          float
    rsi_2c:          float
    ext_2c:          float
    rsi_4a_ceil:     float
    rsi_4b:          float
    rsi_4c:          float
    ext_4c:          float
    rsi_1b_floor:    float
    rsi_3b_ceil:     float
    rvol_confirm:    float
    rvol_window:     int
    max_stale_bars:  int
    breadth_stages:  list[str]


@dataclass
class DownloadConfig:
    chunk_size: int


@dataclass
class RotationConfig:
    window_position:      int
    window_momentum:      int
    tail_length:          int
    cohesion_window:      int
    cohesion_full:        float
    cohesion_min:         float
    min_tickers_cohesion: int
    ema_smooth:           int
    benchmark_weighting:  str   # "equal" or "sqrt_mcap"


@dataclass
class Config:
    data:     DataConfig
    stages:   StageConfig
    download: DownloadConfig
    rotation: RotationConfig


def load(path: Path = CONFIG_FILE) -> Config:
    p = configparser.ConfigParser()
    p.read(path)

    def get(section, key, cast=str, fallback=None):
        try:
            return cast(p[section][key].strip())
        except (KeyError, ValueError):
            return fallback

    return Config(
        data=DataConfig(
            history_years     = get("data", "history_years",     int,   3),
            mcap_refresh_days = get("data", "mcap_refresh_days", int,   7),
        ),
        stages=StageConfig(
            slope_threshold = get("stage_thresholds", "slope_threshold", float, 0.003),
            slope_window    = get("stage_thresholds", "slope_window",    int,   20),
            rsi_2a_floor    = get("stage_thresholds", "rsi_2a_floor",    float, 45.0),
            rsi_2b          = get("stage_thresholds", "rsi_2b",          float, 60.0),
            rsi_2c          = get("stage_thresholds", "rsi_2c",          float, 73.0),
            ext_2c          = get("stage_thresholds", "ext_2c",          float,  5.0),
            rsi_4a_ceil     = get("stage_thresholds", "rsi_4a_ceil",     float, 55.0),
            rsi_4b          = get("stage_thresholds", "rsi_4b",          float, 38.0),
            rsi_4c          = get("stage_thresholds", "rsi_4c",          float, 27.0),
            ext_4c          = get("stage_thresholds", "ext_4c",          float, -3.0),
            rsi_1b_floor    = get("stage_thresholds", "rsi_1b_floor",    float, 40.0),
            rsi_3b_ceil     = get("stage_thresholds", "rsi_3b_ceil",     float, 50.0),
            rvol_confirm    = get("stage_thresholds", "rvol_confirm",    float,  1.1),
            rvol_window     = get("stage_thresholds", "rvol_window",     int,   21),
            max_stale_bars  = get("stage_thresholds", "max_stale_bars",  int,    5),
            breadth_stages  = [s.strip() for s in
                               get("screener", "breadth_stages", str, "2A,2B").split(",")],
        ),
        download=DownloadConfig(
            chunk_size = get("download", "chunk_size", int, 25),
        ),
        rotation=RotationConfig(
            window_position      = get("rotation", "window_position",      int,    20),
            window_momentum      = get("rotation", "window_momentum",      int,     5),
            tail_length          = get("rotation", "tail_length",          int,     7),
            cohesion_window      = get("rotation", "cohesion_window",      int,    30),
            cohesion_full        = get("rotation", "cohesion_full",        float, 0.5),
            cohesion_min         = get("rotation", "cohesion_min",         float, 0.3),
            min_tickers_cohesion = get("rotation", "min_tickers_cohesion", int,   12),
            ema_smooth           = get("rotation", "ema_smooth",           int,     3),
            benchmark_weighting  = get("rotation", "benchmark_weighting",  str, "equal"),
        ),
    )


# Module-level singleton — every other module does: from pipeline.config import cfg
cfg = load()


# ── Runtime / deployment config (from environment, not config.ini) ──────────────
# These differ between your PC and a server (host, port, data location, logging,
# CORS, auth). Analytical knobs stay in config.ini; deployment knobs live here so
# a server can override them without editing tracked files. See .env.example.

@dataclass
class RuntimeConfig:
    host:          str
    port:          int
    data_dir:      Path
    log_level:     str
    live_snapshot: bool        # disable on a server that only wants EOD bars
    cors_origins:  list[str]
    auth_token:    str         # empty == no auth
    alert_webhook: str         # empty == no failure alerts


def _env_bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    return default if v is None else v.strip().lower() in ("1", "true", "yes", "on")


def load_runtime() -> RuntimeConfig:
    data_dir = os.environ.get("SCREENER_DATA_DIR")
    origins  = os.environ.get("SCREENER_CORS_ORIGINS", "").strip()
    return RuntimeConfig(
        host          = os.environ.get("SCREENER_HOST", "0.0.0.0"),
        port          = int(os.environ.get("SCREENER_PORT", "8000")),
        data_dir      = Path(data_dir) if data_dir else DATA_DIR,
        log_level     = os.environ.get("SCREENER_LOG_LEVEL",
                                       os.environ.get("LOG_LEVEL", "INFO")).upper(),
        live_snapshot = _env_bool("SCREENER_LIVE_SNAPSHOT", True),
        cors_origins  = [o.strip() for o in origins.split(",") if o.strip()],
        auth_token    = os.environ.get("SCREENER_AUTH_TOKEN", ""),
        alert_webhook = os.environ.get("SCREENER_ALERT_WEBHOOK", ""),
    )


runtime = load_runtime()
