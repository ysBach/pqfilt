"""Tests for the expression parser."""

from __future__ import annotations

import pytest

import pqfilt

from pqfilt._parser import (
    AndExpr,
    FilterExpr,
    NotExpr,
    OrExpr,
    parse_expression,
    to_pyarrow_expr,
)


class TestSimpleComparisons:
    def test_greater_than(self):
        result = parse_expression("a > 5")
        assert result == FilterExpr(col="a", op=">", val=5)

    def test_less_equal_float(self):
        result = parse_expression("vmag <= 20.5")
        assert result == FilterExpr(col="vmag", op="<=", val=20.5)

    def test_equality(self):
        result = parse_expression("count == 42")
        assert result == FilterExpr(col="count", op="==", val=42)

    def test_not_equal(self):
        result = parse_expression("flag != 0")
        assert result == FilterExpr(col="flag", op="!=", val=0)

    def test_string_value(self):
        result = parse_expression("name == 'foo'")
        assert result == FilterExpr(col="name", op="==", val="foo")


class TestInNotIn:
    def test_in_numeric(self):
        result = parse_expression("desig in 1,2,3")
        assert result == FilterExpr(col="desig", op="in", val=[1, 2, 3])

    def test_not_in_strings(self):
        result = parse_expression("name not in foo,bar")
        assert result == FilterExpr(col="name", op="not in", val=["foo", "bar"])

    def test_in_parenthesized_list(self):
        result = parse_expression("desig in (1, 2, 3)")
        assert result == FilterExpr(col="desig", op="in", val=[1, 2, 3])

    def test_not_in_parenthesized_string_list(self):
        result = parse_expression("name not in ('foo', 'bar')")
        assert result == FilterExpr(col="name", op="not in", val=["foo", "bar"])

    def test_parenthesized_list_in_compound_expression(self):
        result = parse_expression("a in (1,2) & b > 3")
        assert result == AndExpr(
            children=(
                FilterExpr(col="a", op="in", val=[1, 2]),
                FilterExpr(col="b", op=">", val=3),
            )
        )


class TestAndOr:
    def test_and(self):
        result = parse_expression("a > 5 & b < 10")
        assert isinstance(result, AndExpr)
        assert len(result.children) == 2
        assert result.children[0] == FilterExpr(col="a", op=">", val=5)
        assert result.children[1] == FilterExpr(col="b", op="<", val=10)

    def test_or(self):
        result = parse_expression("a > 5 | b < 10")
        assert isinstance(result, OrExpr)
        assert len(result.children) == 2

    def test_precedence_and_binds_tighter(self):
        # a > 5 & b < 10 | c == 1  →  (a>5 AND b<10) OR (c==1)
        result = parse_expression("a > 5 & b < 10 | c == 1")
        assert isinstance(result, OrExpr)
        assert len(result.children) == 2
        assert isinstance(result.children[0], AndExpr)
        assert isinstance(result.children[1], FilterExpr)

    def test_parentheses_override(self):
        # a > 5 & (b < 10 | c == 1)  →  a>5 AND (b<10 OR c==1)
        result = parse_expression("a > 5 & (b < 10 | c == 1)")
        assert isinstance(result, AndExpr)
        assert len(result.children) == 2
        assert isinstance(result.children[0], FilterExpr)
        assert isinstance(result.children[1], OrExpr)

    def test_nested_parens(self):
        result = parse_expression("(a > 5 & b < 10) | (c == 1 & d != 2)")
        assert isinstance(result, OrExpr)
        assert len(result.children) == 2
        assert all(isinstance(c, AndExpr) for c in result.children)


