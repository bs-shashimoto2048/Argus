"""計測記録(reading_records)の正式値の手動修正と、その監査履歴(reading_record_corrections)。

運用者が修正できるのは、原則として次の記録だけ:
  A: value_source = carried_forward(前回確定値を保持した記録。最新Rawが棄却されていた)
  B: baseline conflict中の記録(baseline_conflict=true、または validation_status が decrease_detected / rate_exceeded)
通常のconfirmedな記録は修正できない。

修正で変更するのは正式値(value / numeric_value)と、それに連動するusage / previous_valueだけ。
記録時の元証跡(raw_value / raw_confidence / validation_status / value_source / 画像 / inference_at)は変更しない。
修正のたびに reading_record_corrections へ1行を追加する(UPDATE/DELETEしない=複数回修正しても全履歴が残る)。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from reading.baseline import parse_operator_value
from reading.models import ReadingSettings

from ..models import Monitor, ReadingRecord, ReadingRecordCorrection
from . import reading_baseline_service as baseline_service
from .reading_record_service import _decimal, _iso, _naive_utc, compute_usage, correctable_reason

logger = logging.getLogger("argus.record_corrections")

MAX_TEXT = 500


class CorrectionError(ValueError):
    """修正リクエストの不正。codeはAPI層でHTTPステータスへ変換する。"""

    def __init__(self, code: str, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


def _clean(text: str | None, name: str) -> str:
    value = (text or "").strip()
    if not value:
        raise CorrectionError(f"{name.upper()}_REQUIRED", f"{ {'reason': '修正理由', 'operator': '操作者'}[name] }は必須です")
    if len(value) > MAX_TEXT:
        raise CorrectionError(f"{name.upper()}_TOO_LONG", f"{ {'reason': '修正理由', 'operator': '操作者'}[name] }は{MAX_TEXT}文字以内で入力してください")
    return value


def _serialize_correction(row: ReadingRecordCorrection) -> dict:
    return {
        "id": row.id, "record_id": row.record_id, "monitor_id": row.monitor_id, "corrected_at": _iso(row.corrected_at),
        "operator": row.operator, "reason": row.reason, "old_value": row.old_value, "new_value": row.new_value,
        "old_numeric_value": row.old_numeric_value, "new_numeric_value": row.new_numeric_value, "old_usage": row.old_usage, "new_usage": row.new_usage,
        "raw_value": row.raw_value, "raw_confidence": row.raw_confidence, "validation_status": row.validation_status, "value_source": row.value_source,
        "baseline_value": row.baseline_value, "baseline_conflict": row.baseline_conflict,
        "original_image_path": row.original_image_path, "overlay_image_path": row.overlay_image_path,
        "client_host": row.client_host, "context": row.context,
    }


def list_corrections(db: Session, record_id: int) -> list[dict] | None:
    """記録の修正履歴(新しい順)。記録が存在しなければNone。"""
    if db.get(ReadingRecord, record_id) is None:
        return None
    rows = db.scalars(select(ReadingRecordCorrection).where(ReadingRecordCorrection.record_id == record_id)
                      .order_by(ReadingRecordCorrection.corrected_at.desc(), ReadingRecordCorrection.id.desc())).all()
    return [_serialize_correction(row) for row in rows]


def _neighbor(db: Session, record: ReadingRecord, delta_hours: int) -> ReadingRecord | None:
    """同じMonitorの、1時間前(delta=-1)/1時間後(delta=+1)の計測枠の記録。"""
    bucket = datetime.fromisoformat(record.hour_bucket) + timedelta(hours=delta_hours)
    return db.scalar(select(ReadingRecord).where(ReadingRecord.monitor_id == record.monitor_id, ReadingRecord.hour_bucket == bucket.isoformat()))


def _recompute_usage(db: Session, record: ReadingRecord, monitor_created_at: datetime | None) -> str | None:
    """記録自身の状況(display_status/baseline conflict/記録時刻)で、使用量を再評価する(null条件は維持される)。"""
    previous = _neighbor(db, record, -1)
    record.previous_value = previous.value if previous is not None else None
    recorded_utc = record.recorded_at.replace(tzinfo=timezone.utc)
    return compute_usage(db, record.monitor_id, monitor_created_at, previous, _decimal(record.numeric_value), record.display_status, bool(record.baseline_conflict), recorded_utc,
                         record.value_source, (record.correction_count or 0) > 0)


def correct_record(db: Session, record_id: int, value: str, reason: str, operator: str, client_host: str = "", rebase_current_baseline: bool = False) -> dict:
    record = db.get(ReadingRecord, record_id)
    if record is None:
        raise CorrectionError("RECORD_NOT_FOUND", "計測記録が見つかりません", 404)
    reason, operator = _clean(reason, "reason"), _clean(operator, "operator")
    why = correctable_reason(record)
    if why is None:
        raise CorrectionError("NOT_CORRECTABLE", "この記録は修正できません(修正できるのは、前回確定値を保持した記録と、基準値競合中の記録だけです)", 409)

    monitor = db.get(Monitor, record.monitor_id)
    settings = ReadingSettings.from_dict(monitor.inference.reading if monitor is not None and monitor.inference is not None else None)
    try:
        new_value, new_numeric = parse_operator_value(value, settings.expected_digits, settings.decimal_position)
    except ValueError as exc:
        raise CorrectionError("INVALID_VALUE", str(exc)) from exc
    if record.value == new_value:
        raise CorrectionError("NO_CHANGE", "修正後の値が、現在の正式値と同じです")

    # 現在の読取基準値(runtimeのbaseline)は、履歴の修正では変更しない。明示的に指定されたときだけ、既存のrebase処理を呼ぶ。
    rebase_info: dict = {"requested": bool(rebase_current_baseline), "performed": False}
    if rebase_current_baseline:
        if monitor is None:
            raise CorrectionError("REBASE_NOT_AVAILABLE", "Monitorが存在しないため、基準値を再設定できません", 409)
        try:
            before = baseline_service.get_status(db, monitor).get("baseline")
            baseline_service.rebase_baseline(db, monitor, new_value, f"読取値の修正(record {record.id}): {reason}", operator, client_host, force=False)
        except baseline_service.ForceRequiredError as exc:
            raise CorrectionError("REBASE_FORCE_REQUIRED", f"基準値を{exc.requested}へ再設定すると、最新のRaw合意値({exc.candidate})と大きく異なります。実メーターを確認し、基準値の再設定は「診断」タブの管理操作から行ってください", 409) from exc
        except baseline_service.ReadingDisabledError as exc:
            raise CorrectionError("REBASE_NOT_AVAILABLE", str(exc), 409) from exc
        except baseline_service.InvalidBaselineValueError as exc:
            raise CorrectionError("INVALID_VALUE", str(exc)) from exc
        rebase_info.update({"performed": True, "old_baseline": before.get("value") if before else None, "new_baseline": new_value})

    old_value, old_numeric, old_usage = record.value, record.numeric_value, record.usage
    created_at = monitor.created_at if monitor is not None else None
    now = datetime.now(timezone.utc)
    try:
        record.value = new_value
        record.numeric_value = str(new_numeric)
        if record.original_value is None:
            record.original_value = old_value  # 最初の修正前の正式値
        record.correction_count = (record.correction_count or 0) + 1
        record.corrected_at = _naive_utc(now)
        record.corrected_by = operator
        record.usage = _recompute_usage(db, record, created_at)  # 修正した記録のusage
        # 未来側の記録を時系列順に再評価する。更新するのは previous_value / usage だけ(値・証跡は書き換えない)。
        # usageは「直前1時間との差」なので、修正した記録の値・信頼状態が影響するのは直後の記録だけ。直後の記録の
        # previous_value/usageが変わらなければ、それ以降も変わらないのでそこで止める(以降を無用に書き換えない)。
        affected: list[dict] = []
        cursor = record
        while True:
            nxt = _neighbor(db, cursor, 1)
            if nxt is None:
                break
            before_usage, before_previous = nxt.usage, nxt.previous_value
            nxt.usage = _recompute_usage(db, nxt, created_at)
            affected.append({"record_id": nxt.id, "hour_bucket": nxt.hour_bucket, "value": nxt.value, "value_source": nxt.value_source, "old_usage": before_usage, "new_usage": nxt.usage})
            if nxt.usage == before_usage and nxt.previous_value == before_previous and len(affected) > 0:
                break
            cursor = nxt
        next_info = affected[0] if affected else None
        row = ReadingRecordCorrection(
            record_id=record.id, monitor_id=record.monitor_id, corrected_at=_naive_utc(now), operator=operator, reason=reason,
            old_value=old_value, new_value=new_value, old_numeric_value=old_numeric, new_numeric_value=record.numeric_value, old_usage=old_usage, new_usage=record.usage,
            raw_value=record.raw_value, raw_confidence=record.raw_confidence, validation_status=record.validation_status, value_source=record.value_source,
            baseline_value=_baseline_value(db, record), baseline_conflict=bool(record.baseline_conflict),
            original_image_path=record.original_image_path, overlay_image_path=record.overlay_image_path, client_host=(client_host or "")[:64],
            context={"reason_type": why, "hour_bucket": record.hour_bucket, "recorded_at": _iso(record.recorded_at), "inference_at": _iso(record.inference_at),
                     "display_status": record.display_status, "engine": record.engine, "model_id": record.model_id, "next_record": next_info, "recomputed_records": affected, "rebase": rebase_info,
                     "correction_count": record.correction_count},
        )
        db.add(row)
        db.commit()
    except Exception:
        db.rollback()
        raise
    logger.warning("record %s (monitor %s): 正式値を修正しました %s -> %s (operator=%s, reason=%s)", record.id, record.monitor_id, old_value, new_value, operator, reason)
    return {"record_id": record.id, "correction": _serialize_correction(row), "next_record": next_info, "recomputed_records": affected, "rebase": rebase_info}


def _baseline_value(db: Session, record: ReadingRecord) -> str | None:
    """修正の時点でのMonitorの読取基準値(監査用)。取得できなければNone。"""
    try:
        monitor = db.get(Monitor, record.monitor_id)
        if monitor is None or monitor.reading_baseline is None:
            return None
        return monitor.reading_baseline.value
    except Exception:
        return None
