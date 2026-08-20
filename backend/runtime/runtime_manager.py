from threading import RLock
from .monitor_runtime import MonitorRuntime
from .video_reader import ReaderConfig

class RuntimeManager:
    def __init__(self) -> None:
        self._lock = RLock()
        self._runtimes: dict[int, MonitorRuntime] = {}
        self._status_callback = None
        self._result_callback = None
    def set_status_callback(self, callback) -> None: self._status_callback = callback
    def set_result_callback(self, callback) -> None: self._result_callback = callback
    def start_monitor(self, monitor_id: int, config: ReaderConfig) -> None:
        with self._lock:
            self.stop_monitor(monitor_id)
            runtime = MonitorRuntime(monitor_id, config, self._status_callback or (lambda *_: None), self._result_callback)
            self._runtimes[monitor_id] = runtime
            runtime.start()
    def stop_monitor(self, monitor_id: int) -> None:
        with self._lock:
            runtime = self._runtimes.pop(monitor_id, None)
            if runtime: runtime.stop()
    def restart_monitor(self, monitor_id: int, config: ReaderConfig) -> None: self.start_monitor(monitor_id, config)
    def get_runtime(self, monitor_id: int) -> MonitorRuntime | None:
        with self._lock: return self._runtimes.get(monitor_id)

    def active_local_camera_devices(self) -> set[int]:
        """現在稼働中のlocal camera Monitorが使用しているdevice_idの集合。
        カメラ列挙(/api/cameras)がこれらと同じdeviceを二重にopenして衝突・
        native crashを招かないようにするために使う(Issue #14調査)。
        """
        with self._lock:
            return {
                runtime.config.device_id
                for runtime in self._runtimes.values()
                if runtime.config.source_type in ("camera", "local_camera") and runtime.config.device_id is not None
            }

    def count(self) -> int:
        """現在稼働中のMonitorRuntime数(診断用)。"""
        with self._lock:
            return len(self._runtimes)

    # Public aliases kept close to the runtime domain API.
    def start(self, monitor_id: int, config: ReaderConfig) -> None:
        self.start_monitor(monitor_id, config)

    def stop(self, monitor_id: int) -> None:
        self.stop_monitor(monitor_id)

    def get(self, monitor_id: int) -> MonitorRuntime | None:
        return self.get_runtime(monitor_id)
    def stop_all(self) -> None:
        with self._lock:
            for monitor_id in list(self._runtimes): self.stop_monitor(monitor_id)

runtime_manager = RuntimeManager()
