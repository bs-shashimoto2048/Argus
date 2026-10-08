"""monotonic baseline(基準値)の永続化・復元・reset/rebase・監査(Issue #40)。

方針:
- 永続化するのはCONFIRMEDのみ(LOW_CONFIDENCE/パススルー/棄却されたstatusは対象外)。
- 既存Monitorには自動でbaselineを作らない(LatestResult.valueから復元しない)。baseline行が無い状態は
  従来どおり「最初のCONFIRMEDで基準を作る」挙動のまま。
- 低い値の自動採用はしない。固着の復旧は運用者のreset/rebaseだけで行い、すべて監査履歴に残す。
- reset/rebaseはbaselineだけを変更し、LatestResult(Dashboard表示値)は直接書き換えない。
  次の正常なConfirmedで自然に更新される。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from reading.baseline import (
    CONFLICT_ALERT_SECONDS,
    CONFLICT_PERSIST_INTERVAL_SECONDS,
    CONFLICT_RESUME_SECONDS,
    conflict_alert,
    conflict_active,
    conflict_duration_seconds,
    parse_operator_value,
    rebase_tolerance,
)
from reading.models import Baseline, CandidateStatus, ConfirmedReading, ConflictInfo, ReadingSettings
from runtime.runtime_manager import runtime_manager

from ..core.database import SessionLocal
from ..models import Monitor, ReadingBaseline, ReadingBaselineEvent

logger = logging.getLogger("argus.baseline")

# 値が変わらなくても、確定が続いている間はこの秒数ごとにconfirmed_atを更新する(書込み頻度の抑制)。
_TOUCH_INTERVAL_SECONDS = 60


class BaselineError(Exception):
    """API層でHTTPステータスへ変換するための基底例外。"""


class ReadingDisabledError(BaselineError):
    """reading.enabled=falseのMonitorにはbaselineの概念がない(409)。"""


class InvalidBaselineValueError(BaselineError):
    """基準値の入力不正(422)。"""


class ForceRequiredError(BaselineError):
    """最新のRaw合意値と大きく異なる基準値を、force無しで指定した(409)。"""

    def __init__(self, candidate: str, requested: str, tolerance: Decimal) -> None:
        super().__init__("最新のRaw合意値と大きく異なります")
        self.candidate = candidate
        self.requested = requested
        self.tolerance = tolerance


# --- datetime/Decimal変換 ---

def _naive_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    aware = _aware_utc(value)
    return aware.isoformat().replace("+00:00", "Z") if aware else None


def _decimal(text: str | None) -> Decimal | None:
    if text is None:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _get_row(db: Session, monitor_id: int) -> ReadingBaseline | None:
    return db.scalar(select(ReadingBaseline).where(ReadingBaseline.monitor_id == monitor_id))


def _clear_conflict(row: ReadingBaseline) -> None:
    row.conflict_status = None
    row.conflict_candidate = None
    row.conflict_count = 0
    row.conflict_started_at = None
    row.conflict_last_at = None


def _row_conflict(row: ReadingBaseline | None) -> ConflictInfo | None:
    if row is None or not row.conflict_status or row.conflict_started_at is None or row.conflict_last_at is None:
        return None
    try:
        status = CandidateStatus(row.conflict_status)
    except ValueError:
        return None
    return ConflictInfo(status=status, candidate=row.conflict_candidate or "", count=row.conflict_count or 0,
                        started_at=_aware_utc(row.conflict_started_at), last_at=_aware_utc(row.conflict_last_at))


def _add_event(db: Session, monitor: Monitor, action: str, old: ReadingBaseline | None, old_value: str | None,
               old_confirmed_at: datetime | None, new_value: str | None, reason: str, operator: str,
               client_host: str, context: dict) -> None:
    db.add(ReadingBaselineEvent(
        monitor_id=monitor.id, monitor_name=monitor.name, occurred_at=_naive_utc(_now()), action=action,
        old_value=old_value, old_confirmed_at=old_confirmed_at, new_value=new_value,
        reason=reason, operator=operator, client_host=client_host, context=context,
    ))


# --- 復元(Scheduler再構築/Backend再起動) ---

def restore_baseline(monitor_id: int, settings: ReadingSettings) -> tuple[Baseline | None, int, ConflictInfo | None]:
    """InferenceScheduler構築時に呼ばれるbaseline provider。(baseline, epoch, 継続するconflict)を返す。

    失敗しても例外は伝播させず、baselineなし(従来挙動)で開始する。
    """
    db = SessionLocal()
    try:
        row = _get_row(db, monitor_id)
        if row is None:
            return None, 0, None
        if row.state != "active" or not row.value or _decimal(row.numeric_value) is None:
            return None, row.epoch, None
        # semantic fingerprint: 小数位置/期待桁数が保存時と違えば数値の尺度が変わるため、復元せず自動クリアする。
        if row.decimal_position != settings.decimal_position or row.expected_digits != settings.expected_digits:
            monitor = db.get(Monitor, monitor_id)
            old_value, old_at = row.value, row.confirmed_at
            context = {"saved": {"decimal_position": row.decimal_position, "expected_digits": row.expected_digits},
                       "current": {"decimal_position": settings.decimal_position, "expected_digits": settings.expected_digits}}
            row.state = "pending_reset"
            row.source = "auto_semantic_reset"
            row.epoch += 1
            _clear_conflict(row)
            row.updated_at = _naive_utc(_now())
            _add_event(db, monitor or Monitor(id=monitor_id, name=""), "auto_semantic_reset", row, old_value, old_at, None,
                       "decimal_position/expected_digitsが変更されたためbaselineを自動クリア", "system", "", context)
            db.commit()
            logger.warning("monitor %s: reading設定の変更によりbaselineを自動クリアしました", monitor_id)
            return None, row.epoch, None
        baseline = Baseline(value=row.value, numeric_value=_decimal(row.numeric_value), confirmed_at=_aware_utc(row.confirmed_at),
                            source=row.source, epoch=row.epoch)
        conflict = _row_conflict(row)
        if conflict is not None and (_now() - conflict.last_at).total_seconds() > CONFLICT_RESUME_SECONDS:
            conflict = None
        return baseline, row.epoch, conflict
    except Exception:
        logger.exception("monitor %s: baselineの復元に失敗しました(baselineなしで開始します)", monitor_id)
        return None, 0, None
    finally:
        db.close()


# --- 永続化(ResultStoreから呼ばれる) ---

def record_confirmed(db: Session, monitor_id: int, confirmed: ConfirmedReading) -> None:
    """Confirmed Readingの結果をbaseline/conflictへ反映する。呼び出し元(save_result)のsessionで動く。"""
    status = confirmed.validation_status
    if status not in (CandidateStatus.CONFIRMED, CandidateStatus.LOW_CONFIDENCE, CandidateStatus.DECREASE_DETECTED, CandidateStatus.RATE_EXCEEDED):
        return
    row = _get_row(db, monitor_id)
    if row is not None and confirmed.baseline_epoch < row.epoch:
        return  # reset/rebase前の世代のConfirmed(競合)は、baselineを上書きしない
    now = _naive_utc(_now())

    if status == CandidateStatus.CONFIRMED and confirmed.persist_baseline and confirmed.numeric_value is not None and confirmed.value:
        confirmed_at = _naive_utc(confirmed.confirmed_at) or now
        if row is None:
            row = ReadingBaseline(monitor_id=monitor_id, epoch=confirmed.baseline_epoch)
            db.add(row)
            changed = True
        else:
            same_value = _decimal(row.numeric_value) == confirmed.numeric_value
            changed = (not same_value or row.state != "active" or row.decimal_position != confirmed.decimal_position
                       or row.expected_digits != confirmed.expected_digits or bool(row.conflict_status))
            if not changed and (row.confirmed_at is None or (confirmed_at - row.confirmed_at).total_seconds() >= _TOUCH_INTERVAL_SECONDS):
                # 値が変わらない確定が続いている間は、由来(source)を変えずに確定日時だけを更新する(書込み頻度を抑制)。
                row.confirmed_at = confirmed_at
                row.updated_at = now
                return
        if changed:
            row.value = confirmed.value
            row.numeric_value = str(confirmed.numeric_value)
            row.confirmed_at = confirmed_at
            row.source = "confirmed"
            row.state = "active"
            row.decimal_position = confirmed.decimal_position
            row.expected_digits = confirmed.expected_digits
            _clear_conflict(row)
            row.updated_at = now
        return

    if row is None:
        return
    conflict = confirmed.conflict
    if status in (CandidateStatus.DECREASE_DETECTED, CandidateStatus.RATE_EXCEEDED):
        if conflict is None:
            return
        started, last = _naive_utc(conflict.started_at), _naive_utc(conflict.last_at)
        due = (row.conflict_status != conflict.status.value or row.conflict_started_at != started
               or row.conflict_last_at is None or (last - row.conflict_last_at).total_seconds() >= CONFLICT_PERSIST_INTERVAL_SECONDS)
        if due:
            row.conflict_status = conflict.status.value
            row.conflict_candidate = conflict.candidate
            row.conflict_count = conflict.count
            row.conflict_started_at = started
            row.conflict_last_at = last
            row.updated_at = now
    elif row.conflict_status:
        # LOW_CONFIDENCEで受理された(=棄却が解消した)場合もconflictを解除する。
        _clear_conflict(row)
        row.updated_at = now


# --- 参照 ---

def _reading_settings(monitor: Monitor) -> ReadingSettings:
    reading = monitor.inference.reading if monitor.inference else None
    return ReadingSettings.from_dict(reading)


def summarize(row: ReadingBaseline | None) -> dict | None:
    """Monitor応答(Dashboard用)へ載せる軽量な要約。"""
    if row is None:
        return None
    now = _now()
    conflict = _row_conflict(row)
    return {
        "value": row.value,
        "state": row.state,
        "confirmed_at": _iso(row.confirmed_at),
        "conflict": conflict_alert(conflict, now),
        "conflict_status": conflict.status.value if conflict_active(conflict, now) else None,
        "conflict_candidate": conflict.candidate if conflict_active(conflict, now) else None,
        "conflict_since": _iso(row.conflict_started_at) if conflict_active(conflict, now) else None,
        "conflict_seconds": int(conflict_duration_seconds(conflict)) if conflict_active(conflict, now) else 0,
    }


def _live_stabilizer(monitor_id: int):
    runtime = runtime_manager.get_runtime(monitor_id)
    scheduler = runtime.inference_scheduler if runtime else None
    return scheduler.stabilizer if scheduler else None


def get_status(db: Session, monitor: Monitor) -> dict:
    row = _get_row(db, monitor.id)
    settings = _reading_settings(monitor)
    now = _now()
    stabilizer = _live_stabilizer(monitor.id)
    live_conflict = stabilizer.conflict if stabilizer else None
    conflict = live_conflict if live_conflict is not None else _row_conflict(row)
    candidate = stabilizer.last_candidate if stabilizer else None
    raw_recent = stabilizer.recent_raw[-1] if stabilizer and stabilizer.recent_raw else None
    latest = monitor.latest_result
    baseline = None
    if row is not None:
        baseline = {
            "value": row.value, "numeric_value": row.numeric_value, "confirmed_at": _iso(row.confirmed_at),
            "age_seconds": int((now - _aware_utc(row.confirmed_at)).total_seconds()) if row.confirmed_at else None,
            "source": row.source, "state": row.state, "epoch": row.epoch,
            "decimal_position": row.decimal_position, "expected_digits": row.expected_digits,
        }
    return {
        "monitor_id": monitor.id,
        "baseline": baseline,
        "conflict": None if conflict is None else {
            "status": conflict.status.value, "candidate": conflict.candidate, "count": conflict.count,
            "started_at": _iso(conflict.started_at), "last_at": _iso(conflict.last_at),
            "duration_seconds": int(conflict_duration_seconds(conflict)),
            "active": conflict_active(conflict, now), "alert": conflict_alert(conflict, now),
        },
        "candidate": candidate,
        "latest_raw": raw_recent.value if raw_recent else None,
        "current_confirmed": latest.value if latest else None,
        "reading": {
            "enabled": settings.enabled, "monotonic": settings.monotonic, "allow_rollover": settings.allow_rollover,
            "max_rate_per_minute": settings.max_rate_per_minute, "decimal_position": settings.decimal_position,
            "expected_digits": settings.expected_digits,
        },
        "alert_seconds": CONFLICT_ALERT_SECONDS,
        "runtime_active": stabilizer is not None,
    }


def list_events(db: Session, monitor_id: int, limit: int = 50) -> list[dict]:
    """監査履歴(新しい順)。Monitor削除後も取得できる。

    SQLiteはMonitor IDを再利用し得る(最大IDのMonitorを削除してから新規作成した場合)ため、Monitorが
    存在する間は、そのMonitorの作成時刻以降のイベントだけを返す(別Monitorの履歴が混ざらないように)。
    """
    query = select(ReadingBaselineEvent).where(ReadingBaselineEvent.monitor_id == monitor_id)
    monitor = db.get(Monitor, monitor_id)
    if monitor is not None and monitor.created_at is not None:
        query = query.where(ReadingBaselineEvent.occurred_at >= monitor.created_at)
    rows = db.scalars(query.order_by(ReadingBaselineEvent.occurred_at.desc(), ReadingBaselineEvent.id.desc()).limit(limit)).all()
    return [{
        "id": r.id, "monitor_id": r.monitor_id, "monitor_name": r.monitor_name, "occurred_at": _iso(r.occurred_at),
        "action": r.action, "old_value": r.old_value, "old_confirmed_at": _iso(r.old_confirmed_at), "new_value": r.new_value,
        "reason": r.reason, "operator": r.operator, "client_host": r.client_host, "context": r.context or {},
    } for r in rows]


# --- 操作(reset/rebase) ---

def _prepare_row(db: Session, monitor: Monitor) -> ReadingBaseline:
    row = _get_row(db, monitor.id)
    if row is None:
        row = ReadingBaseline(monitor_id=monitor.id, epoch=0, state="pending_reset")
        db.add(row)
        db.flush()
    return row


def _event_context(monitor: Monitor, row: ReadingBaseline, stabilizer) -> dict:
    inference = monitor.inference
    candidate = stabilizer.last_candidate if stabilizer else None
    conflict = (stabilizer.conflict if stabilizer else None) or _row_conflict(row)
    return {
        "engine": inference.engine if inference else None, "model_id": inference.model_id if inference else None,
        "raw_candidate": candidate, "current_confirmed": monitor.latest_result.value if monitor.latest_result else None,
        "conflict": None if conflict is None else {"status": conflict.status.value, "candidate": conflict.candidate,
                                                  "count": conflict.count, "since": _iso(conflict.started_at)},
        "reading": {"decimal_position": _reading_settings(monitor).decimal_position, "expected_digits": _reading_settings(monitor).expected_digits},
    }


def reset_baseline(db: Session, monitor: Monitor, reason: str, operator: str, client_host: str) -> dict:
    """baselineをpending_resetにする。次に正常にCONFIRMEDされた値が新しいbaselineになる。"""
    settings = _reading_settings(monitor)
    if not settings.enabled:
        raise ReadingDisabledError("reading.enabled=falseのMonitorにはbaselineがありません")
    stabilizer = _live_stabilizer(monitor.id)
    row = _prepare_row(db, monitor)
    old_value, old_at = row.value, row.confirmed_at
    context = _event_context(monitor, row, stabilizer)
    row.epoch += 1
    row.state = "pending_reset"
    row.source = "operator_reset"
    _clear_conflict(row)
    row.updated_at = _naive_utc(_now())
    _add_event(db, monitor, "reset", row, old_value, old_at, None, reason, operator, client_host, context)
    db.commit()
    if stabilizer is not None:
        stabilizer.reset(row.epoch)
    logger.warning("monitor %s: baselineをresetしました (operator=%s, reason=%s)", monitor.id, operator, reason)
    return get_status(db, monitor)


def rebase_baseline(db: Session, monitor: Monitor, value: str, reason: str, operator: str, client_host: str, force: bool = False) -> dict:
    """baselineを、運用者が実メーターで確認した値へ置き換える。"""
    settings = _reading_settings(monitor)
    if not settings.enabled:
        raise ReadingDisabledError("reading.enabled=falseのMonitorにはbaselineがありません")
    try:
        display, numeric = parse_operator_value(value, settings.expected_digits, settings.decimal_position)
    except ValueError as exc:
        raise InvalidBaselineValueError(str(exc)) from exc
    stabilizer = _live_stabilizer(monitor.id)
    candidate = stabilizer.last_candidate if stabilizer else None
    candidate_numeric = _decimal(candidate["value"]) if candidate else None
    if candidate_numeric is not None and not force and abs(numeric - candidate_numeric) > rebase_tolerance(settings.decimal_position):
        raise ForceRequiredError(candidate["value"], display, rebase_tolerance(settings.decimal_position))
    row = _prepare_row(db, monitor)
    old_value, old_at = row.value, row.confirmed_at
    context = _event_context(monitor, row, stabilizer)
    context["forced"] = bool(force)
    now = _now()
    row.epoch += 1
    row.value = display
    row.numeric_value = str(numeric)
    row.confirmed_at = _naive_utc(now)
    row.source = "operator_rebase"
    row.state = "active"
    row.decimal_position = settings.decimal_position
    row.expected_digits = settings.expected_digits
    _clear_conflict(row)
    row.updated_at = _naive_utc(now)
    _add_event(db, monitor, "rebase", row, old_value, old_at, display, reason, operator, client_host, context)
    db.commit()
    if stabilizer is not None:
        stabilizer.rebase(display, numeric, now, row.epoch)
    logger.warning("monitor %s: baselineをrebaseしました %s -> %s (operator=%s, reason=%s)", monitor.id, old_value, display, operator, reason)
    return get_status(db, monitor)
