from __future__ import annotations

import shutil
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np

from .base import Detection, InferenceEngine, InferenceResult, ModelRegistry
from .device import resolve_device
from .meter_interpreter import interpret_digits, normalize_meter_text

# Windows既定のTesseractインストール先。PATH未登録でも検出できるようフォールバックで探索する。
_WINDOWS_TESSERACT_PATHS = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
)


def _find_tesseract_executable() -> str | None:
    found = shutil.which("tesseract")
    if found:
        return found
    for candidate in _WINDOWS_TESSERACT_PATHS:
        if Path(candidate).is_file():
            return candidate
    return None


class _UnavailableEngine(InferenceEngine):
    """デバイス解決やライブラリ未導入でEngineが構築できない場合のフォールバック。

    例外を構築時点(create_engine)で外に伝播させると、Runtime起動やアプリ全体の
    起動処理を巻き込んで落としてしまうため、常にエラー結果を返すEngineに置き換える。
    """

    def __init__(self, error: str, engine_name: str) -> None:
        self.error = error
        self.engine_name = engine_name

    def infer(self, image: np.ndarray, settings: Any | None = None) -> InferenceResult:
        return InferenceResult(error=self.error, engine=self.engine_name)


class YoloInferenceEngine(InferenceEngine):
    def __init__(self, model_id: str, device: str, confidence: float, iou: float, image_size: int, registry: ModelRegistry, model_root: Path) -> None:
        self.model_id = model_id
        self.device = resolve_device(device)
        self.confidence = confidence
        self.iou = iou
        self.image_size = image_size
        self._registry = registry
        self._model_root = model_root.resolve()

    def _model(self):
        candidate = Path(self.model_id)
        candidate = candidate if candidate.is_absolute() else self._model_root / candidate
        candidate = candidate.resolve()
        if self._model_root not in candidate.parents and candidate != self._model_root:
            raise ValueError("MODEL_NOT_FOUND")
        if not candidate.is_file():
            raise FileNotFoundError("MODEL_NOT_FOUND")

        def load():
            try:
                from ultralytics import YOLO
            except ImportError as exc:
                raise RuntimeError("MODEL_NOT_CONFIGURED: ultralytics is not installed") from exc
            return YOLO(str(candidate))

        return self._registry.get(str(candidate), self.device, load, "ultralytics")

    def infer(self, image: np.ndarray, settings: Any | None = None) -> InferenceResult:
        started = perf_counter()
        try:
            model = self._model()
        except (FileNotFoundError, ValueError):
            return InferenceResult(error="MODEL_NOT_FOUND", processing_time_ms=(perf_counter() - started) * 1000, engine="ultralytics", model_id=self.model_id)
        except RuntimeError:
            return InferenceResult(error="MODEL_NOT_CONFIGURED", processing_time_ms=(perf_counter() - started) * 1000, engine="ultralytics", model_id=self.model_id)
        try:
            results = model.predict(image, conf=self.confidence, iou=self.iou, imgsz=self.image_size, device=self.device, verbose=False)
            detections: list[Detection] = []
            result = results[0]
            names = getattr(result, "names", {})
            boxes = getattr(result, "boxes", None)
            if boxes is not None:
                for box, confidence, class_id in zip(boxes.xyxy.tolist(), boxes.conf.tolist(), boxes.cls.tolist()):
                    index = int(class_id)
                    detections.append(Detection(index, str(names.get(index, index)), float(confidence), tuple(float(value) for value in box)))
            if not detections:
                return InferenceResult(error="NO_DETECTION", processing_time_ms=(perf_counter() - started) * 1000, engine="ultralytics", model_id=self.model_id)
            meter = interpret_digits(detections, self.confidence)
            return InferenceResult(meter.value, meter.confidence, detections, (perf_counter() - started) * 1000, engine="ultralytics", model_id=self.model_id)
        except Exception:
            return InferenceResult(error="INFERENCE_FAILED", processing_time_ms=(perf_counter() - started) * 1000, engine="ultralytics", model_id=self.model_id)


