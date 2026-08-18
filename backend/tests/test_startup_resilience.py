"""不正なdevice設定があってもRuntime構築・アプリ起動が落ちないことを確認する回帰テスト。

修正前は resolve_device() が投げる ValueError が
create_engine -> InferenceScheduler.__init__ -> MonitorRuntime.__init__ -> lifespan()
まで素通しになり、1台のMonitorの不正device設定でBackend全体の起動が失敗していた。
"""
from __future__ import annotations

import numpy as np
import pytest

from app.inference.base import ModelRegistry
from app.inference.engines import create_engine
from runtime.monitor_runtime import MonitorRuntime
from runtime.video_reader import ReaderConfig

pytestmark = pytest.mark.unit

IMAGE = np.zeros((10, 10, 3), dtype=np.uint8)


@pytest.mark.parametrize("device", ["cuda:99", "cuda:-1", "not-a-device"])
def test_create_engine_never_raises_for_bad_device(tmp_path, device):
    engine = create_engine({"method": "object_detection", "engine": "ultralytics", "model_id": "model.pt", "device": device}, ModelRegistry(), tmp_path)
    assert engine is not None
    result = engine.infer(IMAGE)
    assert result.error == "DEVICE_UNAVAILABLE"


def test_monitor_runtime_construction_does_not_raise_for_bad_device(monkeypatch):
    class FakeReader:
        def __init__(self, _config):
            pass

        def read(self):
            return False, None

        def close(self):
            pass

    monkeypatch.setattr("runtime.monitor_runtime.VideoReader", FakeReader)
    inference_settings = {"method": "object_detection", "engine": "ultralytics", "model_id": "model.pt", "device": "cuda:99", "inference_fps": 5}
    # 例外を投げずに構築でき、Engine自体はDEVICE_UNAVAILABLEを返す状態になっていること。
    runtime = MonitorRuntime(1, ReaderConfig(source_type="camera", inference_settings=inference_settings), lambda *_: None)
    assert runtime.inference_scheduler is not None
    assert runtime.inference_scheduler.enabled
    runtime.start()
    runtime._stop.wait(0.1)
    runtime.stop()
