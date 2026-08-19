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
