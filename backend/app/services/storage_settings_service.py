"""データ保存設定(画像保存先・Excel保存先・保存ON/OFF・空き容量しきい値)と、保存先のテスト(UI再設計 Phase 2)。

保存先はWindowsのローカルパスとUNC(\\\\server\\share\\...)を想定する。保存先の障害(不通・遅延・容量不足)で
Backend全体(推論/Reading/DB記録)を止めないため、保存先へのアクセスはタイムアウト付きの別スレッドで行う。
"""
from __future__ import annotations

import os
import re
import shutil
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, TypeVar

from sqlalchemy.orm import Session

from ..core.config import settings as app_settings
from .csv_export_service import get_settings

GIB = 1024 ** 3
DEFAULT_WARN_FREE_GB = 10.0
DEFAULT_STOP_FREE_GB = 5.0
# 保存先の確認(書き込みテスト/空き容量の取得)を待つ最大秒数。UNCの不通でAPIが固まらないようにする。
PROBE_TIMEOUT_SECONDS = 10.0

_UNC = re.compile(r"^\\\\[^\\/]+[\\/][^\\/]+")
_CONTROL = re.compile(r"[\x00-\x1f]")

T = TypeVar("T")


class StorageSettingsError(ValueError):
    """設定値の不正(API層で422へ変換する)。"""


class StorageTimeout(Exception):
    pass


def default_image_root() -> Path:
    return (app_settings.data_dir / "images").resolve()


@dataclass(frozen=True)
class StorageConfig:
    """保存処理が1回ごとに参照する設定のスナップショット。"""

    image_root: Path  # 実際に使う画像保存先(未設定ならdefault_image_root)
    image_root_is_default: bool
    save_original: bool
    save_overlay: bool
    warn_free_bytes: int
    stop_free_bytes: int

    @property
    def enabled(self) -> bool:
        return self.save_original or self.save_overlay


def validate_folder(text: str | None) -> str | None:
    """保存先フォルダの文字列を検証する(空はNone=未設定)。絶対パス(ドライブ付き/UNC)のみ受け付ける。"""
    value = (text or "").strip()
    if not value:
        return None
    if _CONTROL.search(value):
        raise StorageSettingsError("保存先に使用できない文字が含まれています")
    if not (os.path.isabs(value) or _UNC.match(value)):
        raise StorageSettingsError(r"保存先は絶対パス(例: D:\data\images または \\server\share\argus)で指定してください")
    if ".." in re.split(r"[\\/]+", value):
        raise StorageSettingsError("保存先に「..」は使用できません")
    return value


def load_config(db: Session) -> StorageConfig:
    row = get_settings(db)
    configured = (row.image_root_folder or "").strip()
    warn = row.storage_warn_free_gb if row.storage_warn_free_gb is not None else DEFAULT_WARN_FREE_GB
    stop = row.storage_stop_free_gb if row.storage_stop_free_gb is not None else DEFAULT_STOP_FREE_GB
    return StorageConfig(
        image_root=Path(configured) if configured else default_image_root(),
        image_root_is_default=not configured,
        save_original=bool(row.save_original_image) if row.save_original_image is not None else True,
        save_overlay=bool(row.save_overlay_image) if row.save_overlay_image is not None else True,
        warn_free_bytes=int(warn * GIB),
        stop_free_bytes=int(stop * GIB),
    )


def serialize(db: Session) -> dict:
    row = get_settings(db)
    config = load_config(db)
    return {
        "image_root_folder": (row.image_root_folder or "").strip() or None,
        "effective_image_root": str(config.image_root),
        "excel_output_folder": (row.excel_output_folder or "").strip() or None,
        "save_original_image": config.save_original,
        "save_overlay_image": config.save_overlay,
        "storage_warn_free_gb": row.storage_warn_free_gb if row.storage_warn_free_gb is not None else DEFAULT_WARN_FREE_GB,
        "storage_stop_free_gb": row.storage_stop_free_gb if row.storage_stop_free_gb is not None else DEFAULT_STOP_FREE_GB,
    }


_UNSET = object()


