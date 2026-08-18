from __future__ import annotations
from threading import Event, Thread
import cv2
from .frame_buffer import LatestFrameBuffer
from .video_reader import ReaderConfig, VideoReader

class MonitorRuntime:
    def __init__(self, monitor_id: int, config: ReaderConfig, on_status) -> None:
        self.monitor_id = monitor_id
        self.config = config
        self.buffer = LatestFrameBuffer()
        self._on_status = on_status
        self._stop = Event()
        self._thread: Thread | None = None
        self.reader: VideoReader | None = None
    def start(self) -> None:
        if self._thread and self._thread.is_alive(): return
        self._stop.clear()
        self._thread = Thread(target=self._run, name=f"argus-monitor-{self.monitor_id}", daemon=True)
        self._thread.start()
    def stop(self) -> None:
        self._stop.set()
        if self.reader: self.reader.close()
        if self._thread and self._thread.is_alive(): self._thread.join(timeout=2)
        self._on_status(self.monitor_id, "stopped")
    def _run(self) -> None:
        self.reader = VideoReader(self.config)
        self._on_status(self.monitor_id, "connecting")
        failures = 0
        try:
            while not self._stop.is_set():
                ok, frame = self.reader.read()
                if not ok or frame is None:
                    failures += 1
                    if failures >= 10:
                        self._on_status(self.monitor_id, "connection_error")
                        self.reader.close()
                        self._stop.wait(1)
                        if not self._stop.is_set(): self.reader = VideoReader(self.config)
                    continue
                failures = 0
                success, encoded = cv2.imencode(".jpg", frame)
                if success:
                    self.buffer.put(encoded.tobytes())
                    self._on_status(self.monitor_id, "normal")
        except Exception:
            self._on_status(self.monitor_id, "read_error")
        finally:
            self.reader.close()
