"""
Golden snapshot test — the safety net for refactoring.

Runs the full pipeline on the frozen fixture and asserts the output parquets
match the committed expected results. If you change pipeline logic and a number
moves, this fails. When the change is intentional and correct, regenerate the
expected files with:  python tests/update_golden.py
"""
from pathlib import Path

import pandas as pd
import pandas.testing as pdt
import pytest

GOLDEN = Path(__file__).parent / "fixtures" / "golden"

OUTPUTS = ["metrics.parquet", "sectors.parquet",
           "rotation.parquet", "rotation_tail.parquet"]


@pytest.mark.parametrize("name", OUTPUTS)
def test_output_matches_golden(built_data, name):
    expected = pd.read_parquet(GOLDEN / name).reset_index(drop=True)
    got      = pd.read_parquet(built_data / name).reset_index(drop=True)
    pdt.assert_frame_equal(got, expected, check_dtype=False,
                           rtol=1e-6, atol=1e-9)
