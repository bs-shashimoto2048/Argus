"""最終運用値の先頭0除去(全Monitor共通のcanonicalization)のテスト(Issue #40)。

整数部の先頭0は、expected_digits検証・decimal_position適用の後で除去する。検出・bbox・
Raw digit sequence・桁数検証は元の桁列のまま。旧`strip_leading_zero`設定は無視される。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.inference.base import InferenceResult
from reading.canonicalizer import strip_leading_zeros
from reading.models import CandidateStatus, ReadingSettings
from reading.stabilizer import ReadingStabilizer

pytestmark = pytest.mark.unit

BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.mark.parametrize("value,expected", [
    ("0372398.5", "372398.5"),
    ("0302398.5", "302398.5"),
    ("3002398.5", "3002398.5"),
    ("0000000.5", "0.5"),
    ("000000.5", "0.5"),
    ("037239.5", "37239.5"),
    ("00372398.5", "372398.5"),
    ("0265771", "265771"),
    ("0215838", "215838"),
    ("0000000", "0"),
    ("0.50", "0.50"),  # 小数部は変更しない
    ("1000", "1000"),  # 途中・末尾の0は変更しない
    (None, None),
    ("", ""),
])
def test_strip_leading_zeros(value, expected):
    assert strip_leading_zeros(value) == expected


def _confirm(settings: ReadingSettings, raw: str):
    stabilizer = ReadingStabilizer(settings)
    confirmed = None
    for index in range(settings.window_size):
        confirmed = stabilizer.update(InferenceResult(value=raw, confidence=0.9, engine="mock", timestamp=BASE_TIME + timedelta(seconds=index)))
    return stabilizer, confirmed


def test_digital_confirmed_drops_leading_zero_and_raw_keeps_it():
    settings = ReadingSettings(expected_digits=7, decimal_position=0)
    stabilizer, confirmed = _confirm(settings, "0265771")
    assert confirmed.validation_status == CandidateStatus.CONFIRMED
    assert confirmed.value == "265771"
    assert confirmed.raw_value == "0265771"
    assert float(confirmed.numeric_value) == 265771
    assert all(reading.value == "0265771" for reading in stabilizer.recent_raw)


def test_drum_example_with_decimal_position():
    # 7桁検出 -> expected_digits=7検証 -> decimal_position=1適用 -> 最終値だけ先頭0除去
    settings = ReadingSettings(expected_digits=7, decimal_position=1)
    _, confirmed = _confirm(settings, "0372395")
    assert confirmed.value == "37239.5"
    assert float(confirmed.numeric_value) == 37239.5
    assert confirmed.raw_value == "0372395"


def test_all_zero_integer_part_keeps_one_digit():
    settings = ReadingSettings(expected_digits=7, decimal_position=1)
    _, confirmed = _confirm(settings, "0000005")
    assert confirmed.value == "0.5"


def test_value_without_leading_zero_is_unchanged():
    settings = ReadingSettings(expected_digits=7, decimal_position=1)
    _, confirmed = _confirm(settings, "3723985")
    assert confirmed.value == "372398.5"


def test_expected_digits_is_validated_before_stripping():
    # 先頭0を除去すると7桁になる8桁の列でも、検証は除去前の桁列で行うため棄却される。
    settings = ReadingSettings(expected_digits=7, decimal_position=1)
    _, confirmed = _confirm(settings, "03723985")
    assert confirmed.validation_status == CandidateStatus.INVALID_FORMAT


def test_decimal_position_is_not_shifted_by_stripping():
    settings = ReadingSettings(expected_digits=7, decimal_position=2)
    _, confirmed = _confirm(settings, "0012345")
    assert confirmed.value == "123.45"  # 小数点は右から2桁のまま


@pytest.mark.parametrize("legacy", [True, False, None])
def test_legacy_strip_leading_zero_setting_is_ignored(legacy):
    data = {"expected_digits": 7, "decimal_position": 0}
    if legacy is not None:
        data["strip_leading_zero"] = legacy
    settings = ReadingSettings.from_dict(data)
    assert not hasattr(settings, "strip_leading_zero")
    _, confirmed = _confirm(settings, "0265771")
    assert confirmed.value == "265771"  # 旧設定の値に関係なく同じ最終値


def test_passthrough_mode_also_formats_value():
    settings = ReadingSettings(enabled=False, expected_digits=7, decimal_position=1)
    confirmed = ReadingStabilizer(settings).update(InferenceResult(value="0372395", confidence=0.9, engine="mock", timestamp=BASE_TIME))
    assert confirmed.value == "37239.5"
    assert confirmed.persist_baseline is False
