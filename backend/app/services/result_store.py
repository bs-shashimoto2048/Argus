from datetime import datetime, timedelta

from sqlalchemy import select

from ..core.database import SessionLocal
from ..models import InferenceResult, LatestResult, Monitor
from ..inference.base import InferenceResult as PipelineResult


def save_result(monitor_id: int, result: PipelineResult) -> None:
    db = SessionLocal()
    try:
        latest = db.scalar(select(LatestResult).where(LatestResult.monitor_id == monitor_id))
        if not latest:
            latest = LatestResult(monitor_id=monitor_id)
            db.add(latest)
        if result.error:
            latest.status = "read_error"
            latest.last_error = result.error
            latest.engine = result.engine or None
        else:
            if result.value is not None and latest.value != result.value:
                latest.previous_value = latest.value
            if result.value is not None:
                latest.value = result.value
            latest.confidence = result.confidence
            latest.status = "low_confidence" if result.confidence is not None and result.confidence < 0.5 else "ok"
            latest.last_error = None
            latest.engine = result.engine or None
        latest.processing_time_ms = result.processing_time_ms
        latest.timestamp = datetime.utcnow()
        monitor = db.get(Monitor, monitor_id)
        if monitor:
            monitor.status = "read_error" if result.error else ("normal" if result.value is not None else "warning")
        last_history = db.scalar(select(InferenceResult).where(InferenceResult.monitor_id == monitor_id).order_by(InferenceResult.created_at.desc()))
        should_record = result.error is not None or last_history is None or last_history.value != result.value or last_history.created_at < datetime.utcnow() - timedelta(seconds=60)
        if should_record:
            db.add(InferenceResult(monitor_id=monitor_id, value=result.value, confidence=result.confidence, detections=[d.__dict__ for d in result.detections], processing_time_ms=result.processing_time_ms, engine=result.engine or None))
        db.commit()
    finally:
        db.close()
