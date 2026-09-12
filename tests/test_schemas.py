"""Multi-file schemas preserve selected values across Arrow, pandas, and CSV."""

from __future__ import annotations

import csv
from collections.abc import Callable, Sequence
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq
import pytest
from click.testing import CliRunner

import pqfilt
from pqfilt.cli import main

ParquetFactory = Callable[[Sequence[pa.Table]], list[Path]]


@pytest.fixture
def write_tables(tmp_path: Path) -> ParquetFactory:
    """Write ordered fragments with each table's own schema."""

    def write(tables: Sequence[pa.Table]) -> list[Path]:
        paths = []
        for index, table in enumerate(tables):
            path = tmp_path / f"part_{index}.parq"
            pq.write_table(table, path)
            paths.append(path)
        return paths

    return write


@pytest.fixture
def mixed_files(write_tables: ParquetFactory) -> tuple[list[Path], pa.Table]:
    """Include null/integer and float/integer fields with empty filtered fragments."""
    longitudes = [2.0, 0.05, 3.0, -0.05, 4.0]
    counts = [None, 7, None, 9, 11]
    orders = [1.5, 2, 3.5, 4, 5]
    tables = []
    for index, (longitude, count, order) in enumerate(zip(longitudes, counts, orders)):
        tables.append(
            pa.table(
                {
                    "id": [index],
                    "longitude": [longitude],
                    "latitude": [-0.5],
                    "optional_count": pa.array(
                        [count], type=pa.null() if count is None else pa.int32()
                    ),
                    "order": pa.array([order], type=pa.float64() if count is None else pa.uint8()),
                }
            )
        )
    expected = pa.table(
        {
            "id": list(range(len(tables))),
            "longitude": longitudes,
            "latitude": [-0.5] * len(tables),
            "optional_count": pa.array(counts, type=pa.int32()),
            "order": pa.array(orders, type=pa.float64()),
        }
    )
    return write_tables(tables), expected


@pytest.mark.parametrize("reverse", [False, True])
def test_scan_and_read_reconcile_mixed_schemas(
    mixed_files: tuple[list[Path], pa.Table], reverse: bool
) -> None:
    files, expected = mixed_files
    source = files[::-1] if reverse else files

    actual = pqfilt.scan(source).to_table().sort_by([("id", "ascending")])
    frame = pqfilt.read(source).sort_values("id").reset_index(drop=True)

    assert actual.equals(expected)
    pd.testing.assert_frame_equal(frame, expected.to_pandas())


@pytest.mark.parametrize("reverse", [False, True])
def test_pandas_nullable_integer_metadata_allows_float_promotion(
    write_tables: ParquetFactory, reverse: bool
) -> None:
    files = write_tables(
        [
            pa.Table.from_pandas(
                pd.DataFrame(
                    {
                        "id": [0, 1],
                        "value": pd.Series([None, 2], dtype="UInt8"),
                        "quality": pd.Series([None, 1], dtype="UInt16"),
                    }
                ),
                preserve_index=False,
            ),
            pa.Table.from_pandas(
                pd.DataFrame(
                    {
                        "id": [2, 3],
                        "value": [0.5, 3.5],
                        "quality": pd.Series([2, None], dtype="UInt16"),
                    }
                ),
                preserve_index=False,
            ),
        ]
    )

    actual = pqfilt.read(files[::-1] if reverse else files).sort_values("id").reset_index(drop=True)

    pd.testing.assert_frame_equal(
        actual,
        pd.DataFrame(
            {
                "id": [0, 1, 2, 3],
                "value": [None, 2.0, 0.5, 3.5],
                "quality": pd.Series([None, 1, 2, None], dtype="UInt16"),
            }
        ),
    )


@pytest.mark.parametrize("reverse", [False, True])
def test_pandas_nullable_integer_promotion_preserves_large_values(
    write_tables: ParquetFactory, reverse: bool
) -> None:
    large = 2**53 + 1
    files = write_tables(
        [
            pa.Table.from_pandas(
                pd.DataFrame({"id": [0, 1], "value": pd.Series([None, 1], dtype="Int8")}),
                preserve_index=False,
            ),
            pa.Table.from_pandas(
                pd.DataFrame({"id": [2], "value": pd.Series([large], dtype="Int64")}),
                preserve_index=False,
            ),
        ]
    )

    actual = pqfilt.read(files[::-1] if reverse else files).sort_values("id").reset_index(drop=True)

    pd.testing.assert_frame_equal(
        actual,
        pd.DataFrame({"id": [0, 1, 2], "value": pd.Series([None, 1, large], dtype="Int64")}),
        check_exact=True,
    )


