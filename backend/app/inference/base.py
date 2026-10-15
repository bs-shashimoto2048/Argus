from __future__ import annotations

import logging
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

    def close(self) -> None:
        """保持中のうちstop()を持つもの(cpp worker等の外部プロセス)を停止してから破棄する。

        1件の停止失敗が他の停止を妨げないよう、例外は握りつぶさずログへ残して続行する。
        """
        with self._lock:
            items = list(self._cache.values())
            self._cache.clear()
        for item in items:
            stop = getattr(item, "stop", None)
            if callable(stop):
                try:
                    stop()
                except Exception:
                    logging.getLogger("argus.shutdown").exception("モデル資源の停止に失敗しました")

    def size(self) -> int:
        with self._lock:
            return len(self._cache)
