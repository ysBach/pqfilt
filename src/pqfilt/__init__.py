"""pqfilt -- Generic Parquet predicate-pushdown filter (CLI + API).

Usage::

    import pqfilt

    df = pqfilt.read("data.parquet", filters="vmag < 20")
    df = pqfilt.read("data/*.parquet", filters="(a < 30 & b > 50) | c == 1")
"""

from __future__ import annotations

from .core import filter_df, read, scan, to_ast, write_filtered
from ._operators import SUPPORTED_OPERATORS, validate_operator
from ._parser import (
    AndExpr,
    FilterExpr,
    NotExpr,
    OrExpr,
    map_leaves,
    parse_expression,
    to_pyarrow_expr,
)

__all__ = [
    "read",
    "scan",
    "write_filtered",
    "filter_df",
    "to_ast",
    "SUPPORTED_OPERATORS",
    "validate_operator",
    "parse_expression",
    "to_pyarrow_expr",
    "map_leaves",
    "FilterExpr",
    "AndExpr",
    "OrExpr",
    "NotExpr",
]
