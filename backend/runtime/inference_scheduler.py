from __future__ import annotations

from io import BytesIO
from threading import Event, Lock, Thread
from time import monotonic, perf_counter
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
from PIL import Image

from app.inference.base import InferenceResult, ModelRegistry
from app.inference.engines import create_engine
from app.services.preprocess_service import apply, crop_roi
from app.schemas.inference import Roi
from reading.models import ConfirmedReading, ReadingSettings
from reading.stabilizer import ReadingStabilizer


class InferenceScheduler:
    def __init__(self, monitor_id: int, buffer, settings: dict, model_registry: ModelRegistry, model_root: Path, on_result: Callable[[int, ConfirmedReading], None]) -> None:
        self.monitor_id = monitor_id
        self.buffer = buffer
        self.settings = settings
        self.on_result = on_result
        self.engine = create_engine(settings, model_registry, model_root)
        # Raw Reading -> Confirmed Readingへの時系列安定化。InferenceScheduler自体が
        # Engine/Model/ROI/Preprocessing/Device変更や再起動のたびに新規構築されるため、
        # ここに紐付けるだけでbufferのresetが自然に満たされる。
        self.stabilizer = ReadingStabilizer(ReadingSettings.from_dict(settings.get("reading")))
        self._stop = Event()
        self._thread: Thread | None = None
        self._busy = Lock()
        self.latest_result: InferenceResult | None = None
        self.latest_confirmed: ConfirmedReading | None = None
        self.latest_overlay: bytes | None = None

    @property
    def enabled(self) -> bool:
        return self.engine is not None

    def start(self) -> None:
        if not self.enabled or self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = Thread(target=self._run, name=f"argus-inference-{self.monitor_id}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def _run(self) -> None:
        interval = 1.0 / max(1, int(self.settings.get("inference_fps", 5)))
        next_tick = monotonic()
        while not self._stop.is_set():
            if monotonic() < next_tick:
                self._stop.wait(max(0.01, next_tick - monotonic()))
                continue
            next_tick = monotonic() + interval
            if not self._busy.acquire(blocking=False):
                continue
            try:
                self._infer_latest()
            finally:
                self._busy.release()

    def _infer_latest(self) -> None:
        started = perf_counter()
        data, _ = self.buffer.get()
        if not data or self.engine is None:
            return
        try:
            raw = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
            if raw is None:
                return
            full_height, full_width = raw.shape[:2]
            roi = Roi.model_validate(self.settings.get("roi") or {})
            x1, y1 = int(full_width * roi.x), int(full_height * roi.y)
            x2, y2 = max(x1 + 1, int(full_width * (roi.x + roi.width))), max(y1 + 1, int(full_height * (roi.y + roi.height)))
            crop = raw[y1:y2, x1:x2]
            pil = Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
            processed = apply(crop_roi(pil, None), self.settings.get("preprocessing") or {})
            image = cv2.cvtColor(np.asarray(processed), cv2.COLOR_RGB2BGR)
            result = self.engine.infer(image, self.settings)
            result.processing_time_ms = (perf_counter() - started) * 1000
            for detection in result.detections:
                if detection.bbox:
                    bx1, by1, bx2, by2 = detection.bbox
                    sx = crop.shape[1] / max(1, image.shape[1])
                    sy = crop.shape[0] / max(1, image.shape[0])
                    detection.bbox = (x1 + bx1 * sx, y1 + by1 * sy, x1 + bx2 * sx, y1 + by2 * sy)
            self.latest_result = result
            overlay = raw.copy()
            for detection in result.detections:
                if detection.bbox:
                    bx1, by1, bx2, by2 = (int(value) for value in detection.bbox)
                    cv2.rectangle(overlay, (bx1, by1), (bx2, by2), (37, 99, 235), 2)
                    cv2.putText(overlay, f"{detection.class_name or ''} {detection.confidence or 0:.2f}", (bx1, max(16, by1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (37, 99, 235), 1)
            ok, encoded = cv2.imencode(".jpg", overlay)
            self.latest_overlay = encoded.tobytes() if ok else None
            confirmed = self.stabilizer.update(result)
            self.latest_confirmed = confirmed
            self.on_result(self.monitor_id, confirmed)
        except Exception:
            result = InferenceResult(error="INFERENCE_FAILED", processing_time_ms=(perf_counter() - started) * 1000)
            self.latest_result = result
            confirmed = self.stabilizer.update(result)
            self.latest_confirmed = confirmed
            self.on_result(self.monitor_id, confirmed)
