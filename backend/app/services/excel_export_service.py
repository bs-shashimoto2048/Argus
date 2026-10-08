"""reading_records(1時間ごとの正式な計測記録)からのExcel(.xlsx)出力(UI再設計 Phase 3)。

- 1 Monitor = 1 worksheet、1ブックにまとめる。データ源はreading_recordsのみ(inference_resultsは使わない)。
- value / previous_value / usage / value_source / validation_status等はDBの値をそのまま出力する(Excel側で再判定・再計算しない)。
- ブラウザダウンロードとサーバー保存は、同じbuild_workbook()を使う。まず一時ファイル(ローカル)へ生成し、
  サーバー保存ではその後に保存先へ書き出す。生成中に保存先(UNC等)へアクセスしないため、保存先の障害は
  書き出しの段階でだけ失敗し、タイムアウト付きで諦める。
- 大量行に備え、XlsxWriterのconstant_memoryで1行ずつ書き、DBはMonitor単位・キーセットのチャンクで読む。
"""
from __future__ import annotations

import os
import re
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path, PureWindowsPath

import xlsxwriter
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from ..models import Monitor, ReadingRecord
from .csv_export_service import JST
from .reading_record_service import _base_query, _naive_utc
from .storage_settings_service import StorageTimeout, run_with_timeout

CHUNK_SIZE = 2000
MAX_SHEET_NAME = 31
# Excelは1シートあたりのハイパーリンクが65,530件まで。超えた分はパス文字列だけにする。
MAX_LINKS_PER_SHEET = 65000
# 画像ファイルの存在確認に使う合計時間の上限(秒)。UNCが遅い場合に、Excel生成を長引かせない。
LINK_CHECK_BUDGET_SECONDS = 20.0
SAVE_TIMEOUT_SECONDS = 60.0
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

HEADERS = [
    "計測日時", "Monitor ID", "Monitor名", "確定値", "前回値", "使用量", "Raw値", "信頼度",
    "validation_status", "value_source", "display_status", "baseline_conflict", "engine", "model_id",
    "元画像パス", "推論画像パス",
]
COLUMN_WIDTHS = [20, 11, 22, 14, 14, 12, 16, 10, 20, 15, 15, 17, 12, 30, 70, 70]
_COL_VALUE, _COL_PREVIOUS, _COL_USAGE, _COL_RAW, _COL_CONFIDENCE, _COL_ORIGINAL, _COL_OVERLAY = 3, 4, 5, 6, 7, 14, 15

_SHEET_FORBIDDEN = re.compile(r"[:\\/?*\[\]\x00-\x1f]")
_RESERVED_SHEET = "history"
_FILENAME_SAFE = re.compile(r"[^A-Za-z0-9_.\-]")


class ExportError(ValueError):
    """依頼内容の不正(API層で422)。"""


class NoRecordsError(Exception):
    """対象期間・Monitorに記録が無い(API層で404)。"""


@dataclass
class SheetSummary:
    monitor_id: int
    sheet_name: str
    rows: int = 0


@dataclass
class ExportSummary:
    sheets: list[SheetSummary] = field(default_factory=list)
    total_rows: int = 0
    image_links: int = 0
    image_links_skipped: bool = False  # 画像保存先に到達できず、ハイパーリンクを付けなかった


# --- 期間・ファイル名 ---

def resolve_period(period: str, start: datetime | None, end: datetime | None, now: datetime | None = None) -> tuple[datetime | None, datetime | None]:
    """期間の指定を(開始, 終了)へ解決する。終了は含まない(recorded_at < 終了)。

    today=今日(JSTの0時〜翌0時) / last_7_days=過去7日(今日を含む7暦日) / custom=from/toをそのまま使う(省略可)。
    """
    if period in ("today", "last_7_days"):
        today = (now or datetime.now(timezone.utc)).astimezone(JST).replace(hour=0, minute=0, second=0, microsecond=0)
        return today - timedelta(days=0 if period == "today" else 6), today + timedelta(days=1)
    if period != "custom":
        raise ExportError("periodはtoday / last_7_days / customのいずれかです")
    if start is not None and end is not None and start >= end:
        raise ExportError("期間が不正です(fromはtoより前にしてください)")
    return start, end


