from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ..inference.device import resolve_device
from ..models import InferenceSettings, LatestResult, Monitor, UrlHistory, VideoSource
from ..schemas.video_source import VideoSourceInput
from .secret_store import decrypt, encrypt
from .video_service import reader_config
from runtime.runtime_manager import runtime_manager


def _ensure_children(db: Session, monitor: Monitor) -> None:
    if not monitor.inference:
        monitor.inference = InferenceSettings()
    if not monitor.latest_result:
        monitor.latest_result = LatestResult()
    db.flush()


def _to_response(monitor: Monitor):
    from ..schemas.monitor import MonitorResponse

    source = None
    if monitor.source:
        source = {"source_type": monitor.source.source_type, "device_id": monitor.source.device_id, "url": monitor.source.url, "username": monitor.source.username, "has_password": bool(monitor.source.encrypted_password)}
    return MonitorResponse(id=monitor.id, name=monitor.name, display_name=monitor.display_name, location=monitor.location, enabled=monitor.enabled, status=monitor.status, created_at=monitor.created_at, updated_at=monitor.updated_at, source=source, inference=monitor.inference, current_value=monitor.latest_result.value if monitor.latest_result else None, previous_value=monitor.latest_result.previous_value if monitor.latest_result else None, confidence=monitor.latest_result.confidence if monitor.latest_result else None, last_updated=monitor.latest_result.timestamp if monitor.latest_result else None, inference_status=monitor.latest_result.status if monitor.latest_result else "disabled", last_inference_error=monitor.latest_result.last_error if monitor.latest_result else None)


def _build_inference_settings(inference: InferenceSettings | None) -> dict | None:
    if not inference:
        return None
    return {"method": inference.method, "engine": inference.engine, "model_id": inference.model_id, "device": inference.device, "video_fps": inference.video_fps, "inference_fps": inference.inference_fps, "confidence": inference.confidence, "iou": inference.iou, "image_size": inference.image_size, "preprocessing": inference.preprocessing, "roi": inference.roi, "reading": inference.reading, "engine_options": inference.engine_options}


def restart_runtime(monitor: Monitor, db: Session) -> None:
    """稼働中Monitorの映像/推論Runtimeを最新設定で再構成する(source変更・enabled切替を含む)。

    VideoReaderからの再接続を伴うため、source(URL/認証情報等)やenabledが変わった
    可能性がある場合に使う。ROIなど推論設定だけの変更には restart_inference_only()
    を使うこと(Issue #16: 不要な再接続で実カメラへの接続が失敗する回帰があったため)。

    PATCH /api/monitors/{id} だけでなく、ROI PUTなど設定を部分更新する
    他のRouterからも呼び出せるよう公開関数にしている。
    """
    if monitor.enabled and monitor.source:
        password = decrypt(monitor.source.encrypted_password)
        fps = monitor.inference.video_fps if monitor.inference else 15.0
        inference_settings = _build_inference_settings(monitor.inference)
        runtime_manager.start_monitor(monitor.id, reader_config(VideoSourceInput(source_type=monitor.source.source_type, device_id=monitor.source.device_id, url=monitor.source.url, username=monitor.source.username), password, fps, inference_settings))
    else:
        runtime_manager.stop_monitor(monitor.id)


def restart_inference_only(monitor: Monitor, db: Session) -> None:
    """推論設定(ROI/preprocessing/model/confidence等)だけを更新する場合に使う。

    稼働中のVideoReader/VideoCapture接続には触れず、InferenceSchedulerだけを
    差し替える(source/enabledは一切変更しない)。対象MonitorのRuntimeがまだ
    起動していない場合は、通常のrestart_runtime()(source込みのフル起動)へ
    フォールバックする。
    """
    if not (monitor.enabled and monitor.source):
        restart_runtime(monitor, db)
        return
    fps = monitor.inference.video_fps if monitor.inference else 15.0
    inference_settings = _build_inference_settings(monitor.inference)
    if not runtime_manager.update_inference_settings(monitor.id, fps, inference_settings):
        restart_runtime(monitor, db)


