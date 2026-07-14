"""Tests for operator utilities."""

from __future__ import annotations

import pytest

from pqfilt._operators import (
    to_numeric_if_possible,
    validate_operator,
)


class TestValidateOperator:
    @pytest.mark.parametrize(
        "op",
        [">", ">=", "<", "<=", "==", "!=", "in", "not in", "is null", "is not null"],
    )
    def test_valid(self, op):
        validate_operator(op)  # should not raise

    def test_invalid(self):
        with pytest.raises(ValueError, match="Unsupported operator"):
            validate_operator("~=")

    def test_invalid_with_col(self):
        with pytest.raises(ValueError, match="column 'x'"):
            validate_operator("~=", col="x")


class TestToNumericIfPossible:
    def test_int(self):
        assert to_numeric_if_possible("42") == 42
        assert isinstance(to_numeric_if_possible("42"), int)

    def test_float(self):
        assert to_numeric_if_possible("3.14") == 3.14
        assert isinstance(to_numeric_if_possible("3.14"), float)

    def test_string(self):
        assert to_numeric_if_possible("foo") == "foo"
        assert isinstance(to_numeric_if_possible("foo"), str)

    def test_negative_int(self):
        assert to_numeric_if_possible("-7") == -7

    def test_negative_float(self):
        assert to_numeric_if_possible("-2.5") == -2.5

    def test_large_int_preserves_precision(self):
        value = "9007199254740993"
        assert to_numeric_if_possible(value) == 9007199254740993

    def test_true_canonical(self):
        result = to_numeric_if_possible("True")
        assert result is True
        assert isinstance(result, bool)

    def test_false_canonical(self):
        result = to_numeric_if_possible("False")
        assert result is False
        assert isinstance(result, bool)

    def test_true_lowercase(self):
        result = to_numeric_if_possible("true")
        assert result is True

    def test_false_uppercase(self):
        result = to_numeric_if_possible("FALSE")
        assert result is False
