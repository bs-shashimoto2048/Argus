"""RuntimeManagerが、差し替え済み(=世代の古い)MonitorRuntimeからの遅延status callbackを
無視することを確認する回帰テスト(Issue #29)。

実機Monitor 4で確認された不整合の原因は、start_monitor()でRuntimeを差し替える際、旧
MonitorRuntimeの背後Thread(stop()のjoin(timeout=2)後もなお生存し得る)が後から送ってくる
status callbackが、新Runtimeが既に書き込んだ正しいMonitor.statusを上書きしてしまう
競合条件だった。ここでは実カメラ/実Threadのタイミングに依存せず、RuntimeManagerが
組み立てるcallback(_make_status_forwarder)そのものを直接呼び出すことで、世代が
進んだ後は無条件に無視されることを検証する。
"""
from __future__ import annotations

import time

import numpy as np

from runtime.runtime_manager import RuntimeManager
from runtime.video_reader import ReaderConfig


class _FakeReader:
    """常にframe読み取りに成功するFake VideoReader。"""

    def __init__(self, _config):
        self.source_fps = None
        self.closed = False

    def read(self):
        return True, np.zeros((4, 4, 3), dtype=np.uint8)

    def close(self):
        self.closed = True


def test_stale_runtime_status_callback_is_ignored_after_restart(monkeypatch):
    monkeypatch.setattr("runtime.monitor_runtime.VideoReader", _FakeReader)

    manager = RuntimeManager()
    statuses: list[str] = []
    manager.set_status_callback(lambda _monitor_id, status: statuses.append(status))

    try:
        manager.start_monitor(1, ReaderConfig(source_type="camera"))
        time.sleep(0.1)
        old_runtime = manager.get_runtime(1)
        assert old_runtime is not None

        # source変更等でRuntimeを差し替える(実運用ではPATCH /api/monitors/{id}等から発生)。
        manager.start_monitor(1, ReaderConfig(source_type="camera"))
        time.sleep(0.1)
        statuses.clear()

        # 旧Runtimeの背後Threadが停止処理後もなお遅延して発火させたcallbackを模す。
        old_runtime._on_status(1, "stopped")
        old_runtime._on_status(1, "running")

        assert statuses == [], "差し替え済みRuntimeからのcallbackは無視されるべき"
    finally:
        manager.stop_all()


def test_status_callback_still_forwards_for_the_current_runtime(monkeypatch):
    """世代の仕組み自体が、通常時のcallback転送まで壊していないことを確認する。"""
    monkeypatch.setattr("runtime.monitor_runtime.VideoReader", _FakeReader)

    manager = RuntimeManager()
    statuses: list[str] = []
    manager.set_status_callback(lambda _monitor_id, status: statuses.append(status))

    try:
        manager.start_monitor(2, ReaderConfig(source_type="camera"))
        time.sleep(0.1)
        assert "connecting" in statuses
        assert "running" in statuses
    finally:
        manager.stop_all()
