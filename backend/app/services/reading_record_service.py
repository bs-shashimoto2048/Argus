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

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from runtime.record_writer import record_writer as default_record_writer
from runtime.runtime_manager import runtime_manager

from ..models import Monitor, ReadingBaselineEvent, ReadingRecord, SystemSettings
from .csv_export_service import JST, get_settings, hour_bucket_jst
from .record_image_service import ImageJob, ImageResult, finalize_record
from .storage_settings_service import StorageConfig, load_config
from .reading_baseline_service import summarize as summarize_baseline

logger = logging.getLogger("argus.records")

# 計測枠の開始からこの秒数を過ぎたら、その枠の記録は作らない(遅れて記録した値を正式な定時計測として扱わない)。
RECORD_GRACE_SECONDS = 600
# 映像/読取が正常でない場合に「値なし」の記録を作るまで待つ秒数(再起動直後などの立ち上がりを待つ)。
RECORD_SETTLE_SECONDS = 120

# usage(使用量)を計算してよいdisplay_status(映像が稼働中で、読取が読取不能でないこと)。
# 値(value)自体は、映像が稼働中なら直前の正常Confirmed値を保持して記録する(下記value_source)。
_VALUE_OK_STATUSES = ("normal", "warning")
# 最新の候補が正常に確定している(accepted)validation_status。それ以外は「棄却中」で、直前の確定値を保持する。
_ACCEPTED_VALIDATION = ("confirmed", "low_confidence")
# 1時間記録の画像に使うフレームの鮮度の上限(秒)。映像が止まっているときの古いフレームを証跡にしない。
_FRAME_MAX_AGE_SECONDS = 10.0
# 記録に使う推論snapshotの鮮度の上限(秒)。映像/推論が止まって古い推論結果を、定時計測の証跡にしない。
_SNAPSHOT_MAX_AGE_SECONDS = 10.0
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


def is_trusted_values(*, numeric: Decimal | None, value_source: str | None, display: str | None, baseline_conflict: bool, corrected: bool) -> bool:
    """usage計算上、「現在の正式値として信頼できる」記録か。

    - 手動修正済み(運用者が画像等を確認して正式値を確定した)は、記録時にbaseline conflict・carried_forward・
      decrease_detected等だったとしても信頼できる(記録時の証跡そのものは変更しない。usage計算の失格条件だけをoverrideする)。
    - 未修正は、通常のConfirmed(value_source=confirmed)で、display_statusが正常系・baseline conflictなしの場合だけ。
      未修正のcarried_forwardは、正式値欄に値があっても信頼しない(実際の使用量0とは保証できない)。
    """
    if numeric is None:
        return False
    if corrected:
        return True
    return value_source == "confirmed" and display in _VALUE_OK_STATUSES and not baseline_conflict


def is_trusted_record(record: ReadingRecord | None) -> bool:
    if record is None:
        return False
    return is_trusted_values(numeric=_decimal(record.numeric_value), value_source=record.value_source, display=record.display_status,
                             baseline_conflict=bool(record.baseline_conflict), corrected=(record.correction_count or 0) > 0)


def compute_usage(
    db: Session,
    monitor_id: int,
    monitor_created_at: datetime | None,
    previous: ReadingRecord | None,
    numeric: Decimal | None,
    display: str,
    baseline_conflict: bool,
    now_utc: datetime,
    value_source: str | None = "confirmed",
    corrected: bool = False,
) -> str | None:
    """使用量 = 今回の定時計測値 - 直前1時間の定時計測値。今回と直前の**両方**が信頼できる記録でなければNone。

    Noneになる条件: 直前記録なし/どちらかが信頼できない(is_trusted_values: 未修正のcarried_forward・baseline conflict・
    正常系でないdisplay_status等。手動修正済みは信頼できる)/値が減少/直前記録以降にbaselineのreset・rebase・自動クリアがあった。
    直前が信頼できない区間を飛ばして、複数時間分を1時間の使用量として計上しない。
    baselineのrebaseは、その新しい値が前後どちらかの信頼できる記録の値と一致する場合(=運用者が確認した値への再設定)は
    連続性を壊さないものとして扱う(監査履歴は変更しない)。
    """
    if previous is None or numeric is None:
        return None
    previous_numeric = _decimal(previous.numeric_value)
    if previous_numeric is None:
        return None
    if not is_trusted_values(numeric=numeric, value_source=value_source, display=display, baseline_conflict=baseline_conflict, corrected=corrected):
        return None
    if not is_trusted_record(previous):
        return None
    if numeric < previous_numeric:
        return None
    query = select(ReadingBaselineEvent).where(
        ReadingBaselineEvent.monitor_id == monitor_id,
        ReadingBaselineEvent.action.in_(_BASELINE_RESET_ACTIONS),
        ReadingBaselineEvent.occurred_at > previous.recorded_at,
        ReadingBaselineEvent.occurred_at <= _naive_utc(now_utc),
    )
    if monitor_created_at is not None:
        query = query.where(ReadingBaselineEvent.occurred_at >= monitor_created_at)
    for event in db.scalars(query):
        if event.action == "rebase" and _decimal(event.new_value) in (numeric, previous_numeric):
            continue  # 確認済みの値への再設定は、連続性を壊さない
        return None
    return format(numeric - previous_numeric, "f")