class TestSpecialColumnNames:
    def test_star_in_column(self):
        result = parse_expression("alpha*360 > 100")
        assert result == FilterExpr(col="alpha*360", op=">", val=100)

    def test_space_in_column(self):
        result = parse_expression("my column <= 50")
        assert result == FilterExpr(col="my column", op="<=", val=50)

    def test_backtick_quoted(self):
        result = parse_expression("`col with spaces` > 5")
        assert result == FilterExpr(col="col with spaces", op=">", val=5)

    def test_hyphen_in_column(self):
        result = parse_expression("obs-rate != 0")
        assert result == FilterExpr(col="obs-rate", op="!=", val=0)

    @pytest.mark.parametrize(
        ("expression", "expected"),
        [
            ("spin > 3", FilterExpr(col="spin", op=">", val=3)),
            ("vmin < 5", FilterExpr(col="vmin", op="<", val=5)),
            ("margin in 1,2", FilterExpr(col="margin", op="in", val=[1, 2])),
            ("bin not in 1,2", FilterExpr(col="bin", op="not in", val=[1, 2])),
            ("`spin` in 1,3", FilterExpr(col="spin", op="in", val=[1, 3])),
        ],
    )
    def test_column_ending_in(self, expression, expected):
        assert parse_expression(expression) == expected


class TestErrors:
    def test_empty_expression(self):
        with pytest.raises(ValueError, match="Empty"):
            parse_expression("")

    def test_no_operator(self):
        with pytest.raises(ValueError, match="No recognised operator"):
            parse_expression("just_a_column_name")

    def test_unmatched_paren(self):
        with pytest.raises(ValueError):
            parse_expression("(a > 5")

    def test_missing_value(self):
        with pytest.raises(ValueError, match="Missing value"):
            parse_expression("a >")

    def test_unterminated_parenthesized_membership_list(self):
        with pytest.raises(ValueError, match="Unterminated parenthesized membership"):
            parse_expression("a in (1,2")


class TestToPyarrowExpr:
    def test_simple_filter(self):
        node = FilterExpr(col="a", op=">", val=5)
        expr = to_pyarrow_expr(node)
        assert expr is not None  # pyarrow Expression

    def test_and_expr(self):
        node = AndExpr(
            children=(
                FilterExpr(col="a", op=">", val=5),
                FilterExpr(col="b", op="<", val=10),
            )
        )
        expr = to_pyarrow_expr(node)
        assert expr is not None

    def test_or_expr(self):
        node = OrExpr(
            children=(
                FilterExpr(col="a", op=">", val=5),
                FilterExpr(col="b", op="<", val=10),
            )
        )
        expr = to_pyarrow_expr(node)
        assert expr is not None

    def test_in_expr(self):
        node = FilterExpr(col="desig", op="in", val=[1, 2, 3])
        expr = to_pyarrow_expr(node)
        assert expr is not None


class TestAstUtilities:
    def test_to_ast_accepts_all_supported_input_forms(self):
        node = FilterExpr(col="a", op=">", val=5)

        assert pqfilt.to_ast("a > 5") == node
        assert pqfilt.to_ast([("a", ">", 5)]) == node
        assert pqfilt.to_ast([[("a", ">", 5)], [("b", "<", 1)]]) == OrExpr(
            children=(node, FilterExpr(col="b", op="<", val=1))
        )
        assert pqfilt.to_ast(node) is node

    def test_map_leaves_recurses_and_allows_expansion(self):
        node = NotExpr(
            child=OrExpr(
                children=(
                    FilterExpr(col="a", op=">", val=5),
                    FilterExpr(col="b", op="<", val=1),
                )
            )
        )

        def rewrite(leaf):
            if leaf.col == "a":
                return AndExpr(
                    children=(
                        FilterExpr(col="a_scaled", op=">", val=50),
                        FilterExpr(col="a_valid", op="!=", val=0),
                    )
                )
            return FilterExpr(col=f"stored_{leaf.col}", op=leaf.op, val=leaf.val)

        assert pqfilt.map_leaves(node, rewrite) == NotExpr(
            child=OrExpr(
                children=(
                    AndExpr(
                        children=(
                            FilterExpr(col="a_scaled", op=">", val=50),
                            FilterExpr(col="a_valid", op="!=", val=0),
                        )
                    ),
                    FilterExpr(col="stored_b", op="<", val=1),
                )
            )
        )

    def test_map_leaves_rejects_invalid_callback_result(self):
        with pytest.raises(TypeError, match="must return an ExprNode"):
            pqfilt.map_leaves(FilterExpr(col="a", op=">", val=5), lambda _: "invalid")


