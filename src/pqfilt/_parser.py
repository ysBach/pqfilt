"""Recursive-descent parser for filter expressions.

Parses expressions like ``"a > 5 & b < 10 | c == 1"`` into an AST
that can be converted to ``pyarrow.compute.Expression``.

Grammar (informal)::

    expr        := or_expr
    or_expr     := and_expr ( '|' and_expr )*
    and_expr    := atom ( '&' atom )*
    atom        := '(' or_expr ')' | comparison
    comparison  := column  operator  value
    column      := backtick_quoted | greedy_match_up_to_operator
    operator    := '>=' | '<=' | '!=' | '==' | '>' | '<' | 'not in' | 'in'
    value       := number | quoted_string | comma_list (for in/not in)

Operator precedence: ``&`` binds tighter than ``|``.
Parentheses override precedence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import pyarrow.dataset as ds

from ._operators import SUPPORTED_OPERATORS, to_numeric_if_possible, validate_operator

__all__ = [
    "FilterExpr",
    "AndExpr",
    "OrExpr",
    "parse_expression",
    "to_pyarrow_expr",
]

# Operators ordered longest-first so '>=' is matched before '>'.
_OPERATOR_PATTERN = re.compile(
    r"(>=|<=|!=|==|not\s+in\b|in\b|>|<)"
)

# Backtick-quoted column name.
_BACKTICK_RE = re.compile(r"^`([^`]+)`")


# -----------------------------------------------------------------
# AST nodes
# -----------------------------------------------------------------

@dataclass(frozen=True)
class FilterExpr:
    """Single comparison: ``col op val``.

    Attributes
    ----------
    col : str
        Column name.
    op : str
        Comparison operator (one of :data:`~pqfilt._operators.SUPPORTED_OPERATORS`).
    val : Any
        Comparison value (scalar or list for ``in`` / ``not in``).
    """

    col: str
    op: str
    val: Any


@dataclass(frozen=True)
class AndExpr:
    """Conjunction (AND) of child nodes.

    Attributes
    ----------
    children : tuple of ExprNode
        All children must evaluate to ``True``.
    """

    children: tuple[FilterExpr | OrExpr | AndExpr, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class OrExpr:
    """Disjunction (OR) of child nodes.

    Attributes
    ----------
    children : tuple of ExprNode
        At least one child must evaluate to ``True``.
    """

    children: tuple[FilterExpr | AndExpr | OrExpr, ...] = field(default_factory=tuple)


# Type alias for any AST node.
ExprNode = FilterExpr | AndExpr | OrExpr


# -----------------------------------------------------------------
# Tokeniser
# -----------------------------------------------------------------

def _tokenise(expression: str) -> list[tuple[str, str]]:
    """Split *expression* into structural tokens and comparison blobs.

    Parameters
    ----------
    expression : str
        Raw expression string.

    Returns
    -------
    list of (str, str)
        Each element is ``(kind, text)`` where *kind* is one of
        ``LPAREN``, ``RPAREN``, ``AND``, ``OR``, or ``CMP``.
    """
    tokens: list[tuple[str, str]] = []
    i = 0
    n = len(expression)
    buf: list[str] = []

    def flush_buf() -> None:
        text = "".join(buf).strip()
        if text:
            tokens.append(("CMP", text))
        buf.clear()

    while i < n:
        ch = expression[i]
        if ch == "(":
            flush_buf()
            tokens.append(("LPAREN", "("))
            i += 1
        elif ch == ")":
            flush_buf()
            tokens.append(("RPAREN", ")"))
            i += 1
        elif ch == "&":
            flush_buf()
            tokens.append(("AND", "&"))
            i += 1
        elif ch == "|":
            flush_buf()
            tokens.append(("OR", "|"))
            i += 1
        else:
            buf.append(ch)
            i += 1

    flush_buf()
    return tokens


# -----------------------------------------------------------------
# Parse a single comparison blob  (col  op  value)
# -----------------------------------------------------------------

def _parse_value_list(raw: str) -> list[int | float | str]:
    """Parse a comma-separated value list for ``in`` / ``not in``.

    Parameters
    ----------
    raw : str
        Comma-separated values, e.g. ``"1,2,3"`` or ``"foo,bar"``.

    Returns
    -------
    list
        Parsed values with numeric coercion applied.
    """
    parts = [p.strip().strip("'\"") for p in raw.split(",")]
    return [to_numeric_if_possible(p) for p in parts if p]


def _parse_comparison(blob: str) -> FilterExpr:
    """Parse a comparison blob like ``'alpha*360 > 100'`` into a FilterExpr.

    Column names may be backtick-quoted to resolve ambiguity with operator
    characters.

    Parameters
    ----------
    blob : str
        Raw comparison string.

    Returns
    -------
    FilterExpr

    Raises
    ------
    ValueError
        If no operator is found or the value is missing.
    """
    blob = blob.strip()
    if not blob:
        raise ValueError("Empty comparison expression")

    # Try backtick-quoted column first.
    m = _BACKTICK_RE.match(blob)
    if m:
        col = m.group(1)
        rest = blob[m.end():].strip()
    else:
        # Find the first operator.  The column name is everything before it.
        m_op = _OPERATOR_PATTERN.search(blob)
        if m_op is None:
            raise ValueError(
                f"No recognised operator in expression: {blob!r}. "
                f"Supported: {', '.join(repr(o) for o in SUPPORTED_OPERATORS)}"
            )
        col = blob[:m_op.start()].strip()
        rest = blob[m_op.start():]

    # Now *rest* should start with the operator.
    m_op = _OPERATOR_PATTERN.match(rest)
    if m_op is None:
        raise ValueError(f"Expected operator after column name in: {blob!r}")

    op_raw = m_op.group(1)
    # Normalise whitespace in "not  in" -> "not in"
    op = re.sub(r"\s+", " ", op_raw).strip()
    validate_operator(op)

    val_str = rest[m_op.end():].strip()
    if not val_str:
        raise ValueError(f"Missing value after operator in: {blob!r}")

    # Strip surrounding quotes from value.
    if (val_str.startswith("'") and val_str.endswith("'")) or (
        val_str.startswith('"') and val_str.endswith('"')
    ):
        val_str = val_str[1:-1]

    if op in ("in", "not in"):
        val: Any = _parse_value_list(val_str)
    else:
        val = to_numeric_if_possible(val_str)

    return FilterExpr(col=col, op=op, val=val)


# -----------------------------------------------------------------
# Recursive-descent parser
# -----------------------------------------------------------------

class _Parser:
    """Recursive-descent parser over the token list."""

    def __init__(self, tokens: list[tuple[str, str]]) -> None:
        self.tokens = tokens
        self.pos = 0

    def _peek(self) -> tuple[str, str] | None:
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return None

    def _consume(self, expected_kind: str | None = None) -> tuple[str, str]:
        tok = self._peek()
        if tok is None:
            raise ValueError("Unexpected end of expression")
        if expected_kind is not None and tok[0] != expected_kind:
            raise ValueError(f"Expected {expected_kind}, got {tok[0]} ({tok[1]!r})")
        self.pos += 1
        return tok

    def parse_or(self) -> ExprNode:
        """Parse: ``or_expr := and_expr ( '|' and_expr )*``."""
        left = self.parse_and()
        children = [left]
        while self._peek() is not None and self._peek()[0] == "OR":
            self._consume("OR")
            children.append(self.parse_and())
        if len(children) == 1:
            return children[0]
        return OrExpr(children=tuple(children))

    def parse_and(self) -> ExprNode:
        """Parse: ``and_expr := atom ( '&' atom )*``."""
        left = self.parse_atom()
        children = [left]
        while self._peek() is not None and self._peek()[0] == "AND":
            self._consume("AND")
            children.append(self.parse_atom())
        if len(children) == 1:
            return children[0]
        return AndExpr(children=tuple(children))

    def parse_atom(self) -> ExprNode:
        """Parse: ``atom := '(' or_expr ')' | comparison``."""
        tok = self._peek()
        if tok is None:
            raise ValueError("Unexpected end of expression")
        if tok[0] == "LPAREN":
            self._consume("LPAREN")
            node = self.parse_or()
            self._consume("RPAREN")
            return node
        if tok[0] == "CMP":
            _, blob = self._consume("CMP")
            return _parse_comparison(blob)
        raise ValueError(f"Unexpected token: {tok[0]} ({tok[1]!r})")


def parse_expression(expr: str) -> ExprNode:
    """Parse a filter expression string into an AST.

    Parameters
    ----------
    expr : str
        Expression such as ``"a > 5 & b < 10 | c == 1"``.

    Returns
    -------
    ExprNode
        A :class:`FilterExpr`, :class:`AndExpr`, or :class:`OrExpr` tree.

    Raises
    ------
    ValueError
        On parse errors (unmatched parentheses, missing operator, etc.).

    Examples
    --------
    >>> parse_expression("vmag < 20")
    FilterExpr(col='vmag', op='<', val=20)

    >>> parse_expression("a > 5 & b < 10")
    AndExpr(children=(FilterExpr(col='a', op='>', val=5), FilterExpr(col='b', op='<', val=10)))
    """
    tokens = _tokenise(expr)
    if not tokens:
        raise ValueError("Empty expression")
    parser = _Parser(tokens)
    result = parser.parse_or()
    if parser.pos < len(parser.tokens):
        remaining = parser.tokens[parser.pos:]
        raise ValueError(f"Unexpected trailing tokens: {remaining}")
    return result


# -----------------------------------------------------------------
# AST -> pyarrow.Expression
# -----------------------------------------------------------------

def _filter_to_pa(node: FilterExpr) -> ds.Expression:
    """Convert a single FilterExpr to a pyarrow Expression."""
    field = ds.field(node.col)
    op = node.op
    val = node.val

    if op == ">":
        return field > val
    elif op == ">=":
        return field >= val
    elif op == "<":
        return field < val
    elif op == "<=":
        return field <= val
    elif op == "==":
        return field == val
    elif op == "!=":
        return field != val
    elif op == "in":
        return field.isin(val)
    elif op == "not in":
        return ~field.isin(val)
    else:
        raise ValueError(f"Unsupported operator: {op!r}")


def to_pyarrow_expr(node: ExprNode) -> ds.Expression:
    """Convert a parsed AST into a ``pyarrow.compute.Expression``.

    Parameters
    ----------
    node : ExprNode
        Output of :func:`parse_expression`.

    Returns
    -------
    pyarrow.compute.Expression
        Expression suitable for ``pyarrow.dataset.Dataset.to_table(filter=...)``.
    """
    if isinstance(node, FilterExpr):
        return _filter_to_pa(node)
    elif isinstance(node, AndExpr):
        exprs = [to_pyarrow_expr(c) for c in node.children]
        result = exprs[0]
        for e in exprs[1:]:
            result = result & e
        return result
    elif isinstance(node, OrExpr):
        exprs = [to_pyarrow_expr(c) for c in node.children]
        result = exprs[0]
        for e in exprs[1:]:
            result = result | e
        return result
    else:
        raise TypeError(f"Unknown node type: {type(node)}")
