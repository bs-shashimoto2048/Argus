"""Confirmed値CSV出力(Issue #17)。

出力対象は常にConfirmed(安定化済み)値 = Monitor.latest_result.value であり、
Raw値は出力しない。decimal_position等の小数点整形はReadingStabilizer/
canonical_value(backend/reading/canonicalizer.py)が既に確定値へ適用済みのため、
ここでは値の再計算・再整形を一切行わない(既存仕様の重複実装を避ける)。
ROI/前処理/InferenceEngine/ReadingStabilizer自体には一切触れない。

ファイルは本番用/テスト用の2つの固定名のみで、いずれも同一フォルダへの
追記(append)方式(Issue #17最新コメントによる変更):
    本番: argus_hourly_readings.csv   (1時間ごと、(monitor_id, hour_bucket)でdedup)
    テスト: argus_hourly_readings_test.csv (dedupなし、何度でも追記可能。
             本番のCsvExportLog(dedup)・最終出力日時には一切影響しない)
row生成ロジック(_build_row)は本番/テストで共通。

JSTは常にUTC+9固定オフセットとして扱う(日本はDSTが無いため、zoneinfoの
Asia/Tokyoデータベース依存(Windows環境ではtzdata追加パッケージが必要になる)を
避けられる。これは近似ではなく、日本時間として厳密に正しい)。
"""
from __future__ import annotations

import csv
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from ..models import CsvExportLog, Monitor, SystemSettings

JST = timezone(timedelta(hours=9))

CSV_HEADER = ["timestamp_jst", "monitor_id", "monitor_name", "display_name", "confirmed_value", "confidence", "status", "engine", "model_id"]

# 本番/テストで出力先フォルダは共通(SystemSettings.csv_output_folder)だが、
# ファイル名を分けることで同じフォルダへ両方追記できるようにする。
CSV_FILENAME_PRODUCTION = "argus_hourly_readings.csv"
CSV_FILENAME_TEST = "argus_hourly_readings_test.csv"

_SETTINGS_ROW_ID = 1

# Backendは単一プロセスで動作するため、OSファイルロックではなくthreading.Lockで
# 十分(1時間ごとの本番Worker tickと、ユーザーが手動で押す「テスト出力」ボタンが
# 同時に走っても、同一ファイルへの追記(header判定+書込)がインターリーブして
# 壊れないようにする)。本番/テストで別ファイルだが、簡潔さのため共通の1つのLockで
# すべてのCSV追記処理を直列化する(書込頻度は低いため性能上の問題にならない)。
_write_lock = threading.Lock()


class CsvExportError(Exception):
    """1 Monitor分のCSV出力に失敗した(Backend/Runtime全体には影響させない)。"""


@dataclass
class ExportOutcome:
    monitor_id: int
    display_name: str
    status: str  # "written" | "skipped_already_exported" | "error"
    detail: str | None = None


def hour_bucket_jst(dt: datetime | None = None) -> datetime:
    """指定時刻(未指定なら現在時刻)をAsia/Tokyo(UTC+9)基準の「時」境界へ切り詰めて返す
    (tz-aware datetime、分/秒/マイクロ秒は0)。dtがtz-naiveな場合はUTCとして扱う。"""
    now = dt if dt is not None else datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now_jst = now.astimezone(JST)
    return now_jst.replace(minute=0, second=0, microsecond=0)


def get_settings(db: Session) -> SystemSettings:
    row = db.get(SystemSettings, _SETTINGS_ROW_ID)
    if row is None:
        row = SystemSettings(id=_SETTINGS_ROW_ID, csv_export_enabled=False, csv_output_folder=None)
        db.add(row)
        db.commit()
    return row


def update_settings(db: Session, *, enabled: bool, output_folder: str | None) -> SystemSettings:
    row = get_settings(db)
    row.csv_export_enabled = enabled
    row.csv_output_folder = (output_folder or "").strip() or None
    db.commit()
    return row


def latest_export_log_by_monitor(db: Session) -> dict[int, CsvExportLog]:
    """Monitorごとの最新(最も新しいhour_bucketの)本番出力成功ログを返す。
    テスト出力(export_monitor_for_test)はCsvExportLogへ一切書き込まないため、
    ここにはテスト出力の影響は含まれない。"""
    rows = db.query(CsvExportLog).order_by(CsvExportLog.monitor_id, CsvExportLog.hour_bucket.desc()).all()
    result: dict[int, CsvExportLog] = {}
    for row in rows:
        if row.monitor_id not in result:
            result[row.monitor_id] = row
    return result


def format_timestamp_jst_for_csv(hour_bucket: datetime) -> str:
    """CSVのtimestamp_jst列用の表記(Excel等で確認しやすい"YYYY/MM/DD HH:mm:ss")。

    hour_bucket_jst()が返すdatetimeは既にJST(UTC+9)のtz-aware値のため、そのまま
    strftimeするだけで正しいJSTの日時が得られる(タイムゾーン変換はここでは行わない)。
    dedup key(CsvExportLog.hour_bucket)やAPIのlast_exported_hour等、CSV以外で
    使うhour_bucketの内部表現(ISO 8601)はこの関数の影響を受けない
    (hour_bucket.isoformat()は他の場所で別途使用し続ける)。
    """
    return hour_bucket.strftime("%Y/%m/%d %H:%M:%S")


