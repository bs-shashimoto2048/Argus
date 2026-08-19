"""Confirmed候補の妥当性検証(pure function)。

InferenceEngineの精度そのものは扱わず、「時系列的に妥当な値の変化か」だけを見る。
すべて副作用なしの純粋関数で、Decimalベースで比較する(float誤差回避)。
"""
from __future__ import annotations

from decimal import Decimal

from .canonicalizer import digit_length


def validate_format(canonical: str | None, expected_digits: int | None) -> bool:
    """expected_digits設定時、桁数(小数点を除く)が一致するかを確認する。"""
    if expected_digits is None:
        return True
    if canonical is None:
        return False
    return digit_length(canonical) == expected_digits


def validate_monotonic(candidate: Decimal | None, previous: Decimal | None, allow_rollover: bool) -> bool:
    """積算メーター等、値が減少しないことを確認する。

    rollover(999999→000000等)が許可されている場合、減少そのものは許容し、
    その減少幅が物理的に妥当かどうかはvalidate_rateへ委ねる。
    """
    if candidate is None or previous is None:
        return True
    if candidate >= previous:
        return True
    return allow_rollover


def validate_rate(
    candidate: Decimal | None,
    previous: Decimal | None,
    elapsed_seconds: float | None,
    max_rate_per_minute: float | None,
    allow_rollover: bool,
    rollover_max: int | None,
) -> bool:
    """単位時間あたりの変化量が上限を超えていないかを確認する。

    rollover発生時(candidate < previous かつ allow_rollover)は、
    rollover_maxを跨いで進んだ距離をdeltaとして扱う。rollover_max未設定時は
    距離を安全に計算できないため拒否する。
    """
    if max_rate_per_minute is None:
        return True
    if candidate is None or previous is None or not elapsed_seconds or elapsed_seconds <= 0:
        return True

    delta = candidate - previous
    if delta < 0:
        if not allow_rollover:
            return False
        if rollover_max is None:
            return False
        delta = (Decimal(rollover_max + 1) - previous) + candidate

    rate_per_minute = delta / (Decimal(str(elapsed_seconds)) / Decimal(60))
    return rate_per_minute <= Decimal(str(max_rate_per_minute))
