"""読取値(正式値)の手動修正で、補正値が前後の正式値・現在の読取基準値などから極端に乖離していないかの安全確認。

誤補正(例: 372457.6 を 37245.7 と入力 = 桁落ち)を、保存前に気づけるようにする。hard blockではない(メーター交換・reset等の正当な大変動もあり得る)ため、
該当する場合は2段階確認(force)を要求する。判定は expected_digits の完全一致ではなく(先頭0を除去した正式値では桁数が変わるMonitorがあるため)、
次の「基準値」との乖離で行う:
  - 直前1時間の正式値 / 次の1時間の正式値(存在すれば) / 現在の読取基準値 に対する倍率が SCALE_RATIO 倍を超える、または 1/SCALE_RATIO 倍未満
    (10倍・1/10倍など、桁が1つ落ちた/増えたレベルは必ず含む)
  - max_rate_per_minute が設定されていれば、1時間あたりの許容増加量(max_rate_per_minute × 60)を超える変化
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from reading.models import ReadingSettings

from ..models import Monitor, ReadingRecord
from .reading_record_service import _decimal, neighbor_record

SCALE_RATIO = Decimal("3")
_SHIFT_TOLERANCE = Decimal("0.15")  # 10^kの倍率に±15%以内なら「桁・小数点位置の誤り」と明示する


def _digit_shift(ratio: Decimal) -> bool:
    for k in (1, 2, 3):
        scale = Decimal(10) ** k
        for target in (scale, Decimal(1) / scale):
            if abs(ratio / target - 1) <= _SHIFT_TOLERANCE:
                return True
    return False


def assess_correction(db: Session, record: ReadingRecord, new_numeric: Decimal, settings: ReadingSettings, monitor: Monitor | None) -> list[dict]:
    """乖離の理由の一覧(空なら安全)。各要素: {kind: scale|rate, reference, reference_value, ratio?, digit_shift?, message}。"""
    references: list[tuple[str, Decimal, str]] = []  # (表示名, 数値, 位置: before|after|baseline)
    previous = neighbor_record(db, record, -1)
    following = neighbor_record(db, record, 1)
    if previous is not None and _decimal(previous.numeric_value) is not None:
        references.append(("直前1時間の正式値", _decimal(previous.numeric_value), "before"))
    if following is not None and _decimal(following.numeric_value) is not None:
        references.append(("次の1時間の正式値", _decimal(following.numeric_value), "after"))
    baseline = monitor.reading_baseline if monitor is not None else None
    baseline_numeric = _decimal(baseline.numeric_value) if baseline is not None else None
    if baseline_numeric is not None:
        references.append(("現在の読取基準値", baseline_numeric, "baseline"))

    reasons: list[dict] = []
    max_rate = Decimal(str(settings.max_rate_per_minute)) if settings.max_rate_per_minute else None
    for label, ref, position in references:
        if ref > 0:
            ratio = new_numeric / ref
            if ratio > SCALE_RATIO or ratio < 1 / SCALE_RATIO:
                shift = _digit_shift(ratio) if ratio > 0 else False
                reasons.append({"kind": "scale", "reference": label, "reference_value": format(ref, "f"), "ratio": float(round(ratio, 4)), "digit_shift": shift,
                                "message": f"{label}（{format(ref, 'f')}）の約{float(round(ratio, 2))}倍です" + ("（桁落ち・小数点位置の誤りの可能性）" if shift else "")})
                continue
        if max_rate is not None and position in ("before", "after"):
            allowed = max_rate * 60
            change = (new_numeric - ref) if position == "before" else (ref - new_numeric)  # 時間の進む向きの増加量
            if change > allowed:
                reasons.append({"kind": "rate", "reference": label, "reference_value": format(ref, "f"), "message": f"{label}（{format(ref, 'f')}）との差が、最大変化率から許容される1時間あたりの増加量（{format(allowed, 'f')}）を超えています"})
    return reasons
