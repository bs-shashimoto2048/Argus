from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session
import time
from ..core.database import get_db
from runtime.runtime_manager import runtime_manager
router = APIRouter(prefix="/api/monitors", tags=["streams"])

def _runtime_or_404(monitor_id: int):
    runtime = runtime_manager.get_runtime(monitor_id)
    if not runtime: raise HTTPException(409, "モニターの映像runtimeは停止中です")
    return runtime

@router.get("/{monitor_id}/snapshot")
def snapshot(monitor_id: int):
    data, _ = _runtime_or_404(monitor_id).buffer.get()
    if not data: raise HTTPException(503, "映像フレームをまだ取得できていません")
    return Response(content=data, media_type="image/jpeg")

@router.get("/{monitor_id}/stream")
def stream(monitor_id: int):
    runtime = _runtime_or_404(monitor_id)
    def generate():
        last = None
        while True:
            data, stamp = runtime.buffer.get()
            if data and stamp != last:
                last = stamp
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + data + b"\r\n"
            time.sleep(0.05)
    return StreamingResponse(generate(), media_type="multipart/x-mixed-replace; boundary=frame")
