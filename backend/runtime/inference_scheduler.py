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

# ROIのセマンティクス(Issue #16: 実機3台での比較検証により再整理)。
#
#   ROI = ユーザーが指定する「関心領域」。常に「最終的に採用するDetectionの中心が
#         入っている範囲」としてのみ使う(=最終結果はROI内のみ)。
#
#   object_detection(ultralytics)には roi_mode という選択肢がある:
#     - filter_only (既定・推奨): Full Frameで推論し、ROI内中心のDetectionだけ採用する。
#       学習時と同じ文脈/スケールを維持できるため、実機3台の比較で
#       margin crop方式より検出数・reading品質が同等以上だった
#       (特にMonitor 4ではmargin=1.0でもFull Frameに劣る結果だった。詳細はdocs参照)。
#     - crop_context (詳細設定): ROI自体をタイトにcropすると検出数が0になることがある
#       (対象がフレームに対して学習時より不自然に大きく写るため)、周囲へ
#       context_margin比率(ROI自体のwidth/height比)だけ広げてcropしてから推論する。
#       実機比較でmargin<1.0(0.25/0.5)は文脈不足で検出0件になるケースがあり、
#       1.0を既定値とする。
#
#   OCR(easyocr/tesseract)はroi_modeの影響を受けない。文字認識ではROIそのものを
#   入力領域にする意味があるため、常にROIをそのままcropする(既存挙動を維持)。
_DEFAULT_CONTEXT_MARGIN = 1.0

# Overlay描画色(BGR)。detection bbox([37,99,235])とは明確に区別する。
_ROI_COLOR = (255, 191, 0)  # ユーザー指定ROI: コバルトブルー破線、常時描画
_CROP_COLOR = (0, 165, 255)  # crop_context時の内部推論crop範囲: アンバー破線(filter_onlyでは描画しない)


