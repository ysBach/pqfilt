"""Operator validation and application utilities."""

from __future__ import annotations

from typing import Any

SUPPORTED_OPERATORS: tuple[str, ...] = (">", ">=", "<", "<=", "==", "!=", "in", "not in")


def validate_operator(op: str, col: str | None = None) -> None:
    """Validate that *op* is a supported filter operator.

    Parameters
    ----------
    op : str
        Operator string.
    col : str, optional
        Column name for error-message context.

    Raises
    ------
    ValueError
        If *op* is not in ``SUPPORTED_OPERATORS``.
    """
    if op not in SUPPORTED_OPERATORS:
        ctx = f" for column '{col}'" if col else ""
        raise ValueError(
            f"Unsupported operator '{op}'{ctx}. "
            f"Supported: {', '.join(repr(o) for o in SUPPORTED_OPERATORS)}"
        )


def apply_filter_operator(op: str, left: Any, right: Any) -> Any:
    """Apply *op* to *left* and *right* operands.

    Works with both ``pyarrow.compute.Expression`` (via ``ds.field``) and
    ``pandas.Series`` / NumPy arrays.

    Parameters
    ----------
    op : str
        One of ``SUPPORTED_OPERATORS``.
    left : pyarrow.Expression, pandas.Series, or array-like
        Left operand.
    right : scalar or array-like
        Right operand.

    Returns
    -------
    result
        Boolean expression or mask.

    Raises
    ------
    ValueError
        If *op* is unsupported.
    TypeError
        If ``in`` / ``not in`` is used with an operand lacking ``isin()``.
    """
    if op == ">":
        return left > right
    elif op == ">=":
        return left >= right
    elif op == "<":
        return left < right
    elif op == "<=":
        return left <= right
    elif op == "==":
        return left == right
    elif op == "!=":
        return left != right
    elif op == "in":
        if hasattr(left, "isin"):
            return left.isin(right)
        raise TypeError(f"'in' operator requires isin() method, got {type(left)}")
    elif op == "not in":
        if hasattr(left, "isin"):
            return ~left.isin(right)
        raise TypeError(f"'not in' operator requires isin() method, got {type(left)}")
    else:
        validate_operator(op)


def to_numeric_if_possible(value_str: str) -> int | float | str:
    """Convert *value_str* to ``int`` or ``float`` if possible.

    Prefers ``int`` when the float value is integer-like.

    Examples
    --------
    >>> to_numeric_if_possible("42")
    42
    >>> to_numeric_if_possible("3.14")
    3.14
    >>> to_numeric_if_possible("foo")
    'foo'
    """
    try:
        numeric_val = float(value_str)
        if numeric_val.is_integer():
            return int(numeric_val)
        return numeric_val
    except ValueError:
        return value_str
