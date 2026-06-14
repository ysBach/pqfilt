"""Operator validation and application utilities."""

from __future__ import annotations

SUPPORTED_OPERATORS: tuple[str, ...] = (
    ">",
    ">=",
    "<",
    "<=",
    "==",
    "!=",
    "in",
    "not in",
    "is null",
    "is not null",
)


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


def to_numeric_if_possible(value_str: str) -> int | float | bool | str:
    """Convert *value_str* to ``bool``, ``int``, or ``float`` if possible.

    Bool recognition is attempted **before** numeric coercion so that
    ``"True"`` / ``"False"`` (case-insensitive) become Python ``bool``
    values rather than strings.  This is required to avoid type mismatches
    when filtering boolean columns via pyarrow predicate pushdown.

    Prefers ``int`` when the float value is integer-like.

    Examples
    --------
    >>> to_numeric_if_possible("True")
    True
    >>> to_numeric_if_possible("false")
    False
    >>> to_numeric_if_possible("42")
    42
    >>> to_numeric_if_possible("3.14")
    3.14
    >>> to_numeric_if_possible("foo")
    'foo'
    """
    # Bool must be checked before float because float("True") raises ValueError,
    # but we want explicit bool semantics, not accidental numeric coercion.
    if value_str.lower() == "true":
        return True
    if value_str.lower() == "false":
        return False
    try:
        numeric_val = float(value_str)
        if numeric_val.is_integer():
            return int(numeric_val)
        return numeric_val
    except ValueError:
        return value_str
