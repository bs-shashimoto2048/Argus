"""同一MonitorのEngine/Device変更時、他Monitorが再構成されないことを確認する。

Backend全体を再起動せず、対象Monitorのruntimeだけを差し替える設計
(RuntimeManager.start_monitor -> stop_monitor + 新規MonitorRuntime)が
「他Monitorを止めない」という要件を満たしているかの回帰テスト。
"""
from __future__ import annotations

import time

import numpy as np
import pytest

from runtime.runtime_manager import RuntimeManager
from runtime.video_reader import ReaderConfig

pytestmark = pytest.mark.integration


class _FakeReader:
    """常にframe読み取りに成功するFake VideoReader(Issue #33)。

    以前はread()が常に(False, None)を返す実装だったため、MonitorRuntime._run()の
    「読取失敗が続くとreader.close()して再接続する」ロジックが自然発火してしまい、
    このテストが検証したい「他Monitorのruntimeはreader.close()されない」という
    assertionが、対象Monitor(1)側のEngine構築(create_engine呼び出し等)の遅さで
    time.sleep(0.05)の前提が崩れるたびに、無関係な自己再接続とタイミングが重なって
    誤ってFailするようになっていた(CI Windows runnerで再現性100%)。
    読取を常に成功させ、この自己再接続の発火条件自体を無くすことで、
    「他Monitorが再構成されないこと」だけを安定して検証できるようにする。
    """

    def __init__(self, _config):
        self.closed = False
        self.source_fps = None

    def read(self):
        return True, np.zeros((2, 2, 3), dtype=np.uint8)

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
