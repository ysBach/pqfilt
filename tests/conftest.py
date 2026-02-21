"""Shared test fixtures."""

from __future__ import annotations

import pandas as pd
import pytest


@pytest.fixture()
def sample_df() -> pd.DataFrame:
    """DataFrame with varied column types for testing."""
    return pd.DataFrame({
        "a": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
        "b": [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0],
        "name": ["alpha", "beta", "gamma", "delta", "epsilon",
                 "zeta", "eta", "theta", "iota", "kappa"],
        "x y": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],  # space in name
        "r*1000": [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000],  # special char
    })


@pytest.fixture()
def sample_parquet(tmp_path, sample_df) -> str:
    """Write sample_df to a Parquet file and return its path."""
    path = tmp_path / "sample.parquet"
    sample_df.to_parquet(path, index=False)
    return str(path)


@pytest.fixture()
def multi_parquet(tmp_path, sample_df) -> list[str]:
    """Write two Parquet files and return their paths."""
    paths = []
    for i in range(2):
        path = tmp_path / f"part_{i}.parquet"
        chunk = sample_df.iloc[i * 5 : (i + 1) * 5]
        chunk.to_parquet(path, index=False)
        paths.append(str(path))
    return paths
