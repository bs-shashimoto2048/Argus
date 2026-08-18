from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload
from ..models import Monitor, VideoSource, UrlHistory, InferenceSettings, LatestResult
from ..schemas.monitor import MonitorCreate, MonitorUpdate
from ..schemas.video_source import VideoSourceInput
from .secret_store import encrypt, decrypt
from .video_service import reader_config
from runtime.runtime_manager import runtime_manager

def _ensure_children(db: Session, monitor: Monitor) -> None:
    if not monitor.inference: monitor.inference = InferenceSettings()
    if not monitor.latest_result: monitor.latest_result = LatestResult()
    db.flush()

def _to_response(m: Monitor):
    from ..schemas.monitor import MonitorResponse
    source = None
    if m.source:
        source = {"source_type": m.source.source_type, "device_id": m.source.device_id, "url": m.source.url, "username": m.source.username, "has_password": bool(m.source.encrypted_password)}
    return MonitorResponse(id=m.id, name=m.name, display_name=m.display_name, location=m.location, enabled=m.enabled, status=m.status, created_at=m.created_at, updated_at=m.updated_at, source=source, inference=m.inference, current_value=m.latest_result.value if m.latest_result else None, previous_value=m.latest_result.previous_value if m.latest_result else None, confidence=m.latest_result.confidence if m.latest_result else None, last_updated=m.latest_result.timestamp if m.latest_result else None)

def _restart_runtime(m: Monitor, db: Session) -> None:
    if m.enabled and m.source:
        password = decrypt(m.source.encrypted_password)
        runtime_manager.start_monitor(m.id, reader_config(VideoSourceInput(source_type=m.source.source_type, device_id=m.source.device_id, url=m.source.url, username=m.source.username), password))
    else: runtime_manager.stop_monitor(m.id)

def list_monitors(db: Session):
    rows = db.scalars(select(Monitor).options(joinedload(Monitor.source), joinedload(Monitor.inference), joinedload(Monitor.latest_result)).order_by(Monitor.id)).unique().all()
    return [_to_response(m) for m in rows]

def get_monitor(db: Session, monitor_id: int) -> Monitor:
    m = db.scalar(select(Monitor).options(joinedload(Monitor.source), joinedload(Monitor.inference), joinedload(Monitor.latest_result)).where(Monitor.id == monitor_id))
    if not m: raise ValueError("モニターが見つかりません")
    _ensure_children(db, m)
    return m

def create_monitor(db: Session, req: MonitorCreate):
    if db.scalar(select(Monitor).where(Monitor.name == req.name)): raise ValueError("モニター名は既に使用されています")
    m = Monitor(name=req.name, display_name=req.display_name, location=req.location)
    m.inference = InferenceSettings(); m.latest_result = LatestResult()
    db.add(m); db.commit(); return _to_response(get_monitor(db, m.id))

def update_monitor(db: Session, monitor_id: int, req: MonitorUpdate):
    m = get_monitor(db, monitor_id)
    data = req.model_dump(exclude_unset=True)
    source_data = data.pop("source", None); inference_data = data.pop("inference", None)
    for key, value in data.items(): setattr(m, key, value)
    if source_data is not None:
        src = source_data
        if src.get("source_type") == "url" and not (src.get("url") or "").strip(): raise ValueError("URLを入力してください")
        if not m.source: m.source = VideoSource()
        for key in ("source_type", "device_id", "url", "username"):
            if key in src: setattr(m.source, key, src[key])
        if src.get("password"):
            m.source.encrypted_password = encrypt(src["password"])
        elif src.get("history_id"):
            history = db.get(UrlHistory, src["history_id"])
            if history and history.encrypted_password:
                m.source.encrypted_password = history.encrypted_password
    if inference_data is not None:
        for key, value in inference_data.items():
            if key == "roi": value = value.model_dump() if hasattr(value, "model_dump") else value
            setattr(m.inference, key, value)
    m.updated_at = datetime.utcnow(); db.commit(); m = get_monitor(db, monitor_id); _restart_runtime(m, db); return _to_response(m)

def delete_monitor(db: Session, monitor_id: int) -> None:
    m = get_monitor(db, monitor_id); runtime_manager.stop_monitor(monitor_id); db.delete(m); db.commit()

def save_verified_url(db: Session, source: VideoSourceInput) -> None:
    row = db.scalar(select(UrlHistory).where(UrlHistory.url == source.url))
    if not row: row = UrlHistory(url=source.url or ""); db.add(row)
    row.username = source.username
    if source.password: row.encrypted_password = encrypt(source.password)
    row.last_verified_at = datetime.utcnow(); db.commit()

def list_url_history(db: Session): return db.scalars(select(UrlHistory).order_by(UrlHistory.last_verified_at.desc())).all()
def delete_url_history(db: Session, history_id: int) -> None:
    row = db.get(UrlHistory, history_id)
    if not row: raise ValueError("URL履歴が見つかりません")
    db.delete(row); db.commit()
