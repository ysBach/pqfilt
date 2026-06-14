"""Core ``read()`` function -- the main public API of pqfilt."""

from __future__ import annotations

import logging
from glob import glob
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq

from ._operators import apply_filter_operator, validate_operator
from ._parser import (
    AndExpr,
    ExprNode,
    FilterExpr,
    OrExpr,
    parse_expression,
    to_pyarrow_expr,
)

__all__ = ["read"]

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
                raise ValueError(
                    f"Each filter must be a 3-tuple (col, op, val), got {item!r}"
                )
            c, o, v = item
            validate_operator(o, col=c)
            children.append(FilterExpr(col=c, op=o, val=v))
        if len(children) == 1:
            return children[0]
        return AndExpr(children=tuple(children))


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


def read(
    source: str | Path | list[str | Path],
    *,
    filters: str | list | ExprNode | None = None,
    columns: list[str] | None = None,
    per_file: bool = True,
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

        **List of 3-tuples** (flat AND)::

            [("a", ">", 5), ("b", "<", 10)]

        **List of lists** (DNF -- OR of AND-groups)::

            [[("a", ">", 5)], [("b", "<", 10)]]

        **Pre-parsed AST node** (``FilterExpr``, ``AndExpr``, ``OrExpr``).

    columns : list of str, optional
        Columns to load (projection pushdown).  ``None`` loads all columns.
    per_file : bool, optional
        If ``True`` (default), apply the filter to each file independently
        and concatenate.  Better memory efficiency for many large files.
        If ``False``, concatenate first, then apply pandas-level filtering
        (useful when the filter cannot be pushed down).
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

    Tuple syntax::

        df = pqfilt.read("data.parquet", filters=[("a", ">", 5), ("b", "<", 10)])
    """
    files = _resolve_files(source)

    # -- normalise filters to a pyarrow Expression (or None) --
    pa_filter: Any | None = None
    ast: ExprNode | None = None

    if filters is not None:
        if isinstance(filters, str):
            ast = parse_expression(filters)
        elif isinstance(filters, list):
            ast = _tuples_to_ast(filters)
        elif isinstance(filters, (FilterExpr, AndExpr, OrExpr)):
            ast = filters
        else:
            raise TypeError(
                f"filters must be str, list, or ExprNode, got {type(filters).__name__}"
            )
        pa_filter = to_pyarrow_expr(ast)

    # -- read --
    # pyarrow.dataset handles multi-file scans natively (parallel I/O via its
    # C++ thread pool), so we build one dataset over all files instead of
    # looping per-file at the Python level.
    dataset = ds.dataset(files, format="parquet")
    out_table: pa.Table | None = None
    if per_file:
        out_table = dataset.to_table(columns=columns, filter=pa_filter)
        result = out_table.to_pandas()
    else:
        # Load everything first, then filter with pandas.
        table = dataset.to_table(columns=columns)
        result = table.to_pandas()
        if ast is not None:
            result = _apply_pandas_filter(result, ast)

    # -- save --
    if output is not None:
        out = Path(output)
        if out.exists() and not overwrite:
            raise FileExistsError(
                f"Output file '{output}' already exists. Use overwrite=True."
            )
        if out.suffix.lower() == ".csv":
            result.to_csv(out, index=False)
        elif out_table is not None:
            # Direct Arrow -> parquet preserves type fidelity (timestamp tz,
            # decimal, large_string, etc.) that a pandas round-trip would drop.
            pq.write_table(out_table, out)
        else:
            result.to_parquet(out, index=False)
        log.info("Saved %d rows to %s", len(result), out)

    return result


# -----------------------------------------------------------------
# Pandas-level filtering (for per_file=False path)
# -----------------------------------------------------------------

def _apply_pandas_filter(df: pd.DataFrame, node: ExprNode) -> pd.DataFrame:
    """Apply a parsed filter AST to a pandas DataFrame.

    Parameters
    ----------
    df : pandas.DataFrame
        Input data.
    node : ExprNode
        Parsed filter AST.

    Returns
    -------
    pandas.DataFrame
        Filtered rows with reset index.
    """
    mask = _eval_node(df, node)
    return df[mask].reset_index(drop=True)


def _eval_node(df: pd.DataFrame, node: ExprNode) -> pd.Series:
    """Recursively evaluate an AST node to a boolean Series."""
    if isinstance(node, FilterExpr):
        if node.col not in df.columns:
            raise KeyError(
                f"Column {node.col!r} not found in DataFrame. "
                f"Available columns: {list(df.columns)}"
            )
        return apply_filter_operator(node.op, df[node.col], node.val)
    elif isinstance(node, AndExpr):
        mask = pd.Series(True, index=df.index)
        for child in node.children:
            mask = mask & _eval_node(df, child)
        return mask
    elif isinstance(node, OrExpr):
        mask = pd.Series(False, index=df.index)
        for child in node.children:
            mask = mask | _eval_node(df, child)
        return mask
    else:
        raise TypeError(f"Unknown node type: {type(node)}")