@pytest.mark.parametrize("first_field", ["missing", "null"])
@pytest.mark.parametrize("dtype", ["Int64", "UInt64"])
@pytest.mark.parametrize("reverse", [False, True])
def test_new_nullable_integer_column_preserves_large_values(
    write_tables: ParquetFactory, first_field: str, dtype: str, reverse: bool
) -> None:
    large = 2**53 + 1 if dtype == "Int64" else 2**63 + 1
    first = pa.table({"id": [0]})
    if first_field == "null":
        first = first.append_column("value", pa.nulls(1))
    files = write_tables(
        [
            first,
            pa.Table.from_pandas(
                pd.DataFrame({"id": [1], "value": pd.Series([large], dtype=dtype)}),
                preserve_index=False,
            ),
        ]
    )

    actual = pqfilt.read(files[::-1] if reverse else files).sort_values("id").reset_index(drop=True)

    pd.testing.assert_frame_equal(
        actual,
        pd.DataFrame({"id": [0, 1], "value": pd.Series([None, large], dtype=dtype)}),
        check_exact=True,
    )


def test_null_integer_promotion_preserves_existing_metadata(
    write_tables: ParquetFactory,
) -> None:
    first = pa.Table.from_pandas(pd.DataFrame({"id": [0], "value": [None]}), preserve_index=False)
    first = first.replace_schema_metadata({**first.schema.metadata, b"origin": b"first-source"})
    large = 2**53 + 1
    files = write_tables([first, pa.table({"id": [1], "value": [large]})])

    actual = pqfilt.read(files)

    pd.testing.assert_frame_equal(
        actual,
        pd.DataFrame({"id": [0, 1], "value": pd.Series([None, large], dtype="Int64")}),
        check_exact=True,
    )
    assert pqfilt.scan(files).dataset_schema.metadata[b"origin"] == b"first-source"


@pytest.mark.parametrize("reverse", [False, True])
def test_schema_union_preserves_fields_and_fills_missing_values(
    write_tables: ParquetFactory, reverse: bool
) -> None:
    files = write_tables(
        [
            pa.table({"id": [0], "left": [10]}),
            pa.table({"id": [1], "right": [20]}),
        ]
    )
    expected = pa.table({"id": [0, 1], "left": [10, None], "right": [None, 20]})

    actual = pqfilt.scan(files[::-1] if reverse else files).to_table()

    assert actual.select(expected.column_names).sort_by([("id", "ascending")]).equals(expected)


def test_missing_nonnullable_field_roundtrips_as_nullable(
    write_tables: ParquetFactory, tmp_path: Path
) -> None:
    files = write_tables(
        [
            pa.table(
                {"id": [0], "value": [7]},
                schema=pa.schema(
                    [pa.field("id", pa.int64()), pa.field("value", pa.int32(), nullable=False)]
                ),
            ),
            pa.table({"id": [1]}),
        ]
    )
    output = tmp_path / "nullable.parquet"

    rows = pqfilt.write_filtered(files, output)
    actual = pq.read_table(output)

    assert rows == 2
    assert actual.schema.field("value").nullable
    assert actual.equals(pa.table({"id": [0, 1], "value": pa.array([7, None], type=pa.int32())}))


def test_duplicate_needed_field_names_are_rejected(write_tables: ParquetFactory) -> None:
    files = write_tables(
        [
            pa.table([[0], [1], [2]], names=["id", "value", "value"]),
            pa.table({"id": [1], "value": [3]}),
        ]
    )

    with pytest.raises((pa.ArrowInvalid, pa.ArrowTypeError), match="value"):
        pqfilt.scan(files, filters="value > 0", columns=["id"])


@pytest.mark.parametrize("first_field", ["null", "missing"])
def test_filter_uses_concrete_type_from_later_file(
    write_tables: ParquetFactory, first_field: str
) -> None:
    first = pa.table({"id": [0]})
    if first_field == "null":
        first = first.append_column("value", pa.nulls(1))
    files = write_tables([first, pa.table({"id": [1, 2], "value": [0.05, 2.0]})])

    actual = pqfilt.scan(files, filters="value < 0.1", columns=["id"]).to_table()

    assert actual.equals(pa.table({"id": [1]}))


def test_nested_filter_preserves_row_count_with_no_output_columns(
    write_tables: ParquetFactory,
) -> None:
    files = write_tables(
        [
            pa.table({"id": [0], "a": [0]}),
            pa.table({"id": [1, 2, 3], "a": [1, 2, 3], "b": [True, False, True]}),
        ]
    )

    actual = pqfilt.scan(files, filters="~((a < 1) | (b == True))", columns=[]).to_table()

    assert actual.num_columns == 0
    assert actual.num_rows == 1


def test_projection_ignores_incompatible_unused_field(write_tables: ParquetFactory) -> None:
    files = write_tables(
        [
            pa.table({"id": [0], "value": [0.05], "unused": ["text"]}),
            pa.table({"id": [1], "value": [0.06], "unused": [7]}),
        ]
    )

    actual = pqfilt.scan(files, filters="value < 0.1", columns=["id"]).to_table()

    assert actual.equals(pa.table({"id": [0, 1]}))


