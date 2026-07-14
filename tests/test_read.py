"""Tests for the core read() function."""

from __future__ import annotations

import pandas as pd
import pytest

import pqfilt


class TestReadBasicFilter:
    def test_gt_filter(self, sample_parquet):
        df = pqfilt.read(sample_parquet, filters="a > 5")
        assert len(df) == 5
        assert all(df["a"] > 5)

    def test_le_filter(self, sample_parquet):
        df = pqfilt.read(sample_parquet, filters="b <= 50")
        assert len(df) == 5
        assert all(df["b"] <= 50)

    def test_eq_filter(self, sample_parquet):
        df = pqfilt.read(sample_parquet, filters="a == 3")
        assert len(df) == 1
        assert df["a"].iloc[0] == 3

    def test_no_filter(self, sample_parquet):
        df = pqfilt.read(sample_parquet)
        assert len(df) == 10

    def test_empty_result(self, sample_parquet):
        df = pqfilt.read(sample_parquet, filters="a > 100")
        assert len(df) == 0


class TestReadExpressionSyntax:
    def test_and(self, sample_parquet):
        df = pqfilt.read(sample_parquet, filters="a > 3 & b < 80")
        assert all(df["a"] > 3)
        assert all(df["b"] < 80)

    def test_or(self, sample_parquet):
        df = pqfilt.read(sample_parquet, filters="a <= 2 | a >= 9")
        assert all((df["a"] <= 2) | (df["a"] >= 9))
        assert len(df) == 4  # 1,2,9,10

    def test_complex(self, sample_parquet):
        df = pqfilt.read(sample_parquet, filters="(a <= 2 & b <= 20) | a == 10")
        assert len(df) == 3  # rows with a=1,2,10

    def test_in(self, sample_parquet):
        df = pqfilt.read(sample_parquet, filters="a in 1,3,5")
        assert set(df["a"]) == {1, 3, 5}


class TestReadTupleSyntax:
    def test_flat_and(self, sample_parquet):
        df = pqfilt.read(sample_parquet, filters=[("a", ">", 5), ("b", "<", 90)])
        assert all(df["a"] > 5)
        assert all(df["b"] < 90)

    def test_dnf_or(self, sample_parquet):
        df = pqfilt.read(
            sample_parquet,
            filters=[
                [("a", "<=", 2)],
                [("a", ">=", 9)],
            ],
        )
        assert len(df) == 4


class TestReadColumns:
    def test_column_selection(self, sample_parquet):
        df = pqfilt.read(sample_parquet, columns=["a", "b"])
        assert list(df.columns) == ["a", "b"]

    def test_column_selection_with_filter(self, sample_parquet):
        df = pqfilt.read(sample_parquet, filters="a > 5", columns=["a", "name"])
        assert set(df.columns) == {"a", "name"}
        assert all(df["a"] > 5)


class TestScan:
    def test_uses_read_defaults(self, sample_parquet):
        assert pqfilt.scan(sample_parquet).to_table().num_rows == 10

    def test_returns_filtered_arrow_scanner(self, sample_parquet):
        scanner = pqfilt.scan(sample_parquet, filters="a > 5", columns=["a", "name"])
        table = scanner.to_table()

        assert table.num_rows == 5
        assert table.column_names == ["a", "name"]
        assert table["a"].to_pylist() == [6, 7, 8, 9, 10]


class TestWriteFiltered:
    def test_streams_filtered_parquet(self, sample_parquet, tmp_path):
        output = tmp_path / "filtered.parquet"

        rows_written = pqfilt.write_filtered(sample_parquet, output, filters="a > 5")

        assert rows_written == 5
        assert pd.read_parquet(output)["a"].tolist() == [6, 7, 8, 9, 10]

    def test_streams_filtered_csv(self, sample_parquet, tmp_path):
        output = tmp_path / "filtered.csv"

        rows_written = pqfilt.write_filtered(sample_parquet, output, filters="a > 5")

        assert rows_written == 5
        assert pd.read_csv(output)["a"].tolist() == [6, 7, 8, 9, 10]

    def test_writes_empty_parquet(self, sample_parquet, tmp_path):
        output = tmp_path / "empty.parquet"

        rows_written = pqfilt.write_filtered(sample_parquet, output, filters="a > 100")

        assert rows_written == 0
        assert pd.read_parquet(output).empty

    def test_rejects_input_as_output(self, sample_parquet):
        with pytest.raises(ValueError, match="must not be an input file"):
            pqfilt.write_filtered(sample_parquet, sample_parquet, overwrite=True)


class TestReadMultiFile:
    def test_multi_file(self, multi_parquet):
        df = pqfilt.read(multi_parquet, filters="a > 3")
        assert all(df["a"] > 3)

    def test_glob(self, multi_parquet, tmp_path):
        pattern = str(tmp_path / "part_*.parquet")
        df = pqfilt.read(pattern)
        assert len(df) == 10


