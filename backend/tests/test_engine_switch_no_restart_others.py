"""同一MonitorのEngine/Device変更時、他Monitorが再構成されないことを確認する。

Backend全体を再起動せず、対象Monitorのruntimeだけを差し替える設計
(RuntimeManager.start_monitor -> stop_monitor + 新規MonitorRuntime)が
「他Monitorを止めない」という要件を満たしているかの回帰テスト。
"""
from __future__ import annotations

import time

import pytest

from runtime.runtime_manager import RuntimeManager
from runtime.video_reader import ReaderConfig

pytestmark = pytest.mark.integration


class _FakeReader:
    def __init__(self, _config):
        self.closed = False

    def read(self):
        return False, None

    def close(self):
        self.closed = True


def test_switching_engine_on_one_monitor_does_not_touch_another(monkeypatch):
    monkeypatch.setattr("runtime.monitor_runtime.VideoReader", _FakeReader)
    manager = RuntimeManager()

    other_config = ReaderConfig(source_type="camera", inference_settings=None)
    manager.start_monitor(2, other_config)
    other_runtime_before = manager.get_runtime(2)
    assert other_runtime_before is not None
    time.sleep(0.05)

    yolo_config = ReaderConfig(source_type="camera", inference_settings={"method": "object_detection", "engine": "ultralytics", "model_id": None})
    manager.start_monitor(1, yolo_config)
    target_runtime_v1 = manager.get_runtime(1)
    time.sleep(0.05)

    # Engineをyolo(model未設定=推論disabled) -> easyocr へ切り替え。
    ocr_config = ReaderConfig(source_type="camera", inference_settings={"method": "ocr", "engine": "easyocr", "engine_options": {"languages": ["en"]}})
    manager.start_monitor(1, ocr_config)
    target_runtime_v2 = manager.get_runtime(1)
    time.sleep(0.05)

    try:
        assert target_runtime_v2 is not target_runtime_v1, "対象Monitorのruntimeは再構成されていること"
        assert target_runtime_v2.inference_scheduler.enabled, "easyocrへ切替後はEngineが有効であること"
        assert manager.get_runtime(2) is other_runtime_before, "他Monitorのruntimeは再構成されていないこと"
        assert not other_runtime_before.reader.closed if other_runtime_before.reader else True
    finally:
        manager.stop_all()