def _live_raw_and_validation(monitor_id: int) -> tuple[str | None, str | None]:
    runtime = runtime_manager.get_runtime(monitor_id)
    scheduler = runtime.inference_scheduler if runtime else None
    confirmed = scheduler.latest_confirmed if scheduler else None
    if confirmed is None:
        return None, None
    return confirmed.raw_value, confirmed.validation_status.value


def get_fresh_snapshot(monitor_id: int, now_utc: datetime):
    """そのMonitorの、直近の完了した推論tickのsnapshotを**1回だけ**取得する(古い場合・無い場合はNone)。

    定時計測recordの値・Raw・判定・画像・engine/modelは、すべてこの1つのsnapshotから作る(別tickの値を混ぜない)。
    """
    runtime = runtime_manager.get_runtime(monitor_id)
    scheduler = getattr(runtime, "inference_scheduler", None) if runtime else None
    getter = getattr(scheduler, "get_record_snapshot", None) if scheduler else None
    snapshot = getter() if getter else None
    if snapshot is None or (now_utc - snapshot.inference_at).total_seconds() > _SNAPSHOT_MAX_AGE_SECONDS:
        return None
    return snapshot


def build_record(db: Session, monitor: Monitor, bucket: datetime, now_utc: datetime, snapshot=None) -> ReadingRecord:
    """計測枠bucketの記録(未保存)を組み立てる。

    snapshot(1推論tickの不変な情報)がある場合は、値・Raw・Rawのconfidence・判定・baseline conflict・engine/model・推論時刻を
    すべてそのsnapshotだけから使う(LatestResult等を読み直さない)。snapshotが無い場合(推論が無効/停止中など)は従来の経路。
    """
    latest = monitor.latest_result
    use_snapshot = snapshot is not None and monitor.status == "running"
    if use_snapshot:
        display = display_status(monitor.status, snapshot.inference_status or (latest.status if latest else None))
        baseline_conflict = bool(snapshot.baseline_conflict)
    else:
        display = display_status(monitor.status, latest.status if latest else None)
        conflict_summary = summarize_baseline(monitor.reading_baseline)
        baseline_conflict = bool(conflict_summary and conflict_summary.get("conflict"))
    # 正式記録値: 映像が稼働中なら、直前の正常Confirmed値(LatestResult.value)を記録する。最新のRawが棄却中
    # (pending/invalid_format/decrease_detected/rate_exceeded/no_reading等、桁の回転途中・見切れ中を含む)でも、
    # 「直近の最高値」ではなく直前の正常確定値を保持する(value_source=carried_forward)。映像が稼働していない
    # (通信異常・停止中・接続中)間は記録しない(value_source=none)。
    if use_snapshot:
        has_value = snapshot.confirmed_value is not None
        value = snapshot.confirmed_value if has_value else None
        raw_value, validation_status = snapshot.raw_value, snapshot.validation_status
    else:
        has_value = monitor.status == "running" and latest is not None and latest.value is not None
        value = latest.value if has_value else None
        raw_value, validation_status = _live_raw_and_validation(monitor.id)
        if validation_status is None and has_value:
            validation_status = {"ok": "confirmed", "low_confidence": "low_confidence"}.get(latest.status or "", "no_reading")
    numeric = _decimal(value)
    if not has_value:
        value_source = "none"
    elif validation_status in _ACCEPTED_VALIDATION:
        value_source = "confirmed"
    else:
        value_source = "carried_forward"

    previous = db.scalar(select(ReadingRecord).where(
        ReadingRecord.monitor_id == monitor.id, ReadingRecord.hour_bucket == (bucket - timedelta(hours=1)).isoformat()))
    usage = compute_usage(db, monitor.id, monitor.created_at, previous, numeric, display, baseline_conflict, now_utc, value_source)
    inference = monitor.inference
    if use_snapshot:
        confidence = snapshot.confirmed_confidence if has_value else None
        engine = snapshot.engine or (inference.engine if inference else None)
        model_id = snapshot.model_id or (inference.model_id if inference else None)
        raw_confidence, inference_at = snapshot.raw_confidence, _naive_utc(snapshot.inference_at)
    else:
        confidence = latest.confidence if has_value else None
        engine = (latest.engine if latest and latest.engine else None) or (inference.engine if inference else None)
        model_id = inference.model_id if inference else None
        raw_confidence, inference_at = None, None  # snapshotによる同一tick保証が無い記録(推測で補わない)
    return ReadingRecord(
        monitor_id=monitor.id,
        monitor_name=monitor.display_name or monitor.name,
        hour_bucket=bucket.isoformat(),
        recorded_at=_naive_utc(now_utc),
        value=value,
        value_source=value_source,
        numeric_value=str(numeric) if numeric is not None else None,
        raw_value=raw_value if has_value else None,
        previous_value=previous.value if previous is not None else None,
        usage=usage,
        confidence=confidence,
        raw_confidence=raw_confidence,
        inference_at=inference_at,
        validation_status=validation_status,
        display_status=display,
        baseline_conflict=baseline_conflict,
        engine=engine,
        model_id=model_id,
        image_status="not_saved",  # record_dueが、画像保存の設定/フレームの有無に応じてpending/disabled/failedへ更新する
    )


