from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..services import storage_settings_service as svc
from ..services.record_image_service import space_state
from runtime.record_writer import record_writer

router = APIRouter(prefix="/api/system/data-storage", tags=["data-storage"])


class DataStorageInput(BaseModel):
    """指定した項目だけを更新する(未指定の項目は変更しない)。保存先の空文字は「未設定」。"""

    image_root_folder: str | None = None
    excel_output_folder: str | None = None
    save_original_image: bool | None = None
    save_overlay_image: bool | None = None
    storage_warn_free_gb: float | None = None
    storage_stop_free_gb: float | None = None


class StorageTestInput(BaseModel):
    target: str = "image"  # image / excel
    path: str | None = None  # 未指定なら、現在の設定(画像は実効の保存先)を試す


@router.get("")
def get_data_storage(db: Session = Depends(get_db)):
    return svc.serialize(db)


@router.put("")
def put_data_storage(body: DataStorageInput, db: Session = Depends(get_db)):
    fields = {name: getattr(body, name) for name in body.model_fields_set}
    try:
        return svc.update(db, **fields)
    except svc.StorageSettingsError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/test")
def test_data_storage(body: StorageTestInput, db: Session = Depends(get_db)):
    """保存先の書き込みテスト(一時ファイルの作成と削除)と、空き容量の確認。結果は常に200で返す(ok=falseで失敗理由)。"""
    if body.target not in ("image", "excel"):
        raise HTTPException(422, "targetはimageまたはexcelです")
    path = body.path
    if path is None:
        row = svc.serialize(db)
        path = row["effective_image_root"] if body.target == "image" else row["effective_excel_output_folder"]
        if body.target == "excel" and row["excel_output_folder"] is None:
            try:  # 既定のExcel保存先(<data_dir>/exports)だけは、画像の既定と同様に自動作成する
                svc.run_with_timeout(lambda: svc.default_excel_root().mkdir(parents=True, exist_ok=True), 5.0)
            except (svc.StorageTimeout, OSError):
                pass
    return svc.probe_folder(path)


@router.get("/status")
def data_storage_status(db: Session = Depends(get_db)):
    """画像保存の状態(UIの警告用)。保存先の不通・遅延・容量不足でも、この応答自体は固まらない。"""
    config = svc.load_config(db)
    writer = record_writer.status()
    free, space = None, "ok"
    try:
        free, space = svc.run_with_timeout(lambda: space_state(config.image_root, config), 5.0)
    except (svc.StorageTimeout, OSError):
        space = "unreachable"
    if not config.enabled:
        state = "disabled"
    elif space == "unreachable" or writer["circuit_open"]:
        state = "failing"
    elif space == "stopped":
        state = "stopped"
    elif writer["counts"].get("failed", 0) > 0 and writer["last_error_at"] and writer["last_success_at"] is None:
        state = "failing"
    elif space == "warning":
        state = "warning"
    else:
        state = "ok"
    return {
        "state": state,
        "image_root": str(config.image_root),
        "image_root_is_default": config.image_root_is_default,
        "save_original_image": config.save_original,
        "save_overlay_image": config.save_overlay,
        "free_gb": round(free / svc.GIB, 2) if free is not None else None,
        "warn_free_gb": round(config.warn_free_bytes / svc.GIB, 2),
        "stop_free_gb": round(config.stop_free_bytes / svc.GIB, 2),
        "space": space,
        **writer,
    }
