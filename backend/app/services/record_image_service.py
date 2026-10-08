"""1時間記録の画像(元画像・推論オーバーレイ)の保存(UI再設計 Phase 2)。

保存先: <image_root>/<表示名>__<monitor_id>/YYYY/MM/DD/YYYYMMDD_HHMMSS_<value>_original.jpg と ..._overlay.jpg
- 日付/時刻は実際の記録時刻(recorded_at)のJST。DBには画像保存先からの相対パス(/区切り)を保存する。
- 表示名はファイルシステムの禁止文字をsanitizeする。表示名を変更しても過去のフォルダはrenameしない
  (以後の記録は新しい表示名のフォルダへ保存され、過去の記録はDBの相対パスで引き続き辿れる)。
- 保存は一時ファイルへ書いてからrenameする。既存ファイルは上書きしない(同名があれば連番)。
- 全推論フレームは保存しない(1時間記録を作ったときの1組だけ)。自動削除はしない(証跡)。
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..core.database import SessionLocal
from ..models import ReadingRecord
from .csv_export_service import JST
from .storage_settings_service import GIB, StorageConfig, existing_ancestor, free_bytes

# Windowsのパス長の上限(MAX_PATH=260)に余裕を持たせた、保存するファイルのフルパス長の上限。
MAX_FULL_PATH_LENGTH = 240
# YYYYMMDD_HHMMSS_<値32文字>_<連番>_original.jpg.tmp の最大長(余裕を含む)。
_LONGEST_FILE_NAME = 70

_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_EDGE_CHARS = re.compile(r"^[\x00-\x20.]+|[\x00-\x20.]+$")
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def sanitize_name(text: str | None, fallback: str = "monitor", max_length: int = 60) -> str:
    """表示名などを、Windowsのフォルダ名/ファイル名として安全な文字列にする。"""
    # 先頭と末尾の空白・制御文字(実データには末尾のタブがある)・ピリオドは除き、途中の禁止文字は「_」にする。
    value = _EDGE_CHARS.sub("", text or "")
    value = _INVALID_CHARS.sub("_", value)[:max_length].strip(" .")
    if not value:
        return fallback
    if value.split(".")[0].upper() in _RESERVED:
        value = "_" + value
    return value


def monitor_folder_name(display_name: str | None, monitor_id: int) -> str:
    """<表示名>__<monitor_id>。ID付きにすることで、同じ表示名のMonitorが衝突しない。"""
    return f"{sanitize_name(display_name)}__{monitor_id}"


def value_for_filename(value: str | None) -> str:
    cleaned = _INVALID_CHARS.sub("_", value or "").strip(" .")
    return cleaned[:32] if cleaned else "none"


def relative_dir(display_name: str | None, monitor_id: int, recorded_at_utc: datetime) -> str:
    jst = _to_jst(recorded_at_utc)
    return f"{monitor_folder_name(display_name, monitor_id)}/{jst:%Y}/{jst:%m}/{jst:%d}"


def file_stem(recorded_at_utc: datetime, value: str | None) -> str:
    return f"{_to_jst(recorded_at_utc):%Y%m%d_%H%M%S}_{value_for_filename(value)}"


def _to_jst(value: datetime) -> datetime:
    aware = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    return aware.astimezone(JST)


@dataclass
class ImageJob:
    record_id: int
    monitor_id: int
    monitor_name: str
    recorded_at: datetime  # naive UTC(DBのrecorded_atと同じ)
    value: str | None
    original: bytes | None
    overlay: bytes | None
    want_original: bool
    want_overlay: bool


@dataclass
class ImageResult:
    status: str  # ok / failed / dropped
    original_path: str | None = None
    overlay_path: str | None = None
    error: str | None = None
    io_failure: bool = False  # 保存先へのI/Oが失敗した(欠損データではない)。連続するとWriterが一時停止する
    free_bytes: int | None = None


def _unique_path(directory: Path, stem: str, kind: str) -> Path:
    candidate = directory / f"{stem}_{kind}.jpg"
    counter = 2
    while candidate.exists():
        candidate = directory / f"{stem}_{counter}_{kind}.jpg"
        counter += 1
    return candidate


def _write_atomic(path: Path, data: bytes) -> None:
    temp = path.with_name(path.name + ".tmp")
    try:
        with open(temp, "wb") as handle:
            handle.write(data)
        os.replace(temp, path)
    finally:
        if temp.exists():
            try:
                temp.unlink()
            except OSError:
                pass


def save_job(job: ImageJob, config: StorageConfig) -> ImageResult:
    """1件分の画像を保存する(例外は投げず、結果で返す)。"""
    root = config.image_root
    try:
        if not root.exists():
            if not config.image_root_is_default:
                return ImageResult("failed", error=f"画像保存先が見つかりません: {root}", io_failure=True)
            root.mkdir(parents=True, exist_ok=True)  # 既定の保存先(<data_dir>/images)だけは自動作成する
        free = free_bytes(root)
        if free < config.stop_free_bytes:
            return ImageResult("dropped", error=f"空き容量{free / GIB:.1f}GBが停止しきい値{config.stop_free_bytes / GIB:.1f}GB未満のため、画像を保存しませんでした", free_bytes=free)
        directory = root / relative_dir(job.monitor_name, job.monitor_id, job.recorded_at)
        # フォルダを作る前に、最長のファイル名(.tmp含む)を付けたフルパスがWindowsの上限を超えないか確認する。
        if len(str(directory)) + 1 + _LONGEST_FILE_NAME > MAX_FULL_PATH_LENGTH:
            return ImageResult("failed", error=f"保存先のパスが長すぎます({len(str(directory))}文字)。画像保存先を短いパスにしてください")
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return ImageResult("failed", error=f"保存先にアクセスできません: {exc}", io_failure=True)

    stem = file_stem(job.recorded_at, job.value)
    saved: dict[str, str] = {}
    errors: list[str] = []
    io_failure = False
    for kind, wanted, data in (("original", job.want_original, job.original), ("overlay", job.want_overlay, job.overlay)):
        if not wanted:
            continue
        if not data:
            errors.append(f"{'元画像' if kind == 'original' else '推論オーバーレイ'}を取得できませんでした(フレームなし)")
            continue
        try:
            target = _unique_path(directory, stem, kind)
            if len(str(target)) > MAX_FULL_PATH_LENGTH:
                errors.append(f"保存先のパスが長すぎます({len(str(target))}文字)。保存先を短いパスにしてください")
                continue
            _write_atomic(target, data)
            saved[kind] = target.relative_to(root).as_posix()
        except OSError as exc:
            io_failure = True
            errors.append(f"{kind}の保存に失敗しました: {exc}")
    status = "failed" if errors else "ok"
    return ImageResult(status, saved.get("original"), saved.get("overlay"), "; ".join(errors) or None, io_failure, free)


def finalize_record(record_id: int, result: ImageResult) -> None:
    """保存結果をreading_recordsへ反映する(計測値の列は変更しない)。"""
    db = SessionLocal()
    try:
        record = db.get(ReadingRecord, record_id)
        if record is None:
            return
        record.image_status = result.status
        record.original_image_path = result.original_path
        record.overlay_image_path = result.overlay_path
        record.image_error = result.error
        db.commit()
    finally:
        db.close()


def resolve_image_path(root: Path, relative: str) -> Path | None:
    """DBの相対パスを画像保存先の配下の実パスへ解決する。保存先の外を指すパスは拒否する(None)。"""
    try:
        base = root.resolve()
        target = (root / relative).resolve()
        target.relative_to(base)
    except (OSError, ValueError):
        return None
    return target


def space_state(root: Path, config: StorageConfig) -> tuple[int | None, str]:
    """(空き容量byte, 'ok'|'warning'|'stopped')。計測できなければ(None, 'ok')。"""
    try:
        free = free_bytes(existing_ancestor(root))
    except OSError:
        return None, "ok"
    if free < config.stop_free_bytes:
        return free, "stopped"
    if free < config.warn_free_bytes:
        return free, "warning"
    return free, "ok"
