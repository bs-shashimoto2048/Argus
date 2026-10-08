"""1時間記録の画像を保存するBackground Writer(UI再設計 Phase 2)。

推論スレッド/計測記録のDB保存とは独立した専用スレッド+有限キューで画像を書く。保存先(特にUNC共有)が
遅い・不通・容量不足でも、推論・Reading・計測値のDB記録は止まらない。保存に失敗した画像は、
reading_recordsの`image_status`(failed/dropped)と`image_error`に残る。

- キューが満杯なら新しいジョブはその場で`dropped`にする。
- 保存先I/Oの失敗が連続したら、一定時間は保存を試みず`dropped`にして(サーキットブレーカー)、保存先の復旧後に自動再開する。
- 書き込み中のジョブが長引いている場合は、その経過時間を状態として公開する(UIの警告用)。
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread

from app.core.database import SessionLocal
from app.services.record_image_service import ImageJob, ImageResult, finalize_record, save_job
from app.services.storage_settings_service import load_config

logger = logging.getLogger("argus.record_writer")

_QUEUE_SIZE = 64
# 保存先I/Oの失敗がこの回数連続したら、_CIRCUIT_OPEN_SECONDS秒間は保存を試みない。
_CIRCUIT_FAILURES = 3
_CIRCUIT_OPEN_SECONDS = 60.0


class RecordWriter:
    def __init__(self, queue_size: int = _QUEUE_SIZE) -> None:
        self._queue: Queue[ImageJob] = Queue(maxsize=queue_size)
        self._stop = Event()
        self._thread: Thread | None = None
        self._lock = Lock()
        self._consecutive_io_failures = 0
        self._circuit_open_until = 0.0
        self.counts = {"ok": 0, "failed": 0, "dropped": 0}
        self.last_success_at: datetime | None = None
        self.last_error: str | None = None
        self.last_error_at: datetime | None = None
        self.last_free_bytes: int | None = None
        self.working_since: float | None = None  # 書き込み中のジョブの開始(monotonic)

    # --- 制御 ---

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = Thread(target=self._run, name="argus-record-writer", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def submit(self, job: ImageJob) -> bool:
        """ジョブをキューへ入れる。満杯ならFalse(呼び出し側が`dropped`として記録する)。"""
        try:
            self._queue.put_nowait(job)
            return True
        except Full:
            self._count("dropped", "画像保存のキューが満杯のため、画像を保存しませんでした")
            return False

    # --- 状態 ---

    def status(self) -> dict:
        now = time.monotonic()
        with self._lock:
            return {
                "worker_running": self.is_running(),
                "queue_length": self._queue.qsize(),
                "writing_seconds": round(now - self.working_since, 1) if self.working_since is not None else None,
                "circuit_open": now < self._circuit_open_until,
                "counts": dict(self.counts),
                "last_success_at": self.last_success_at.isoformat().replace("+00:00", "Z") if self.last_success_at else None,
                "last_error": self.last_error,
                "last_error_at": self.last_error_at.isoformat().replace("+00:00", "Z") if self.last_error_at else None,
                "last_free_bytes": self.last_free_bytes,
            }

    def _count(self, status: str, error: str | None = None) -> None:
        with self._lock:
            self.counts[status] = self.counts.get(status, 0) + 1
            if error and status != "ok":
                self.last_error = error
                self.last_error_at = datetime.now(timezone.utc)

    # --- 処理 ---

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                job = self._queue.get(timeout=1.0)
            except Empty:
                continue
            try:
                self.process(job)
            except Exception:  # Writerの予期しない例外でBackend本体を落とさない
                logger.exception("画像保存のジョブ処理に失敗しました (record %s)", job.record_id)
                try:
                    finalize_record(job.record_id, ImageResult("failed", error="画像保存の内部エラー"))
                except Exception:
                    pass

    def process(self, job: ImageJob) -> ImageResult:
        """1件を処理して結果をDBへ反映する(テストからも直接呼べる)。"""
        now = time.monotonic()
        if now < self._circuit_open_until:
            result = ImageResult("dropped", error="保存先が応答しないため、画像の保存を一時停止しています")
        else:
            db = SessionLocal()
            try:
                config = load_config(db)
            finally:
                db.close()
            with self._lock:
                self.working_since = time.monotonic()
            try:
                result = save_job(job, config)
            finally:
                with self._lock:
                    self.working_since = None
            if result.free_bytes is not None:
                self.last_free_bytes = result.free_bytes
            if result.io_failure:
                self._consecutive_io_failures += 1
                if self._consecutive_io_failures >= _CIRCUIT_FAILURES:
                    self._circuit_open_until = time.monotonic() + _CIRCUIT_OPEN_SECONDS
                    logger.warning("画像保存先のI/O失敗が続いたため、%d秒間保存を一時停止します", int(_CIRCUIT_OPEN_SECONDS))
            elif result.status == "ok":
                self._consecutive_io_failures = 0
        if result.status == "ok":
            with self._lock:
                self.counts["ok"] += 1
                self.last_success_at = datetime.now(timezone.utc)
        else:
            self._count(result.status, result.error)
            logger.warning("monitor %s: 画像を保存できませんでした (%s): %s", job.monitor_id, result.status, result.error)
        finalize_record(job.record_id, result)
        return result


record_writer = RecordWriter()
