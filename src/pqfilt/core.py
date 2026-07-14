"""Core ``read()`` function -- the main public API of pqfilt."""

from __future__ import annotations

import logging
from glob import glob
from pathlib import Path
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
            and_children = [FilterExpr(col=c, op=o, val=v) for c, o, v in group]
            if len(and_children) == 1:
                or_children.append(and_children[0])
            else:
                or_children.append(AndExpr(children=tuple(and_children)))
        if len(or_children) == 1:
            return or_children[0]
        return OrExpr(children=tuple(or_children))
    else:
        # Flat AND
        children = []
        for item in filters:
            if not (isinstance(item, tuple) and len(item) == 3):
                raise ValueError(f"Each filter must be a 3-tuple (col, op, val), got {item!r}")
            c, o, v = item
            validate_operator(o, col=c)
            children.append(FilterExpr(col=c, op=o, val=v))
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
        Single path, glob pattern, or list of paths.

    Returns
    -------
    list of str
        Resolved file paths.

    Raises
    ------
    FileNotFoundError
        If no files match *source*.
    """
    if isinstance(source, (str, Path)):
        s = str(source)
        if any(c in s for c in ["*", "?", "[", "]"]):
            files = sorted(glob(s))
        else:
            files = [s]
    else:
        files = [str(f) for f in source]

    if not files:
        raise FileNotFoundError(f"No files found matching: {source}")
    return files


def scan(
    source: str | Path | list[str | Path],
    *,
    filters: str | list | ExprNode | None = None,
    columns: list[str] | None = None,
) -> ds.Scanner:
    """Create an Arrow scanner with the pqfilt filter and projection policy.

    Parameters
    ----------
    source : str, Path, or list
        File path, glob pattern, or explicit list of paths.
    filters : str, list, ExprNode, or None
        Filter specification accepted by :func:`to_ast`.
    columns : list of str, optional
        Columns to project from the input dataset.

    Returns
    -------
    pyarrow.dataset.Scanner
        Lazily evaluated scanner configured with the requested filter and
        projection.
    """
    pa_filter: Any | None = None
    if filters is not None:
        pa_filter = to_pyarrow_expr(to_ast(filters))
    return ds.dataset(_resolve_files(source), format="parquet").scanner(
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
    when *output* has a ``.csv`` suffix.

    Parameters
    ----------
    source : str, Path, or list
        File path, glob pattern, or explicit list of paths.
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
    if out.exists() and not overwrite:
        raise FileExistsError(f"Output file '{output}' already exists. Use overwrite=True.")
    if out.resolve() in {Path(file).resolve() for file in files}:
        raise ValueError("Output path must not be an input file for streaming writes.")

    scanner = scan(files, filters=filters, columns=columns)
    rows_written = 0
    writer: pq.ParquetWriter | pacsv.CSVWriter
    if out.suffix.lower() == ".csv":
        writer = pacsv.CSVWriter(str(out), scanner.projected_schema)
    else:
        writer = pq.ParquetWriter(out, scanner.projected_schema)

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
    if out.exists() and not overwrite:
        raise FileExistsError(f"Output file '{output}' already exists. Use overwrite=True.")
    if out.suffix.lower() == ".csv":
        (dataframe if dataframe is not None else table.to_pandas()).to_csv(out, index=False)
    else:
        pq.write_table(table, out)
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
        File path, glob pattern (e.g., ``"data/*.parquet"``), or explicit
        list of paths.
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
        Columns to load (projection pushdown).  ``None`` loads all columns.
    output : str or Path, optional
        Save the result to this path (``.parquet`` or ``.csv``).
    overwrite : bool, optional
        Allow overwriting *output* if it already exists.

    Returns
    -------
    pandas.DataFrame
        Filtered (and optionally column-selected) DataFrame.

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
