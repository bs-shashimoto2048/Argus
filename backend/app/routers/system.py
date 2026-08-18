from fastapi import APIRouter

from ..inference.diagnostics import system_diagnostics

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/inference")
def inference_diagnostics():
    return system_diagnostics()
