"""pqfilt -- Generic Parquet predicate-pushdown filter (CLI + API).

Usage::

    import pqfilt

    df = pqfilt.read("data.parquet", filters="vmag < 20")
    df = pqfilt.read("data/*.parquet", filters="(a < 30 & b > 50) | c == 1")
"""

from __future__ import annotations

from .core import read
from ._parser import parse_expression, FilterExpr, AndExpr, OrExpr

__all__ = ["read", "parse_expression", "FilterExpr", "AndExpr", "OrExpr"]
