from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any
import numpy as np

@dataclass
class Detection:
    class_name: str
    confidence: float
    box: tuple[float, float, float, float]

@dataclass
class InferenceResult:
    value: str | None = None
    confidence: float | None = None
    detections: list[Detection] = field(default_factory=list)
    processing_time_ms: float | None = None
    error: str | None = None

class InferenceEngine(ABC):
    @abstractmethod
    def infer(self, frame: np.ndarray) -> InferenceResult: ...

class ModelRegistry:
    """将来の共有モデルキャッシュ用インターフェース。MVPではロードしない。"""
    def get(self, model_id: str, device: str = "auto") -> Any:
        raise NotImplementedError("AI inference is scheduled for the next phase")