def update(db: Session, *, image_root_folder=_UNSET, excel_output_folder=_UNSET, save_original_image=_UNSET, save_overlay_image=_UNSET,
           storage_warn_free_gb=_UNSET, storage_stop_free_gb=_UNSET) -> dict:
    """指定された項目だけを更新する。不正な値はStorageSettingsError。"""
    row = get_settings(db)
    new_warn = row.storage_warn_free_gb if row.storage_warn_free_gb is not None else DEFAULT_WARN_FREE_GB
    new_stop = row.storage_stop_free_gb if row.storage_stop_free_gb is not None else DEFAULT_STOP_FREE_GB
    if storage_warn_free_gb is not _UNSET:
        new_warn = float(storage_warn_free_gb)
    if storage_stop_free_gb is not _UNSET:
        new_stop = float(storage_stop_free_gb)
    if new_warn < 0 or new_stop < 0:
        raise StorageSettingsError("空き容量のしきい値は0以上で指定してください")
    if new_stop > new_warn:
        raise StorageSettingsError("停止しきい値は警告しきい値以下にしてください")
    image_root = validate_folder(image_root_folder) if image_root_folder is not _UNSET else _UNSET
    excel_folder = validate_folder(excel_output_folder) if excel_output_folder is not _UNSET else _UNSET
    if image_root is not _UNSET:
        row.image_root_folder = image_root
    if excel_folder is not _UNSET:
        row.excel_output_folder = excel_folder
    if save_original_image is not _UNSET:
        row.save_original_image = bool(save_original_image)
    if save_overlay_image is not _UNSET:
        row.save_overlay_image = bool(save_overlay_image)
    row.storage_warn_free_gb, row.storage_stop_free_gb = new_warn, new_stop
    db.commit()
    return serialize(db)


# --- 保存先へのアクセス(タイムアウト付き) ---

def run_with_timeout(func: Callable[[], T], timeout: float = PROBE_TIMEOUT_SECONDS) -> T:
    """ブロックし得る処理(UNCの不通など)を別スレッドで実行し、timeout秒で諦める。"""
    box: dict = {}

    def target() -> None:
        try:
            box["value"] = func()
        except BaseException as exc:  # noqa: BLE001 - 呼び出し元へそのまま伝える
            box["error"] = exc

    thread = threading.Thread(target=target, name="argus-storage-probe", daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        raise StorageTimeout(f"保存先の応答が{timeout:.0f}秒以内にありませんでした")
    if "error" in box:
        raise box["error"]
    return box["value"]


def existing_ancestor(path: Path) -> Path:
    current = path
    while not current.exists():
        if current.parent == current:
            break
        current = current.parent
    return current


def free_bytes(path: Path) -> int:
    """pathの属するボリュームの空き容量(byte)。pathが未作成なら、存在する親で計測する。"""
    return shutil.disk_usage(existing_ancestor(path)).free


def probe_folder(path_text: str | None) -> dict:
    """保存先の書き込みテスト(一時ファイルの作成と削除)。結果はdictで返す(例外にしない)。"""
    try:
        value = validate_folder(path_text)
    except StorageSettingsError as exc:
        return {"ok": False, "path": path_text, "message": str(exc), "free_gb": None}
    if value is None:
        return {"ok": False, "path": None, "message": "保存先が指定されていません", "free_gb": None}
    folder = Path(value)

    def work() -> dict:
        if not folder.exists():
            return {"ok": False, "path": value, "message": "フォルダが見つかりません(UNCの場合は共有名・権限・ネットワークを確認してください)", "free_gb": None}
        if not folder.is_dir():
            return {"ok": False, "path": value, "message": "指定したパスはフォルダではありません", "free_gb": None}
        probe = folder / f".argus_write_test_{uuid.uuid4().hex[:8]}"
        probe.write_bytes(b"argus")
        probe.unlink()
        return {"ok": True, "path": value, "message": "書き込みできました", "free_gb": round(free_bytes(folder) / GIB, 2)}

    try:
        return run_with_timeout(work)
    except StorageTimeout as exc:
        return {"ok": False, "path": value, "message": str(exc), "free_gb": None}
    except OSError as exc:
        return {"ok": False, "path": value, "message": f"書き込みに失敗しました: {exc}", "free_gb": None}
