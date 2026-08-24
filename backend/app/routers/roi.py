from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..schemas.inference import Roi, RoiUpdateRequest, RoiUpdateResponse
from ..services import monitor_service

router = APIRouter(prefix="/api/monitors", tags=["roi"])


@router.get("/{monitor_id}/roi", response_model=RoiUpdateResponse)
def get_roi(monitor_id: int, db: Session = Depends(get_db)):
    try:
        monitor = monitor_service.get_monitor(db, monitor_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    roi = Roi.model_validate(monitor.inference.roi or {})
    return RoiUpdateResponse(**roi.model_dump(), roi_mode=monitor.inference.roi_mode, context_margin=monitor.inference.context_margin)


@router.put("/{monitor_id}/roi", response_model=RoiUpdateResponse)
def update_roi(monitor_id: int, payload: RoiUpdateRequest, db: Session = Depends(get_db)):
    try:
        monitor = monitor_service.get_monitor(db, monitor_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    monitor.inference.roi = Roi(x=payload.x, y=payload.y, width=payload.width, height=payload.height).model_dump()
    # roi_mode/context_marginはobject_detection時のみROI Editorが送るが、未指定(None)なら
    # 既存値を変更しない(OCR設定のMonitorから呼ばれた場合など)。
    if payload.roi_mode is not None:
        monitor.inference.roi_mode = payload.roi_mode
    if payload.context_margin is not None:
        monitor.inference.context_margin = payload.context_margin
    db.commit()
    # DB保存だけでは稼働中InferenceSchedulerの設定dictへ反映されないため、
    # 稼働中Runtimeへ反映する。ROIはsourceと無関係なので、VideoReaderの再接続は
    # 行わずInferenceSchedulerだけを差し替える(Issue #16: ROI保存後に映像ソースが
    # 開けなくなる回帰の修正)。
    monitor = monitor_service.get_monitor(db, monitor_id)
    monitor_service.restart_inference_only(monitor, db)
    roi = Roi.model_validate(monitor.inference.roi)
    return RoiUpdateResponse(**roi.model_dump(), roi_mode=monitor.inference.roi_mode, context_margin=monitor.inference.context_margin)
