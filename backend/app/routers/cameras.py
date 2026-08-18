from fastapi import APIRouter
import cv2
router = APIRouter(prefix="/api/cameras", tags=["cameras"])
@router.get("")
def list_cameras():
    result = []
    backend = getattr(cv2, "CAP_DSHOW", 0)
    for index in range(5):
        cap = None
        try:
            cap = cv2.VideoCapture(index, backend) if backend else cv2.VideoCapture(index)
            if cap.isOpened(): result.append({"device_id": index, "label": f"Camera {index}"})
        finally:
            if cap is not None: cap.release()
    return {"cameras": result}
