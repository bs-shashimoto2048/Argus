from fastapi import APIRouter
router = APIRouter(prefix="/api", tags=["health"])
@router.get("/health")
def health(): return {"status": "ok", "app": "Argus", "version": "0.1.0"}
