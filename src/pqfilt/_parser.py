"""Recursive-descent parser for filter expressions.

Parses expressions like ``"a > 5 & b < 10 | c == 1"`` into an AST
that can be converted to ``pyarrow.compute.Expression``.

Grammar (informal)::

    expr        := or_expr
    or_expr     := and_expr ( '|' and_expr )*
    and_expr    := not_expr ( '&' not_expr )*
    not_expr    := '~' not_expr | atom
    atom        := '(' or_expr ')' | comparison
    comparison  := column  operator  value?
    column      := backtick_quoted | greedy_match_up_to_operator
    operator    := '>=' | '<=' | '!=' | '==' | '>' | '<'
                 | 'not in' | 'in' | 'is null' | 'is not null'
    value       := number | quoted_string | comma_list (for in/not in)
                 | (none, for 'is null' / 'is not null')

Operator precedence (loose -> tight): ``|`` < ``&`` < ``~`` < atom.
Parentheses override precedence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Union

import pyarrow.dataset as ds

from ._operators import SUPPORTED_OPERATORS, to_numeric_if_possible, validate_operator

__all__ = [
    "FilterExpr",
    "AndExpr",
    "OrExpr",
    "NotExpr",
    "map_leaves",
    "parse_expression",
    "to_pyarrow_expr",
]

# Operators ordered longest-first so '>=' is matched before '>', and
# 'is not null' before 'is null'.
_OPERATOR_PATTERN = re.compile(
    r"(>=|<=|!=|==|(?<!\S)is\s+not\s+null\b|(?<!\S)is\s+null\b|"
    r"(?<!\S)not\s+in\b|(?<!\S)in\b|>|<)"
)
_MEMBERSHIP_OPERATOR_AT_END = re.compile(r"(?<!\S)(?:not\s+in|in)\s*$")

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

    children: tuple["ExprNode", ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class OrExpr:
    """Disjunction (OR) of child nodes.

    Attributes
    ----------
    children : tuple of ExprNode
        At least one child must evaluate to ``True``.
    """

    children: tuple["ExprNode", ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class NotExpr:
    """Logical negation of a child node.

    Attributes
    ----------
    child : ExprNode
        The expression to negate.
    """

    child: "ExprNode"


# Type alias for any AST node.
ExprNode = Union[FilterExpr, AndExpr, OrExpr, NotExpr]


def map_leaves(
    node: ExprNode,
    fn: Callable[[FilterExpr], ExprNode],
) -> ExprNode:
    """Return a copy of an AST with each leaf transformed by ``fn``.

    Parameters
    ----------
    node : ExprNode
        AST node to transform.
    fn : callable
        Function that accepts a :class:`FilterExpr` and returns an AST node.
        It may replace a leaf with a compound expression.

    Returns
    -------
    ExprNode
        Transformed AST. Compound nodes are reconstructed recursively.

    Raises
    ------
    TypeError
        If *fn* does not return an AST node.
    """
    if isinstance(node, FilterExpr):
        transformed = fn(node)
        if not isinstance(transformed, (FilterExpr, AndExpr, OrExpr, NotExpr)):
            raise TypeError(
                f"map_leaves callback must return an ExprNode, got {type(transformed).__name__}"
            )
        return transformed
    if isinstance(node, AndExpr):
        return AndExpr(children=tuple(map_leaves(child, fn) for child in node.children))
    if isinstance(node, OrExpr):
        return OrExpr(children=tuple(map_leaves(child, fn) for child in node.children))
    if isinstance(node, NotExpr):
        return NotExpr(child=map_leaves(node.child, fn))
    raise TypeError(f"Unknown node type: {type(node)}")


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
    quote: str | None = None  # active quote char: "'", '"', or '`'
    membership_list_depth = 0

    def flush_buf() -> None:
        text = "".join(buf).strip()
        if text:
            tokens.append(("CMP", text))
        buf.clear()

    while i < n:
        ch = expression[i]
        if quote is not None:
            # Inside a quoted span: pass through verbatim until the matching
            # closing quote. Structural chars (&, |, (, )) have no meaning
            # here -- they are part of the column name or value.
            buf.append(ch)
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in ("'", '"', "`"):
            quote = ch
            buf.append(ch)
            i += 1
            continue
        if membership_list_depth:
            buf.append(ch)
            if ch == "(":
                membership_list_depth += 1
            elif ch == ")":
                membership_list_depth -= 1
            i += 1
            continue
        if ch == "(":
            if _MEMBERSHIP_OPERATOR_AT_END.search("".join(buf)):
                membership_list_depth = 1
                buf.append(ch)
            else:
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
        elif ch == "~" and not "".join(buf).strip():
            # `~` is a prefix negation operator. Only recognised when no
            # non-whitespace CMP text has accumulated yet.
            buf.clear()
            tokens.append(("NOT", "~"))
            i += 1
        else:
            buf.append(ch)
            i += 1

    if membership_list_depth:
        raise ValueError("Unterminated parenthesized membership value list")
    flush_buf()
    return tokens


# -----------------------------------------------------------------
# Parse a single comparison blob  (col  op  value)
# -----------------------------------------------------------------


def _parse_value_list(raw: str) -> list[Any]:
    """Parse a comma-separated value list for ``in`` / ``not in``.

    If a value is explicitly wrapped in single or double quotes
    (e.g., ``'3200'``), it is strictly preserved as a string to prevent
    type errors during predicate pushdown in pyarrow. Otherwise,
    numeric coercion is attempted. Also supports stripping list enclosing
    brackets like ``[1, 2, 3]``.

    Parameters
    ----------
    raw : str
        Comma-separated values, e.g. ``"1,2,3"`` or ``"foo,'356'"``.

    Returns
    -------
    list
        Parsed values with numeric coercion or preserved strings.
    """
    raw = raw.strip()
    if (raw.startswith("(") and raw.endswith(")")) or (raw.startswith("[") and raw.endswith("]")):
        raw = raw[1:-1]

    parts = []
    for p in _split_top_level_commas(raw):
        p = p.strip()
        if not p:
            continue

        was_quoted = False
        if (p.startswith("'") and p.endswith("'")) or (p.startswith('"') and p.endswith('"')):
            p = p[1:-1]
            was_quoted = True

        if was_quoted:
            parts.append(p)
        else:
            parts.append(to_numeric_if_possible(p))
    return parts


def _split_top_level_commas(s: str) -> list[str]:
    """Split *s* on commas not inside ``'``/``"`` quoted spans."""
    out: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    for ch in s:
        if quote is not None:
            buf.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
            buf.append(ch)
            continue
        if ch == ",":
            out.append("".join(buf))
            buf.clear()
            continue
        buf.append(ch)
    out.append("".join(buf))
    return out


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
        rest = blob[m.end() :].strip()
    else:
        # Find the first operator.  The column name is everything before it.
        m_op = _OPERATOR_PATTERN.search(blob)
        if m_op is None:
            raise ValueError(
                f"No recognised operator in expression: {blob!r}. "
                f"Supported: {', '.join(repr(o) for o in SUPPORTED_OPERATORS)}"
            )
        col = blob[: m_op.start()].strip()
        rest = blob[m_op.start() :]

    # Now *rest* should start with the operator.
    m_op = _OPERATOR_PATTERN.match(rest)
    if m_op is None:
        raise ValueError(f"Expected operator after column name in: {blob!r}")

    op_raw = m_op.group(1)
    # Normalise whitespace in "not  in" -> "not in"
    op = re.sub(r"\s+", " ", op_raw).strip()
    validate_operator(op)

    val_str = rest[m_op.end() :].strip()

    # `is null` / `is not null` are unary -- no right-hand value.
    if op in ("is null", "is not null"):
        if val_str:
            raise ValueError(f"Operator {op!r} takes no value, got {val_str!r} in: {blob!r}")
        return FilterExpr(col=col, op=op, val=None)

    if not val_str:
        raise ValueError(f"Missing value after operator in: {blob!r}")

    # Strip surrounding quotes from value.  If quoted, the user explicitly
    # wants a string comparison — skip numeric coercion.
    # We DO NOT apply this top-level quote stripping to `in` / `not in` lists
    # because they handle their own item-level quote stripping.
    if op in ("in", "not in"):
        val: Any = _parse_value_list(val_str)
    else:
        was_quoted = False
        if (val_str.startswith("'") and val_str.endswith("'")) or (
            val_str.startswith('"') and val_str.endswith('"')
        ):
            val_str = val_str[1:-1]
            was_quoted = True

        if was_quoted:
            val = val_str
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
        """Parse: ``and_expr := not_expr ( '&' not_expr )*``."""
        left = self.parse_not()
        children = [left]
        while self._peek() is not None and self._peek()[0] == "AND":
            self._consume("AND")
            children.append(self.parse_not())
        if len(children) == 1:
            return children[0]
        return AndExpr(children=tuple(children))

    def parse_not(self) -> ExprNode:
        """Parse: ``not_expr := '~' not_expr | atom``.

        Right-associative; binds tighter than ``&``/``|``.
        """
        tok = self._peek()
        if tok is not None and tok[0] == "NOT":
            self._consume("NOT")
            return NotExpr(child=self.parse_not())
        return self.parse_atom()

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
        remaining = parser.tokens[parser.pos :]
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
    elif op == "is null":
        return field.is_null()
    elif op == "is not null":
        return field.is_valid()
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
    elif isinstance(node, NotExpr):
        return ~to_pyarrow_expr(node.child)
    else:
        raise TypeError(f"Unknown node type: {type(node)}")