def export_filename(start: datetime | None, end: datetime | None) -> str:
    """Argus_MeterRecords_<開始日>_<終了日>.xlsx(同じ日なら1日分、期間の指定が無ければAll)。日付はJST。"""
    if start is None and end is None:
        return "Argus_MeterRecords_All.xlsx"
    first = start.astimezone(JST).strftime("%Y%m%d") if start is not None else "Begin"
    if end is None:
        last = "Latest"
    else:
        # endは含まないので、日の境界ちょうどなら前日までを表す
        last_dt = (end - timedelta(microseconds=1)).astimezone(JST)
        last = last_dt.strftime("%Y%m%d")
    return f"Argus_MeterRecords_{first}.xlsx" if first == last else f"Argus_MeterRecords_{first}_{last}.xlsx"


def safe_filename(name: str) -> str:
    stem, ext = os.path.splitext(name)
    return (_FILENAME_SAFE.sub("_", stem) or "Argus_MeterRecords") + (ext or ".xlsx")


def unique_filename(folder: Path, filename: str) -> str:
    """folder内で既存ファイルと重ならない名前(重なれば_2, _3...)。"""
    stem, ext = os.path.splitext(filename)
    candidate, counter = filename, 2
    while (folder / candidate).exists():
        candidate = f"{stem}_{counter}{ext}"
        counter += 1
    return candidate


# --- worksheet名 ---

def sanitize_sheet_name(text: str | None) -> str:
    value = _SHEET_FORBIDDEN.sub("_", text or "").strip().strip("'").strip()
    return value[:MAX_SHEET_NAME].strip().strip("'")


def unique_sheet_name(display_name: str | None, monitor_id: int, used: set[str]) -> str:
    """Excelの制約(31文字以内・禁止文字・大文字小文字を区別しない重複なし)を満たすシート名。"""
    base = sanitize_sheet_name(display_name)
    if not base or base.lower() == _RESERVED_SHEET:
        base = f"Monitor_{monitor_id}"
    name = base
    if name.lower() in used:
        suffix = f"_{monitor_id}"
        name = base[: MAX_SHEET_NAME - len(suffix)] + suffix
        counter = 2
        while name.lower() in used:
            suffix = f"_{monitor_id}_{counter}"
            name = base[: MAX_SHEET_NAME - len(suffix)] + suffix
            counter += 1
    used.add(name.lower())
    return name


# --- 画像パス ---

class ImageLinker:
    """DBの相対パス + 現在のimage_rootから実パスを構成し、存在すればハイパーリンク対象にする。

    ファイルが無い/保存先に到達できない場合でもExcel生成は続け、パス文字列だけを残す。
    """

    def __init__(self, image_root: Path | None) -> None:
        self.root = image_root
        self.reachable = False
        self.checked_seconds = 0.0
        if image_root is not None:
            try:
                self.reachable = bool(run_with_timeout(lambda: image_root.is_dir(), 5.0))
            except (StorageTimeout, OSError):
                self.reachable = False

    def resolve(self, relative: str | None) -> tuple[str | None, bool]:
        """(セルに出す文字列, ハイパーリンクにするか)。"""
        if not relative:
            return None, False
        if self.root is None:
            return relative, False
        parts = PureWindowsPath(relative.replace("/", "\\"))
        if parts.is_absolute() or parts.anchor or ".." in parts.parts:
            return relative, False  # 画像保存先の外を指すパスは、構成せずそのまま文字列で残す
        full = self.root / relative
        if not self.reachable or self.checked_seconds > LINK_CHECK_BUDGET_SECONDS:
            return str(full), False
        started = time.monotonic()
        try:
            exists = full.is_file()
        except OSError:
            exists = False
        self.checked_seconds += time.monotonic() - started
        return str(full), exists


