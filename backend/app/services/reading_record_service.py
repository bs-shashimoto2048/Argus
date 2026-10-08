"""1時間ごとの正式な計測記録(reading_records)の作成・参照(UI再設計 Phase 1)。

- 1 Monitor 1時間 1件。毎時00分(Asia/Tokyo)の計測枠(hour_bucket)ごとに、その時点の最終運用値
  (LatestResult。先頭0除去後のConfirmed)を記録する。値が変わるたびの記録ではない。
- 状態変化(通信異常/読取不能/baseline conflict/reset/rebase)は別概念。ここでは、記録時点の
  display_statusとbaseline_conflictを付記し、usage(使用量)を無効にする根拠として参照するだけで、
  イベントを独立した行として混在させない。
- 推論/Reading/baselineのロジックには触れない(DBとruntime情報の読み取りのみ)。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from runtime.runtime_manager import runtime_manager

from ..models import Monitor, ReadingBaselineEvent, ReadingRecord, SystemSettings
from .csv_export_service import JST, get_settings, hour_bucket_jst
from .reading_baseline_service import summarize as summarize_baseline

logger = logging.getLogger("argus.records")

# 計測枠の開始からこの秒数を過ぎたら、その枠の記録は作らない(遅れて記録した値を正式な定時計測として扱わない)。
RECORD_GRACE_SECONDS = 600
# 映像/読取が正常でない場合に「値なし」の記録を作るまで待つ秒数(再起動直後などの立ち上がりを待つ)。
RECORD_SETTLE_SECONDS = 120

# 値を記録してよいdisplay_status(映像が稼働中で、読取が読取不能でないこと)。
_VALUE_OK_STATUSES = ("normal", "warning")
# usageを無効にする、baselineの操作イベント。
_BASELINE_RESET_ACTIONS = ("reset", "rebase", "auto_semantic_reset")


def display_status(monitor_status: str | None, inference_status: str | None) -> str:
    """映像Runtime状態と読取・推論状態を1つの表示状態へ合成する(Frontendのcombinedmonitorstatusと同じ規則)。"""
    status = monitor_status or "stopped"
    if status != "running":
        return status
    if inference_status == "read_error":
        return "read_error"
    if inference_status == "low_confidence":
        return "warning"
    return "normal"


def _decimal(text: str | None) -> Decimal | None:
    if text is None or text == "":
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _naive_utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo is not None else value


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    aware = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return aware.isoformat().replace("+00:00", "Z")


def hourly_records_enabled(db: Session) -> bool:
    settings: SystemSettings = get_settings(db)
    return bool(settings.hourly_record_enabled) if settings.hourly_record_enabled is not None else True


def set_hourly_records_enabled(db: Session, enabled: bool) -> None:
    get_settings(db).hourly_record_enabled = enabled
    db.commit()


def compute_usage(
    db: Session,
    monitor_id: int,
    monitor_created_at: datetime | None,
    previous: ReadingRecord | None,
    numeric: Decimal | None,
    display: str,
    baseline_conflict: bool,
    now_utc: datetime,
) -> str | None:
    """使用量 = 今回の定時計測値 - 前回の定時計測値。連続した正常なデータでなければNone。

    Noneになる条件: 前回記録なし/どちらかの値なし/値が減少/どちらかが正常でない
    (display_statusが正常・要確認以外、またはbaseline conflict)/前回記録以降にbaselineの
    reset・rebase・自動クリアがあった。
    """
    if previous is None or numeric is None:
        return None
    previous_numeric = _decimal(previous.numeric_value)
    if previous_numeric is None:
        return None
    if display not in _VALUE_OK_STATUSES or previous.display_status not in _VALUE_OK_STATUSES:
        return None
    if baseline_conflict or previous.baseline_conflict:
        return None
    if numeric < previous_numeric:
        return None
    query = select(func.count()).select_from(ReadingBaselineEvent).where(
        ReadingBaselineEvent.monitor_id == monitor_id,
        ReadingBaselineEvent.action.in_(_BASELINE_RESET_ACTIONS),
        ReadingBaselineEvent.occurred_at > previous.recorded_at,
        ReadingBaselineEvent.occurred_at <= _naive_utc(now_utc),
    )
    if monitor_created_at is not None:
        query = query.where(ReadingBaselineEvent.occurred_at >= monitor_created_at)
    if (db.scalar(query) or 0) > 0:
        return None
    return format(numeric - previous_numeric, "f")


def _live_raw_and_validation(monitor_id: int) -> tuple[str | None, str | None]:
    runtime = runtime_manager.get_runtime(monitor_id)
    scheduler = runtime.inference_scheduler if runtime else None
    confirmed = scheduler.latest_confirmed if scheduler else None
    if confirmed is None:
        return None, None
    return confirmed.raw_value, confirmed.validation_status.value


def build_record(db: Session, monitor: Monitor, bucket: datetime, now_utc: datetime) -> ReadingRecord:
    """計測枠bucketの記録(未保存)を組み立てる。"""
    latest = monitor.latest_result
    display = display_status(monitor.status, latest.status if latest else None)
    conflict_summary = summarize_baseline(monitor.reading_baseline)
    baseline_conflict = bool(conflict_summary and conflict_summary.get("conflict"))
    value_ok = display in _VALUE_OK_STATUSES and latest is not None and latest.value is not None
    value = latest.value if value_ok else None
    numeric = _decimal(value)
    raw_value, validation_status = _live_raw_and_validation(monitor.id)
    if validation_status is None and value_ok:
        validation_status = "low_confidence" if latest.status == "low_confidence" else "confirmed"

    previous = db.scalar(select(ReadingRecord).where(
        ReadingRecord.monitor_id == monitor.id, ReadingRecord.hour_bucket == (bucket - timedelta(hours=1)).isoformat()))
    usage = compute_usage(db, monitor.id, monitor.created_at, previous, numeric, display, baseline_conflict, now_utc)
    inference = monitor.inference
    return ReadingRecord(
        monitor_id=monitor.id,
        monitor_name=monitor.display_name or monitor.name,
        hour_bucket=bucket.isoformat(),
        recorded_at=_naive_utc(now_utc),
        value=value,
        numeric_value=str(numeric) if numeric is not None else None,
        raw_value=raw_value if value_ok else None,
        previous_value=previous.value if previous is not None else None,
        usage=usage,
        confidence=latest.confidence if value_ok else None,
        validation_status=validation_status,
        display_status=display,
        baseline_conflict=baseline_conflict,
        engine=(latest.engine if latest and latest.engine else None) or (inference.engine if inference else None),
        model_id=inference.model_id if inference else None,
        image_status="not_saved",
    )


@dataclass
class RecordOutcome:
    monitor_id: int
    hour_bucket: str
    status: str  # created / exists / waiting / skipped
    record_id: int | None = None


def record_due(db: Session, now_utc: datetime | None = None, started_at: datetime | None = None) -> list[RecordOutcome]:
    """現在の計測枠について、未記録のMonitorの記録を作る(毎時00分から猶予時間内)。

    - 計測枠の開始からRECORD_GRACE_SECONDS(10分)を過ぎた枠は記録しない(遅れた値を定時計測にしない)。
    - 映像/読取が正常なら即時に記録する。正常でない間は、立ち上がり(Backend再起動直後等)を
      待つためRECORD_SETTLE_SECONDS(2分)待ち、それでも正常でなければ「値なし」の記録を作る
      (欠損の理由をdisplay_statusで残す)。
    - 有効(enabled)かつ映像ソースのあるMonitorだけが対象。機能が無効の場合は何もしない。
    """
    now_utc = now_utc or datetime.now(timezone.utc)
    if not hourly_records_enabled(db):
        return []
    bucket = hour_bucket_jst(now_utc)
    elapsed = (now_utc - bucket.astimezone(timezone.utc)).total_seconds()
    if elapsed > RECORD_GRACE_SECONDS:
        return []
    started = started_at or now_utc
    settle_origin = max(bucket.astimezone(timezone.utc), started)
    settled = (now_utc - settle_origin).total_seconds() >= RECORD_SETTLE_SECONDS

    monitors = db.scalars(select(Monitor).options(
        joinedload(Monitor.latest_result), joinedload(Monitor.inference), joinedload(Monitor.reading_baseline), joinedload(Monitor.source)
    ).where(Monitor.enabled.is_(True)).order_by(Monitor.id)).unique().all()
    outcomes: list[RecordOutcome] = []
    for monitor in monitors:
        if monitor.source is None:
            continue
        key = bucket.isoformat()
        existing = db.scalar(select(ReadingRecord.id).where(ReadingRecord.monitor_id == monitor.id, ReadingRecord.hour_bucket == key))
        if existing is not None:
            outcomes.append(RecordOutcome(monitor.id, key, "exists", existing))
            continue
        status = display_status(monitor.status, monitor.latest_result.status if monitor.latest_result else None)
        if status not in _VALUE_OK_STATUSES and not settled:
            outcomes.append(RecordOutcome(monitor.id, key, "waiting"))
            continue
        try:
            record = build_record(db, monitor, bucket, now_utc)
            db.add(record)
            db.commit()
            outcomes.append(RecordOutcome(monitor.id, key, "created", record.id))
        except IntegrityError:
            db.rollback()  # 同時に別のtickが作成済み(UNIQUE制約)
            outcomes.append(RecordOutcome(monitor.id, key, "exists"))
        except Exception:
            db.rollback()
            logger.exception("monitor %s: 計測記録の作成に失敗しました", monitor.id)
            outcomes.append(RecordOutcome(monitor.id, key, "skipped"))
    return outcomes


# --- 参照 ---

def serialize(record: ReadingRecord) -> dict:
    return {
        "id": record.id, "monitor_id": record.monitor_id, "monitor_name": record.monitor_name,
        "hour_bucket": record.hour_bucket, "recorded_at": _iso(record.recorded_at),
        "value": record.value, "numeric_value": record.numeric_value, "raw_value": record.raw_value,
        "previous_value": record.previous_value, "usage": record.usage, "confidence": record.confidence,
        "validation_status": record.validation_status, "display_status": record.display_status,
        "baseline_conflict": record.baseline_conflict, "engine": record.engine, "model_id": record.model_id,
        "original_image_path": record.original_image_path, "overlay_image_path": record.overlay_image_path,
        "image_status": record.image_status, "image_error": record.image_error,
    }


def _base_query(monitor_ids: list[int] | None, start: datetime | None, end: datetime | None):
    query = select(ReadingRecord)
    if monitor_ids:
        query = query.where(ReadingRecord.monitor_id.in_(monitor_ids))
    if start is not None:
        query = query.where(ReadingRecord.recorded_at >= _naive_utc(start))
    if end is not None:
        query = query.where(ReadingRecord.recorded_at < _naive_utc(end))
    # Monitor IDは再利用され得るため、Monitorが存在する間はその作成時刻以降の記録だけを対象にする。
    created = select(Monitor.created_at).where(Monitor.id == ReadingRecord.monitor_id).scalar_subquery()
    return query.where(ReadingRecord.recorded_at >= func.coalesce(created, datetime(1970, 1, 1)))


def list_records(db: Session, monitor_ids: list[int] | None = None, start: datetime | None = None, end: datetime | None = None,
                 limit: int = 100, offset: int = 0) -> tuple[list[ReadingRecord], int]:
    query = _base_query(monitor_ids, start, end)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(ReadingRecord.recorded_at.desc(), ReadingRecord.id.desc()).limit(limit).offset(offset)).all()
    return list(rows), int(total)


def get_record(db: Session, record_id: int) -> ReadingRecord | None:
    return db.get(ReadingRecord, record_id)


def parse_period(value: str | None) -> datetime | None:
    """APIの期間パラメータ(ISO 8601)を解釈する。タイムゾーンが無い場合はJSTとして扱う。"""
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=JST) if parsed.tzinfo is None else parsed