@dataclass
class RecordOutcome:
    monitor_id: int
    hour_bucket: str
    status: str  # created / exists / waiting / skipped
    record_id: int | None = None


def record_due(db: Session, now_utc: datetime | None = None, started_at: datetime | None = None, writer=None) -> list[RecordOutcome]:
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
    writer = writer or default_record_writer
    storage_config = load_config(db)
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
            # 推論snapshotは記録ごとに1回だけ取得し、同じsnapshotだけから記録(Raw/判定/値)と画像ジョブを作る。
            snapshot = get_fresh_snapshot(monitor.id, now_utc)
            record = build_record(db, monitor, bucket, now_utc, snapshot)
            db.add(record)
            db.commit()  # 計測値の記録を先に確定する(画像保存の成否に関わらず残る)
            outcomes.append(RecordOutcome(monitor.id, key, "created", record.id))
            _attach_images(db, monitor, record, storage_config, writer, snapshot)
        except IntegrityError:
            db.rollback()  # 同時に別のtickが作成済み(UNIQUE制約)
            outcomes.append(RecordOutcome(monitor.id, key, "exists"))
        except Exception:
            db.rollback()
            logger.exception("monitor %s: 計測記録の作成に失敗しました", monitor.id)
            outcomes.append(RecordOutcome(monitor.id, key, "skipped"))
    return outcomes


# --- 画像保存(Phase 2) ---

def _capture_frames(monitor_id: int) -> tuple[bytes | None, bytes | None]:
    """記録時点の元画像(JPEG)と推論オーバーレイ(JPEG)を、runtimeから取り出す(推論は行わない)。

    元画像は、overlayの元になったフレームがあればそれ(両者が同じフレームになる)、無ければ最新フレーム。
    映像が止まっていて古い場合は、証跡として誤解を招くため取得しない。
    """
    runtime = runtime_manager.get_runtime(monitor_id)
    if runtime is None:
        return None, None
    age = runtime.buffer.age()
    if age is None or age > _FRAME_MAX_AGE_SECONDS:
        return None, None
    scheduler = runtime.inference_scheduler
    overlay = scheduler.latest_overlay if scheduler else None
    original = (scheduler.latest_overlay_source if scheduler else None) or runtime.buffer.get()[0]
    return original, overlay


def _attach_images(db: Session, monitor: Monitor, record: ReadingRecord, config: StorageConfig, writer, snapshot=None) -> None:
    """記録の作成直後に、画像保存のジョブを作る。失敗しても計測値の記録には影響しない。

    snapshotがある場合、元画像とoverlayは記録と同じsnapshot(同じ推論tick・同じフレーム)から取り出す。
    """
    try:
        if not config.enabled:
            record.image_status = "disabled"
            db.commit()
            return
        if snapshot is not None and record.inference_at is not None:
            original, overlay = snapshot.original_jpeg, snapshot.overlay_jpeg
        else:
            original, overlay = _capture_frames(monitor.id)
        job = ImageJob(record_id=record.id, monitor_id=monitor.id, monitor_name=record.monitor_name, recorded_at=record.recorded_at,
                       value=record.value, original=original, overlay=overlay, want_original=config.save_original, want_overlay=config.save_overlay)
        if not ((config.save_original and original) or (config.save_overlay and overlay)):
            record.image_status = "failed"
            record.image_error = "映像のフレームを取得できないため、画像を保存できませんでした"
            db.commit()
            return
        record.image_status = "pending"
        db.commit()
        if not writer.submit(job):
            finalize_record(record.id, ImageResult("dropped", error="画像保存のキューが満杯のため、画像を保存しませんでした"))
    except Exception:
        db.rollback()
        logger.exception("monitor %s: 記録画像の保存の準備に失敗しました", monitor.id)
        try:  # 計測値の記録は残したまま、画像だけ失敗として記録する
            finalize_record(record.id, ImageResult("failed", error="画像保存の準備に失敗しました"))
        except Exception:
            logger.exception("monitor %s: 画像保存の失敗を記録できませんでした", monitor.id)


