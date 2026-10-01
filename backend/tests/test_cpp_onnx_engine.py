"""cpp_onnx inference backend（Issue #37）のsmoke test。

argus_cpp_onnx_worker.exe（C++常駐worker）のbuildと、yolo_pipeline_studio
Issue #47/#48のDigital/Drum ONNX artifact（data/models/*.onnx）がローカルに
揃っている環境でのみ実行する（通常CIでは`optional_inference`マーカーでskip、
test_inference_engines_real.pyと同じ方針）。

実行例:
    cd backend
    pytest -m optional_inference -k cpp_onnx -v
"""
from __future__ import annotations

from pathlib import Path

import cv2
import pytest

from app.core.config import settings as app_settings
from app.inference.base import ModelRegistry
from app.inference.cpp_onnx_engine import CppOnnxEngineConfigError, CppOnnxInferenceEngine
from app.inference.engines import create_engine
from app.services.monitor_service import _normalize_engine

pytestmark = pytest.mark.optional_inference

MODEL_ROOT = Path(__file__).resolve().parents[2] / "data" / "models"
_YPS_ROOT = Path(__file__).resolve().parents[3] / "yolo_pipeline_studio"

_DIGITAL_FIXTURE = (
    _YPS_ROOT / "projects/yolo26_digital/datasets/matched_source_v1/images/train/src_002_20260903_142400.jpg"
)
_DIGITAL_EXPECTED_READING = "0215234"
_DRUM_FIXTURE = (
    _YPS_ROOT / "projects/yolo26_dram_crop/datasets/matched_source_v1/images/train/src_004_20260906_002400.jpg"
)
_DRUM_EXPECTED_READING = "3718333"


def _require_worker_and_models() -> None:
    if not app_settings.cpp_onnx_worker_path.is_file():
        pytest.skip(f"argus_cpp_onnx_worker.exe not built at {app_settings.cpp_onnx_worker_path}; "
                    f"see docs/CPP_ONNX_INTEGRATION.md for build instructions")
    for model_id in ("digital_production_v1.onnx", "drum_production_v1.onnx"):
        if not (MODEL_ROOT / model_id).is_file():
            pytest.skip(f"{model_id} not found at {MODEL_ROOT}; see docs/CPP_ONNX_INTEGRATION.md")


def _require_fixture(path: Path) -> None:
    if not path.is_file():
        pytest.skip(f"yolo_pipeline_studio fixture image not available locally ({path})")


def test_normalize_engine_allows_cpp_onnx_for_object_detection() -> None:
    assert _normalize_engine("object_detection", "cpp_onnx") == "cpp_onnx"
    assert _normalize_engine("object_detection", "ultralytics") == "ultralytics"
    # 不正な組合せ(object_detection + OCR engine)は既存どおりultralyticsへ矯正する。
    assert _normalize_engine("object_detection", "tesseract") == "ultralytics"


def test_cpp_onnx_engine_rejects_unregistered_model_id_without_raising() -> None:
    registry = ModelRegistry()
    with pytest.raises(CppOnnxEngineConfigError):
        CppOnnxInferenceEngine("not_in_registry.onnx", registry, MODEL_ROOT)
    # create_engine()自体は例外を外へ伝播させない(Runtime起動を道連れにしない既存方針)。
    engine = create_engine(
        {"method": "object_detection", "engine": "cpp_onnx", "model_id": "not_in_registry.onnx"},
        registry, MODEL_ROOT,
    )
    result = engine.infer(None, {})  # _UnavailableEngineはimageを使わない
    assert result.error == "MODEL_NOT_CONFIGURED"


def test_cpp_onnx_engine_digital_fixture_matches_golden() -> None:
    _require_worker_and_models()
    _require_fixture(_DIGITAL_FIXTURE)
    registry = ModelRegistry()
    engine = create_engine(
        {"method": "object_detection", "engine": "cpp_onnx", "model_id": "digital_production_v1.onnx"},
        registry, MODEL_ROOT,
    )
    assert isinstance(engine, CppOnnxInferenceEngine)
    image = cv2.imread(str(_DIGITAL_FIXTURE))
    result = engine.infer(image, {"confidence": 0.60})
    assert result.error is None
    assert result.engine == "cpp_onnx"
    assert result.model_id == "digital_production_v1.onnx"
    assert result.value == _DIGITAL_EXPECTED_READING
    assert len(result.detections) == 7


def test_cpp_onnx_engine_drum_fixture_matches_golden() -> None:
    _require_worker_and_models()
    _require_fixture(_DRUM_FIXTURE)
    registry = ModelRegistry()
    engine = create_engine(
        {"method": "object_detection", "engine": "cpp_onnx", "model_id": "drum_production_v1.onnx"},
        registry, MODEL_ROOT,
    )
    image = cv2.imread(str(_DRUM_FIXTURE))
    result = engine.infer(image, {"confidence": 0.80})
    assert result.error is None
    assert result.value == _DRUM_EXPECTED_READING
    assert len(result.detections) == 7


def test_cpp_onnx_worker_process_is_reused_across_monitors_with_same_registry() -> None:
    """同一ModelRegistryを共有する2つのEngineインスタンス(=2 Monitor相当)が、
    同じ常駐workerプロセスを共有する(Issue #37 §33: 毎推論・毎Monitorでprocessを
    起動しない)。"""
    _require_worker_and_models()
    _require_fixture(_DIGITAL_FIXTURE)
    registry = ModelRegistry()
    engine_a = create_engine(
        {"method": "object_detection", "engine": "cpp_onnx", "model_id": "digital_production_v1.onnx"},
        registry, MODEL_ROOT,
    )
    engine_b = create_engine(
        {"method": "object_detection", "engine": "cpp_onnx", "model_id": "digital_production_v1.onnx"},
        registry, MODEL_ROOT,
    )
    image = cv2.imread(str(_DIGITAL_FIXTURE))
    engine_a.infer(image, {"confidence": 0.60})
    assert engine_a._worker() is engine_b._worker()  # noqa: SLF001 (white-box reuse check)


def test_cpp_onnx_engine_invalid_frame_reports_error_not_exception() -> None:
    _require_worker_and_models()
    import numpy as np  # noqa: PLC0415

    registry = ModelRegistry()
    engine = create_engine(
        {"method": "object_detection", "engine": "cpp_onnx", "model_id": "digital_production_v1.onnx"},
        registry, MODEL_ROOT,
    )
    blank = np.zeros((10, 10, 3), dtype=np.uint8)
    result = engine.infer(blank, {"confidence": 0.60})
    # 検出0件(NO_DETECTION)になることを期待する(クラッシュしないことが主眼)。
    assert result.error in ("NO_DETECTION",)
