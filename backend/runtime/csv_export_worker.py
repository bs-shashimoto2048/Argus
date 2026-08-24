"""Confirmed値CSV出力を担うBackground Worker(Issue #17)。

MonitorRuntime/InferenceScheduler(同じbackend/runtime/*)と同じEventベースの
協調停止スレッドパターンを使う。ROI/推論/ReadingStabilizer自体には一切関与せず、
Monitor.latest_result(=Confirmed値、DB上のLatestResult)を読むだけ。

本番(tick, 1時間ごとの自動実行, dedupあり)とテスト(run_test_export, 手動・
何度でも実行可、dedupなし)は、行生成/ファイル追記ロジック(csv_export_service)を
共有するが、出力先ファイル・dedupの有無が異なる別々のentry pointであり、
テスト側の実行が本番のCsvExportLog(dedup)・最終出力日時を消費/更新することはない。
"""
from __future__ import annotations

from datetime import datetime, timezone
from threading import Event, Thread

from app.core.database import SessionLocal
from app.services.csv_export_service import (
    ExportOutcome,
    export_all_monitors_for_hour,
    export_all_monitors_for_test,
    get_settings,
    hour_bucket_jst,
)

# 1時間ごとの境界を跨いだかどうかを見るための内部チェック間隔。本番の出力周期(1時間)
# 自体を変更するものではない(dedupにより同一hourでは何度tickしても1回しか書き込まれない)。
_DEFAULT_POLL_INTERVAL_SECONDS = 60.0


class CsvExportWorker:
    def __init__(self, poll_interval_seconds: float = _DEFAULT_POLL_INTERVAL_SECONDS) -> None:
        self._poll_interval = poll_interval_seconds
        self._stop = Event()
        self._thread: Thread | None = None
        self.last_tick_at: datetime | None = None
        self.last_outcomes: list[ExportOutcome] = []
        self.last_test_run_at: datetime | None = None
        self.last_test_outcomes: list[ExportOutcome] = []

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = Thread(target=self._run, name="argus-csv-export", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                # Background Workerの予期しない例外でBackend本体を落とさない。
                pass
            if self._stop.wait(self._poll_interval):
                break

    def tick(self) -> list[ExportOutcome]:
        """本番: 現在時刻(Asia/Tokyo)のhour境界に対する出力を試みる(argus_hourly_readings.csv、
        (monitor_id, hour_bucket)でdedup)。CSV出力が無効、または出力フォルダ未設定の場合は
        何もしない(Backendは落とさない)。"""
        db = SessionLocal()
        try:
            settings = get_settings(db)
            self.last_tick_at = datetime.now(timezone.utc)
            if not settings.csv_export_enabled or not settings.csv_output_folder:
                self.last_outcomes = []
                return []
            outcomes = export_all_monitors_for_hour(db, hour_bucket_jst(), settings.csv_output_folder)
            self.last_outcomes = outcomes
            return outcomes
        finally:
            db.close()

    def run_test_export(self) -> list[ExportOutcome]:
        """テスト・確認用: 1時間待たずに何度でも実行できる。argus_hourly_readings_test.csvへ
        追記するのみで、本番のCsvExportLog(dedup)・最終出力日時には一切影響しない
        (export_all_monitors_for_testはDB書込を行わない)。「CSV出力を有効にする」トグルとは
        独立に動作する(無効時でも接続確認のために実行できる)が、出力フォルダが未設定の
        場合はValueErrorを投げる。"""
        db = SessionLocal()
        try:
            settings = get_settings(db)
            if not settings.csv_output_folder:
                raise ValueError("出力フォルダが設定されていません")
            outcomes = export_all_monitors_for_test(db, hour_bucket_jst(), settings.csv_output_folder)
            self.last_test_run_at = datetime.now(timezone.utc)
            self.last_test_outcomes = outcomes
            return outcomes
        finally:
            db.close()


csv_export_worker = CsvExportWorker()
