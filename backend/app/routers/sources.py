from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..core.database import get_db
from ..schemas.video_source import VideoSourceInput
from ..schemas.result import ConnectionCheckResponse
from ..services import monitor_service, video_service, source_service
router = APIRouter(prefix="/api", tags=["sources"])

@router.post("/sources/check", response_model=ConnectionCheckResponse)
def check_source(source: VideoSourceInput, db: Session = Depends(get_db)):
    ok, message = video_service.check_source(source, source.password)
    if ok and source.source_type == "url": monitor_service.save_verified_url(db, source)
    return ConnectionCheckResponse(success=ok, message=message, detail=None if ok else message)
@router.get("/url-history")
def list_history(db: Session = Depends(get_db)): return {"items": source_service.histories(db)}
@router.delete("/url-history/{history_id}", status_code=204)
def delete_history(history_id: int, db: Session = Depends(get_db)):
    try: monitor_service.delete_url_history(db, history_id)
    except ValueError as exc: raise HTTPException(404, str(exc)) from exc
