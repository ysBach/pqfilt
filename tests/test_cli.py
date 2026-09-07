"""Tests for the pqfilt command-line interface."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from click.testing import CliRunner

from pqfilt.cli import main


def test_cli_writes_filtered_parquet(sample_parquet, tmp_path):
    """The CLI writes the filtered Arrow table as Parquet."""
    output = tmp_path / "filtered.parquet"

    result = CliRunner().invoke(
        main,
        [sample_parquet, "--filter", "a > 5", "--output", str(output)],
    )

    assert result.exit_code == 0, result.output
    assert pd.read_parquet(output)["a"].tolist() == [6, 7, 8, 9, 10]


def test_cli_expands_multiple_globs(multi_parquet: list[str], tmp_path: Path) -> None:
    output = tmp_path / "filtered.parquet"
    result = CliRunner().invoke(
        main,
        [
            str(tmp_path / "part_*.parquet"),
            str(tmp_path / "part_1*.parquet"),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    assert pd.read_parquet(output)["a"].tolist() == list(range(1, 11))