class EasyOcrInferenceEngine(InferenceEngine):
    def __init__(self, languages: list[str], device: str, registry: ModelRegistry) -> None:
        self.languages = languages
        self.device = resolve_device(device)
        self.registry = registry

    def infer(self, image: np.ndarray, settings: Any | None = None) -> InferenceResult:
        started = perf_counter()
        try:
            import easyocr
            key = ",".join(self.languages)
            reader = self.registry.get(key, self.device, lambda: easyocr.Reader(self.languages, gpu=self.device.startswith("cuda:")), "easyocr")
            detections: list[Detection] = []
            for polygon, text, confidence in reader.readtext(image):
                points = np.asarray(polygon)
                x1, y1 = points.min(axis=0)
                x2, y2 = points.max(axis=0)
                detections.append(Detection(None, text, float(confidence), (float(x1), float(y1), float(x2), float(y2))))
            if not detections:
                return InferenceResult(error="NO_DETECTION", processing_time_ms=(perf_counter() - started) * 1000, engine="easyocr")
            value = normalize_meter_text("".join(item.class_name or "" for item in detections))
            confidence = sum(item.confidence or 0 for item in detections) / len(detections)
            return InferenceResult(value, confidence, detections, (perf_counter() - started) * 1000, engine="easyocr")
        except ImportError:
            return InferenceResult(error="OCR_ENGINE_UNAVAILABLE", processing_time_ms=(perf_counter() - started) * 1000, engine="easyocr")
        except Exception:
            return InferenceResult(error="INFERENCE_FAILED", processing_time_ms=(perf_counter() - started) * 1000, engine="easyocr")


class TesseractInferenceEngine(InferenceEngine):
    def __init__(self, language: str, psm: int, oem: int, executable_path: str | None = None) -> None:
        self.language, self.psm, self.oem, self.executable_path = language, psm, oem, executable_path

    def infer(self, image: np.ndarray, settings: Any | None = None) -> InferenceResult:
        started = perf_counter()
        try:
            import pytesseract
        except ImportError:
            return InferenceResult(error="OCR_ENGINE_UNAVAILABLE", processing_time_ms=(perf_counter() - started) * 1000, engine="tesseract")
        try:
            pytesseract.pytesseract.tesseract_cmd = self.executable_path or _find_tesseract_executable() or pytesseract.pytesseract.tesseract_cmd
            config = f"--psm {self.psm} --oem {self.oem}"
            text = pytesseract.image_to_string(image, lang=self.language, config=config)
            value = normalize_meter_text(text)
            if value is None:
                return InferenceResult(error="NO_DETECTION", processing_time_ms=(perf_counter() - started) * 1000, engine="tesseract")
            return InferenceResult(value, None, [], (perf_counter() - started) * 1000, engine="tesseract")
        except pytesseract.pytesseract.TesseractNotFoundError:
            return InferenceResult(error="TESSERACT_NOT_INSTALLED", processing_time_ms=(perf_counter() - started) * 1000, engine="tesseract")
        except Exception:
            return InferenceResult(error="INFERENCE_FAILED", processing_time_ms=(perf_counter() - started) * 1000, engine="tesseract")


def create_engine(settings: dict[str, Any], registry: ModelRegistry, model_root: Path) -> InferenceEngine | None:
    """設定からInferenceEngineを組み立てる。

    device解決失敗（GPU無し、PyTorch未導入等）はここでは伝播させない。
    構築自体を落とすとRuntime起動・アプリ起動全体を巻き込むため、
    常に`DEVICE_UNAVAILABLE`を返す_UnavailableEngineに差し替える。
    """
    method = settings.get("method", "object_detection")
    engine = settings.get("engine", "ultralytics")
    device = settings.get("device", "auto")
    try:
        if method == "object_detection" and engine == "ultralytics":
            model_id = settings.get("model_id")
            return YoloInferenceEngine(model_id, device, settings.get("confidence", 0.25), settings.get("iou", 0.7), settings.get("image_size", 640), registry, model_root) if model_id else None
        options = settings.get("engine_options") or {}
        if engine == "easyocr":
            return EasyOcrInferenceEngine(options.get("languages", ["en"]), device, registry)
        if engine == "tesseract":
            return TesseractInferenceEngine(options.get("language", "eng"), int(options.get("psm", 6)), int(options.get("oem", 3)), options.get("executable_path"))
        return None
    except ValueError:
        return _UnavailableEngine("DEVICE_UNAVAILABLE", engine)
