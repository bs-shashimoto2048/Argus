import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.background import BackgroundTask
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..services import excel_export_service as excel
from ..services import reading_record_service as svc
from ..services.record_image_service import resolve_image_path
from ..services.storage_settings_service import StorageTimeout, excel_output_folder, load_config
from runtime.hourly_record_worker import hourly_record_worker

router = APIRouter(prefix="/api/records", tags=["records"])


class RecordSettingsInput(BaseModel):
    enabled: bool


class ExcelExportInput(BaseModel):
    """Excel出力の依頼。monitor_idsが空なら全Monitor。period=custom(既定)ではfrom/to(省略可)を使い、toは含まない。"""

    model_config = ConfigDict(populate_by_name=True)
    monitor_ids: list[int] = Field(default_factory=list)
    period: Literal["today", "last_7_days", "custom"] = "custom"
    start: str | None = Field(default=None, alias="from")
    end: str | None = Field(default=None, alias="to")
    save_to_server: bool = False  # true=設定の保存先フォルダへ保存してJSONを返す / false=ブラウザへダウンロード


_export_lock = Lock()  # Excel生成は1件ずつ(重い処理でBackendを圧迫しない)


def _period(value: str | None, name: str) -> datetime | None:
    try:
        return svc.parse_period(value)
    except ValueError as exc:
        raise HTTPException(422, f"{name}はISO 8601形式で指定してください(例: 2026-10-08T00:00:00+09:00)") from exc


@router.get("")
def list_records(
    monitor_id: list[int] = Query(default=[]),
    start: str | None = Query(default=None, alias="from"),
    end: str | None = Query(default=None, alias="to"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """1時間ごとの計測履歴(新しい順)。from/toは記録時刻(recorded_at)の期間で、タイムゾーンなしはJST。"""
    rows, total = svc.list_records(db, monitor_id or None, _period(start, "from"), _period(end, "to"), limit, offset)
    return {"items": [svc.serialize(row) for row in rows], "total": total, "limit": limit, "offset": offset}


@router.get("/status")
def records_status(db: Session = Depends(get_db)):
    """計測記録の有効/無効と、Workerの状態。"""
    return {
        "enabled": svc.hourly_records_enabled(db),
        "worker_running": hourly_record_worker.is_running(),
        "last_tick_at": svc._iso(hourly_record_worker.last_tick_at),
        "last_error": hourly_record_worker.last_error,
    }


@router.put("/settings")
def update_records_settings(body: RecordSettingsInput, db: Session = Depends(get_db)):
    svc.set_hourly_records_enabled(db, body.enabled)
    return {"enabled": svc.hourly_records_enabled(db)}


def _remove_dir(path: str) -> None:
    shutil.rmtree(path, ignore_errors=True)


@router.post("/export/excel")
def export_excel(body: ExcelExportInput, db: Session = Depends(get_db)):
    """reading_recordsからExcel(.xlsx)を出力する(1 Monitor 1 worksheet)。

    save_to_server=false: .xlsxをダウンロード / true: 設定のExcel保存先へ保存し、保存先を返す。
    このAPIの失敗は他の機能(映像・推論・Reading・定時記録・画像保存)へ影響しない。
    """
    start, end = _period(body.start, "from"), _period(body.end, "to")
    try:
        start, end = excel.resolve_period(body.period, start, end)
    except excel.ExportError as exc:
        raise HTTPException(422, str(exc)) from exc
    filename = excel.export_filename(start, end)
    if not _export_lock.acquire(blocking=False):
        raise HTTPException(409, {"code": "EXPORT_IN_PROGRESS", "message": "別のExcel出力を実行中です。完了してからやり直してください"})
    work_dir = tempfile.mkdtemp(prefix="argus_excel_")
    keep_work_dir = False
    try:
        source = Path(work_dir) / filename
        try:
            summary = excel.build_workbook(db, source, body.monitor_ids or None, start, end, load_config(db).image_root)
        except excel.NoRecordsError as exc:
            raise HTTPException(404, {"code": "NO_RECORDS", "message": str(exc)}) from exc
        sheets = [{"monitor_id": s.monitor_id, "sheet_name": s.sheet_name, "rows": s.rows} for s in summary.sheets]
        if not body.save_to_server:
            keep_work_dir = True
            return FileResponse(source, media_type=excel.XLSX_MEDIA_TYPE, filename=filename,
                                headers={"Cache-Control": "no-store", "X-Argus-Total-Rows": str(summary.total_rows)},
                                background=BackgroundTask(_remove_dir, work_dir))
        folder, is_default = excel_output_folder(db)
        try:
            saved = excel.save_to_folder(source, folder, filename, create=is_default)
        except StorageTimeout as exc:
            raise HTTPException(503, {"code": "EXPORT_SAVE_TIMEOUT", "message": f"{exc}(保存先: {folder})"}) from exc
        except OSError as exc:
            raise HTTPException(503, {"code": "EXPORT_SAVE_FAILED", "message": f"Excelを保存できませんでした: {exc}"}) from exc
        return {"saved": True, "path": str(saved), "filename": saved.name, "folder": str(folder), "size_bytes": source.stat().st_size,
                "total_rows": summary.total_rows, "sheets": sheets, "image_links": summary.image_links,
                "image_links_skipped": summary.image_links_skipped}
    finally:
        _export_lock.release()
        if not keep_work_dir:
            shutil.rmtree(work_dir, ignore_errors=True)


@router.get("/{record_id}")
def get_record(record_id: int, db: Session = Depends(get_db)):
    record = svc.get_record(db, record_id)
    if record is None:
        raise HTTPException(404, "計測記録が見つかりません")
    return svc.serialize(record)


@router.get("/{record_id}/image/{kind}")
def get_record_image(record_id: int, kind: str, db: Session = Depends(get_db)):
    """記録時に保存した画像(kind=original|overlay)。保存済みのファイルだけを返し、現在の映像は取得しない。"""
    if kind not in ("original", "overlay"):
        raise HTTPException(404, "画像の種類はoriginalまたはoverlayです")
    record = svc.get_record(db, record_id)
    if record is None:
        raise HTTPException(404, "計測記録が見つかりません")
    relative = record.original_image_path if kind == "original" else record.overlay_image_path
    if not relative:
        raise HTTPException(404, {"code": "IMAGE_NOT_SAVED", "message": record.image_error or "この記録には画像が保存されていません", "image_status": record.image_status})
    target = resolve_image_path(load_config(db).image_root, relative)
    if target is None:
        raise HTTPException(404, {"code": "IMAGE_PATH_INVALID", "message": "画像のパスが保存先の外を指しています"})
    try:
        exists = target.is_file()
    except OSError:
        exists = False
    if not exists:
        raise HTTPException(404, {"code": "IMAGE_FILE_MISSING", "message": "保存した画像ファイルが見つかりません(保存先の変更や削除、共有フォルダの不通の可能性があります)"})
    return FileResponse(target, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})
