from fastapi import APIRouter

from ..core.config import settings
from ..inference.diagnostics import system_diagnostics
from ..inference.model_catalog import load_registry

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/inference")
def inference_diagnostics():
    return system_diagnostics()


@router.get("/models")
def list_models():
    """data/models/registry.jsonのModel Catalogを返す(role/精度要約/推奨設定等)。"""
    return {"models": load_registry(settings.data_dir / "models")}
