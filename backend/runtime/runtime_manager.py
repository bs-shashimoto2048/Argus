from threading import RLock
from .monitor_runtime import MonitorRuntime
from .video_reader import ReaderConfig

class RuntimeManager:
    def __init__(self) -> None:
        self._lock = RLock()
        self._runtimes: dict[int, MonitorRuntime] = {}
        self._status_callback = None
    def set_status_callback(self, callback) -> None: self._status_callback = callback
    def start_monitor(self, monitor_id: int, config: ReaderConfig) -> None:
        with self._lock:
            self.stop_monitor(monitor_id)
            runtime = MonitorRuntime(monitor_id, config, self._status_callback or (lambda *_: None))
            self._runtimes[monitor_id] = runtime
            runtime.start()
    def stop_monitor(self, monitor_id: int) -> None:
        with self._lock:
            runtime = self._runtimes.pop(monitor_id, None)
            if runtime: runtime.stop()
    def restart_monitor(self, monitor_id: int, config: ReaderConfig) -> None: self.start_monitor(monitor_id, config)
    def get_runtime(self, monitor_id: int) -> MonitorRuntime | None:
        with self._lock: return self._runtimes.get(monitor_id)
    def stop_all(self) -> None:
        with self._lock:
            for monitor_id in list(self._runtimes): self.stop_monitor(monitor_id)

runtime_manager = RuntimeManager()
