"""推論エラーコードが実際に発生・区別されることを確認するテスト。

重いAIライブラリの実体には依存せず、必要なモジュールはfakeで差し替えることで
通常CIでも高速・安定に実行できるようにしている（ultralytics/easyocr/torchが
実際に入っているかどうかに関係なく成立する）。
"""
from __future__ import annotations

import sys
import types

import numpy as np
import pytest

from app.inference.base import Detection, ModelRegistry
from app.inference.engines import EasyOcrInferenceEngine, TesseractInferenceEngine, YoloInferenceEngine, create_engine

pytestmark = pytest.mark.unit

IMAGE = np.zeros((20, 20, 3), dtype=np.uint8)


def test_model_not_found_when_file_missing(tmp_path):
    engine = YoloInferenceEngine("missing.pt", "cpu", 0.25, 0.7, 640, ModelRegistry(), tmp_path)
    result = engine.infer(IMAGE)
    assert result.error == "MODEL_NOT_FOUND"


def test_model_not_configured_when_ultralytics_missing(tmp_path, monkeypatch):
    model_path = tmp_path / "model.pt"
    model_path.write_bytes(b"not-a-real-model")
    engine = YoloInferenceEngine("model.pt", "cpu", 0.25, 0.7, 640, ModelRegistry(), tmp_path)
    monkeypatch.setattr(engine, "_model", lambda: (_ for _ in ()).throw(RuntimeError("MODEL_NOT_CONFIGURED: ultralytics is not installed")))
    result = engine.infer(IMAGE)
    assert result.error == "MODEL_NOT_CONFIGURED"


def test_no_detection_when_yolo_finds_nothing(tmp_path, monkeypatch):
    class FakeBoxes:
        xyxy = types.SimpleNamespace(tolist=lambda: [])
        conf = types.SimpleNamespace(tolist=lambda: [])
        cls = types.SimpleNamespace(tolist=lambda: [])

    class FakeResult:
        names = {}
        boxes = FakeBoxes()

    class FakeModel:
        def predict(self, *a, **kw):
            return [FakeResult()]

    engine = YoloInferenceEngine("model.pt", "cpu", 0.25, 0.7, 640, ModelRegistry(), tmp_path)
    monkeypatch.setattr(engine, "_model", lambda: FakeModel())
    result = engine.infer(IMAGE)
    assert result.error == "NO_DETECTION"


def test_inference_failed_on_unexpected_exception(tmp_path, monkeypatch):
    class FakeModel:
        def predict(self, *a, **kw):
            raise RuntimeError("boom")

    engine = YoloInferenceEngine("model.pt", "cpu", 0.25, 0.7, 640, ModelRegistry(), tmp_path)
    monkeypatch.setattr(engine, "_model", lambda: FakeModel())
    result = engine.infer(IMAGE)
    assert result.error == "INFERENCE_FAILED"


def test_device_unavailable_is_not_raised_but_returned(tmp_path):
    # create_engineは不正device(存在しないGPU index)でも例外を外へ伝播させない。
    engine = create_engine({"method": "object_detection", "engine": "ultralytics", "model_id": "model.pt", "device": "cuda:99"}, ModelRegistry(), tmp_path)
    assert engine is not None
    result = engine.infer(IMAGE)
    assert result.error == "DEVICE_UNAVAILABLE"


def test_easyocr_unavailable_when_package_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "easyocr", None)
    engine = EasyOcrInferenceEngine(["en"], "cpu", ModelRegistry())
    result = engine.infer(IMAGE)
    assert result.error == "OCR_ENGINE_UNAVAILABLE"


def test_easyocr_no_detection_when_reader_finds_nothing(monkeypatch):
    class FakeReader:
        def __init__(self, *_a, **_kw):
            pass

        def readtext(self, _image):
            return []

    fake_module = types.ModuleType("easyocr")
    fake_module.Reader = FakeReader
    monkeypatch.setitem(sys.modules, "easyocr", fake_module)
    engine = EasyOcrInferenceEngine(["en"], "cpu", ModelRegistry())
    result = engine.infer(IMAGE)
    assert result.error == "NO_DETECTION"


def test_easyocr_success_with_fake_reader(monkeypatch):
    class FakeReader:
        def __init__(self, *_a, **_kw):
            pass

        def readtext(self, _image):
            return [([[0, 0], [10, 0], [10, 10], [0, 10]], "5", 0.9)]

    fake_module = types.ModuleType("easyocr")
    fake_module.Reader = FakeReader
    monkeypatch.setitem(sys.modules, "easyocr", fake_module)
    engine = EasyOcrInferenceEngine(["en"], "cpu", ModelRegistry())
    result = engine.infer(IMAGE)
    assert result.error is None
    assert result.value == "5"


def _make_fake_pytesseract(*, not_found=False, other_error=False, text="123.45"):
    class TesseractNotFoundError(Exception):
        pass

    def image_to_string(_image, lang=None, config=None):
        if not_found:
            raise TesseractNotFoundError("tesseract is not installed")
        if other_error:
            raise RuntimeError("boom")
        return text

    inner = types.SimpleNamespace(tesseract_cmd="tesseract", TesseractNotFoundError=TesseractNotFoundError)
    module = types.ModuleType("pytesseract")
    module.pytesseract = inner
    module.image_to_string = image_to_string
    module.get_tesseract_version = lambda: "5.0.0"
    return module


def test_tesseract_ocr_engine_unavailable_when_package_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "pytesseract", None)
    engine = TesseractInferenceEngine("eng", 6, 3)
    result = engine.infer(IMAGE)
    assert result.error == "OCR_ENGINE_UNAVAILABLE"


def test_tesseract_not_installed_when_executable_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "pytesseract", _make_fake_pytesseract(not_found=True))
    engine = TesseractInferenceEngine("eng", 6, 3, executable_path="Z:/does/not/exist/tesseract.exe")
    result = engine.infer(IMAGE)
    assert result.error == "TESSERACT_NOT_INSTALLED"


def test_tesseract_inference_failed_is_distinct_from_not_installed(monkeypatch):
    monkeypatch.setitem(sys.modules, "pytesseract", _make_fake_pytesseract(other_error=True))
    engine = TesseractInferenceEngine("eng", 6, 3, executable_path="tesseract")
    result = engine.infer(IMAGE)
    assert result.error == "INFERENCE_FAILED"


def test_tesseract_success_with_fake_binary(monkeypatch):
    monkeypatch.setitem(sys.modules, "pytesseract", _make_fake_pytesseract(text="123.45"))
    engine = TesseractInferenceEngine("eng", 6, 3, executable_path="tesseract")
    result = engine.infer(IMAGE)
    assert result.error is None
    assert result.value == "123.45"