def test_nested_struct_projection_matches_arrow(write_tables: ParquetFactory) -> None:
    files = write_tables(
        [
            pa.table({"s": [{"x": 1, "y": 10}]}),
            pa.table({"s": [{"x": 2, "y": 20}]}),
        ]
    )
    expected = ds.dataset([str(file) for file in files], format="parquet").to_table(columns=["s.x"])

    actual = pqfilt.scan(files, columns=["s.x"]).to_table()

    assert actual.equals(expected)


def test_literal_dotted_column_takes_precedence_over_struct(
    write_tables: ParquetFactory,
) -> None:
    files = write_tables(
        [
            pa.table({"s.x": [11], "s": [{"x": 1}]}),
            pa.table({"s.x": [12], "s": ["unused"]}),
        ]
    )

    actual = pqfilt.scan(files, columns=["s.x"]).to_table()

    assert actual.equals(pa.table({"s.x": [11, 12]}))


@pytest.mark.parametrize("reverse", [False, True])
def test_incompatible_selected_field_has_actionable_error(
    write_tables: ParquetFactory, reverse: bool
) -> None:
    files = write_tables(
        [
            pa.table({"id": [0], "payload": ["text"]}),
            pa.table({"id": [1], "payload": [7]}),
        ]
    )

    with pytest.raises(pa.ArrowTypeError, match="payload"):
        pqfilt.scan(files[::-1] if reverse else files).to_table()


@pytest.mark.parametrize("reverse", [False, True])
def test_integer_float_promotion_rejects_precision_loss(
    write_tables: ParquetFactory, reverse: bool
) -> None:
    files = write_tables(
        [
            pa.table({"id": [0], "measurement": [0.5]}),
            pa.table({"id": [1], "measurement": [2**53 + 1]}),
        ]
    )

    with pytest.raises(pa.ArrowInvalid):
        pqfilt.scan(files[::-1] if reverse else files).to_table()


@pytest.mark.parametrize("suffix", [".parquet", ".csv"])
@pytest.mark.parametrize("existing", [False, True])
def test_lazy_cast_failure_preserves_destination(
    write_tables: ParquetFactory, tmp_path: Path, suffix: str, existing: bool
) -> None:
    first = pa.table({"measurement": [0.5]})
    files = write_tables([first, pa.table({"measurement": [2**53 + 1]})])
    batches = pqfilt.scan(files).to_batches()
    assert next(batches).equals(first.to_batches()[0])
    with pytest.raises(pa.ArrowInvalid):
        next(batches)

    output = tmp_path / f"filtered{suffix}"
    original = b"previous output"
    if existing:
        output.write_bytes(original)
    before = set(tmp_path.iterdir())

    with pytest.raises(pa.ArrowInvalid):
        pqfilt.write_filtered(files, output, overwrite=existing)

    assert set(tmp_path.iterdir()) == before
    if existing:
        assert output.read_bytes() == original
    else:
        assert not output.exists()


@pytest.mark.parametrize("suffix", [".parquet", ".csv"])
def test_write_filtered_preserves_values_with_empty_fragments(
    mixed_files: tuple[list[Path], pa.Table], tmp_path: Path, suffix: str
) -> None:
    files, full = mixed_files
    output = tmp_path / f"filtered{suffix}"
    expected = full.take(pa.array([1, 3]))

    rows = pqfilt.write_filtered(files, output, filters="longitude > -0.1 & longitude < 0.1")

    assert rows == expected.num_rows
    if suffix == ".parquet":
        assert pq.read_table(output).equals(expected)
    else:
        pd.testing.assert_frame_equal(pd.read_csv(output), expected.to_pandas(), check_dtype=False)


def test_all_empty_mixed_schema_csv_has_one_header(
    mixed_files: tuple[list[Path], pa.Table], tmp_path: Path
) -> None:
    files, expected = mixed_files
    output = tmp_path / "empty.csv"

    rows = pqfilt.write_filtered(files, output, filters="longitude < -100")

    assert rows == 0
    with output.open(newline="") as stream:
        assert list(csv.reader(stream)) == [expected.column_names]


def test_cli_filters_mixed_schemas_without_column_selection(
    mixed_files: tuple[list[Path], pa.Table], tmp_path: Path
) -> None:
    _, full = mixed_files
    output = tmp_path / "filtered.csv"
    expected = full.take(pa.array([1, 3]))

    result = CliRunner().invoke(
        main,
        [
            str(tmp_path / "*.parq"),
            "-f",
            "(longitude < 0.1) & (longitude > -0.1) & (latitude < 0) & (latitude > -1)",
            "-o",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Filtered 2 rows" in result.output
    with output.open(newline="") as stream:
        rows = list(csv.reader(stream))
    assert rows[0] == expected.column_names
    assert len(rows) == expected.num_rows + 1
    pd.testing.assert_frame_equal(pd.read_csv(output), expected.to_pandas(), check_dtype=False)
