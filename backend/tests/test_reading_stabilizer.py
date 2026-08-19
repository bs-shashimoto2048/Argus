"""ReadingStabilizerのSynthetic Test(Issue: Improve Meter Reading Accuracy and Temporal Stabilization #49相当)。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.inference.base import InferenceResult
from reading.models import CandidateStatus, ReadingSettings, StabilizationMode
from reading.stabilizer import ReadingStabilizer

pytestmark = pytest.mark.unit

BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _reading(value=None, confidence=0.9, error=None, offset_seconds=0):
    return InferenceResult(value=value, confidence=confidence, error=error, engine="mock", timestamp=BASE_TIME + timedelta(seconds=offset_seconds))


def _feed(stabilizer, values, confidences=None, errors=None):
    confirmed = None
    for index, value in enumerate(values):
        confidence = confidences[index] if confidences else 0.9
        error = errors[index] if errors else None
        confirmed = stabilizer.update(_reading(value, confidence, error, offset_seconds=index))
    return confirmed


def test_majority_consensus():
    stabilizer = ReadingStabilizer(ReadingSettings(window_size=5, required_matches=3))
    confirmed = _feed(stabilizer, ["100", "100", "101", "100", "100"])
    assert confirmed.validation_status == CandidateStatus.CONFIRMED
    assert confirmed.value == "100"


def test_no_consensus_stays_pending():
    stabilizer = ReadingStabilizer(ReadingSettings(window_size=5, required_matches=3))
    confirmed = _feed(stabilizer, ["100", "101", "102"])
    assert confirmed.validation_status == CandidateStatus.PENDING
    assert confirmed.value is None


def test_consecutive_mode_confirms_on_three_in_a_row():
    stabilizer = ReadingStabilizer(ReadingSettings(mode=StabilizationMode.CONSECUTIVE, window_size=5, required_matches=3))
    confirmed = _feed(stabilizer, ["100", "100", "100"])
    assert confirmed.validation_status == CandidateStatus.CONFIRMED
    assert confirmed.value == "100"


def test_consecutive_mode_breaks_on_mismatch():
    stabilizer = ReadingStabilizer(ReadingSettings(mode=StabilizationMode.CONSECUTIVE, window_size=5, required_matches=3))
    confirmed = _feed(stabilizer, ["100", "100", "101"])
    assert confirmed.validation_status == CandidateStatus.PENDING


def test_low_confidence_still_confirms_value_but_flags_status():
    # required_matches=1で単発readingを即Confirmed候補にし、confidenceのみを検証する。
    stabilizer = ReadingStabilizer(ReadingSettings(window_size=1, required_matches=1, min_confidence=0.60))
    confirmed = _feed(stabilizer, ["100"], confidences=[0.2])
    assert confirmed.validation_status == CandidateStatus.LOW_CONFIDENCE
    assert confirmed.value == "100"  # 値そのものは保持する


def test_fixed_digit_length_valid():
    stabilizer = ReadingStabilizer(ReadingSettings(window_size=1, required_matches=1, expected_digits=6))
    confirmed = _feed(stabilizer, ["001234"])
    assert confirmed.validation_status == CandidateStatus.CONFIRMED


def test_fixed_digit_length_invalid():
    stabilizer = ReadingStabilizer(ReadingSettings(window_size=1, required_matches=1, expected_digits=6))
    confirmed = _feed(stabilizer, ["01234"])
    assert confirmed.validation_status == CandidateStatus.INVALID_FORMAT
    # invalid_format時は値を確定させない(前回値なしなのでNoneのまま)
    assert confirmed.value is None


def test_leading_zero_is_preserved_in_confirmed_value():
    stabilizer = ReadingStabilizer(ReadingSettings(window_size=1, required_matches=1))
    confirmed = _feed(stabilizer, ["002560"])
    assert confirmed.value == "002560"
    assert confirmed.numeric_value == 2560


def test_decimal_position_applied_to_confirmed_value():
    stabilizer = ReadingStabilizer(ReadingSettings(window_size=1, required_matches=1, decimal_position=2))
    confirmed = _feed(stabilizer, ["002560"])
    assert confirmed.value == "0025.60"


def test_monotonic_rejects_decrease():
    stabilizer = ReadingStabilizer(ReadingSettings(window_size=1, required_matches=1, monotonic=True))
    first = _feed(stabilizer, ["100"])
    assert first.validation_status == CandidateStatus.CONFIRMED
    second = stabilizer.update(_reading("99", offset_seconds=1))
    assert second.validation_status == CandidateStatus.DECREASE_DETECTED
    # 前回のConfirmed値(100)が保持されること。
    assert second.value == "100"


def test_monotonic_disabled_allows_decrease():
    stabilizer = ReadingStabilizer(ReadingSettings(window_size=1, required_matches=1, monotonic=False))
    _feed(stabilizer, ["100"])
    second = stabilizer.update(_reading("99", offset_seconds=1))
    assert second.validation_status == CandidateStatus.CONFIRMED
    assert second.value == "99"


def test_max_rate_rejects_sudden_spike():
    stabilizer = ReadingStabilizer(ReadingSettings(window_size=1, required_matches=1, max_rate_per_minute=10))
    stabilizer.update(_reading("100", offset_seconds=0))
    # 60秒で900増加 = 900/min >> 10/min
    spike = stabilizer.update(_reading("1000", offset_seconds=60))
    assert spike.validation_status == CandidateStatus.RATE_EXCEEDED
    assert spike.value == "100"


def test_missing_reading_keeps_last_confirmed_value():
    stabilizer = ReadingStabilizer(ReadingSettings(window_size=5, required_matches=1, max_consecutive_failures=5))
    stabilizer.update(_reading("100", offset_seconds=0))
    # NO_DETECTIONが1回挟まっても、値そのものは失われない
    # (window内にまだ有効な"100"が残っているため多数決でも維持されるか、
    # あるいはcarry_forwardにより前回値が保持される — どちらの経路でも良い)。
    missing = stabilizer.update(_reading(None, error="NO_DETECTION", offset_seconds=1))
    assert missing.value == "100"
    recovered = stabilizer.update(_reading("100", offset_seconds=2))
    assert recovered.validation_status == CandidateStatus.CONFIRMED
    assert recovered.value == "100"


def test_consecutive_failure_threshold_triggers_no_reading():
    stabilizer = ReadingStabilizer(ReadingSettings(window_size=5, required_matches=1, max_consecutive_failures=3))
    stabilizer.update(_reading("100", offset_seconds=0))
    stabilizer.update(_reading(None, error="NO_DETECTION", offset_seconds=1))
    stabilizer.update(_reading(None, error="NO_DETECTION", offset_seconds=2))
    escalated = stabilizer.update(_reading(None, error="NO_DETECTION", offset_seconds=3))
    assert escalated.validation_status == CandidateStatus.NO_READING
    # 値そのものは(表示上)最後の確定値を保持したまま返す。
    assert escalated.value == "100"


def test_rollover_accepted_when_allowed():
    stabilizer = ReadingStabilizer(ReadingSettings(window_size=1, required_matches=1, monotonic=True, allow_rollover=True, rollover_max=999999, max_rate_per_minute=None))
    stabilizer.update(_reading("999999", offset_seconds=0))
    wrapped = stabilizer.update(_reading("000001", offset_seconds=1))
    assert wrapped.validation_status == CandidateStatus.CONFIRMED
    assert wrapped.value == "000001"


def test_rollover_rejected_when_not_allowed():
    stabilizer = ReadingStabilizer(ReadingSettings(window_size=1, required_matches=1, monotonic=True, allow_rollover=False))
    stabilizer.update(_reading("999999", offset_seconds=0))
    wrapped = stabilizer.update(_reading("000001", offset_seconds=1))
    assert wrapped.validation_status == CandidateStatus.DECREASE_DETECTED
    assert wrapped.value == "999999"


def test_stabilization_disabled_passes_through_raw_value():
    stabilizer = ReadingStabilizer(ReadingSettings(enabled=False))
    confirmed = stabilizer.update(_reading("123456", confidence=0.1))
    assert confirmed.validation_status == CandidateStatus.CONFIRMED
    assert confirmed.value == "123456"


def test_none_confidence_is_not_excluded_from_voting():
    # Tesseract等confidenceが取れないengineでも多数決に参加できる。
    stabilizer = ReadingStabilizer(ReadingSettings(window_size=5, required_matches=3, min_confidence=0.60))
    confirmed = _feed(stabilizer, ["100", "100", "100"], confidences=[None, None, None])
    assert confirmed.validation_status == CandidateStatus.CONFIRMED
    assert confirmed.value == "100"
