"""表示用文字列(leading zero保持)と、比較・計算用のDecimalを分離するための純粋関数群。

数値比較(monotonic/rate)はfloat誤差を避けるためDecimalで行う。
表示用のcanonical文字列はleading zeroを保持したまま返す(int/Decimal化しない)。
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from app.inference.meter_interpreter import normalize_meter_text


def canonical_value(text: str | None, decimal_position: int | None = None) -> str | None:
    """表示用canonical文字列を作る。既存のOCR/YOLO正規化ロジック(app.inference側)を再利用する。"""
    if not text:
        return None
    return normalize_meter_text(text, decimal_position)


def strip_leading_zeros(canonical: str | None) -> str | None:
    """最終運用値の整形: 整数部の先頭の0を除去する(整数部は最低1桁残す)。

    expected_digits検証・decimal_position適用が済んだcanonical文字列に対してのみ使う
    (検出・bbox・Raw digit sequence・桁数検証では先頭0を維持する)。途中の0・小数部は変えない。
    例: "0372398.5" -> "372398.5" / "0302398.5" -> "302398.5" / "3002398.5" -> そのまま /
        "0000000.5" -> "0.5"
    """
    if not canonical:
        return canonical
    integer, dot, fraction = canonical.partition(".")
    if not integer:
        return canonical
    return (integer.lstrip("0") or "0") + dot + fraction


def to_numeric(canonical: str | None) -> Decimal | None:
    """canonical文字列(例: "0025.60")を比較・計算用のDecimalへ変換する。数値化できなければNone。"""
    if not canonical:
        return None
    try:
        return Decimal(canonical)
    except InvalidOperation:
        return None


def digit_length(canonical: str | None) -> int:
    """canonical文字列に含まれる数字の桁数(小数点は含まない)を返す。"""
    if not canonical:
        return 0
    return sum(1 for char in canonical if char.isdigit())
