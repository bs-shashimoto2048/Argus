from datetime import datetime, timedelta

from sqlalchemy import select

from ..core.database import SessionLocal
from ..models import InferenceResult, LatestResult, Monitor
from reading.models import CandidateStatus, ConfirmedReading

# LatestResult.value/previous_value/statusを更新する(=運用値として採用する)status。
_ACCEPTED_STATUSES = (CandidateStatus.CONFIRMED, CandidateStatus.LOW_CONFIDENCE)


def save_result(monitor_id: int, confirmed: ConfirmedReading) -> None:
    """ReadingStabilizerが確定したConfirmed Readingを永続化する。

    ここではTemporal Stabilization/Validationのロジックを一切持たない
    (ReadingStabilizer/ReadingValidatorの責務であり、ResultStoreは保存のみ)。
    """
    db = SessionLocal()
    try:
        latest = db.scalar(select(LatestResult).where(LatestResult.monitor_id == monitor_id))
        if not latest:
            latest = LatestResult(monitor_id=monitor_id)
            db.add(latest)

        status = confirmed.validation_status
        if status in _ACCEPTED_STATUSES:
            if confirmed.value is not None and latest.value != confirmed.value:
                latest.previous_value = latest.value
            if confirmed.value is not None:
                latest.value = confirmed.value
            latest.confidence = confirmed.confidence
            latest.status = "ok" if status == CandidateStatus.CONFIRMED else "low_confidence"
            latest.last_error = None
            latest.engine = confirmed.engine or None
        elif status == CandidateStatus.NO_READING:
            # 連続読取失敗が閾値へ到達した場合のみread_error扱いにする。
            # (単発のNO_DETECTION等はここへ来ず、値も温存される)
            latest.status = "read_error"
            latest.last_error = confirmed.raw_error or "NO_DETECTION"
            latest.engine = confirmed.engine or None
        elif status == CandidateStatus.PENDING and latest.value is None:
            # 初回起動などまだ一度もConfirmed実績が無い場合のみ「判定中」を表示する。
            # 既にConfirmed値が存在する場合は、そのまま(ok/low_confidence等)を維持する。
            latest.status = "pending"
        # rejected/invalid_format/decrease_detected/rate_exceededは一時的な異常値として
        # 静かに棄却する(LatestResult/Monitor.statusを一切変更しない)。Alertは常にこの
        # Confirmed Readingの正常経路だけを見る設計にするため、ここでRawの棄却理由を
        # 運用値へ混ぜない。

        latest.processing_time_ms = confirmed.processing_time_ms
        latest.timestamp = datetime.utcnow()

        monitor = db.get(Monitor, monitor_id)
        if monitor:
            if status == CandidateStatus.CONFIRMED:
                monitor.status = "normal"
            elif status == CandidateStatus.LOW_CONFIDENCE:
                monitor.status = "warning"
            elif status == CandidateStatus.NO_READING:
                monitor.status = "read_error"
            # pending/rejected系はMonitor.status(video状態と共有の粗いbadge)を変更しない。

        if status in _ACCEPTED_STATUSES or status == CandidateStatus.NO_READING:
            effective_value = confirmed.value if status in _ACCEPTED_STATUSES else None
            last_history = db.scalar(select(InferenceResult).where(InferenceResult.monitor_id == monitor_id).order_by(InferenceResult.created_at.desc()))
            should_record = last_history is None or last_history.value != effective_value or last_history.created_at < datetime.utcnow() - timedelta(seconds=60)
            if should_record:
                db.add(InferenceResult(monitor_id=monitor_id, value=effective_value, confidence=confirmed.confidence if status in _ACCEPTED_STATUSES else None, detections=[], processing_time_ms=confirmed.processing_time_ms, engine=confirmed.engine or None))
        db.commit()
    finally:
        db.close()
