"""monotonic baseline(基準値)まわりの定数と、運用者が入力する基準値の検証(pure function)。

Issue #40: baselineは永続化され、Scheduler再構築/Backend再起動後も復元される。誤値が確定して
固着した場合の復旧手段として、運用者がreset/rebaseできる。低い値を自動採用することはしない。
"""
from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal

from .canonicalizer import digit_length, strip_leading_zeros
from .models import ConflictInfo

# baselineと矛盾する合意候補(decrease_detected/rate_exceeded)がこの秒数以上続いたらbaseline_conflict=true。
CONFLICT_ALERT_SECONDS = 300
# 棄却が途切れても、この秒数以内に同じstatusの棄却が再発すれば同一のconflictとして継続扱いにする。
CONFLICT_GAP_SECONDS = 60
# Scheduler再構築/Backend再起動をまたいで、DBに保存されたconflictの継続を許す最大の空白秒数。
CONFLICT_RESUME_SECONDS = 600
# conflictをDBへ書き込む最小間隔(状態が変わったときは即時に書く)。
CONFLICT_PERSIST_INTERVAL_SECONDS = 30
# rebase値が最新のRaw合意値と、最下位桁の何単位以上離れていたらforce確認を要求するか。
REBASE_WARN_UNITS = 10

_NUMBER = re.compile(r"^\d+(\.\d+)?$")


def parse_operator_value(text: str, expected_digits: int | None, decimal_position: int | None) -> tuple[str, Decimal]:
    """運用者が入力した基準値を検証し、(最終運用値の形式の文字列, Decimal)を返す。

    先頭0の有無は問わない("0265754"も"265754"も同じ値として受理)。expected_digitsは先頭0を除いた
    桁数が超えていないことを、decimal_position(>0)は小数部の桁数が一致することを確認する。
    不正な場合はValueError(メッセージはそのままAPIの422詳細になる)。
    """
    value = (text or "").strip()
    if not _NUMBER.match(value):
        raise ValueError("基準値は数字と小数点だけで入力してください(例: 265754 / 372398.5)")
    display = strip_leading_zeros(value)
    integer, _, fraction = display.partition(".")
    if expected_digits is not None and digit_length(display) > expected_digits:
        raise ValueError(f"桁数が期待桁数({expected_digits}桁)を超えています")
    if decimal_position and decimal_position > 0 and len(fraction) != decimal_position:
        raise ValueError(f"小数部は{decimal_position}桁で入力してください(例: 372398.{'0' * decimal_position})")
    return display, Decimal(display)


def rebase_tolerance(decimal_position: int | None) -> Decimal:
    """最新のRaw合意値との差がこの値を超えたらforce確認を要求する(最下位桁のREBASE_WARN_UNITS単位)。"""
    places = decimal_position if decimal_position and decimal_position > 0 else 0
    return Decimal(REBASE_WARN_UNITS) / (Decimal(10) ** places)


def conflict_active(conflict: ConflictInfo | None, now: datetime) -> bool:
    return conflict is not None and (now - conflict.last_at).total_seconds() <= CONFLICT_GAP_SECONDS


def conflict_duration_seconds(conflict: ConflictInfo | None) -> float:
    return (conflict.last_at - conflict.started_at).total_seconds() if conflict else 0.0


def conflict_alert(conflict: ConflictInfo | None, now: datetime) -> bool:
    return conflict_active(conflict, now) and conflict_duration_seconds(conflict) >= CONFLICT_ALERT_SECONDS