def list_monitors(db: Session):
    rows = db.scalars(select(Monitor).options(joinedload(Monitor.source), joinedload(Monitor.inference), joinedload(Monitor.latest_result)).order_by(Monitor.id)).unique().all()
    return [_to_response(monitor) for monitor in rows]


def get_monitor(db: Session, monitor_id: int) -> Monitor:
    monitor = db.scalar(select(Monitor).options(joinedload(Monitor.source), joinedload(Monitor.inference), joinedload(Monitor.latest_result)).where(Monitor.id == monitor_id))
    if not monitor:
        raise ValueError("モニターが見つかりません")
    _ensure_children(db, monitor)
    return monitor


def create_monitor(db: Session, req):
    if db.scalar(select(Monitor).where(Monitor.name == req.name)):
        raise ValueError("モニター名は既に使用されています")
    monitor = Monitor(name=req.name, display_name=req.display_name, location=req.location)
    monitor.inference = InferenceSettings()
    monitor.latest_result = LatestResult()
    db.add(monitor)
    db.commit()
    return _to_response(get_monitor(db, monitor.id))


def update_monitor(db: Session, monitor_id: int, req):
    monitor = get_monitor(db, monitor_id)
    data = req.model_dump(exclude_unset=True)
    source_data = data.pop("source", None)
    inference_data = data.pop("inference", None)
    for key, value in data.items():
        setattr(monitor, key, value)
    if source_data is not None:
        if source_data.get("source_type") == "url" and not (source_data.get("url") or "").strip():
            raise ValueError("URLを入力してください")
        if not monitor.source:
            monitor.source = VideoSource()
        for key in ("source_type", "device_id", "url", "username"):
            if key in source_data:
                setattr(monitor.source, key, source_data[key])
        if source_data.get("password"):
            monitor.source.encrypted_password = encrypt(source_data["password"])
        elif source_data.get("history_id"):
            history = db.get(UrlHistory, source_data["history_id"])
            if history and history.encrypted_password:
                monitor.source.encrypted_password = history.encrypted_password
    if inference_data is not None:
        if "device" in inference_data:
            try:
                resolve_device(inference_data["device"])
            except ValueError as exc:
                raise ValueError(f"DEVICE_UNAVAILABLE: {exc}") from exc
        for key, value in inference_data.items():
            if key in {"roi", "preprocessing", "reading"} and hasattr(value, "model_dump"):
                value = value.model_dump()
            setattr(monitor.inference, key, value)
    monitor.updated_at = datetime.utcnow()
    db.commit()
    monitor = get_monitor(db, monitor_id)
    # source(URL/認証情報等)やenabledが変わっていなければ、VideoReaderを再接続せず
    # 推論設定だけを差し替える(Issue #16: 不要な再接続による接続失敗を避ける)。
    if source_data is None and "enabled" not in data:
        restart_inference_only(monitor, db)
    else:
        restart_runtime(monitor, db)
    return _to_response(monitor)


def delete_monitor(db: Session, monitor_id: int) -> None:
    monitor = get_monitor(db, monitor_id)
    runtime_manager.stop_monitor(monitor_id)
    db.delete(monitor)
    db.commit()


def save_verified_url(db: Session, source: VideoSourceInput) -> None:
    row = db.scalar(select(UrlHistory).where(UrlHistory.url == source.url))
    if not row:
        row = UrlHistory(url=source.url or "")
        db.add(row)
    row.username = source.username
    if source.password:
        row.encrypted_password = encrypt(source.password)
    row.last_verified_at = datetime.utcnow()
    db.commit()


def list_url_history(db: Session):
    return db.scalars(select(UrlHistory).order_by(UrlHistory.last_verified_at.desc())).all()


def delete_url_history(db: Session, history_id: int) -> None:
    row = db.get(UrlHistory, history_id)
    if not row:
        raise ValueError("URL履歴が見つかりません")
    db.delete(row)
    db.commit()
