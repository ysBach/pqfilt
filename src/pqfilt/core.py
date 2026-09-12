"""Core ``read()`` function -- the main public API of pqfilt."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from glob import glob
from pathlib import Path
from stat import S_IMODE
from tempfile import TemporaryDirectory
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.dataset as ds
import pyarrow.parquet as pq

from ._operators import validate_operator
from ._parser import (
    AndExpr,
    ExprNode,
    FilterExpr,
    NotExpr,
    OrExpr,
    parse_expression,
    to_pyarrow_expr,
)

__all__ = ["read", "scan", "write_filtered", "filter_df", "to_ast"]

log = logging.getLogger(__name__)


def _tuple_to_leaf(item: Any) -> FilterExpr:
    """Validate a filter tuple and convert it to a leaf AST node.

    Parameters
    ----------
    item : Any
        Candidate ``(column, operator, value)`` tuple.

    Returns
    -------
    FilterExpr
        Validated filter leaf.

    Raises
    ------
    ValueError
        If *item* is not a 3-tuple or its operator is unsupported.
    """
    if not (isinstance(item, tuple) and len(item) == 3):
        raise ValueError(f"Each filter must be a 3-tuple (col, op, val), got {item!r}")
    col, op, val = item
    validate_operator(op, col=col)
    return FilterExpr(col=col, op=op, val=val)


def _tuples_to_ast(filters: list) -> ExprNode:
    """Convert tuple-style filters to an AST node.

    Supports two layouts:

    * **Flat AND**: ``[("a", ">", 5), ("b", "<", 10)]``
    * **DNF (OR of AND-groups)**: ``[[("a", ">", 5)], [("b", "<", 10)]]``

    Parameters
    ----------
    filters : list
        List of 3-tuples (flat AND) or list of lists of 3-tuples (DNF).

    Returns
    -------
    ExprNode
        Parsed AST node.

    Raises
    ------
    ValueError
        If ``filters`` is empty or contains invalid entries.
    """
    if not filters:
        raise ValueError("Empty filter list")

    # Detect DNF vs flat
    if isinstance(filters[0], list):
        # DNF: each sub-list is an AND-group, groups are OR-ed.
        or_children: list[ExprNode] = []
        for group in filters:
            if not isinstance(group, list):
                raise ValueError(f"Each DNF group must be a list of filter tuples, got {group!r}")
            if not group:
                raise ValueError("Each DNF group must contain at least one filter tuple")
            and_children = [_tuple_to_leaf(item) for item in group]
            if len(and_children) == 1:
                or_children.append(and_children[0])
            else:
                or_children.append(AndExpr(children=tuple(and_children)))
        if len(or_children) == 1:
            return or_children[0]
        return OrExpr(children=tuple(or_children))
    else:
        # Flat AND
        children = [_tuple_to_leaf(item) for item in filters]
        if len(children) == 1:
            return children[0]
        return AndExpr(children=tuple(children))


def to_ast(filters: str | list | ExprNode) -> ExprNode:
    """Convert a supported filter specification to an AST.

    Parameters
    ----------
    filters : str, list, or ExprNode
        Expression string, flat list of filter tuples, DNF list of filter
        tuples, or a pre-parsed AST node.

    Returns
    -------
    ExprNode
        Parsed or supplied AST node.

    Raises
    ------
    TypeError
        If *filters* is not a supported filter specification.
    ValueError
        If the supplied string or tuple filters are invalid.
    """
    if isinstance(filters, str):
        return parse_expression(filters)
    if isinstance(filters, list):
        return _tuples_to_ast(filters)
    if isinstance(filters, (FilterExpr, AndExpr, OrExpr, NotExpr)):
        return filters
    raise TypeError(f"filters must be str, list, or ExprNode, got {type(filters).__name__}")


def _resolve_files(source: str | Path | list[str | Path]) -> list[str]:
    """Resolve *source* to a list of file paths (with glob expansion).

    Parameters
    ----------
    source : str, Path, or list
        Single path, glob pattern, or list of paths and patterns. Existing
        paths are treated literally, including names containing brackets.

    Returns
    -------
    list of str
        Distinct files in first-occurrence order. Paths to the same file,
        including symbolic and hard links, appear only once.

    Raises
    ------
    FileNotFoundError
        If no files match *source*.
    """
    sources = [source] if isinstance(source, (str, Path)) else source
    files: list[str] = []
    seen: set[tuple[int, int]] = set()
    for item in sources:
        path = str(item)
        matches = [path] if Path(path).exists() else sorted(glob(path))
        if not matches:
            raise FileNotFoundError(f"No files found matching: {item}")
        for match in matches:
            file_stat = os.stat(match)
            identity = (file_stat.st_dev, file_stat.st_ino)
            if identity not in seen:
                seen.add(identity)
                files.append(match)

    if not files:
        raise FileNotFoundError(f"No files found matching: {source}")
    return files


@contextmanager
def _atomic_output(output: str | Path, overwrite: bool) -> Iterator[Path]:
    """Stage an output beside its destination and publish only on success.

    Parameters
    ----------
    output : str or pathlib.Path
        Destination path. Overwrites follow an existing symbolic link.
    overwrite : bool
        Whether an existing destination may be replaced.

    Yields
    ------
    pathlib.Path
        Temporary file path for the caller to write and close.

    Notes
    -----
    A same-filesystem rename publishes overwrites atomically. For exclusive
    creation, a hard link prevents replacing a concurrently created file.
    Temporary files are removed if writing or publication fails.
    """
    out = Path(output)
    if not overwrite and (out.exists() or out.is_symlink()):
        raise FileExistsError(f"Output file '{output}' already exists. Use overwrite=True.")
    if overwrite:
        out = out.resolve()
    with TemporaryDirectory(prefix=".pqfilt-", dir=out.parent) as directory:
        staged = Path(directory) / out.name
        yield staged
        if overwrite:
            if out.exists():
                staged.chmod(S_IMODE(out.stat().st_mode))
            os.replace(staged, out)
        else:
            os.link(staged, out)


def _dataset_schema(files: list[str], columns: set[str] | None) -> pa.Schema:
    """Combine column types from file metadata before scanning rows.

    Parameters
    ----------
    files : list of str
        Input paths in scan order, after glob expansion and deduplication.
    columns : set of str or None
        Output and filter fields, or `None` for all fields.

    Returns
    -------
    pyarrow.Schema
        All needed fields with compatible common types. Missing fields are
        nullable. Pandas metadata preserves promoted and newly nullable
        integers; scan casts still check the target's supported range.

    Raises
    ------
    pyarrow.ArrowTypeError
        If a needed field has incompatible types across files.
    pyarrow.ArrowInvalid
        If an input schema repeats a needed field name.
    """
    schemas = [pq.read_schema(file) for file in files]
    if columns is not None:
        # Let Arrow resolve nested projections, including escaped field names.
        # Literal dotted column names take precedence over nested paths.
        unresolved = columns - {field.name for schema in schemas for field in schema}
        for name in unresolved:
            for schema in schemas:
                for field in schema:
                    if field.name in columns or not pa.types.is_struct(field.type):
                        continue
                    probe = pa.Table.from_batches([], schema=pa.schema([field]))
                    try:
                        ds.dataset(probe).scanner(columns=[name])
                    except pa.ArrowInvalid:
                        continue
                    columns.add(field.name)

    fields: dict[str, list[pa.Field]] = {}
    for schema in schemas:
        seen: set[str] = set()
        for field in schema:
            if columns is None or field.name in columns:
                if field.name in seen:
                    raise pa.ArrowInvalid(f"Duplicate field name {field.name!r} in input schema")
                seen.add(field.name)
                fields.setdefault(field.name, []).append(field)

    merged_fields = []
    for versions in fields.values():
        numeric = all(
            pa.types.is_null(field.type)
            or pa.types.is_integer(field.type)
            or pa.types.is_floating(field.type)
            for field in versions
        )
        merged = pa.unify_schemas(
            [pa.schema([field]) for field in versions],
            promote_options="permissive" if numeric else "default",
        )
        merged_field = merged.field(0)
        if len(versions) < len(schemas):
            merged_field = merged_field.with_nullable(True)
        merged_fields.append(merged_field)

    metadata = schemas[0].metadata
    pandas_metadata = (
        json.loads(metadata[b"pandas"]) if metadata and b"pandas" in metadata else None
    )
    column_metadata = (
        {column["field_name"]: column for column in pandas_metadata["columns"]}
        if pandas_metadata is not None
        else {}
    )
    overrides: dict[str, pd.Series] = {}
    for field in merged_fields:
        target = field.type
        if not (pa.types.is_integer(target) or pa.types.is_floating(target)):
            continue
        versions = fields[field.name]
        column = column_metadata.get(field.name)
        if column is not None and target != versions[0].type:
            # Stored pandas dtypes must not narrow a promoted Arrow field.
            dtype = target.to_pandas_dtype().__name__
            original = pd.api.types.pandas_dtype(column["numpy_type"])
            if pa.types.is_integer(target) and isinstance(
                original, pd.api.extensions.ExtensionDtype
            ):
                prefix = "UInt" if pa.types.is_unsigned_integer(target) else "Int"
                dtype = f"{prefix}{target.bit_width}"
            overrides[field.name] = pd.Series([], dtype=dtype)
        if pa.types.is_integer(target) and target.bit_width == 64:
            inserted_nulls = len(versions) < len(schemas) or any(
                pa.types.is_null(version.type) for version in versions
            )
            if inserted_nulls:
                # float64 cannot preserve all 64-bit integers after null insertion.
                nullable_dtype = (
                    pd.UInt64Dtype() if pa.types.is_unsigned_integer(target) else pd.Int64Dtype()
                )
                overrides[field.name] = pd.Series([], dtype=nullable_dtype)

    if overrides:
        # Generate standard pandas metadata through Arrow instead of guessing it.
        generated = pa.Table.from_pandas(pd.DataFrame(overrides), preserve_index=False).schema
        generated_metadata = json.loads(generated.metadata[b"pandas"])
        if pandas_metadata is None:
            pandas_metadata = generated_metadata
        else:
            for column in generated_metadata["columns"]:
                original = column_metadata.get(column["field_name"])
                if original is None:
                    pandas_metadata["columns"].append(column)
                else:
                    for key in ("pandas_type", "numpy_type", "metadata"):
                        original[key] = column[key]
        metadata = {**(metadata or {}), b"pandas": json.dumps(pandas_metadata).encode()}

    return pa.schema(merged_fields, metadata=metadata)


def scan(
    source: str | Path | list[str | Path],
    *,
    filters: str | list | ExprNode | None = None,
    columns: list[str] | None = None,
) -> ds.Scanner:
    """Create a scanner that filters rows and selects output columns.

    Parameters
    ----------
    source : str, Path, or list
        File path, glob pattern, or list of paths and patterns.
    filters : str, list, ExprNode, or None
        Filter specification accepted by :func:`to_ast`.
    columns : list of str, optional
        Columns to return. `None` includes every column found across the files.

    Returns
    -------
    pyarrow.dataset.Scanner
        Scanner ready to read the filtered result as a table or record batches.

    Notes
    -----
    Files may have different columns or compatible column types. Missing
    fields become nulls. Integer and floating-point types follow Arrow's
    numeric promotion rules; unsafe integer casts raise during scanning.

    File metadata is read before scanning. Rows are still filtered and streamed
    in batches. See :ref:`multi-file-schemas` for examples and type limits.
    """
    pa_filter: Any | None = None
    needed = None if columns is None else set(columns)
    if filters is not None:
        ast = to_ast(filters)
        pa_filter = to_pyarrow_expr(ast)
        if needed is not None:
            pending = [ast]
            while pending:
                node = pending.pop()
                if isinstance(node, FilterExpr):
                    needed.add(node.col)
                elif isinstance(node, NotExpr):
                    pending.append(node.child)
                else:
                    pending.extend(node.children)

    files = _resolve_files(source)
    schema = _dataset_schema(files, needed) if len(files) > 1 else None
    return ds.dataset(files, format="parquet", schema=schema).scanner(
        columns=columns,
        filter=pa_filter,
    )


def write_filtered(
    source: str | Path | list[str | Path],
    output: str | Path,
    *,
    filters: str | list | ExprNode | None = None,
    columns: list[str] | None = None,
    overwrite: bool = False,
) -> int:
    """Filter Parquet file(s) and write the result batch by batch.

    Unlike :func:`read`, this function does not materialize the complete
    filtered result in memory. It writes Parquet by default and writes CSV
    when *output* has a ``.csv`` suffix. Output is staged beside the destination
    and published only after writing succeeds, preserving it on failure.

    Parameters
    ----------
    source : str, Path, or list
        File path, glob pattern, or list of paths and patterns.
    output : str or Path
        Destination path for the filtered result.
    filters : str, list, ExprNode, or None, optional
        Filter specification accepted by :func:`to_ast`.
    columns : list of str, optional
        Columns to write. ``None`` writes all columns.
    overwrite : bool, optional
        Whether an existing output file may be replaced.

    Returns
    -------
    int
        Number of rows written.

    Raises
    ------
    FileExistsError
        If *output* exists and *overwrite* is ``False``.
    ValueError
        If *output* is one of the input files.
    """
    files = _resolve_files(source)
    out = Path(output)
    if out.exists():
        if not overwrite:
            raise FileExistsError(f"Output file '{output}' already exists. Use overwrite=True.")
        output_stat = out.stat()
        if any(os.path.samestat(output_stat, Path(file).stat()) for file in files):
            raise ValueError("Output path must not be an input file for streaming writes.")

    with _atomic_output(out, overwrite) as staged:
        scanner = scan(files, filters=filters, columns=columns)
        rows_written = 0
        writer: pq.ParquetWriter | pacsv.CSVWriter
        if out.suffix.lower() == ".csv":
            writer = pacsv.CSVWriter(str(staged), scanner.projected_schema)
        else:
            writer = pq.ParquetWriter(staged, scanner.projected_schema)

        with writer:
            for batch in scanner.to_batches():
                writer.write_batch(batch)
                rows_written += batch.num_rows
    return rows_written


def _write_table(
    table: pa.Table,
    output: str | Path,
    overwrite: bool,
    *,
    dataframe: pd.DataFrame | None = None,
) -> Path:
    """Write an Arrow table while avoiding an unnecessary pandas conversion.

    Parameters
    ----------
    table : pyarrow.Table
        Table to write.
    output : str or Path
        Destination path. A ``.csv`` suffix selects CSV output; all other
        suffixes select Parquet output.
    overwrite : bool
        Whether an existing output file may be replaced.
    dataframe : pandas.DataFrame, optional
        Already-converted representation to use for CSV output.

    Returns
    -------
    pathlib.Path
        Written destination path.

    Raises
    ------
    FileExistsError
        If *output* exists and *overwrite* is ``False``.
    """
    out = Path(output)
    with _atomic_output(out, overwrite) as staged:
        if out.suffix.lower() == ".csv":
            (dataframe if dataframe is not None else table.to_pandas()).to_csv(staged, index=False)
        else:
            pq.write_table(table, staged)
    return out


def read(
    source: str | Path | list[str | Path],
    *,
    filters: str | list | ExprNode | None = None,
    columns: list[str] | None = None,
    output: str | Path | None = None,
    overwrite: bool = False,
) -> pd.DataFrame:
    """Read Parquet file(s) with predicate-pushdown filtering.

    Wraps ``pyarrow.dataset`` to apply row-group-level predicate pushdown,
    avoiding unnecessary I/O and memory usage.

    Parameters
    ----------
    source : str, Path, or list
        File path, glob pattern (e.g., ``"data/*.parquet"``), or list of
        paths and patterns.
    filters : str, list, ExprNode, or None, optional
        Filter specification.  Accepts several formats:

        **Expression string** -- parsed via the built-in mini-language::

            "vmag < 20"
            "(a < 30 & b > 50) | c == 1"
            "desig in 1,2,3"
            "~(a > 5)"
            "v is null"

        **List of 3-tuples** (flat AND)::

            [("a", ">", 5), ("b", "<", 10)]

        **List of lists** (DNF -- OR of AND-groups)::

            [[("a", ">", 5)], [("b", "<", 10)]]

        **Pre-parsed AST node** (``FilterExpr``, ``AndExpr``, ``OrExpr``,
        ``NotExpr``).

    columns : list of str, optional
        Columns to load. `None` includes every column found across the files.
    output : str or Path, optional
        Save the result to this path (``.parquet`` or ``.csv``).
    overwrite : bool, optional
        Allow overwriting *output* if it already exists.

    Returns
    -------
    pandas.DataFrame
        Filtered (and optionally column-selected) DataFrame.

    Notes
    -----
    If combining files adds nulls to a 64-bit integer column, the result uses
    pandas `Int64` or `UInt64` to preserve large integers exactly. See
    :ref:`multi-file-schemas` for the common-type rules and limits.

    Raises
    ------
    FileNotFoundError
        No files matched *source*.
    FileExistsError
        *output* exists and *overwrite* is ``False``.
    ValueError
        Invalid filter syntax.
    TypeError
        *filters* is not a supported type.

    Examples
    --------
    Simple filter::

        df = pqfilt.read("data.parquet", filters="vmag < 20")

    AND + OR expression::

        df = pqfilt.read("data.parquet", filters="(a < 30 & b > 50) | c == 1")

    Negation::

        df = pqfilt.read("data.parquet", filters="~(a > 5)")

    Null check::

        df = pqfilt.read("data.parquet", filters="v is null")

    Tuple syntax::

        df = pqfilt.read("data.parquet", filters=[("a", ">", 5), ("b", "<", 10)])
    """
    out_table = scan(source, filters=filters, columns=columns).to_table()
    result = out_table.to_pandas()

    # -- save --
    if output is not None:
        out = _write_table(out_table, output, overwrite, dataframe=result)
        log.info("Saved %d rows to %s", len(result), out)

    return result


def filter_df(
    df: pd.DataFrame,
    filters: str | list | ExprNode,
) -> pd.DataFrame:
    """Filter an already-loaded pandas DataFrame using the pqfilt expression syntax.

    Applies the same filter language as :func:`read` — expression strings,
    tuple lists, DNF, and pre-parsed AST nodes — directly to a DataFrame.

    Parameters
    ----------
    df : pandas.DataFrame
        Input data.
    filters : str, list, or ExprNode
        Filter specification (same formats accepted by :func:`read`).

    Returns
    -------
    pandas.DataFrame
        Filtered rows with reset index.

    Notes
    -----
    Comparisons on missing values use PyArrow's three-valued semantics:
    an unknown comparison result is excluded from the returned rows. Membership
    filters follow PyArrow's ``isin`` behavior, where a missing value matches
    a membership list containing a missing value.

    Raises
    ------
    KeyError
        A column named in the filter does not exist in *df*.
    TypeError
        *filters* is not a supported type.
    ValueError
        Invalid filter syntax.

    Examples
    --------
    ::

        import pandas as pd
        import pqfilt

        df = pd.DataFrame({"a": range(10), "b": range(0, 100, 10)})

        pqfilt.filter_df(df, "a > 5")
        pqfilt.filter_df(df, "a > 3 & b < 80")
        pqfilt.filter_df(df, "~(a in 1,2,3)")
        pqfilt.filter_df(df, [("a", ">", 5), ("b", "<", 90)])
    """
    mask = _eval_node(df, to_ast(filters))
    return df[mask.fillna(False)].reset_index(drop=True)


def _eval_node(df: pd.DataFrame, node: ExprNode) -> pd.Series:
    """Recursively evaluate an AST node to a nullable boolean mask over *df*."""
    if isinstance(node, FilterExpr):
        if node.col not in df.columns:
            raise KeyError(
                f"Column {node.col!r} not found in DataFrame. Available columns: {list(df.columns)}"
            )
        col = df[node.col]
        op, val = node.op, node.val
        if val is None and op in (">", ">=", "<", "<=", "==", "!="):
            return pd.Series(pd.NA, index=df.index, dtype="boolean")
        if op == ">":
            return _comparison_mask(col, col > val)
        elif op == ">=":
            return _comparison_mask(col, col >= val)
        elif op == "<":
            return _comparison_mask(col, col < val)
        elif op == "<=":
            return _comparison_mask(col, col <= val)
        elif op == "==":
            return _comparison_mask(col, col == val)
        elif op == "!=":
            return _comparison_mask(col, col != val)
        elif op == "in":
            return _membership_mask(col, val)
        elif op == "not in":
            return ~_membership_mask(col, val)
        elif op == "is null":
            return col.isna().astype("boolean")
        elif op == "is not null":
            return col.notna().astype("boolean")
        else:
            raise ValueError(f"Unsupported operator: {op!r}")
    elif isinstance(node, AndExpr):
        mask = _eval_node(df, node.children[0])
        for child in node.children[1:]:
            mask = mask & _eval_node(df, child)
        return mask
    elif isinstance(node, OrExpr):
        mask = _eval_node(df, node.children[0])
        for child in node.children[1:]:
            mask = mask | _eval_node(df, child)
        return mask
    elif isinstance(node, NotExpr):
        return ~_eval_node(df, node.child)
    else:
        raise TypeError(f"Unknown node type: {type(node)}")


def _comparison_mask(column: pd.Series, mask: pd.Series) -> pd.Series:
    """Represent comparisons with missing inputs as unknown.

    Parameters
    ----------
    column : pandas.Series
        Compared column.
    mask : pandas.Series
        Boolean comparison result.

    Returns
    -------
    pandas.Series
        Nullable boolean mask, with missing column values represented by
        ``pd.NA``.
    """
    return mask.astype("boolean").mask(column.isna(), pd.NA)


def _membership_mask(column: pd.Series, values: Any) -> pd.Series:
    """Evaluate membership with PyArrow's missing-value behavior.

    Parameters
    ----------
    column : pandas.Series
        Column to test.
    values : Any
        Membership values accepted by :meth:`pandas.Series.isin`.

    Returns
    -------
    pandas.Series
        Nullable boolean mask. Missing column values match when *values*
        contains a missing value.
    """
    mask = column.isin(values).astype("boolean")
    contains_missing = any(pd.isna(value) for value in values)
    return mask.mask(column.isna(), contains_missing)
