"""Unit tests for RRG pure functions."""
import numpy as np
import pandas as pd

from pipeline.rotation import _cohesion_weight, _quadrant, _xy


def test_quadrants():
    assert _quadrant(1, 1)   == "STRONG"
    assert _quadrant(-1, 1)  == "WARMING"
    assert _quadrant(-1, -1) == "WEAK"
    assert _quadrant(1, -1)  == "COOLING"
    assert _quadrant(0, 0)   == "STRONG"   # boundary: x>=0 and y>=0


def test_cohesion_weight_ramp(cfg):
    assert _cohesion_weight(0.2, cfg) == 0.0   # below cohesion_min (0.3)
    assert _cohesion_weight(0.6, cfg) == 1.0   # above cohesion_full (0.5)
    mid = _cohesion_weight(0.4, cfg)            # midpoint -> soft ramp
    assert 0.5 < mid < 1.0


def test_cohesion_weight_nan_is_zero(cfg):
    assert _cohesion_weight(np.nan, cfg) == 0.0


def test_xy_short_series_returns_nan():
    x, y = _xy(pd.Series(range(3)), window_pos=20, window_mom=5)
    assert np.isnan(x) and np.isnan(y)


def test_xy_rising_series_positive_momentum():
    rs = pd.Series(np.linspace(0, 10, 60))     # steadily rising
    x, y = _xy(rs, window_pos=20, window_mom=5)
    assert x > 0 and y > 0
