from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..core.database import get_db
from ..schemas.monitor import MonitorCreate, MonitorOrderInput, MonitorUpdate
from ..services import monitor_service
from ..core import auth as auth_core
from ..core.auth import ADMIN_ONLY
router = APIRouter(prefix="/api/monitors", tags=["monitors"])

@router.get("")
def list_monitors(db: Session = Depends(get_db), role: str = Depends(auth_core.current_role)):
    monitors = monitor_service.list_monitors(db)
    return {"monitors": monitors if role == auth_core.ADMIN else [monitor_service.viewer_projection(m) for m in monitors]}
@router.put("/order", dependencies=ADMIN_ONLY)
def reorder_monitors(req: MonitorOrderInput, db: Session = Depends(get_db)):
    """表示順(Dashboard/モニター管理)だけを1 transactionで更新する。全MonitorのIDを表示したい順に指定する。"""
    try: return {"monitor_ids": monitor_service.reorder_monitors(db, req.monitor_ids)}
    except monitor_service.MonitorOrderError as exc:
        status = 409 if exc.code == "ORDER_STALE" else 422
        raise HTTPException(status, {"code": exc.code, "message": str(exc)}) from exc
@router.post("", status_code=201, dependencies=ADMIN_ONLY)
def create_monitor(req: MonitorCreate, db: Session = Depends(get_db)):
    try: return monitor_service.create_monitor(db, req)
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc
@router.get("/{monitor_id}")
def get_monitor(monitor_id: int, db: Session = Depends(get_db), role: str = Depends(auth_core.current_role)):
    try:
        response = monitor_service._to_response(monitor_service.get_monitor(db, monitor_id))
        return response if role == auth_core.ADMIN else monitor_service.viewer_projection(response)
    except ValueError as exc: raise HTTPException(404, str(exc)) from exc
@router.patch("/{monitor_id}", dependencies=ADMIN_ONLY)
def update_monitor(monitor_id: int, req: MonitorUpdate, db: Session = Depends(get_db)):
    try: return monitor_service.update_monitor(db, monitor_id, req)
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc
@router.delete("/{monitor_id}", status_code=204, dependencies=ADMIN_ONLY)
def delete_monitor(monitor_id: int, db: Session = Depends(get_db)):
    try: monitor_service.delete_monitor(db, monitor_id)
    except ValueError as exc: raise HTTPException(404, str(exc)) from exc
