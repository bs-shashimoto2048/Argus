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
from app.inference.meter_interpreter import interpret_digits
from app.services.preprocess_service import apply, crop_roi
from app.schemas.inference import Roi
from reading.models import ConfirmedReading, ReadingSettings
from reading.stabilizer import ReadingStabilizer

# ROIを設定して物体検出(object_detection/ultralytics)で推論する際、指定ROIの
# 領域をそのまま(文脈なしで)crop・推論すると検出数が0になることを実機検証で確認した
# (Issue #16)。数字表示部だけをタイトにcropすると、対象がフレームに対して学習時より
# 不自然に大きく写り、モデルが検出できなくなる。ROI自体の幅/高さに対してこの比率だけ
# 周囲へ余白を広げてcropすることで、モデルに十分な文脈を与えつつ、実測で検出が
# 安定して復活することを確認した値(margin=1.0: 左右上下にROI自体のwidth/height分だけ広げる)。
_ROI_INFERENCE_MARGIN = 1.0


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
            # ユーザーが指定した本来のROI(結果を絞り込む境界)。
            roi_x1, roi_y1 = int(full_width * roi.x), int(full_height * roi.y)
            roi_x2 = max(roi_x1 + 1, int(full_width * (roi.x + roi.width)))
            roi_y2 = max(roi_y1 + 1, int(full_height * (roi.y + roi.height)))
            # 物体検出(object_detection/ultralytics)のみ、モデルに文脈を与えるため
            # margin付きでcropする(理由は_ROI_INFERENCE_MARGINのコメント参照)。
            # OCR系(easyocr/tesseract)は対象外(全文字を読むため、ROI外の文字列が
            # 混入するリスクがあり、この修正のスコープ外)。
            is_object_detection = self.settings.get("method") == "object_detection"
            if is_object_detection:
                margin_x, margin_y = roi.width * _ROI_INFERENCE_MARGIN, roi.height * _ROI_INFERENCE_MARGIN
                x1 = int(full_width * max(0.0, roi.x - margin_x))
                y1 = int(full_height * max(0.0, roi.y - margin_y))
                x2 = int(full_width * min(1.0, roi.x + roi.width + margin_x))
                y2 = int(full_height * min(1.0, roi.y + roi.height + margin_y))
                x1, y1 = min(x1, roi_x1), min(y1, roi_y1)
                x2, y2 = max(x2, roi_x2), max(y2, roi_y2)
            else:
                x1, y1, x2, y2 = roi_x1, roi_y1, roi_x2, roi_y2
            x2, y2 = max(x1 + 1, x2), max(y1 + 1, y2)
            crop = raw[y1:y2, x1:x2]
            pil = Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
            processed = apply(crop_roi(pil, None), self.settings.get("preprocessing") or {})
            image = cv2.cvtColor(np.asarray(processed), cv2.COLOR_RGB2BGR)
            result = self.engine.infer(image, self.settings)
            result.processing_time_ms = (perf_counter() - started) * 1000
            sx = crop.shape[1] / max(1, image.shape[1])
            sy = crop.shape[0] / max(1, image.shape[0])
            for detection in result.detections:
                if detection.bbox:
                    bx1, by1, bx2, by2 = detection.bbox
                    detection.bbox = (x1 + bx1 * sx, y1 + by1 * sy, x1 + bx2 * sx, y1 + by2 * sy)
            if is_object_detection and (x1, y1, x2, y2) != (roi_x1, roi_y1, roi_x2, roi_y2):
                # margin付きcropで拾った、ユーザー指定ROI外の検出は結果へ反映しない
                # (推論への文脈提供と、「ROI外は検出対象外」という利用者の意図の両立)。
                in_roi = []
                for detection in result.detections:
                    if not detection.bbox:
                        continue
                    dx1, dy1, dx2, dy2 = detection.bbox
                    cx, cy = (dx1 + dx2) / 2, (dy1 + dy2) / 2
                    if roi_x1 <= cx <= roi_x2 and roi_y1 <= cy <= roi_y2:
                        in_roi.append(detection)
                if len(in_roi) != len(result.detections):
                    result.detections = in_roi
                    if in_roi:
                        meter = interpret_digits(in_roi, self.settings.get("confidence", 0.25), (self.settings.get("reading") or {}).get("decimal_position"))
                        result.value, result.confidence = meter.value, meter.confidence
                        result.error = None
                    else:
                        result.value, result.confidence, result.error = None, None, "NO_DETECTION"
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
