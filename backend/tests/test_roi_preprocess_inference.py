from datetime import datetime

import pytest
import cv2
import numpy as np
from PIL import Image

from app.inference.base import ModelRegistry
from app.inference.device import resolve_device
from app.schemas.inference import PreprocessSettings, Roi
from app.services.preprocess_service import apply, crop_roi
from runtime.monitor_runtime import MonitorRuntime
from runtime.frame_buffer import LatestFrameBuffer
from runtime.video_reader import ReaderConfig
from runtime.inference_scheduler import InferenceScheduler
from app.inference.base import InferenceResult
from app.inference.registry import model_registry


def test_roi_must_fit_frame():
    with pytest.raises(ValueError):
        Roi(x=0.8, y=0, width=0.4, height=0.2)


def test_roi_pixel_crop_and_preprocess_output():
    image = Image.new("RGB", (100, 50), "white")
    cropped = crop_roi(image, Roi(x=0.1, y=0.2, width=0.5, height=0.5))
    processed = apply(cropped, PreprocessSettings(grayscale=True, binary=True, threshold=200, invert=True))
    assert cropped.size == (50, 25)
    assert processed.size == cropped.size
    assert processed.mode == "RGB"


def test_model_registry_loads_same_key_once():
    registry = ModelRegistry()
    calls = 0

    def loader():
        nonlocal calls
        calls += 1
        return object()

    assert registry.get("model.pt", "cpu", loader) is registry.get("model.pt", "cpu", loader)
    assert calls == 1


def test_device_resolver_cpu():
    assert resolve_device("cpu") == "cpu"


def test_runtime_diagnostics_marks_old_frame_stale():
    runtime = MonitorRuntime(1, ReaderConfig(source_type="camera"), lambda *_: None)
    runtime.last_frame_timestamp = datetime.now().timestamp() - 10
    runtime.buffer.put(b"frame")
    runtime.buffer._updated_at -= 10
    assert runtime.diagnostics()["stale"] is True


def test_inference_scheduler_processes_latest_frame(monkeypatch, tmp_path):
    class FakeEngine:
        def infer(self, image, settings=None):
            assert image.shape[2] == 3
            return InferenceResult(value="002560", confidence=0.9, engine="mock")

    monkeypatch.setattr("runtime.inference_scheduler.create_engine", lambda *args: FakeEngine())
    image = np.zeros((40, 80, 3), dtype=np.uint8)
    ok, encoded = cv2.imencode(".jpg", image)
    assert ok
    buffer = LatestFrameBuffer()
    buffer.put(encoded.tobytes())
    results = []
    # required_matches=1: この既存テストの目的は「Schedulerが最新frameをEngineへ渡す」ことの
    # 確認であり、複数tickにわたる時系列安定化(reading.stabilizer)の合意形成は対象外のため、
    # 単発readingで即Confirmedになるよう設定する。
    scheduler = InferenceScheduler(1, buffer, {"inference_fps": 10, "roi": {"x": 0, "y": 0, "width": 1, "height": 1}, "preprocessing": {}, "reading": {"window_size": 1, "required_matches": 1}}, model_registry, tmp_path, lambda _id, value: results.append(value))
    scheduler.start()
    scheduler._stop.wait(0.25)
    scheduler.stop()
    assert results and results[-1].value == "002560"
