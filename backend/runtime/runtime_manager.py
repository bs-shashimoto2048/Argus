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

    def update_inference_settings(self, monitor_id: int, video_fps: float, inference_settings: dict | None) -> bool:
        """既存Runtimeが稼働中なら、VideoReaderを再接続せず推論設定だけを更新する。

        対象Runtimeが存在しない(未起動)場合はFalseを返す。呼び出し元はその場合
        start_monitor()等でRuntimeをフルに起動すること(Issue #16)。
        """
        with self._lock:
            runtime = self._runtimes.get(monitor_id)
            if runtime is None:
                return False
            runtime.update_settings(video_fps, inference_settings)
            return True
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
