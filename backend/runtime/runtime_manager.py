import logging
from threading import RLock, Thread
from time import monotonic
from .monitor_runtime import MonitorRuntime
from .video_reader import ReaderConfig

logger = logging.getLogger("uvicorn.error")

# stop_all全体の待ち上限。各Runtimeの停止は並列で、1台が詰まっても他と全体を無期限に待たせない
# (各Runtime内の停止は reader.close 3秒 + scheduler join 2秒 + 映像thread join 2秒 = 最大約7秒)。
STOP_ALL_TIMEOUT_SECONDS = 12.0


class RuntimeManager:
    def __init__(self) -> None:
        self._lock = RLock()
        self._runtimes: dict[int, MonitorRuntime] = {}
        # Issue #29: Monitor IDごとの「世代」カウンタ。start_monitor()でRuntimeを
        # 差し替える(または単にstop_monitor()する)たびに世代を進め、その時点で
        # 生きているMonitorRuntimeだけが現在の世代を持つようにする。旧Runtimeの
        # 背後Threadはstop()のjoin(timeout=2)後もしばらく生存し得るため、そこから
        # 遅延して届くstatus callback(例: 停止処理中に取りこぼしたreadが後から
        # "running"や"stopped"を報告する)が、新Runtimeが既に書き込んだ正しい
        # Monitor.statusを上書きしてしまう競合があった(実機Monitor 4で確認)。
        self._generation: dict[int, int] = {}
        self._status_callback = None
        self._result_callback = None
        self._baseline_provider = None
    def set_status_callback(self, callback) -> None: self._status_callback = callback
    def set_result_callback(self, callback) -> None: self._result_callback = callback
    def set_baseline_provider(self, provider) -> None: self._baseline_provider = provider
    def start_monitor(self, monitor_id: int, config: ReaderConfig) -> None:
        with self._lock:
            self.stop_monitor(monitor_id)
            generation = self._generation.get(monitor_id, 0) + 1
            self._generation[monitor_id] = generation
            runtime = MonitorRuntime(monitor_id, config, self._make_status_forwarder(monitor_id, generation), self._result_callback, self._baseline_provider)
            self._runtimes[monitor_id] = runtime
            runtime.start()
    def stop_monitor(self, monitor_id: int) -> None:
        with self._lock:
            runtime = self._runtimes.pop(monitor_id, None)
            if runtime:
                runtime.stop()
            # runtime.stop()自体の"stopped"通知は、stop()呼び出し時点でまだ有効な
            # 世代を使って送出済み(上のpopの後でもまだ古い世代のまま)。ここで世代を
            # 進めるのは、stop()のjoin(timeout=2)後もなお生き残った背後Threadが
            # この先さらに送ってくるかもしれない遅延callbackを無視するため。
            self._generation[monitor_id] = self._generation.get(monitor_id, 0) + 1
    def restart_monitor(self, monitor_id: int, config: ReaderConfig) -> None: self.start_monitor(monitor_id, config)

    def _make_status_forwarder(self, monitor_id: int, generation: int):
        """指定した世代のMonitorRuntime専用のstatus callbackを作る。

        呼び出し時点でその世代がまだ現在世代(self._generation[monitor_id])で
        あればそのまま外側のcallbackへ転送し、既に別のRuntimeへ差し替わっている
        (=世代が進んでいる)場合は黙って無視する(Issue #29)。
        """
        def _forward(_monitor_id: int, status: str) -> None:
            with self._lock:
                if self._generation.get(monitor_id) != generation:
                    return
            if self._status_callback:
                self._status_callback(monitor_id, status)
        return _forward

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
    def stop_all(self, timeout: float = STOP_ALL_TIMEOUT_SECONDS) -> None:
        """全Runtimeを並列に停止する(Issue #72)。1台の停止が詰まっても、timeoutで見切って先へ進む。"""
        with self._lock:
            runtimes = dict(self._runtimes)
            self._runtimes.clear()
        started = monotonic()
        durations: dict[int, float] = {}

        def stop_one(monitor_id: int, runtime: MonitorRuntime) -> None:
            begin = monotonic()
            try:
                runtime.stop()
            except Exception:
                logger.exception("monitor %s のRuntime停止に失敗しました", monitor_id)
            durations[monitor_id] = monotonic() - begin

        threads = {mid: Thread(target=stop_one, args=(mid, rt), name=f"argus-stop-{mid}", daemon=True) for mid, rt in runtimes.items()}
        for thread in threads.values():
            thread.start()
        deadline = started + timeout
        for thread in threads.values():
            thread.join(max(0.0, deadline - monotonic()))
        with self._lock:
            for monitor_id in runtimes:
                self._generation[monitor_id] = self._generation.get(monitor_id, 0) + 1
        stuck = [mid for mid, thread in threads.items() if thread.is_alive()]
        logger.info("Runtime停止: %s台 / %.1f秒 (各台: %s)", len(runtimes), monotonic() - started, ", ".join(f"{mid}={sec:.1f}s" for mid, sec in sorted(durations.items())) or "-")
        if stuck:
            logger.warning("Runtime停止が%.0f秒以内に完了しませんでした(monitor %s)。待たずに終了処理を続行します", timeout, stuck)

runtime_manager = RuntimeManager()
