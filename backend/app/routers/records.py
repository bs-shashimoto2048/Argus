from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..services import reading_record_service as svc
from runtime.hourly_record_worker import hourly_record_worker

router = APIRouter(prefix="/api/records", tags=["records"])


class RecordSettingsInput(BaseModel):
    enabled: bool


def _period(value: str | None, name: str) -> datetime | None:
    try:
        return svc.parse_period(value)
    except ValueError as exc:
        raise HTTPException(422, f"{name}はISO 8601形式で指定してください(例: 2026-10-08T00:00:00+09:00)") from exc


@router.get("")
def list_records(
    monitor_id: list[int] = Query(default=[]),
    start: str | None = Query(default=None, alias="from"),
    end: str | None = Query(default=None, alias="to"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """1時間ごとの計測履歴(新しい順)。from/toは記録時刻(recorded_at)の期間で、タイムゾーンなしはJST。"""
    rows, total = svc.list_records(db, monitor_id or None, _period(start, "from"), _period(end, "to"), limit, offset)
    return {"items": [svc.serialize(row) for row in rows], "total": total, "limit": limit, "offset": offset}


@router.get("/status")
def records_status(db: Session = Depends(get_db)):
    """計測記録の有効/無効と、Workerの状態。"""
    return {
        "enabled": svc.hourly_records_enabled(db),
        "worker_running": hourly_record_worker.is_running(),
        "last_tick_at": svc._iso(hourly_record_worker.last_tick_at),
        "last_error": hourly_record_worker.last_error,
    }


@router.put("/settings")
def update_records_settings(body: RecordSettingsInput, db: Session = Depends(get_db)):
    svc.set_hourly_records_enabled(db, body.enabled)
    return {"enabled": svc.hourly_records_enabled(db)}


@router.get("/{record_id}")
def get_record(record_id: int, db: Session = Depends(get_db)):
    record = svc.get_record(db, record_id)
    if record is None:
        raise HTTPException(404, "計測記録が見つかりません")
    return svc.serialize(record)
