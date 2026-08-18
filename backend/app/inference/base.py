from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Callable

import numpy as np


@dataclass
class Detection:
    class_id: int | None = None
    class_name: str | None = None
    confidence: float | None = None
    bbox: tuple[float, float, float, float] | None = None


@dataclass
class InferenceResult:
    value: str | None = None
    confidence: float | None = None
    detections: list[Detection] = field(default_factory=list)
    processing_time_ms: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    error: str | None = None
    engine: str = ""
    model_id: str | None = None


class InferenceEngine(ABC):
    @abstractmethod
    def infer(self, image: np.ndarray, settings: Any | None = None) -> InferenceResult:
        raise NotImplementedError


class ModelRegistry:
    """同一キーのモデルを共有するスレッドセーフなキャッシュ。"""

    def __init__(self) -> None:
        self._lock = RLock()
        self._cache: dict[tuple[str, str, str], Any] = {}

    def get(self, model_id: str, device: str = "auto", loader: Callable[[], Any] | None = None, engine_type: str = "default") -> Any:
        key = (engine_type, model_id, device)
        with self._lock:
            if key not in self._cache:
                if loader is None:
                    raise KeyError(f"model is not registered: {key}")
                self._cache[key] = loader()
            return self._cache[key]

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    def size(self) -> int:
        with self._lock:
            return len(self._cache)
