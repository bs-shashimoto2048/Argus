"""C++ ONNX Runtime推論backend（Issue #37、yolo_pipeline_studio Issue #47/#48成果物統合）。

既存のInferenceEngineインターフェース(.infer(image, settings) -> InferenceResult)に
従い、常駐C++ worker process(argus_cpp_onnx_worker.exe)へフレームを送って結果を
受け取る。ROI/resize/grayscale/sharpenは既存のpreprocess_service/InferenceScheduler
(呼び出し元)が行うため、本Engineはletterbox以降(ONNX推論+NMS+座標復元)のみを担当する
(Issue #37 §5: 変更するのは「1フレームからdigit detection/readingを生成する部分」)。

reading構成は既存のapp.inference.meter_interpreter.interpret_digits()を再利用する
(既存のYoloInferenceEngineと同じinput semantics、Issue #37 §25)。
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np

from ..core.config import settings as app_settings
from .base import Detection, InferenceEngine, InferenceResult, ModelRegistry
from .cpp_worker_process import CppOnnxWorkerProcess, CppWorkerError
from .meter_interpreter import interpret_digits
from .model_catalog import get_model_entry

_VALID_PROFILES = {"digital", "drum"}


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class CppOnnxEngineConfigError(RuntimeError):
    """registry.json記載不備・ONNXファイル欠落・SHA256不一致等、起動時に検知すべき設定不備。"""


class CppOnnxInferenceEngine(InferenceEngine):
    def __init__(self, model_id: str, registry: ModelRegistry, model_root: Path,
                 worker_exe_path: Path | None = None) -> None:
        self.model_id = model_id
        self._model_root = model_root.resolve()
        self._registry = registry
        self._worker_exe_path = worker_exe_path or app_settings.cpp_onnx_worker_path

        entry = get_model_entry(self._model_root, model_id)
        if entry is None:
            raise CppOnnxEngineConfigError(f"MODEL_NOT_CONFIGURED: '{model_id}' is not registered in registry.json")
        profile = entry.get("profile")
        if profile not in _VALID_PROFILES:
            raise CppOnnxEngineConfigError(
                f"MODEL_NOT_CONFIGURED: registry entry for '{model_id}' has invalid profile={profile!r} "
                f"(expected one of {sorted(_VALID_PROFILES)})"
            )
        self.profile = profile
        self.contract_version = entry.get("contract_version")

        onnx_path = self._model_root / model_id
        if not onnx_path.is_file():
            raise CppOnnxEngineConfigError(f"MODEL_NOT_FOUND: {onnx_path}")
        expected_sha = entry.get("sha256")
        if expected_sha:
            actual_sha = _sha256_file(onnx_path)
            if actual_sha != expected_sha:
                raise CppOnnxEngineConfigError(
                    f"MODEL_HASH_MISMATCH: {model_id} expected={expected_sha} actual={actual_sha}"
                )
        self.onnx_path = onnx_path
        self.onnx_sha256 = expected_sha

    def _worker(self) -> CppOnnxWorkerProcess:
        # ModelRegistryを再利用し、worker処理プロセスをprocess全体で1つだけ共有する
        # (Issue #37 §33/#35: 複数Monitorが同じ常駐workerプロセスを共有し、直列化する)。
        return self._registry.get("cpp_onnx_worker", "cpu", lambda: CppOnnxWorkerProcess(self._worker_exe_path, "cpu"), "cpp_onnx_process")

    def infer(self, image: np.ndarray, settings: Any | None = None) -> InferenceResult:
        started = perf_counter()
        if image is None or image.ndim != 3 or image.shape[2] != 3:
            return InferenceResult(error="INVALID_FRAME", processing_time_ms=(perf_counter() - started) * 1000,
                                    engine="cpp_onnx", model_id=self.model_id)
        height, width = image.shape[:2]
        # 生のBGR24ピクセルをそのまま転送する(JPEG等の圧縮を経由しない)。JPEG往復は
        # カメラ由来の圧縮に追加の非可逆劣化を重ね、production parityを損なうことが
        # 実測で判明したため(Issue #37)。
        contiguous = np.ascontiguousarray(image)
        try:
            worker = self._worker()
            response = worker.infer(self.onnx_path, self.profile, frame_id="-",
                                     bgr_bytes=contiguous.tobytes(), width=width, height=height)
        except CppWorkerError as exc:
            return InferenceResult(error=f"CPP_WORKER_ERROR: {exc}",
                                    processing_time_ms=(perf_counter() - started) * 1000,
                                    engine="cpp_onnx", model_id=self.model_id)

        if response.get("error"):
            return InferenceResult(error=str(response["error"]),
                                    processing_time_ms=(perf_counter() - started) * 1000,
                                    engine="cpp_onnx", model_id=self.model_id)

        detections: list[Detection] = [
            Detection(int(d["cls"]), str(d["class_name"]), float(d["conf"]), tuple(float(v) for v in d["bbox"]))
            for d in response.get("detections", [])
        ]
        if not detections:
            return InferenceResult(error="NO_DETECTION", processing_time_ms=(perf_counter() - started) * 1000,
                                    engine="cpp_onnx", model_id=self.model_id)

        confidence_threshold = float((settings or {}).get("confidence", 0.0)) if settings else 0.0
        decimal_position = (settings or {}).get("reading", {}).get("decimal_position") if settings else None
        meter = interpret_digits(detections, confidence_threshold, decimal_position)
        return InferenceResult(meter.value, meter.confidence, detections,
                                (perf_counter() - started) * 1000, engine="cpp_onnx", model_id=self.model_id)
