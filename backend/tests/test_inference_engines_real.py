"""実ultralytics/実easyocr/実tesseractを使ったSmoke Test。

重いAI依存(requirements-inference.txt)のインストールが必要なため、通常CIでは
実行しない(`optional_inference`マーカー)。GPU smoke testはさらに`hardware`
マーカーで隔離し、CUDAが実際に利用可能な環境でのみ実行する。

実行例:
    py -m pip install -r requirements-inference.txt
    pytest -m optional_inference          # CPU smoke test一式
    pytest -m hardware                    # GPU smoke test（CUDA環境のみ）
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.inference.base import ModelRegistry
from app.inference.diagnostics import tesseract_diagnostics
from app.inference.engines import EasyOcrInferenceEngine, TesseractInferenceEngine, YoloInferenceEngine, create_engine
from tests.fixtures.generate_digit_image import generate_digit_image

pytestmark = pytest.mark.optional_inference

ultralytics = pytest.importorskip("ultralytics")
torch = pytest.importorskip("torch")

MODEL_ROOT = Path(__file__).resolve().parents[2] / "data" / "models"
MODEL_ID = "meter_digits_v1.pt"


def _require_digit_model():
    if not (MODEL_ROOT / MODEL_ID).is_file():
        pytest.skip(f"digit model not found at {MODEL_ROOT / MODEL_ID}; see docs for placement rules")


def test_yolo_cpu_smoke_test_runs_end_to_end():
    _require_digit_model()
    image = generate_digit_image("002560")
    engine = YoloInferenceEngine(MODEL_ID, "cpu", confidence=0.25, iou=0.7, image_size=640, registry=ModelRegistry(), model_root=MODEL_ROOT)
    result = engine.infer(image)

    assert result.engine == "ultralytics"
    assert result.model_id == MODEL_ID
    assert result.processing_time_ms > 0
    # 一般的な数字画像に対してこのモデルが検出できるとは限らないため、
    # 「例外なく最後まで動く」「NO_DETECTIONも正当な結果として許容する」を確認する。
    assert result.error in (None, "NO_DETECTION")


def test_yolo_respects_confidence_iou_image_size(monkeypatch):
    _require_digit_model()
    image = generate_digit_image("002560")
    engine = YoloInferenceEngine(MODEL_ID, "cpu", confidence=0.42, iou=0.55, image_size=320, registry=ModelRegistry(), model_root=MODEL_ROOT)
    model = engine._model()
    captured = {}
    original_predict = model.predict

    def spy_predict(*args, **kwargs):
        captured.update(kwargs)
        return original_predict(*args, **kwargs)

    monkeypatch.setattr(model, "predict", spy_predict)
    engine.infer(image)

    assert captured["conf"] == pytest.approx(0.42)
    assert captured["iou"] == pytest.approx(0.55)
    assert captured["imgsz"] == 320
    assert captured["device"] == "cpu"


CUSTOM_MODEL_ID = "meter_digits_v2_candidate_001_best.pt"


def test_custom_model_meter_digits_v2_candidate_001_loads_and_runs_end_to_end():
    """Issue #16: Argusへ正式配置したcustom model(meter_digits_v2_candidate_001_best.pt)が
    baselineと同様にresolve・load・推論まで実行できることを確認する回帰テスト。
    """
    if not (MODEL_ROOT / CUSTOM_MODEL_ID).is_file():
        pytest.skip(f"custom model not found at {MODEL_ROOT / CUSTOM_MODEL_ID}; Issue #16の配置手順を参照")
    image = generate_digit_image("002560")
    engine = YoloInferenceEngine(CUSTOM_MODEL_ID, "cpu", confidence=0.25, iou=0.7, image_size=640, registry=ModelRegistry(), model_root=MODEL_ROOT)
    result = engine.infer(image)

    assert result.engine == "ultralytics"
    assert result.model_id == CUSTOM_MODEL_ID
    assert result.error != "MODEL_NOT_FOUND", "配置済みのcustom modelがMODEL_NOT_FOUNDにならないこと"
    assert result.error != "MODEL_NOT_CONFIGURED"
    assert result.error in (None, "NO_DETECTION")


def test_model_registry_reuses_real_model_across_requests():
    _require_digit_model()
    registry = ModelRegistry()
    image = generate_digit_image("002560")
    settings = {"method": "object_detection", "engine": "ultralytics", "model_id": MODEL_ID, "device": "cpu"}

    create_engine(settings, registry, MODEL_ROOT).infer(image)
    assert registry.size() == 1
    create_engine(settings, registry, MODEL_ROOT).infer(image)
    assert registry.size() == 1, "同一model_id+deviceの2回目要求でロードが増えないこと"


@pytest.mark.hardware
def test_yolo_gpu_smoke_test_runs_end_to_end():
    _require_digit_model()
    if not torch.cuda.is_available():
        pytest.skip("CUDAが利用できない環境のためGPU smoke testは未実施")
    image = generate_digit_image("002560")
    engine = YoloInferenceEngine(MODEL_ID, "cuda:0", confidence=0.25, iou=0.7, image_size=640, registry=ModelRegistry(), model_root=MODEL_ROOT)
    result = engine.infer(image)

    assert result.engine == "ultralytics"
    assert result.processing_time_ms > 0
    assert result.error in (None, "NO_DETECTION")


def test_easyocr_smoke_test_reads_digit_image():
    easyocr = pytest.importorskip("easyocr")
    image = generate_digit_image("002560")
    engine = EasyOcrInferenceEngine(["en"], "cpu", ModelRegistry())
    result = engine.infer(image)

    assert result.engine == "easyocr"
    assert result.error is None, f"EasyOCRがエラーを返した: {result.error}"
    assert result.value is not None and any(ch.isdigit() for ch in result.value)
    assert result.confidence is not None


def test_tesseract_smoke_test_or_correct_not_installed_error():
    diagnostics = tesseract_diagnostics()
    image = generate_digit_image("123.45")
    engine = TesseractInferenceEngine("eng", psm=7, oem=3)
    result = engine.infer(image)

    if diagnostics["executable"]:
        assert result.error is None, f"Tesseract実行エラー: {result.error}"
        assert result.value is not None and any(ch.isdigit() for ch in result.value)
    else:
        assert result.error == "TESSERACT_NOT_INSTALLED"
