from fastapi import APIRouter
import cv2

from runtime.runtime_manager import runtime_manager

router = APIRouter(prefix="/api/cameras", tags=["cameras"])


@router.get("")
def list_cameras():
    """接続済みローカルカメラを列挙する。

    Issue #14調査: 稼働中のMonitorRuntimeが既に使用しているdevice_idを実際に
    open/closeで再probeすると、同一device二重openによる競合(read失敗の連発・
    reconnect storm、実機DSHOWドライバでは native crashの引き金になり得る)が
    再現することを確認した。稼働中のdeviceは実際にはopenせず「使用中」として
    そのまま返すことで、この自己衝突を避ける。
    """
    in_use = runtime_manager.active_local_camera_devices()
    result = []
    backend = getattr(cv2, "CAP_DSHOW", 0)
    for index in range(5):
        if index in in_use:
            result.append({"device_id": index, "label": f"Camera {index}（使用中）"})
            continue
        cap = None
        try:
            cap = cv2.VideoCapture(index, backend) if backend else cv2.VideoCapture(index)
            if cap.isOpened():
                result.append({"device_id": index, "label": f"Camera {index}"})
        finally:
            if cap is not None:
                cap.release()
    return {"cameras": result}