def _build_row(monitor: Monitor, hour_bucket: datetime) -> list[str]:
    """本番/テストで共通のrow生成ロジック。credential/URL等は一切含めない。"""
    latest = monitor.latest_result
    confirmed_value = latest.value if latest and latest.value is not None else ""
    confidence = "" if not latest or latest.confidence is None else f"{latest.confidence:.4f}"
    status = latest.status if latest else "disabled"
    engine = latest.engine if latest and latest.engine else ""
    model_id = monitor.inference.model_id if monitor.inference and monitor.inference.model_id else ""
    return [format_timestamp_jst_for_csv(hour_bucket), str(monitor.id), monitor.name, monitor.display_name, confirmed_value, confidence, status, engine, model_id]


def _append_csv_row(output_folder: str, filename: str, row: list[str]) -> None:
    """1行をfilenameへ追記する(header未書込のファイルには初回のみheaderを書く)。
    排他(_write_lock)により、header判定から書込までを1つの操作として直列化する。
    """
    folder = Path(output_folder)
    if not folder.is_dir():
        raise CsvExportError(f"出力フォルダが見つかりません: {output_folder}")
    path = folder / filename
    with _write_lock:
        try:
            is_new = not path.exists() or path.stat().st_size == 0
            with open(path, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                if is_new:
                    writer.writerow(CSV_HEADER)
                writer.writerow(row)
        except OSError as exc:
            raise CsvExportError(f"CSV書込に失敗しました({path}): {exc}") from exc


def export_monitor_for_hour(db: Session, monitor: Monitor, hour_bucket: datetime, output_folder: str) -> ExportOutcome:
    """本番: 指定Monitor・指定hour境界の出力を1回だけ行う(同一hourは二重出力しない)。
    argus_hourly_readings.csvへ追記する。

    dedup方式: (monitor_id, hour_bucket)にUNIQUE制約のあるCsvExportLogへ先に
    「予約」行をINSERT/commitし、それが成功した場合だけファイルへ書き込む。
    既に同じhourの行が存在する場合はIntegrityErrorとなり、書込自体を行わず
    SKIPを返す(Backend再起動後の再実行でも同じDBを見るため二重出力しない)。
    ファイル書込に失敗した場合は予約行を削除し、次回tick(同一hour内)で
    再試行できるようにする(出力エラーがそのhourを「出力済み」として固定しない
    = CsvExportLogだけが残る不整合を避ける)。
    """
    hour_key = hour_bucket.isoformat()
    log = CsvExportLog(monitor_id=monitor.id, hour_bucket=hour_key)
    db.add(log)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return ExportOutcome(monitor.id, monitor.display_name, "skipped_already_exported")
    try:
        _append_csv_row(output_folder, CSV_FILENAME_PRODUCTION, _build_row(monitor, hour_bucket))
    except CsvExportError as exc:
        db.delete(log)
        db.commit()
        return ExportOutcome(monitor.id, monitor.display_name, "error", str(exc))
    return ExportOutcome(monitor.id, monitor.display_name, "written")


def export_all_monitors_for_hour(db: Session, hour_bucket: datetime, output_folder: str) -> list[ExportOutcome]:
    """本番: 全Monitorについて、指定hour境界のCSV出力を試みる。1台の失敗が他Monitorや
    Backend全体に影響しないよう、Monitorごとに例外を握り込む。"""
    monitors = db.query(Monitor).options(joinedload(Monitor.latest_result), joinedload(Monitor.inference)).order_by(Monitor.id).all()
    outcomes: list[ExportOutcome] = []
    for monitor in monitors:
        try:
            outcomes.append(export_monitor_for_hour(db, monitor, hour_bucket, output_folder))
        except Exception as exc:  # 予期しない例外でも他Monitor・Backend全体を落とさない
            db.rollback()
            outcomes.append(ExportOutcome(monitor.id, monitor.display_name, "error", str(exc)))
    return outcomes


def export_monitor_for_test(monitor: Monitor, hour_bucket: datetime, output_folder: str) -> ExportOutcome:
    """テスト用: dedupなし。何度でもargus_hourly_readings_test.csvへ追記できる。
    DBへの書込を一切行わないため、本番のCsvExportLog(dedup)・最終出力日時には
    一切影響しない。"""
    try:
        _append_csv_row(output_folder, CSV_FILENAME_TEST, _build_row(monitor, hour_bucket))
    except CsvExportError as exc:
        return ExportOutcome(monitor.id, monitor.display_name, "error", str(exc))
    return ExportOutcome(monitor.id, monitor.display_name, "written")


def export_all_monitors_for_test(db: Session, hour_bucket: datetime, output_folder: str) -> list[ExportOutcome]:
    """テスト用: 全Monitorについてargus_hourly_readings_test.csvへ追記する(dedupなし、
    本番のCsvExportLogは一切更新しない、読み取り専用のMonitor一覧取得のみ行う)。"""
    monitors = db.query(Monitor).options(joinedload(Monitor.latest_result), joinedload(Monitor.inference)).order_by(Monitor.id).all()
    outcomes: list[ExportOutcome] = []
    for monitor in monitors:
        try:
            outcomes.append(export_monitor_for_test(monitor, hour_bucket, output_folder))
        except Exception as exc:
            outcomes.append(ExportOutcome(monitor.id, monitor.display_name, "error", str(exc)))
    return outcomes