# --- 書き込み ---

def _decimal_number(text: str | None) -> float | None:
    if text is None or text == "":
        return None
    try:
        return float(Decimal(text))
    except (InvalidOperation, ValueError):
        return None


def _to_excel_datetime(value: datetime) -> datetime:
    aware = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    return aware.astimezone(JST).replace(tzinfo=None)  # Excelの日時にはタイムゾーンが無いため、JSTの壁時計時刻で書く


def _monitor_ids_with_records(db: Session, monitor_ids: list[int] | None, start: datetime | None, end: datetime | None) -> list[int]:
    sub = _base_query(monitor_ids, start, end).subquery()
    return [row for row in db.scalars(select(sub.c.monitor_id).distinct().order_by(sub.c.monitor_id))]


def _sheet_title(db: Session, monitor_id: int, start: datetime | None, end: datetime | None) -> str | None:
    """Monitorが現存すれば現在の表示名、削除済みなら最新の記録に残る表示名。"""
    monitor = db.get(Monitor, monitor_id)
    if monitor is not None:
        return monitor.display_name
    return db.scalar(select(ReadingRecord.monitor_name).where(ReadingRecord.monitor_id == monitor_id).order_by(ReadingRecord.recorded_at.desc()).limit(1))


def _iter_chunks(db: Session, monitor_id: int, start: datetime | None, end: datetime | None):
    """1 Monitorの記録を、古い順にキーセットのチャンクで返す(全件をlistへ載せない)。"""
    last: tuple[datetime, int] | None = None
    while True:
        query = _base_query([monitor_id], start, end)
        if last is not None:
            query = query.where(or_(ReadingRecord.recorded_at > last[0], and_(ReadingRecord.recorded_at == last[0], ReadingRecord.id > last[1])))
        rows = db.scalars(query.order_by(ReadingRecord.recorded_at, ReadingRecord.id).limit(CHUNK_SIZE)).all()
        if not rows:
            return
        last = (rows[-1].recorded_at, rows[-1].id)
        yield rows
        db.expunge_all()  # 読み取り専用。チャンクごとにセッションから外し、メモリを増やさない
        if len(rows) < CHUNK_SIZE:
            return


def build_workbook(db: Session, dest: Path, monitor_ids: list[int] | None, start: datetime | None, end: datetime | None,
                   image_root: Path | None) -> ExportSummary:
    """条件に合うreading_recordsを、1 Monitor 1 worksheetのブックとしてdest(ローカルの一時ファイル)へ書く。"""
    ids = _monitor_ids_with_records(db, monitor_ids, start, end)
    if not ids:
        raise NoRecordsError("指定した条件に該当する計測記録がありません")
    linker = ImageLinker(image_root)
    summary = ExportSummary(image_links_skipped=image_root is not None and not linker.reachable)
    workbook = xlsxwriter.Workbook(str(dest), {"constant_memory": True, "default_date_format": "yyyy/mm/dd hh:mm:ss"})
    try:
        workbook.set_properties({"title": "Argus 計測記録", "comments": "reading_recordsから出力(確定値・使用量等はDBの値のまま)"})
        fmt = {
            "header": workbook.add_format({"bold": True, "bg_color": "#E8EEF4", "border": 1, "valign": "vcenter"}),
            "date": workbook.add_format({"num_format": "yyyy/mm/dd hh:mm:ss"}),
            "confidence": workbook.add_format({"num_format": "0.000"}),
            "text": workbook.add_format({"num_format": "@"}),
            "link": workbook.add_format({"font_color": "blue", "underline": 1}),
        }
        used: set[str] = set()
        for monitor_id in ids:
            sheet_name = unique_sheet_name(_sheet_title(db, monitor_id, start, end), monitor_id, used)
            sheet = SheetSummary(monitor_id, sheet_name)
            ws = workbook.add_worksheet(sheet_name)
            for col, (title, width) in enumerate(zip(HEADERS, COLUMN_WIDTHS)):
                ws.set_column(col, col, width)
                ws.write_string(0, col, title, fmt["header"])
            ws.freeze_panes(1, 0)
            row_no, links = 1, 0
            for rows in _iter_chunks(db, monitor_id, start, end):
                for record in rows:
                    links += _write_row(ws, row_no, record, fmt, linker, links)
                    row_no += 1
            sheet.rows = row_no - 1
            # constant_memoryでは範囲指定のautofilterを、行数が確定してから設定する
            ws.autofilter(0, 0, max(sheet.rows, 1), len(HEADERS) - 1)
            ws.ignore_errors({"number_stored_as_text": f"G2:G{max(sheet.rows + 1, 2)}"})
            summary.sheets.append(sheet)
            summary.total_rows += sheet.rows
            summary.image_links += links
    finally:
        workbook.close()
    return summary