def backfill_value_source(connection) -> None:
    """value_source列を追加した直後に、既存の記録(Phase 1)へ由来を設定する(起動時の1回限り)。"""
    connection.execute(text(
        "UPDATE reading_records SET value_source = CASE "
        "WHEN value IS NULL THEN 'none' "
        "WHEN validation_status IN ('confirmed', 'low_confidence') THEN 'confirmed' "
        "ELSE 'carried_forward' END"))


# --- 参照 ---

# 手動修正の対象になる読取判定(基準値と矛盾して棄却された記録)。
_CONFLICT_VALIDATIONS = ("decrease_detected", "rate_exceeded")


def correctable_reason(record: ReadingRecord) -> str | None:
    """正式値を手動修正できる理由(carried_forward / baseline_conflict)。修正できない記録(通常のconfirmed等)はNone。"""
    if record.value is None:
        return None  # 正式値が無い記録(通信異常等)は修正の対象外
    if record.value_source == "carried_forward":
        return "carried_forward"
    if record.baseline_conflict or (record.validation_status in _CONFLICT_VALIDATIONS):
        return "baseline_conflict"
    return None


def serialize(record: ReadingRecord) -> dict:
    return {
        "id": record.id, "monitor_id": record.monitor_id, "monitor_name": record.monitor_name,
        "hour_bucket": record.hour_bucket, "recorded_at": _iso(record.recorded_at),
        "value": record.value, "value_source": record.value_source, "numeric_value": record.numeric_value, "raw_value": record.raw_value,
        "previous_value": record.previous_value, "usage": record.usage, "confidence": record.confidence,
        "validation_status": record.validation_status, "display_status": record.display_status,
        "baseline_conflict": record.baseline_conflict, "engine": record.engine, "model_id": record.model_id,
        "original_image_path": record.original_image_path, "overlay_image_path": record.overlay_image_path,
        "image_status": record.image_status, "image_error": record.image_error,
        # 証跡の整合性: raw_confidenceは最新Raw側のconfidence(confidenceは正式値側)。inference_atはその証跡snapshotの推論時刻。
        # inference_atがNULLの記録は、snapshotによる同一tick保証が無かった既存データ。
        "raw_confidence": record.raw_confidence, "inference_at": _iso(record.inference_at), "snapshot_consistent": record.inference_at is not None,
        # 手動修正(監査の正本は reading_record_corrections / GET /api/records/{id}/corrections)。元証跡は修正しても変わらない。
        "is_corrected": (record.correction_count or 0) > 0, "correction_count": record.correction_count or 0, "original_value": record.original_value,
        "corrected_at": _iso(record.corrected_at), "corrected_by": record.corrected_by,
        "correctable": correctable_reason(record) is not None, "correctable_reason": correctable_reason(record),
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
    # 正式な順序: 計測枠(hour_bucket)の新しい順 -> 同じ計測枠の中ではMonitorの表示順(display_order) -> monitor_id -> id。
    # hour_bucketはJSTの固定オフセット表記(例 2026-10-09T13:00:00+09:00)なので、文字列の降順が時刻の新しい順になる。
    # limit/offset(段階読み込み)もこの順序で行うため、同じ計測枠の行が取得境界をまたいでも連続し、既存の行の位置が動かない。
    display_order = func.coalesce(select(Monitor.display_order).where(Monitor.id == ReadingRecord.monitor_id).scalar_subquery(), 2147483647)
    ordered = query.order_by(ReadingRecord.hour_bucket.desc(), display_order.asc(), ReadingRecord.monitor_id.asc(), ReadingRecord.id.desc())
    rows = db.scalars(ordered.limit(limit).offset(offset)).all()
    return list(rows), int(total)


def get_record(db: Session, record_id: int) -> ReadingRecord | None:
    return db.get(ReadingRecord, record_id)


def parse_period(value: str | None) -> datetime | None:
    """APIの期間パラメータ(ISO 8601)を解釈する。タイムゾーンが無い場合はJSTとして扱う。"""
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=JST) if parsed.tzinfo is None else parsed
