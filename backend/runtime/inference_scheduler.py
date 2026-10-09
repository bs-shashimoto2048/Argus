from __future__ import annotations

import logging
from datetime import datetime, timezone

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
from reading.baseline import CONFLICT_ALERT_SECONDS
from reading.models import ConfirmedReading, ReadingSettings
from reading.stabilizer import ReadingStabilizer
from .record_snapshot import InferenceRecordSnapshot

logger = logging.getLogger("argus.scheduler")

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

# Overlay描画色(BGR)。overlay.jpgは「前処理後画像(inference-input.jpgと同じ見た目) + bbox + ラベル」。
_ROI_COLOR = (255, 191, 0)  # ユーザー指定ROI: コバルトブルー破線(推論cropがROIと異なる場合のみ描画)
_BBOX_COLOR = (20, 255, 57)  # detection bboxの枠線とラベル: 蛍光緑(#39FF14)


# overlay.jpgの表示範囲: 検出bbox群の外接矩形に余白を付けて切り出し、小さければ拡大して数字部分を大きく見せる。
# 推論そのもの(Full Frame/ROI cropでの推論、Raw/Confirmed)には影響しない、表示だけの処理。
_OVERLAY_MARGIN_RATIO = 0.12  # 外接矩形の幅/高さに対する上下左右の余白
_OVERLAY_MIN_WIDTH = 480  # 切り出し後の幅がこれ以上なら拡大しない(Drum等、既に読みやすい大きさ)
_OVERLAY_TARGET_WIDTH = 960  # 拡大する場合の目標幅(アスペクト比は維持)
_OVERLAY_MAX_SCALE = 6.0
_OVERLAY_MAX_HEIGHT = 720  # 拡大後の高さの上限
_OVERLAY_LABEL_HEADROOM = 24  # bbox上端より上に確保するラベル用の余白(表示後のpixel)


