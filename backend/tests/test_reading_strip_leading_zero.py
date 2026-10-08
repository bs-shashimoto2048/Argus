"""最終運用値の先頭0除去(strip_leading_zero)のテスト(Issue #38 Drum acceptance)。

検出・Raw・expected_digits検証は先頭0を含む桁列のまま行い、Confirmed(=UI/DB/CSVの運用値)
だけを整形する。既定(False)では従来どおり先頭0を保持し、Digitalには影響しない。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.inference.base import InferenceResult
from app.main import app
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
    ("00372398.5", "372398.5"),
    ("0372398", "372398"),
    ("0000000", "0"),
    ("0.5", "0.5"),
    ("0265754", "265754"),
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


def test_leading_zero_removed_from_confirmed_only_when_enabled():
    # 7桁検出 -> expected_digits=7検証 -> decimal_position=1適用 -> 先頭0除去
    settings = ReadingSettings(expected_digits=7, decimal_position=1, strip_leading_zero=True)
    stabilizer, confirmed = _confirm(settings, "0372395")
    assert confirmed.validation_status == CandidateStatus.CONFIRMED
    assert confirmed.value == "37239.5"
    # 比較用のnumeric_valueは整形の影響を受けない。
    assert float(confirmed.numeric_value) == 37239.5
    # Raw(元の桁列)とdiagnostics用のRawバッファは先頭0を保持する。
    assert confirmed.raw_value == "0372395"
    assert all(reading.value == "0372395" for reading in stabilizer.recent_raw)


def test_value_without_leading_zero_is_unchanged():
    settings = ReadingSettings(expected_digits=7, decimal_position=1, strip_leading_zero=True)
    _, confirmed = _confirm(settings, "3723985")
    assert confirmed.value == "372398.5"


def test_expected_digits_is_validated_before_stripping():
    # 8桁を検出した場合、先頭0を除去すると7桁になるが、検証は除去前の桁列で行うため棄却される。
    settings = ReadingSettings(expected_digits=7, decimal_position=1, strip_leading_zero=True)
    _, confirmed = _confirm(settings, "03723985")
    assert confirmed.validation_status == CandidateStatus.INVALID_FORMAT


def test_all_zero_integer_part_keeps_one_digit():
    settings = ReadingSettings(expected_digits=8, decimal_position=1, strip_leading_zero=True)
    _, confirmed = _confirm(settings, "00000005")
    assert confirmed.value == "0.5"


def test_default_keeps_leading_zero_so_digital_is_unchanged():
    # Digital(ex. 0265754)は既定(strip_leading_zero=False)のため変化しない。
    for settings in (ReadingSettings(), ReadingSettings(expected_digits=7, decimal_position=0)):
        _, confirmed = _confirm(settings, "0265754")
        assert confirmed.value == "0265754"
    assert ReadingSettings.from_dict(None).strip_leading_zero is False
    assert ReadingSettings.from_dict({"expected_digits": 7}).strip_leading_zero is False
    assert ReadingSettings.from_dict({"strip_leading_zero": True}).strip_leading_zero is True


def test_monotonic_compares_numeric_value_not_formatted_string():
    settings = ReadingSettings(expected_digits=7, decimal_position=1, strip_leading_zero=True, window_size=3, required_matches=2)
    stabilizer = ReadingStabilizer(settings)
    for index, raw in enumerate(["0372395"] * 3):
        stabilizer.update(InferenceResult(value=raw, confidence=0.9, engine="mock", timestamp=BASE_TIME + timedelta(seconds=index)))
    # 減少(0372390 -> 37239.0 < 37239.5)は整形後でも減少として棄却される。
    last = None
    for index, raw in enumerate(["0372390"] * 3):
        last = stabilizer.update(InferenceResult(value=raw, confidence=0.9, engine="mock", timestamp=BASE_TIME + timedelta(seconds=10 + index)))
    assert last.validation_status == CandidateStatus.DECREASE_DETECTED
    assert last.value == "37239.5"


def test_passthrough_mode_also_formats_value():
    settings = ReadingSettings(enabled=False, expected_digits=7, decimal_position=1, strip_leading_zero=True)
    stabilizer = ReadingStabilizer(settings)
    confirmed = stabilizer.update(InferenceResult(value="0372395", confidence=0.9, engine="mock", timestamp=BASE_TIME))
    assert confirmed.value == "37239.5"


def test_api_roundtrip_defaults_false_and_persists():
    with TestClient(app) as client:
        created = client.post("/api/monitors", json={"name": "test_strip_leading_zero", "display_name": "s"})
        assert created.status_code == 201, created.text
        monitor_id = created.json()["id"]
        try:
            assert created.json()["inference"]["reading"]["strip_leading_zero"] is False
            res = client.patch(f"/api/monitors/{monitor_id}", json={"inference": {"method": "object_detection", "reading": {"strip_leading_zero": True}}})
            assert res.status_code == 200, res.text
            assert client.get(f"/api/monitors/{monitor_id}").json()["inference"]["reading"]["strip_leading_zero"] is True
        finally:
            client.delete(f"/api/monitors/{monitor_id}")