def _write_row(ws, row: int, record: ReadingRecord, fmt: dict, linker: ImageLinker, links_so_far: int) -> int:
    """1行を書く。戻り値は追加したハイパーリンク数。"""
    ws.write_datetime(row, 0, _to_excel_datetime(record.recorded_at), fmt["date"])
    ws.write_number(row, 1, record.monitor_id)
    ws.write_string(row, 2, record.monitor_name or "")
    for col, text in ((_COL_VALUE, record.value), (_COL_PREVIOUS, record.previous_value), (_COL_USAGE, record.usage)):
        number = _decimal_number(text)
        if number is not None:
            ws.write_number(row, col, number)
        elif text:  # 数値として解釈できない文字列は、値を失わないよう文字列で残す
            ws.write_string(row, col, text)
    if record.raw_value is not None:
        ws.write_string(row, _COL_RAW, record.raw_value, fmt["text"])  # 先頭0を保持するため、常に文字列
    if record.confidence is not None:
        ws.write_number(row, _COL_CONFIDENCE, record.confidence, fmt["confidence"])
    for col, text in ((8, record.validation_status), (9, record.value_source), (10, record.display_status), (12, record.engine), (13, record.model_id)):
        if text is not None:
            ws.write_string(row, col, text)
    ws.write_boolean(row, 11, bool(record.baseline_conflict))
    added = 0
    for col, relative in ((_COL_ORIGINAL, record.original_image_path), (_COL_OVERLAY, record.overlay_image_path)):
        text, linkable = linker.resolve(relative)
        if text is None:
            continue
        if linkable and links_so_far + added < MAX_LINKS_PER_SHEET:
            if ws.write_url(row, col, "external:" + text, fmt["link"], string=text) == 0:
                added += 1
                continue
        ws.write_string(row, col, text)
    return added


# --- 保存 ---

def save_to_folder(source: Path, folder: Path, filename: str, create: bool = False) -> Path:
    """生成済みのブックを保存先へ書き出す。保存先が不通/遅延でもtimeout秒で諦める(例外: StorageTimeout/OSError)。

    既存ファイルは上書きしない(同名があれば連番)。排他的に作成し、書き込みに失敗したら中途半端なファイルを消す。
    """
    def work() -> Path:
        if create:
            folder.mkdir(parents=True, exist_ok=True)  # 既定の保存先(<data_dir>/exports)だけは自動作成する
        if not folder.exists():
            raise FileNotFoundError(f"Excelの保存先フォルダが見つかりません: {folder}")
        if not folder.is_dir():
            raise NotADirectoryError(f"Excelの保存先がフォルダではありません: {folder}")
        name = unique_filename(folder, filename)
        while True:
            target = folder / name
            try:
                handle = open(target, "xb")  # 排他的に作成して、同時の同名保存で上書きしない
            except FileExistsError:
                name = unique_filename(folder, filename)
                continue
            try:
                with handle, open(source, "rb") as src:
                    shutil.copyfileobj(src, handle)
            except BaseException:
                try:
                    target.unlink()
                except OSError:
                    pass
                raise
            return target

    return run_with_timeout(work, SAVE_TIMEOUT_SECONDS)
