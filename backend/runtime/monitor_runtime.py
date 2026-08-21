from __future__ import annotations

from threading import Event, Lock, Thread, current_thread
import time

import cv2

from .frame_buffer import LatestFrameBuffer
from .video_reader import ReaderConfig, VideoReader
from .inference_scheduler import InferenceScheduler
from app.core.config import settings as app_settings
from app.inference.registry import model_registry


class MonitorRuntime:
    def __init__(self, monitor_id: int, config: ReaderConfig, on_status, on_result=None) -> None:
        self.monitor_id = monitor_id
        self.config = config
        self.buffer = LatestFrameBuffer()
        self._on_status = on_status
        self._on_result = on_result or (lambda *_: None)
        self._stop = Event()
        self._state_lock = Lock()
        self._state = "stopped"
        self._thread: Thread | None = None
        self.reader: VideoReader | None = None
        self.frame_width: int | None = None
        self.frame_height: int | None = None
        self.source_fps: float | None = None
        self.reconnect_count = 0
        self.last_error: str | None = None
        self.last_frame_timestamp: float | None = None
        self.stale_after_seconds = max(3.0, 3.0 / max(1.0, config.video_fps))
        self.inference_scheduler = InferenceScheduler(monitor_id, self.buffer, config.inference_settings or {}, model_registry, app_settings.data_dir / "models", self._on_result) if config.inference_settings else None

    @property
    def state(self) -> str:
        with self._state_lock:
            return self._state

    def _set_status(self, status: str) -> None:
        with self._state_lock:
            if self._state == status:
                return
            self._state = status
        self._on_status(self.monitor_id, status)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._set_status("connecting")
        self._thread = Thread(target=self._run, name=f"argus-monitor-{self.monitor_id}", daemon=True)
        self._thread.start()
        if self.inference_scheduler:
            self.inference_scheduler.start()

    def stop(self) -> None:
        self._stop.set()
        reader = self.reader
        if reader:
            reader.close()
        if self.inference_scheduler:
            self.inference_scheduler.stop()
        if self._thread and self._thread.is_alive() and self._thread is not current_thread():
            self._thread.join(timeout=2)
        self._set_status("stopped")

    def update_settings(self, video_fps: float, inference_settings: dict | None) -> None:
        """映像取得(VideoReader/VideoCapture)を再接続せず、推論設定だけを更新する。

        Issue #16: ROIをPUT/保存すると、稼働中の映像ソースが「映像ソースを開けません」に
        なる回帰が発生した。原因は、ROIのようなInferenceScheduler専用の設定変更でも、
        従来はRuntimeManager.start_monitor()経由でVideoReaderから丸ごと再接続していたため
        (実カメラによっては直前の接続が解放される前に再接続され、失敗することがある)。
        source(source_type/device_id/url/username/password)はここでは一切変更しない
        (呼び出し元がsource変更を検知した場合は、代わりにRuntimeManager.start_monitor()で
        Runtime全体を再構築すること)。
        """
        self.config.video_fps = video_fps
        self.config.inference_settings = inference_settings
        self.stale_after_seconds = max(3.0, 3.0 / max(1.0, video_fps))
        old_scheduler = self.inference_scheduler
        self.inference_scheduler = (
            InferenceScheduler(self.monitor_id, self.buffer, inference_settings, model_registry, app_settings.data_dir / "models", self._on_result)
            if inference_settings else None
        )
        if old_scheduler:
            old_scheduler.stop()
        if self.inference_scheduler and self.state != "stopped":
            self.inference_scheduler.start()

    def diagnostics(self) -> dict[str, object]:
        return {
            "source_type": self.config.source_type,
            "state": self.state,
            "frame_width": self.frame_width,
            "frame_height": self.frame_height,
            "source_fps": self.source_fps,
            "last_frame_timestamp": self.last_frame_timestamp,
            "reconnect_count": self.reconnect_count,
            "last_error": self.last_error,
            "frame_age": self.buffer.age(),
            "stale": self.buffer.age() is not None and self.buffer.age() > self.stale_after_seconds,
            "inference_enabled": bool(self.inference_scheduler and self.inference_scheduler.enabled),
            "inference_result": self.inference_scheduler.latest_result.value if self.inference_scheduler and self.inference_scheduler.latest_result else None,
        }

    def _run(self) -> None:
        self.reader = VideoReader(self.config)
        failures = 0
        reconnect_count = 0
        next_tick = time.monotonic()
        try:
            while not self._stop.is_set():
                try:
                    ok, frame = self.reader.read()
                except Exception:
                    ok, frame = False, None
                if not ok or frame is None:
                    failures += 1
                    stale = self.buffer.age() is not None and self.buffer.age() > self.stale_after_seconds
                    self.last_error = "STALE_FRAME" if stale else "READ_FAILED"
                    if failures < 10 and not stale:
                        self._stop.wait(0.05)
                        continue
                    reconnect_count += 1
                    self.reconnect_count += 1
                    self._set_status("reconnecting")
                    self.reader.close()
                    delay = min(10.0, float((1, 2, 5, 10)[min(reconnect_count - 1, 3)]))
                    if self._stop.wait(delay):
                        break
                    self.reader = VideoReader(self.config)
                    failures = 0
                    continue

                failures = 0
                reconnect_count = 0
                self.last_error = None
                self.frame_height, self.frame_width = frame.shape[:2]
                if self.reader and self.reader.source_fps:
                    self.source_fps = self.reader.source_fps
                self.last_frame_timestamp = time.time()
                success, encoded = cv2.imencode(".jpg", frame)
                if success:
                    self.buffer.put(encoded.tobytes())
                    self._set_status("running")
                interval = 1.0 / max(1.0, self.config.video_fps)
                next_tick += interval
                wait_for = next_tick - time.monotonic()
                if wait_for > 0:
                    self._stop.wait(wait_for)
                else:
                    next_tick = time.monotonic()
        except Exception as exc:
            self.last_error = type(exc).__name__
            self._set_status("error")
        finally:
            if self.reader:
                self.reader.close()
            if self.inference_scheduler:
                self.inference_scheduler.stop()
            if self.state != "stopped":
                self._set_status("error")