def _draw_dashed_rect(image: np.ndarray, pt1: tuple[int, int], pt2: tuple[int, int], color: tuple[int, int, int], thickness: int = 2, dash: int = 10, gap: int = 6) -> None:
    """破線の矩形を描画する(cv2に破線矩形の組込みAPIが無いため自前実装)。

    ユーザー指定ROIと、object_detectionのmargin付き内部推論crop範囲を、
    detection bboxの実線と混同しないよう区別して描画するために使う(Issue #16)。
    """
    (x1, y1), (x2, y2) = pt1, pt2
    for (sx, sy), (ex, ey) in (((x1, y1), (x2, y1)), ((x2, y1), (x2, y2)), ((x2, y2), (x1, y2)), ((x1, y2), (x1, y1))):
        length = max(1, int(((ex - sx) ** 2 + (ey - sy) ** 2) ** 0.5))
        step = dash + gap
        for i in range(length // step + 1):
            t0 = min(1.0, (i * step) / length)
            t1 = min(1.0, (i * step + dash) / length)
            cv2.line(image, (int(sx + (ex - sx) * t0), int(sy + (ey - sy) * t0)), (int(sx + (ex - sx) * t1), int(sy + (ey - sy) * t1)), color, thickness)


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
        # Issue #16追加: 実際にengine.infer()へ渡した最終推論入力画像そのもの(表示用の
        # 再生成ではない)と、ROI/crop/前処理/検出数のpipeline diagnostics。
        self.latest_inference_input: bytes | None = None
        self.latest_diagnostics: dict = {}

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
            # roi_modeはobject_detection(ultralytics)のみ意味を持つ。method=="object_detection"
            # のままengineがtesseract/easyocrに設定されている場合(実UIで確認された組み合わせ)は
            # create_engine()もYoloInferenceEngineを返さないため、OCR系と同じ扱い(タイトROI)にする。
            is_object_detection = self.settings.get("method") == "object_detection" and self.settings.get("engine") == "ultralytics"
            roi_mode = self.settings.get("roi_mode", "filter_only") if is_object_detection else None
            if is_object_detection and roi_mode == "crop_context":
                margin = float(self.settings.get("context_margin", _DEFAULT_CONTEXT_MARGIN))
                margin_x, margin_y = roi.width * margin, roi.height * margin
                x1 = int(full_width * max(0.0, roi.x - margin_x))
                y1 = int(full_height * max(0.0, roi.y - margin_y))
                x2 = int(full_width * min(1.0, roi.x + roi.width + margin_x))
                y2 = int(full_height * min(1.0, roi.y + roi.height + margin_y))
                x1, y1 = min(x1, roi_x1), min(y1, roi_y1)
                x2, y2 = max(x2, roi_x2), max(y2, roi_y2)
            elif is_object_detection:  # filter_only: Full Frameで推論する
                x1, y1, x2, y2 = 0, 0, full_width, full_height
            else:  # OCR / method!=object_detection: 従来通りROIそのものをcropする
                x1, y1, x2, y2 = roi_x1, roi_y1, roi_x2, roi_y2
            x2, y2 = max(x1 + 1, x2), max(y1 + 1, y2)
            crop = raw[y1:y2, x1:x2]
            pil = Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
            processed = apply(crop_roi(pil, None), self.settings.get("preprocessing") or {})
            image = cv2.cvtColor(np.asarray(processed), cv2.COLOR_RGB2BGR)

            # Issue #16: 実際にEngineへ渡す最終推論入力画像(image)そのものをJPEG化して
            # 保存する。UI表示用に別途再生成せず、本番推論と同一のデータ経路から取得する。
            ok_input, encoded_input = cv2.imencode(".jpg", image)
            self.latest_inference_input = encoded_input.tobytes() if ok_input else None

            result = self.engine.infer(image, self.settings)
            result.processing_time_ms = (perf_counter() - started) * 1000
            raw_detection_count = len(result.detections)
            sx = crop.shape[1] / max(1, image.shape[1])
            sy = crop.shape[0] / max(1, image.shape[0])
            for detection in result.detections:
                if detection.bbox:
                    bx1, by1, bx2, by2 = detection.bbox
                    detection.bbox = (x1 + bx1 * sx, y1 + by1 * sy, x1 + bx2 * sx, y1 + by2 * sy)
            roi_filtered_detection_count = raw_detection_count
            if is_object_detection:
                # filter_only/crop_contextいずれも、ROI外に中心があるDetectionは
                # 結果へ反映しない(「最終結果は常にROI内」というROIのセマンティクス)。
                in_roi = []
                for detection in result.detections:
                    if not detection.bbox:
                        continue
                    dx1, dy1, dx2, dy2 = detection.bbox
                    cx, cy = (dx1 + dx2) / 2, (dy1 + dy2) / 2
                    if roi_x1 <= cx <= roi_x2 and roi_y1 <= cy <= roi_y2:
                        in_roi.append(detection)
                roi_filtered_detection_count = len(in_roi)
                if len(in_roi) != len(result.detections):
                    result.detections = in_roi
                    if in_roi:
                        meter = interpret_digits(in_roi, self.settings.get("confidence", 0.25), (self.settings.get("reading") or {}).get("decimal_position"))
                        result.value, result.confidence = meter.value, meter.confidence
                        result.error = None
                    else:
                        result.value, result.confidence, result.error = None, None, "NO_DETECTION"
            self.latest_result = result
            # Issue #16: ROI/crop/前処理/検出数のpipeline diagnostics(secretは含まない)。
            self.latest_diagnostics = {
                "frame_width": full_width,
                "frame_height": full_height,
                "roi_mode": roi_mode,  # object_detection以外(OCR等)はNone
                "context_margin": float(self.settings.get("context_margin", _DEFAULT_CONTEXT_MARGIN)) if roi_mode == "crop_context" else None,
                "roi_normalized": roi.model_dump(),
                "roi_pixel": [roi_x1, roi_y1, roi_x2, roi_y2],
                "inference_crop_pixel": [x1, y1, x2, y2],
                "crop_shape": [int(crop.shape[0]), int(crop.shape[1])],
                "preprocess_output_shape": [int(image.shape[0]), int(image.shape[1])],
                # model_input_shape: 現状の実装では、前処理後の画像(image)をそのまま
                # engine.infer()へ渡しており、Scheduler側で追加のresizeは行っていないため
                # preprocess_output_shapeと同一になる。Engine内部(例:ultralyticsの
                # letterbox)でさらに変形される場合があるが、それはEngine内部の実装詳細で
                # Scheduler側からは追跡できないため、ここでは「Engineへ渡した画像のshape」
                # を報告する。
                "model_input_shape": [int(image.shape[0]), int(image.shape[1])],
                "raw_detection_count": raw_detection_count,
                "roi_filtered_detection_count": roi_filtered_detection_count,
                "engine": result.engine,
                "model_id": result.model_id or self.settings.get("model_id"),
            }
            overlay = raw.copy()
            # ユーザーが指定した実ROIは常時描画する(コバルトブルー破線)。
            _draw_dashed_rect(overlay, (roi_x1, roi_y1), (roi_x2, roi_y2), _ROI_COLOR, 2)
            # crop_contextモードの場合のみ、内部推論crop範囲を区別できる別スタイル
            # (アンバー破線)で追加描画する(filter_onlyでは内部crop枠は表示しない)。
            if roi_mode == "crop_context" and (x1, y1, x2, y2) != (roi_x1, roi_y1, roi_x2, roi_y2):
                _draw_dashed_rect(overlay, (x1, y1), (x2, y2), _CROP_COLOR, 1)
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
