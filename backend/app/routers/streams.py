import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, StreamingResponse

from runtime.runtime_manager import runtime_manager

router = APIRouter(prefix="/api/monitors", tags=["streams"])


def _runtime_or_404(monitor_id: int):
    runtime = runtime_manager.get_runtime(monitor_id)
    if not runtime:
        raise HTTPException(409, "モニターの映像runtimeは停止中です")
    return runtime


def _snapshot_response(monitor_id: int) -> Response:
    data, _ = _runtime_or_404(monitor_id).buffer.get()
    if not data:
        raise HTTPException(503, "映像フレームをまだ取得できていません")
    return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.get("/{monitor_id}/snapshot")
def snapshot(monitor_id: int):
    return _snapshot_response(monitor_id)


@router.get("/{monitor_id}/preview.jpg")
def preview(monitor_id: int):
    return _snapshot_response(monitor_id)


@router.get("/{monitor_id}/overlay.jpg")
def overlay(monitor_id: int):
    runtime = _runtime_or_404(monitor_id)
    scheduler = runtime.inference_scheduler
    overlay_bytes = scheduler.latest_overlay if scheduler else None
    if overlay_bytes:
        return Response(content=overlay_bytes, media_type="image/jpeg", headers={"Cache-Control": "no-store"})
    # 推論未実行・overlay未生成でも映像自体は見えるよう、通常のsnapshotへフォールバックする。
    return _snapshot_response(monitor_id)


@router.get("/{monitor_id}/inference-input.jpg")
def inference_input(monitor_id: int):
    """実際にInferenceEngineへ渡した最終推論入力画像そのものを返す(Issue #16)。

    表示用に別途再生成するのではなく、InferenceScheduler._infer_latest()が
    engine.infer()へ渡した画像バイト列(latest_inference_input)をそのまま配信する。
    """
    runtime = _runtime_or_404(monitor_id)
    scheduler = runtime.inference_scheduler
    data = scheduler.latest_inference_input if scheduler else None
    if not data:
        raise HTTPException(503, "推論入力画像をまだ取得できていません")
    return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.get("/{monitor_id}/runtime")
def runtime_diagnostics(monitor_id: int):
    diagnostics = _runtime_or_404(monitor_id).diagnostics()
    return diagnostics


def _stream_response(monitor_id: int) -> StreamingResponse:
    runtime = _runtime_or_404(monitor_id)

    def generate():
        last = None
        while runtime.state != "stopped":
            data, stamp = runtime.buffer.get()
            if data and stamp != last:
                last = stamp
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + data + b"\r\n"
            time.sleep(0.05)

    return StreamingResponse(generate(), media_type="multipart/x-mixed-replace; boundary=frame")


@router.get("/{monitor_id}/stream")
def stream(monitor_id: int):
    return _stream_response(monitor_id)


@router.get("/{monitor_id}/stream.mjpg")
def stream_mjpg(monitor_id: int):
    return _stream_response(monitor_id)
