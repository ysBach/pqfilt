"""Tests for the pqfilt command-line interface."""

from __future__ import annotations

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
