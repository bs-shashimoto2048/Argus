from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..schemas.inference import Roi
from ..services import monitor_service

router = APIRouter(prefix="/api/monitors", tags=["roi"])


@router.get("/{monitor_id}/roi", response_model=Roi)
def get_roi(monitor_id: int, db: Session = Depends(get_db)):
    try:
        monitor = monitor_service.get_monitor(db, monitor_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return Roi.model_validate(monitor.inference.roi or {})


@router.put("/{monitor_id}/roi", response_model=Roi)
def update_roi(monitor_id: int, roi: Roi, db: Session = Depends(get_db)):
    try:
        monitor = monitor_service.get_monitor(db, monitor_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    monitor.inference.roi = roi.model_dump()
    db.commit()
    # DB保存だけでは稼働中InferenceSchedulerの設定dictへ反映されないため、
    # 稼働中Runtimeへ反映する。ROIはsourceと無関係なので、VideoReaderの再接続は
    # 行わずInferenceSchedulerだけを差し替える(Issue #16: ROI保存後に映像ソースが
    # 開けなくなる回帰の修正)。
    monitor = monitor_service.get_monitor(db, monitor_id)
    monitor_service.restart_inference_only(monitor, db)
    return roi
