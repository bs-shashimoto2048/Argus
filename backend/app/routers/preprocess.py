from io import BytesIO

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from PIL import Image

from ..schemas.preprocess import PreprocessPreviewRequest
from ..services import preprocess_service
from runtime.runtime_manager import runtime_manager

router = APIRouter(prefix="/api/monitors", tags=["preprocess"])


@router.post("/{monitor_id}/preprocess/preview")
def preview(monitor_id: int, request: PreprocessPreviewRequest):
    runtime = runtime_manager.get_runtime(monitor_id)
    if not runtime:
        raise HTTPException(409, "モニターの映像runtimeは停止中です")
    data, _ = runtime.buffer.get()
    if not data:
        raise HTTPException(503, "映像フレームをまだ取得できていません")
    try:
        image = Image.open(BytesIO(data)).convert("RGB")
        processed = preprocess_service.apply(preprocess_service.crop_roi(image, request.roi), request.settings)
        output = BytesIO()
        processed.save(output, format="JPEG", quality=90)
        return Response(output.getvalue(), media_type="image/jpeg", headers={"Cache-Control": "no-store"})
    except Exception as exc:
        raise HTTPException(422, "前処理Previewを生成できません") from exc