def _overlay_view(image_shape: tuple[int, ...], boxes: list[tuple[float, float, float, float]]) -> tuple[int, int, int, int, float]:
    """bbox群の外接矩形を基準にした、overlayの切り出し範囲と拡大率(x1, y1, x2, y2, scale)を返す。

    前処理後画像の座標系で、画像端を超える余白はクランプする。ラベルを描く分だけ上側の余白を広く取る。
    """
    height, width = image_shape[:2]
    ux1, uy1 = min(box[0] for box in boxes), min(box[1] for box in boxes)
    ux2, uy2 = max(box[2] for box in boxes), max(box[3] for box in boxes)
    union_w, union_h = max(1.0, ux2 - ux1), max(1.0, uy2 - uy1)
    x1, x2 = max(0.0, ux1 - union_w * _OVERLAY_MARGIN_RATIO), min(float(width), ux2 + union_w * _OVERLAY_MARGIN_RATIO)
    crop_w = max(1.0, x2 - x1)
    scale = 1.0 if crop_w >= _OVERLAY_MIN_WIDTH else min(_OVERLAY_MAX_SCALE, _OVERLAY_TARGET_WIDTH / crop_w)
    y1 = max(0.0, uy1 - max(union_h * _OVERLAY_MARGIN_RATIO, _OVERLAY_LABEL_HEADROOM / scale))
    y2 = min(float(height), uy2 + union_h * _OVERLAY_MARGIN_RATIO)
    crop_h = max(1.0, y2 - y1)
    if scale > 1.0 and crop_h * scale > _OVERLAY_MAX_HEIGHT:
        scale = max(1.0, _OVERLAY_MAX_HEIGHT / crop_h)
    ix1, iy1 = int(np.floor(x1)), int(np.floor(y1))
    ix2, iy2 = max(ix1 + 1, int(np.ceil(x2))), max(iy1 + 1, int(np.ceil(y2)))
    return ix1, iy1, min(ix2, int(width)), min(iy2, int(height)), scale


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
    def __init__(self, monitor_id: int, buffer, settings: dict, model_registry: ModelRegistry, model_root: Path, on_result: Callable[[int, ConfirmedReading], None], baseline_provider=None) -> None:
        self.monitor_id = monitor_id
        self.buffer = buffer
        self.settings = settings
        self.on_result = on_result
        self.engine = create_engine(settings, model_registry, model_root)
        # Raw Reading -> Confirmed Readingへの時系列安定化。InferenceScheduler自体が
        # Engine/Model/ROI/Preprocessing/Device変更や再起動のたびに新規構築されるため、
        # ここに紐付けるだけでbufferのresetが自然に満たされる。
        reading_settings = ReadingSettings.from_dict(settings.get("reading"))
        baseline, epoch, conflict = None, 0, None
        if baseline_provider is not None and reading_settings.enabled:
            # Raw window/連続失敗回数は再構築のたびに初期化されるが、monotonic baselineはDBから復元する。
            # 復元に失敗した場合は従来どおりbaselineなしで開始する(provider側でもログを出す)。
            try:
                baseline, epoch, conflict = baseline_provider(monitor_id, reading_settings)
            except Exception:
                logger.exception("monitor %s: baselineの復元に失敗しました", monitor_id)
        self.stabilizer = ReadingStabilizer(reading_settings, baseline, epoch, conflict)
        self._stop = Event()
        self._thread: Thread | None = None
        self._busy = Lock()
        self.latest_result: InferenceResult | None = None
        self.latest_confirmed: ConfirmedReading | None = None
        self.latest_overlay: bytes | None = None
        # overlayの元になったフレーム(JPEG)。1時間記録の「元画像」と「overlay」を同じフレームにするために保持する(推論には使わない)。
        self.latest_overlay_source: bytes | None = None
        # Issue #16追加: 実際にengine.infer()へ渡した最終推論入力画像そのもの(表示用の
        # 再生成ではない)と、ROI/crop/前処理/検出数のpipeline diagnostics。
        self.latest_inference_input: bytes | None = None
        self.latest_diagnostics: dict = {}
        # 1推論tick = 1 immutable snapshot(定時計測recordの証跡用)。tickの処理がすべて終わってから、丸ごと差し替える。
        self._snapshot: InferenceRecordSnapshot | None = None
        self._snapshot_lock = Lock()
        self._tick = 0

    def get_record_snapshot(self) -> InferenceRecordSnapshot | None:
        """直近の完了した推論tickのsnapshotを取得する(不変オブジェクトなので、取得後に別tickの値が混ざらない)。"""
        with self._snapshot_lock:
            return self._snapshot

    def _publish_snapshot(self, snapshot: InferenceRecordSnapshot) -> None:
        with self._snapshot_lock:
            self._snapshot = snapshot  # オブジェクトを丸ごと交換する(フィールド単位の更新はしない)

    def _build_snapshot(self, *, inference_at: datetime, captured_at: datetime | None, original: bytes | None, overlay: bytes | None,
                        result: InferenceResult, confirmed: ConfirmedReading, formal: dict | None, processing_time_ms: float) -> InferenceRecordSnapshot:
        """そのtickの情報だけから、snapshotを組み立てる(推論・overlay・Stabilizer・運用値の保存がすべて終わった後に呼ぶ)。"""
        self._tick += 1
        baseline = self.stabilizer.baseline_snapshot()
        conflict = confirmed.conflict
        now = datetime.now(timezone.utc)
        conflict_alert = conflict is not None and (now - conflict.started_at).total_seconds() >= CONFLICT_ALERT_SECONDS
        candidate = self.stabilizer.last_candidate
        status = confirmed.validation_status.value
        if formal is None:
            # 運用値の保存結果が無い場合(on_resultが値を返さない構成)は、このtickの採用結果だけから判断する。
            accepted = status in ("confirmed", "low_confidence")
            formal = {"value": confirmed.value if accepted else None, "confidence": confirmed.confidence if accepted else None, "confirmed_at": confirmed.confirmed_at if accepted else None, "status": None}
        return InferenceRecordSnapshot(
            monitor_id=self.monitor_id, tick=self._tick, inference_at=inference_at, captured_at=captured_at,
            original_jpeg=original, overlay_jpeg=overlay,
            raw_value=confirmed.raw_value, raw_confidence=confirmed.raw_confidence, raw_error=confirmed.raw_error, detection_count=len(result.detections),
            validation_status=status, candidate_value=candidate["value"] if candidate else None, agreement_count=confirmed.agreement_count, raw_count=confirmed.raw_count,
            confirmed_value=formal.get("value"), confirmed_confidence=formal.get("confidence"), confirmed_at=formal.get("confirmed_at"), inference_status=formal.get("status"),
            engine=result.engine or confirmed.engine or None, model_id=result.model_id or self.settings.get("model_id"), processing_time_ms=processing_time_ms,
            baseline_value=baseline["value"] if baseline else None, baseline_epoch=int(confirmed.baseline_epoch or 0),
            baseline_conflict=bool(conflict_alert), conflict_status=conflict.status.value if conflict else None,
            conflict_candidate=conflict.candidate if conflict else None, conflict_count=conflict.count if conflict else 0,
        )

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
        inference_at = datetime.now(timezone.utc)
        data, frame_ts = self.buffer.get()
        if not data or self.engine is None:
            return
        captured_at = datetime.fromtimestamp(frame_ts, timezone.utc) if frame_ts else None
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
            # overlayは前処理後画像の座標系で描画するため、full-frame座標へ変換する前のbboxを控える。
            model_space_boxes = {id(detection): detection.bbox for detection in result.detections}
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
            # 前処理後画像(engine.infer()へ渡した画像そのもの。inference-input.jpgと同じ見た目)の上へ、
            # bboxとラベルを描く。bboxは前処理後画像の座標系(model_space_boxes)のまま描画する。
            drawn = [(detection, model_space_boxes.get(id(detection))) for detection in result.detections]
            drawn = [(detection, box) for detection, box in drawn if box]
            if drawn:
                # 検出がある場合: bbox群の外接矩形(+余白)で切り出し、小さければ拡大して数字部分を大きく見せる。
                vx1, vy1, vx2, vy2, view_scale = _overlay_view(image.shape, [box for _detection, box in drawn])
                overlay = image[vy1:vy2, vx1:vx2]
                if view_scale != 1.0:
                    overlay = cv2.resize(overlay, None, fx=view_scale, fy=view_scale, interpolation=cv2.INTER_CUBIC)
                else:
                    overlay = overlay.copy()
            else:
                # 検出が無い(初期状態/検出失敗)場合は、従来どおり前処理後の全体画像を表示する。
                vx1, vy1, view_scale = 0, 0, 1.0
                overlay = image.copy()

            def to_view(px: float, py: float) -> tuple[int, int]:
                return int(round((px - vx1) * view_scale)), int(round((py - vy1) * view_scale))

            if (x1, y1, x2, y2) != (roi_x1, roi_y1, roi_x2, roi_y2):
                # 推論cropがROIより広い場合(filter_only/crop_context)は、ユーザー指定ROIを前処理後画像の
                # 座標系へ変換し、表示範囲の座標系で破線を描く(ROIそのものをcropする場合は画像全体がROIのため描かない)。
                scale_x = image.shape[1] / max(1, crop.shape[1])
                scale_y = image.shape[0] / max(1, crop.shape[0])
                _draw_dashed_rect(overlay, to_view((roi_x1 - x1) * scale_x, (roi_y1 - y1) * scale_y), to_view((roi_x2 - x1) * scale_x, (roi_y2 - y1) * scale_y), _ROI_COLOR, 2)
            for detection, box in drawn:
                bx1, by1 = to_view(box[0], box[1])
                bx2, by2 = to_view(box[2], box[3])
                cv2.rectangle(overlay, (bx1, by1), (bx2, by2), _BBOX_COLOR, 2)
                cv2.putText(overlay, f"{detection.class_name or ''}/{detection.confidence or 0:.2f}", (bx1, max(16, by1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, _BBOX_COLOR, 1)
            ok, encoded = cv2.imencode(".jpg", overlay)
            tick_overlay = encoded.tobytes() if ok else None
            self.latest_overlay = tick_overlay
            self.latest_overlay_source = data if ok else None
            confirmed = self.stabilizer.update(result)
            self.latest_confirmed = confirmed
            formal = self.on_result(self.monitor_id, confirmed)
            # このtickのsnapshot: 元画像(推論に使ったフレームそのもの)・overlay・Raw・判定・運用値・baselineをすべて同じtickの値で1つにまとめて公開する。
            self._publish_snapshot(self._build_snapshot(inference_at=inference_at, captured_at=captured_at, original=data, overlay=tick_overlay, result=result, confirmed=confirmed,
                                                        formal=formal if isinstance(formal, dict) else None, processing_time_ms=result.processing_time_ms))
        except Exception:
            result = InferenceResult(error="INFERENCE_FAILED", processing_time_ms=(perf_counter() - started) * 1000)
            self.latest_result = result
            confirmed = self.stabilizer.update(result)
            self.latest_confirmed = confirmed
            formal = self.on_result(self.monitor_id, confirmed)
            # 失敗したtickでも、その時点の完全なsnapshotを作る(overlayは無い。別tickのoverlayは使わない)。
            self._publish_snapshot(self._build_snapshot(inference_at=inference_at, captured_at=captured_at, original=data, overlay=None, result=result, confirmed=confirmed,
                                                        formal=formal if isinstance(formal, dict) else None, processing_time_ms=result.processing_time_ms))
