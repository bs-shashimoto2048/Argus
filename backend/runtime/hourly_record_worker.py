"""1時間ごとの正式な計測記録(reading_records)を作るBackground Worker(UI再設計 Phase 1)。

csv_export_workerと同じEventベースの協調停止スレッド。推論/ReadingStabilizer/baselineには関与せず、
DB上のLatestResultとruntime情報を読んで記録するだけ。内部のtick間隔は計測枠の判定用で、
同じ枠(monitor_id, hour_bucket)ではUNIQUE制約により何度tickしても1件しか作られない。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from threading import Event, Thread

from app.core.database import SessionLocal
from app.services.reading_record_service import RecordOutcome, record_due

logger = logging.getLogger("argus.records")

_DEFAULT_POLL_INTERVAL_SECONDS = 30.0
# 毎時00分から_FAST_POLL_WINDOW_SECONDS秒間は、_FAST_POLL_INTERVAL_SECONDS間隔で確認する(JSTのUTC+9は毎時00分が一致する)。
_FAST_POLL_INTERVAL_SECONDS = 1.0
_FAST_POLL_WINDOW_SECONDS = 20.0


class HourlyRecordWorker:
    def __init__(self, poll_interval_seconds: float = _DEFAULT_POLL_INTERVAL_SECONDS) -> None:
        self._poll_interval = poll_interval_seconds
        self._stop = Event()
        self._thread: Thread | None = None
        self.started_at: datetime | None = None
        self.last_tick_at: datetime | None = None
        self.last_error: str | None = None
        self.last_outcomes: list[RecordOutcome] = []

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self.started_at = datetime.now(timezone.utc)
        self._thread = Thread(target=self._run, name="argus-hourly-records", daemon=True)
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
            except Exception as exc:  # Background Workerの予期しない例外でBackend本体を落とさない
                self.last_error = f"{type(exc).__name__}: {exc}"
                logger.exception("計測記録のtickに失敗しました")
            if self._stop.wait(self._next_wait()):
                break

    def _next_wait(self, now: datetime | None = None) -> float:
        """毎時00分の直後だけ短い間隔で確認する(基準時刻の前後から選ぶsnapshotの探索範囲が揃った時点で、すぐ記録するため)。"""
        now = now or datetime.now(timezone.utc)
        seconds_into_hour = now.minute * 60 + now.second
        return _FAST_POLL_INTERVAL_SECONDS if seconds_into_hour < _FAST_POLL_WINDOW_SECONDS else self._poll_interval

    def tick(self, now: datetime | None = None) -> list[RecordOutcome]:
        db = SessionLocal()
        try:
            self.last_tick_at = datetime.now(timezone.utc)
            outcomes = record_due(db, now, self.started_at)
            self.last_outcomes = outcomes
            self.last_error = None
            return outcomes
        finally:
            db.close()


hourly_record_worker = HourlyRecordWorker()
