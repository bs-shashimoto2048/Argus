"""ReadingStabilizerのbaseline(注入/reset/rebase/conflict/epoch)のテスト(Issue #40)。"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.inference.base import InferenceResult
from reading.baseline import CONFLICT_ALERT_SECONDS, conflict_active, conflict_alert, parse_operator_value, rebase_tolerance
from reading.models import Baseline, CandidateStatus, ReadingSettings
from reading.stabilizer import ReadingStabilizer

pytestmark = pytest.mark.unit

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _raw(value, seconds):
    return InferenceResult(value=value, confidence=0.9, engine="mock", timestamp=T0 + timedelta(seconds=seconds))


def _settings(**kw):
    base = dict(window_size=3, required_matches=2, expected_digits=7, decimal_position=0)
    base.update(kw)
    return ReadingSettings(**base)


def _baseline(value="265759", epoch=0):
    return Baseline(value=value, numeric_value=Decimal(value), confirmed_at=T0 - timedelta(hours=1), epoch=epoch)


def _feed(stabilizer, value, start, count):
    last = None
    for i in range(count):
        last = stabilizer.update(_raw(value, start + i))
    return last


# --- baselineの注入(復元) ---

def test_injected_baseline_rejects_decrease_and_keeps_value():
    stabilizer = ReadingStabilizer(_settings(), baseline=_baseline("265759"))
    result = _feed(stabilizer, "0265754", 0, 3)
    assert result.validation_status == CandidateStatus.DECREASE_DETECTED
    assert result.value == "265759"  # 表示値は基準値のまま、Rawは棄却される
    assert result.raw_value == "0265754"
    assert result.persist_baseline is False


def test_without_baseline_first_confirmed_becomes_baseline():
    stabilizer = ReadingStabilizer(_settings())
    result = _feed(stabilizer, "0265754", 0, 3)
    assert result.validation_status == CandidateStatus.CONFIRMED
    assert result.persist_baseline is True
    assert stabilizer.baseline_snapshot()["value"] == "265754"


def test_low_confidence_is_not_marked_for_persistence():
    stabilizer = ReadingStabilizer(_settings(min_confidence=0.95))
    result = _feed(stabilizer, "0265754", 0, 3)
    assert result.validation_status == CandidateStatus.LOW_CONFIDENCE
    assert result.persist_baseline is False


def test_result_carries_fingerprint_and_epoch():
    stabilizer = ReadingStabilizer(_settings(decimal_position=1, expected_digits=7), epoch=4)
    result = _feed(stabilizer, "3723985", 0, 3)
    assert (result.baseline_epoch, result.decimal_position, result.expected_digits) == (4, 1, 7)


# --- reset / rebase ---

def test_reset_makes_next_confirmed_the_new_baseline():
    stabilizer = ReadingStabilizer(_settings(), baseline=_baseline("265759"))
    assert _feed(stabilizer, "0265754", 0, 3).validation_status == CandidateStatus.DECREASE_DETECTED
    stabilizer.reset(epoch=1)
    assert stabilizer.baseline_snapshot() is None
    result = _feed(stabilizer, "0265754", 10, 1)
    assert result.validation_status == CandidateStatus.CONFIRMED
    assert result.value == "265754"
    assert result.baseline_epoch == 1
    assert stabilizer.baseline_snapshot()["value"] == "265754"


def test_rebase_resolves_a_stuck_baseline_immediately():
    stabilizer = ReadingStabilizer(_settings(), baseline=_baseline("265759"))
    stuck = _feed(stabilizer, "0265754", 0, 3)
    assert stuck.validation_status == CandidateStatus.DECREASE_DETECTED
    stabilizer.rebase("265754", Decimal("265754"), T0 + timedelta(seconds=5), epoch=2)
    assert stabilizer.conflict is None
    result = stabilizer.update(_raw("0265754", 6))
    assert result.validation_status == CandidateStatus.CONFIRMED
    assert result.value == "265754"
    assert result.baseline_epoch == 2
    # rebase後は、その値を下回る読取が再び棄却される。
    assert _feed(stabilizer, "0265700", 10, 3).validation_status == CandidateStatus.DECREASE_DETECTED


def test_reset_and_rebase_are_thread_safe_with_update():
    stabilizer = ReadingStabilizer(_settings(window_size=1, required_matches=1), baseline=_baseline("100"))
    errors = []

    def updater():
        try:
            for i in range(300):
                stabilizer.update(_raw("0000200", i))
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    thread = threading.Thread(target=updater)
    thread.start()
    for epoch in range(1, 30):
        stabilizer.rebase("150", Decimal("150"), T0, epoch)
        stabilizer.reset(epoch + 100)
    thread.join()
    assert errors == []


# --- conflict ---

def test_decrease_conflict_tracks_duration_and_alerts_after_threshold():
    stabilizer = ReadingStabilizer(_settings(), baseline=_baseline("265759"))
    last = None
    for second in range(0, CONFLICT_ALERT_SECONDS + 30, 10):
        last = stabilizer.update(_raw("0265754", second))
    conflict = last.conflict
    assert conflict is not None and conflict.status == CandidateStatus.DECREASE_DETECTED
    assert conflict.candidate == "265754"  # 先頭0除去後の表示値
    assert conflict.count > 10
    now = T0 + timedelta(seconds=CONFLICT_ALERT_SECONDS + 20)
    assert conflict_active(conflict, now)
    assert conflict_alert(conflict, now)


def test_conflict_not_alerting_before_threshold():
    stabilizer = ReadingStabilizer(_settings(), baseline=_baseline("265759"))
    last = None
    for second in range(0, 60, 10):
        last = stabilizer.update(_raw("0265754", second))
    assert last.conflict is not None
    assert not conflict_alert(last.conflict, T0 + timedelta(seconds=60))


def test_rate_conflict():
    settings = _settings(max_rate_per_minute=1.0)
    stabilizer = ReadingStabilizer(settings, baseline=Baseline(value="100", numeric_value=Decimal("100"), confirmed_at=T0 - timedelta(seconds=60)))
    result = _feed(stabilizer, "0000500", 0, 3)
    assert result.validation_status == CandidateStatus.RATE_EXCEEDED
    assert result.conflict is not None and result.conflict.status == CandidateStatus.RATE_EXCEEDED
    assert result.conflict.candidate == "500"


def test_conflict_cleared_when_a_value_is_confirmed():
    stabilizer = ReadingStabilizer(_settings(), baseline=_baseline("265759"))
    _feed(stabilizer, "0265754", 0, 3)
    assert stabilizer.conflict is not None
    result = _feed(stabilizer, "0265760", 10, 3)
    assert result.validation_status == CandidateStatus.CONFIRMED
    assert result.conflict is None


def test_conflict_survives_interleaved_invalid_format_ticks():
    stabilizer = ReadingStabilizer(_settings(window_size=1, required_matches=1), baseline=_baseline("265759"))
    stabilizer.update(_raw("0265754", 0))
    stabilizer.update(_raw("026575", 1))  # 6桁: invalid_format(conflictは維持される)
    result = stabilizer.update(_raw("0265754", 2))
    assert result.conflict is not None and result.conflict.count == 2


def test_resumed_conflict_continues_across_rebuild():
    first = ReadingStabilizer(_settings(), baseline=_baseline("265759"))
    for second in range(0, 40, 10):
        last = first.update(_raw("0265754", second))
    # 再構築(Backend再起動相当): DBから復元したconflictを引き継ぐ。空白が60秒を超えても600秒以内なら継続。
    resumed = ReadingStabilizer(_settings(), baseline=_baseline("265759"), conflict=last.conflict)
    again = None
    for second in range(200, 260, 10):
        again = resumed.update(_raw("0265754", second))
    assert again.conflict.started_at == last.conflict.started_at


# --- 設定ごとの挙動 ---

def test_monotonic_false_accepts_lower_value_and_has_no_conflict():
    stabilizer = ReadingStabilizer(_settings(monotonic=False), baseline=_baseline("265759"))
    result = _feed(stabilizer, "0265754", 0, 3)
    assert result.validation_status == CandidateStatus.CONFIRMED
    assert result.conflict is None


def test_allow_rollover_accepts_decrease_without_conflict():
    stabilizer = ReadingStabilizer(_settings(allow_rollover=True, rollover_max=9999999), baseline=_baseline("9999990"))
    result = _feed(stabilizer, "0000005", 0, 3)
    assert result.validation_status == CandidateStatus.CONFIRMED
    assert result.value == "5"
    assert result.conflict is None


def test_reading_disabled_never_persists_baseline():
    stabilizer = ReadingStabilizer(_settings(enabled=False))
    result = stabilizer.update(_raw("0265754", 0))
    assert result.persist_baseline is False
    assert result.value == "265754"


# --- 運用者が入力する基準値の検証 ---

@pytest.mark.parametrize("text,expected_digits,decimal_position,display", [
    ("0265754", 7, 0, "265754"),
    ("265754", 7, 0, "265754"),
    ("372398.5", 7, 1, "372398.5"),
    ("0372398.5", 7, 1, "372398.5"),
    ("0.5", 7, 1, "0.5"),
])
def test_parse_operator_value_accepts(text, expected_digits, decimal_position, display):
    shown, numeric = parse_operator_value(text, expected_digits, decimal_position)
    assert shown == display and numeric == Decimal(display)


@pytest.mark.parametrize("text,expected_digits,decimal_position", [
    ("", 7, 0), ("abc", 7, 0), ("-5", 7, 0), ("12345678", 7, 0), ("372399", 7, 1), ("372398.55", 7, 1), ("1e5", 7, 0),
])
def test_parse_operator_value_rejects(text, expected_digits, decimal_position):
    with pytest.raises(ValueError):
        parse_operator_value(text, expected_digits, decimal_position)


def test_rebase_tolerance_scales_with_decimal_position():
    assert rebase_tolerance(0) == Decimal(10)
    assert rebase_tolerance(1) == Decimal(1)
    assert rebase_tolerance(None) == Decimal(10)
