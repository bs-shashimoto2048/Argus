from __future__ import annotations

from decimal import Decimal

import pytest

from reading.canonicalizer import canonical_value, digit_length, to_numeric

pytestmark = pytest.mark.unit


def test_canonical_value_keeps_leading_zero_without_decimal_position():
    assert canonical_value("002560", None) == "002560"


def test_canonical_value_inserts_decimal_point_from_position():
    assert canonical_value("002560", 2) == "0025.60"


def test_canonical_value_does_not_double_apply_decimal_point():
    assert canonical_value("123.45", 2) == "123.45"


def test_canonical_value_none_for_empty_text():
    assert canonical_value("", None) is None
    assert canonical_value(None, None) is None  # type: ignore[arg-type]


def test_to_numeric_preserves_precision():
    assert to_numeric("0025.60") == Decimal("0025.60")
    assert to_numeric(None) is None
    assert to_numeric("") is None


def test_digit_length_excludes_decimal_point():
    assert digit_length("0025.60") == 6
    assert digit_length("001234") == 6
    assert digit_length("01234") == 5
    assert digit_length(None) == 0
