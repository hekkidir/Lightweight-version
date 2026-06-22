"""Tests for the data health check."""
from pipeline.health import check


def test_built_data_is_healthy(built_data):
    assert check(built_data) == []


def test_empty_dir_reports_missing_files(tmp_path):
    problems = check(tmp_path)
    assert any("missing file" in p for p in problems)
