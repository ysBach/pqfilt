"""Tests for filter_df() -- pandas DataFrame filtering."""

from __future__ import annotations

import pandas as pd
import pytest

import pqfilt


@pytest.fixture
def df():
    return pd.DataFrame(
        {
            "a": list(range(1, 11)),
            "b": list(range(10, 110, 10)),
            "name": [f"obj{i}" for i in range(1, 11)],
            "flag": [True, False] * 5,
            "v": [1.0, None, 3.0, None, 5.0, 6.0, 7.0, None, 9.0, 10.0],
        }
    )


class TestFilterDfBasic:
    def test_gt(self, df):
        out = pqfilt.filter_df(df, "a > 5")
        assert list(out["a"]) == [6, 7, 8, 9, 10]

    def test_le(self, df):
        out = pqfilt.filter_df(df, "b <= 50")
        assert all(out["b"] <= 50)

    def test_eq(self, df):
        out = pqfilt.filter_df(df, "a == 3")
        assert len(out) == 1 and out["a"].iloc[0] == 3

    def test_ne(self, df):
        out = pqfilt.filter_df(df, "a != 5")
        assert 5 not in out["a"].values

    def test_no_match(self, df):
        assert len(pqfilt.filter_df(df, "a > 100")) == 0

    def test_index_reset(self, df):
        out = pqfilt.filter_df(df, "a > 5")
        assert list(out.index) == list(range(len(out)))


class TestFilterDfCompound:
    def test_and(self, df):
        out = pqfilt.filter_df(df, "a > 3 & b < 80")
        assert all(out["a"] > 3) and all(out["b"] < 80)

    def test_or(self, df):
        out = pqfilt.filter_df(df, "a <= 2 | a >= 9")
        assert len(out) == 4

    def test_complex(self, df):
        out = pqfilt.filter_df(df, "(a <= 2 & b <= 20) | a == 10")
        assert set(out["a"]) == {1, 2, 10}

    def test_not_simple(self, df):
        out = pqfilt.filter_df(df, "~(a > 5)")
        assert all(out["a"] <= 5)

    def test_not_compound(self, df):
        out = pqfilt.filter_df(df, "~(a <= 2 | a >= 9)")
        assert len(out) == 6
        assert all((out["a"] > 2) & (out["a"] < 9))


class TestFilterDfMembership:
    def test_in(self, df):
        out = pqfilt.filter_df(df, "a in 1,3,5")
        assert set(out["a"]) == {1, 3, 5}

    def test_not_in(self, df):
        out = pqfilt.filter_df(df, "a not in 1,2,3")
        assert not any(v in out["a"].values for v in [1, 2, 3])

    def test_not_in_negation(self, df):
        out = pqfilt.filter_df(df, "~(a in 1,2,3)")
        assert set(out["a"]) == set(pqfilt.filter_df(df, "a not in 1,2,3")["a"])


class TestFilterDfNull:
    def test_is_null(self, df):
        out = pqfilt.filter_df(df, "v is null")
        assert out["v"].isna().all()
        assert len(out) == 3

    def test_is_not_null(self, df):
        out = pqfilt.filter_df(df, "v is not null")
        assert out["v"].notna().all()
        assert len(out) == 7

    def test_is_null_tuple(self, df):
        out = pqfilt.filter_df(df, [("v", "is null", None)])
        assert len(out) == 3


class TestFilterDfArrowNullSemantics:
    @pytest.fixture
    def nullable_df(self):
        return pd.DataFrame({"id": [1, 2, 3], "a": [1.0, 2.0, None]})

    @pytest.mark.parametrize(
        "filters",
        [
            "a != 2",
            "~(a == 2)",
            "a > 1 | a == 1",
            "a in 1,2",
            "a not in 1,2",
            [("a", "in", [None])],
            [("a", "not in", [None])],
        ],
    )
    def test_matches_read(self, nullable_df, tmp_path, filters):
        path = tmp_path / "nullable.parquet"
        nullable_df.to_parquet(path, index=False)

        from_dataframe = pqfilt.filter_df(nullable_df, filters)
        from_parquet = pqfilt.read(path, filters=filters)

        assert from_dataframe["id"].tolist() == from_parquet["id"].tolist()


class TestFilterDfBool:
    def test_true(self, df):
        out = pqfilt.filter_df(df, "flag == True")
        assert out["flag"].all()

    def test_false(self, df):
        out = pqfilt.filter_df(df, "flag == False")
        assert not out["flag"].any()


class TestFilterDfTupleSyntax:
    def test_flat_and(self, df):
        out = pqfilt.filter_df(df, [("a", ">", 5), ("b", "<", 90)])
        assert all(out["a"] > 5) and all(out["b"] < 90)

    def test_dnf(self, df):
        out = pqfilt.filter_df(df, [[("a", "<=", 2)], [("a", ">=", 9)]])
        assert len(out) == 4


class TestFilterDfErrors:
    def test_missing_column(self, df):
        with pytest.raises(KeyError, match="no_such_col"):
            pqfilt.filter_df(df, "no_such_col > 0")

    def test_invalid_type(self, df):
        with pytest.raises(TypeError):
            pqfilt.filter_df(df, 42)
