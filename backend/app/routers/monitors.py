from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..core.database import get_db
from ..schemas.monitor import MonitorCreate, MonitorUpdate
from ..services import monitor_service
router = APIRouter(prefix="/api/monitors", tags=["monitors"])

@router.get("")
def list_monitors(db: Session = Depends(get_db)): return {"monitors": monitor_service.list_monitors(db)}
@router.post("", status_code=201)
def create_monitor(req: MonitorCreate, db: Session = Depends(get_db)):
    try: return monitor_service.create_monitor(db, req)
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc
@router.get("/{monitor_id}")
def get_monitor(monitor_id: int, db: Session = Depends(get_db)):
    try: return monitor_service._to_response(monitor_service.get_monitor(db, monitor_id))
    except ValueError as exc: raise HTTPException(404, str(exc)) from exc
@router.patch("/{monitor_id}")
def update_monitor(monitor_id: int, req: MonitorUpdate, db: Session = Depends(get_db)):
    try: return monitor_service.update_monitor(db, monitor_id, req)
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc
@router.delete("/{monitor_id}", status_code=204)
def delete_monitor(monitor_id: int, db: Session = Depends(get_db)):
    try: monitor_service.delete_monitor(db, monitor_id)
    except ValueError as exc: raise HTTPException(404, str(exc)) from exc