class TestNullOperators:
    def test_is_null(self):
        result = parse_expression("x is null")
        assert result == FilterExpr(col="x", op="is null", val=None)

    def test_is_not_null(self):
        result = parse_expression("x is not null")
        assert result == FilterExpr(col="x", op="is not null", val=None)

    def test_is_null_extra_whitespace(self):
        result = parse_expression("x   is    null")
        assert result == FilterExpr(col="x", op="is null", val=None)

    def test_is_null_with_value_raises(self):
        with pytest.raises(ValueError, match="takes no value"):
            parse_expression("x is null 5")

    def test_is_null_in_compound(self):
        result = parse_expression("a > 5 & b is null")
        assert result == AndExpr(
            children=(
                FilterExpr(col="a", op=">", val=5),
                FilterExpr(col="b", op="is null", val=None),
            )
        )

    def test_is_null_pyarrow(self):
        expr = to_pyarrow_expr(parse_expression("x is null"))
        assert expr is not None
        expr = to_pyarrow_expr(parse_expression("x is not null"))
        assert expr is not None


class TestQuotedLiterals:
    """String literals must survive structural characters (&, |, (, ), ,)."""

    def test_pipe_inside_string_value(self):
        result = parse_expression("name == 'a|b'")
        assert result == FilterExpr(col="name", op="==", val="a|b")

    def test_amp_inside_string_value(self):
        result = parse_expression("name == 'a&b'")
        assert result == FilterExpr(col="name", op="==", val="a&b")

    def test_paren_inside_string_value(self):
        result = parse_expression("name == 'foo(bar)'")
        assert result == FilterExpr(col="name", op="==", val="foo(bar)")

    def test_pipe_inside_backticked_column(self):
        result = parse_expression("`a|b` > 5")
        assert result == FilterExpr(col="a|b", op=">", val=5)

    def test_comma_inside_quoted_in_list(self):
        result = parse_expression("desig in 'a,b', 'c'")
        assert result == FilterExpr(col="desig", op="in", val=["a,b", "c"])

    def test_double_quoted_value(self):
        result = parse_expression('name == "a|b"')
        assert result == FilterExpr(col="name", op="==", val="a|b")


class TestNegation:
    def test_simple_not(self):
        result = parse_expression("~(a > 5)")
        assert result == NotExpr(child=FilterExpr(col="a", op=">", val=5))

    def test_not_without_parens(self):
        result = parse_expression("~a > 5")
        assert result == NotExpr(child=FilterExpr(col="a", op=">", val=5))

    def test_not_precedence_over_and(self):
        # ~a > 5 | b < 1  →  (~(a>5)) OR (b<1)
        result = parse_expression("~a > 5 | b < 1")
        assert isinstance(result, OrExpr)
        assert isinstance(result.children[0], NotExpr)
        assert isinstance(result.children[1], FilterExpr)

    def test_not_in_and(self):
        result = parse_expression("a > 5 & ~(b in 1,2)")
        assert isinstance(result, AndExpr)
        assert isinstance(result.children[1], NotExpr)
        inner = result.children[1].child
        assert inner == FilterExpr(col="b", op="in", val=[1, 2])

    def test_double_not(self):
        result = parse_expression("~~a > 5")
        assert isinstance(result, NotExpr)
        assert isinstance(result.child, NotExpr)
        assert result.child.child == FilterExpr(col="a", op=">", val=5)

    def test_not_pyarrow(self):
        node = NotExpr(child=FilterExpr(col="a", op=">", val=5))
        expr = to_pyarrow_expr(node)
        assert expr is not None

    def test_not_or(self):
        result = parse_expression("~(a > 5 | b < 1)")
        assert isinstance(result, NotExpr)
        assert isinstance(result.child, OrExpr)
