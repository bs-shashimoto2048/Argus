from __future__ import annotations

from decimal import Decimal

import pytest

from reading.validator import validate_format, validate_monotonic, validate_rate

pytestmark = pytest.mark.unit


def test_validate_format_no_expected_digits_always_valid():
    assert validate_format("12345", None) is True


def test_validate_format_matches_expected_digits():
    assert validate_format("001234", 6) is True
    assert validate_format("01234", 6) is False


def test_validate_monotonic_allows_increase():
    assert validate_monotonic(Decimal("125.30"), Decimal("124.90"), allow_rollover=False) is True


def test_validate_monotonic_rejects_decrease_without_rollover():
    assert validate_monotonic(Decimal("124.90"), Decimal("125.30"), allow_rollover=False) is False


def test_validate_monotonic_allows_decrease_when_rollover_permitted():
    assert validate_monotonic(Decimal("1"), Decimal("999999"), allow_rollover=True) is True


def test_validate_monotonic_no_previous_is_always_valid():
    assert validate_monotonic(Decimal("10"), None, allow_rollover=False) is True


def test_validate_rate_no_limit_configured():
    assert validate_rate(Decimal("1000"), Decimal("0"), elapsed_seconds=1, max_rate_per_minute=None, allow_rollover=False, rollover_max=None) is True


def test_validate_rate_within_limit():
    # 10 unit/min limit, 5 unit increase over 60s -> ok
    assert validate_rate(Decimal("15"), Decimal("10"), elapsed_seconds=60, max_rate_per_minute=10, allow_rollover=False, rollover_max=None) is True


def test_validate_rate_exceeds_limit():
    # 10 unit/min limit, 50 unit increase over 60s -> reject
    assert validate_rate(Decimal("60"), Decimal("10"), elapsed_seconds=60, max_rate_per_minute=10, allow_rollover=False, rollover_max=None) is False


def test_validate_rate_rollover_without_max_is_rejected():
    assert validate_rate(Decimal("1"), Decimal("999999"), elapsed_seconds=60, max_rate_per_minute=10, allow_rollover=True, rollover_max=None) is False


def test_validate_rate_rollover_computes_wrapped_delta():
    # rollover_max=999999: 999998 -> 000002 は 999999+1-999998+2 = 4 unit分の進み
    assert validate_rate(Decimal("2"), Decimal("999998"), elapsed_seconds=60, max_rate_per_minute=10, allow_rollover=True, rollover_max=999999) is True
    # 大きすぎるwrap distanceはrate超過として拒否
    assert validate_rate(Decimal("500000"), Decimal("999998"), elapsed_seconds=60, max_rate_per_minute=10, allow_rollover=True, rollover_max=999999) is False


def test_validate_rate_ignored_without_elapsed_time():
    assert validate_rate(Decimal("1000"), Decimal("0"), elapsed_seconds=None, max_rate_per_minute=10, allow_rollover=False, rollover_max=None) is True
