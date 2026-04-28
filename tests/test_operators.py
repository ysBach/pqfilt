"""Tests for operator utilities."""

from __future__ import annotations

import pandas as pd
import pyarrow.dataset as ds
import pytest

from pqfilt._operators import (
    apply_filter_operator,
    to_numeric_if_possible,
    validate_operator,
)


class TestValidateOperator:
    @pytest.mark.parametrize("op", [">", ">=", "<", "<=", "==", "!=", "in", "not in"])
    def test_valid(self, op):
        validate_operator(op)  # should not raise

    def test_invalid(self):
        with pytest.raises(ValueError, match="Unsupported operator"):
            validate_operator("~=")

    def test_invalid_with_col(self):
        with pytest.raises(ValueError, match="column 'x'"):
            validate_operator("~=", col="x")


class TestApplyFilterOperator:
    def test_gt_pandas(self):
        s = pd.Series([1, 2, 3, 4, 5])
        result = apply_filter_operator(">", s, 3)
        assert list(result) == [False, False, False, True, True]

    def test_eq_pandas(self):
        s = pd.Series([1, 2, 3])
        result = apply_filter_operator("==", s, 2)
        assert list(result) == [False, True, False]

    def test_in_pandas(self):
        s = pd.Series([1, 2, 3, 4])
        result = apply_filter_operator("in", s, [2, 4])
        assert list(result) == [False, True, False, True]

    def test_not_in_pandas(self):
        s = pd.Series([1, 2, 3, 4])
        result = apply_filter_operator("not in", s, [2, 4])
        assert list(result) == [True, False, True, False]

    def test_gt_pyarrow(self):
        field = ds.field("a")
        expr = apply_filter_operator(">", field, 5)
        assert expr is not None  # pyarrow Expression

    def test_in_without_isin_raises(self):
        with pytest.raises(TypeError, match="isin"):
            apply_filter_operator("in", 42, [1, 2])


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
