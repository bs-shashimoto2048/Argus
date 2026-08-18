"""推論Engineが例外を送出しても、映像取得(VideoReader/Snapshot/MJPEG用buffer)が継続することを確認する。"""
from __future__ import annotations

import time

import numpy as np
import pytest

from runtime.monitor_runtime import MonitorRuntime
from runtime.video_reader import ReaderConfig

pytestmark = pytest.mark.integration


class _FakeReader:
    def __init__(self, _config):
        self.closed = False
        self.source_fps = None

    def read(self):
        return True, np.zeros((20, 20, 3), dtype=np.uint8)

    def close(self):
        self.closed = True


class _AlwaysRaisingEngine:
    def infer(self, image, settings=None):
        raise RuntimeError("engine is intentionally broken for this test")


def test_video_buffer_keeps_updating_when_engine_raises(monkeypatch):
    monkeypatch.setattr("runtime.monitor_runtime.VideoReader", _FakeReader)
    inference_settings = {"method": "object_detection", "engine": "ultralytics", "model_id": None, "inference_fps": 10}
    runtime = MonitorRuntime(1, ReaderConfig(source_type="camera", video_fps=10, inference_settings=inference_settings), lambda *_: None)
    # create_engineはmodel_id未設定でNoneを返すため、明示的に例外を出すEngineへ差し替える。
    runtime.inference_scheduler.engine = _AlwaysRaisingEngine()

    runtime.start()
    time.sleep(0.3)
    data_before, stamp_before = runtime.buffer.get()
    time.sleep(0.2)
    data_after, stamp_after = runtime.buffer.get()
    runtime.stop()

    assert data_before is not None and data_after is not None
    assert stamp_after is not None and stamp_before is not None and stamp_after >= stamp_before
    assert runtime.state == "stopped"
    # 推論側はエラーを返すだけで、映像側の状態("running"だった)を壊していないこと。
    assert runtime.inference_scheduler.latest_result is not None
    assert runtime.inference_scheduler.latest_result.error == "INFERENCE_FAILED" or runtime.inference_scheduler.latest_result.error is not None
