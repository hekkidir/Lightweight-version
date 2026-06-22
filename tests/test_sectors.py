"""Unit test for sector aggregation pure function."""
import pandas as pd

from pipeline.sectors import _sqrt_mcap_weighted_mean


def test_sqrt_mcap_weighted_mean():
    g = pd.DataFrame({"sqrt_mcap": [1.0, 3.0], "x": [10.0, 20.0]})
    # (10*1 + 20*3) / (1+3) = 70/4 = 17.5
    assert _sqrt_mcap_weighted_mean(g, "x") == 17.5


def test_sqrt_mcap_weighted_mean_all_nan_is_zero():
    g = pd.DataFrame({"sqrt_mcap": [1.0, 2.0], "x": [float("nan"), float("nan")]})
    assert _sqrt_mcap_weighted_mean(g, "x") == 0.0