class TestReadOutput:
    def test_save_parquet(self, sample_parquet, tmp_path):
        out = str(tmp_path / "out.parquet")
        df = pqfilt.read(sample_parquet, filters="a > 5", output=out)
        reloaded = pd.read_parquet(out)
        assert len(reloaded) == len(df)

    def test_save_csv(self, sample_parquet, tmp_path):
        out = str(tmp_path / "out.csv")
        df = pqfilt.read(sample_parquet, filters="a > 5", output=out)
        reloaded = pd.read_csv(out)
        assert len(reloaded) == len(df)

    def test_overwrite_false_raises(self, sample_parquet, tmp_path):
        out = str(tmp_path / "exists.parquet")
        pqfilt.read(sample_parquet, output=out)
        with pytest.raises(FileExistsError):
            pqfilt.read(sample_parquet, output=out, overwrite=False)

    def test_overwrite_true(self, sample_parquet, tmp_path):
        out = str(tmp_path / "exists.parquet")
        pqfilt.read(sample_parquet, output=out)
        pqfilt.read(sample_parquet, filters="a > 5", output=out, overwrite=True)
        reloaded = pd.read_parquet(out)
        assert len(reloaded) == 5


class TestReadSpecialColumns:
    def test_space_in_column(self, sample_parquet):
        df = pqfilt.read(sample_parquet, filters="`x y` > 0.5")
        assert all(df["x y"] > 0.5)

    def test_star_in_column(self, sample_parquet):
        df = pqfilt.read(sample_parquet, filters="`r*1000` >= 500")
        assert all(df["r*1000"] >= 500)


class TestReadNullOperators:
    @pytest.fixture
    def nullable_parquet(self, tmp_path):
        path = tmp_path / "nullable.parquet"
        df = pd.DataFrame(
            {
                "id": [1, 2, 3, 4, 5],
                "v": [1.0, None, 3.0, None, 5.0],
            }
        )
        df.to_parquet(path, index=False)
        return str(path)

    def test_is_null_pushdown(self, nullable_parquet):
        df = pqfilt.read(nullable_parquet, filters="v is null")
        assert len(df) == 2
        assert df["id"].tolist() == [2, 4]

    def test_is_not_null_pushdown(self, nullable_parquet):
        df = pqfilt.read(nullable_parquet, filters="v is not null")
        assert len(df) == 3
        assert df["id"].tolist() == [1, 3, 5]

    def test_is_null_tuple_syntax(self, nullable_parquet):
        df = pqfilt.read(nullable_parquet, filters=[("v", "is null", None)])
        assert len(df) == 2


class TestReadErrors:
    def test_nonexistent_file(self):
        with pytest.raises(FileNotFoundError):
            pqfilt.read("/nonexistent/*.parquet")

    def test_invalid_filter_type(self, sample_parquet):
        with pytest.raises(TypeError):
            pqfilt.read(sample_parquet, filters=42)


@pytest.fixture()
def bool_parquet(tmp_path):
    """Parquet file with a bool column ``is_comet``."""
    df = pd.DataFrame(
        {
            "name": ["A", "B", "C", "D"],
            "is_comet": [True, False, True, False],
            "value": [1, 2, 3, 4],
        }
    )
    path = tmp_path / "bool_test.parquet"
    df.to_parquet(path, index=False)
    return str(path)


class TestReadBoolFilter:
    def test_true_string(self, bool_parquet):
        df = pqfilt.read(bool_parquet, filters="is_comet == True")
        assert list(df["is_comet"]) == [True, True]
        assert set(df["name"]) == {"A", "C"}

    def test_false_string(self, bool_parquet):
        df = pqfilt.read(bool_parquet, filters="is_comet == False")
        assert list(df["is_comet"]) == [False, False]
        assert set(df["name"]) == {"B", "D"}

    def test_true_lowercase(self, bool_parquet):
        df = pqfilt.read(bool_parquet, filters="is_comet == true")
        assert len(df) == 2

    def test_false_uppercase(self, bool_parquet):
        df = pqfilt.read(bool_parquet, filters="is_comet == FALSE")
        assert len(df) == 2

    def test_true_tuple_syntax(self, bool_parquet):
        df = pqfilt.read(bool_parquet, filters=[("is_comet", "==", True)])
        assert len(df) == 2

    def test_neq_bool(self, bool_parquet):
        df = pqfilt.read(bool_parquet, filters="is_comet != True")
        assert len(df) == 2
        assert all(~df["is_comet"])

    def test_bool_and_numeric(self, bool_parquet):
        df = pqfilt.read(bool_parquet, filters="is_comet == True & value > 1")
        assert len(df) == 1
        assert df["name"].iloc[0] == "C"


class TestReadLargeIntegers:
    def test_uint64_scalar_and_membership_filters_preserve_precision(self, tmp_path):
        path = tmp_path / "uint64.parquet"
        large_id = 9007199254740993
        pd.DataFrame({"id": pd.Series([large_id, large_id + 1], dtype="uint64")}).to_parquet(
            path,
            index=False,
        )

        scalar = pqfilt.read(path, filters=f"id == {large_id}")
        membership = pqfilt.read(path, filters=f"id in {large_id}")

        assert scalar["id"].tolist() == [large_id]
        assert membership["id"].tolist() == [large_id]


class TestReadNegation:
    def test_not_simple(self, sample_parquet):
        df = pqfilt.read(sample_parquet, filters="~(a > 5)")
        assert all(df["a"] <= 5)
        assert len(df) == 5

    def test_not_compound(self, sample_parquet):
        # ~(a <= 2 | a >= 9) should give rows 3..8
        df = pqfilt.read(sample_parquet, filters="~(a <= 2 | a >= 9)")
        assert len(df) == 6
        assert all((df["a"] > 2) & (df["a"] < 9))
