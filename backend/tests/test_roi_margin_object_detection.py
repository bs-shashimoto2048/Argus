"""Issue #16: ROI付き物体検出(object_detection/ultralytics)推論の回帰テスト。

実機検証で、ROIをタイトに(文脈なしで)crop・推論すると検出数が0になることを確認した
(meter_digits_v1.pt / meter_digits_v2_candidate_001_best.pt のどちらでも再現)。
InferenceScheduler._infer_latestが、

  - object_detectionの場合のみ、モデルへ文脈を与えるためROIへmarginを加えてcropすること
  - OCR(ocr method)の場合は既存どおりタイトROIのままcropすること(この修正のスコープ外)
  - margin付きcropで得た検出のbboxがfull-frame座標へ正しく復元されること
  - ユーザーが指定したROI外に中心があるdetectionは最終結果から除外され、
    value/confidenceがROI内の検出だけから再計算されること
  - ROI外の検出が無い場合(全てROI内)は何も変わらないこと

を確認する。
"""
from __future__ import annotations

import cv2
import numpy as np
import pytest

from app.inference.base import Detection, InferenceResult
from app.inference.registry import model_registry
from runtime.frame_buffer import LatestFrameBuffer
from runtime.inference_scheduler import InferenceScheduler

pytestmark = pytest.mark.unit

FULL_W, FULL_H = 200, 100
ROI = {"x": 0.25, "y": 0.2, "width": 0.25, "height": 0.3}  # pixel: x[50,100) y[20,50)


def _make_frame(width: int, height: int) -> bytes:
    image = np.zeros((height, width, 3), dtype=np.uint8)
    ok, encoded = cv2.imencode(".jpg", image)
    assert ok
    return encoded.tobytes()


class _RecordingEngine:
    """受け取ったcrop画像の形状を記録し、指定したdetections(crop-local座標)を返す。"""

    def __init__(self, detections: list[Detection]):
        self.detections = detections
        self.seen_shapes: list[tuple[int, int]] = []

    def infer(self, image, settings=None):
        self.seen_shapes.append(image.shape[:2])
        return InferenceResult(detections=list(self.detections), engine="fake")


def _build_scheduler(monkeypatch, settings: dict, engine):
    monkeypatch.setattr("runtime.inference_scheduler.create_engine", lambda *a, **kw: engine)
    buffer = LatestFrameBuffer()
    buffer.put(_make_frame(FULL_W, FULL_H))
    results = []
    scheduler = InferenceScheduler(
        1, buffer, settings, model_registry, ".", lambda _id, value: results.append(value)
    )
    return scheduler, results


def test_object_detection_crops_with_margin_larger_than_tight_roi(monkeypatch, tmp_path):
    engine = _RecordingEngine([])
    settings = {"inference_fps": 10, "method": "object_detection", "roi": ROI, "preprocessing": {}}
    scheduler, _ = _build_scheduler(monkeypatch, settings, engine)
    scheduler._infer_latest()

    assert engine.seen_shapes, "engineへ画像が渡っていること"
    seen_h, seen_w = engine.seen_shapes[0]
    tight_w, tight_h = 50, 30  # ROIをそのままcropした場合のサイズ (x:50->100, y:20->50)
    assert seen_w > tight_w and seen_h > tight_h, "object_detectionではtight ROIより広くcropされること"


def test_non_object_detection_method_keeps_tight_roi_crop(monkeypatch, tmp_path):
    """OCR(method='ocr')は今回の修正対象外で、従来どおりタイトROIのままcropされること。"""
    engine = _RecordingEngine([])
    settings = {"inference_fps": 10, "method": "ocr", "roi": ROI, "preprocessing": {}}
    scheduler, _ = _build_scheduler(monkeypatch, settings, engine)
    scheduler._infer_latest()

    seen_h, seen_w = engine.seen_shapes[0]
    assert (seen_w, seen_h) == (50, 30), "OCR系はmarginを加えずtight ROIのままであること(既存挙動を維持)"


def test_detection_inside_roi_is_kept_and_bbox_restored_with_margin_offset(monkeypatch, tmp_path):
    """margin付きcropのcrop-local座標で返ったdetectionが、正しくfull-frame座標へ
    復元され(margin cropのオフセット基準)、ROI内なので結果に残ることを確認する。
    """
    engine_probe = _RecordingEngine([])
    settings = {"inference_fps": 10, "method": "object_detection", "roi": ROI, "preprocessing": {}}
    scheduler, _ = _build_scheduler(monkeypatch, settings, engine_probe)
    scheduler._infer_latest()
    margin_h, margin_w = engine_probe.seen_shapes[0]
    # margin crop の full-frame上の左上オフセット: ROI(x:50,y:20,w:50,h:30)に対し
    # margin=1.0(ROI自体のwidth/height分)を各方向へ広げるので x:[0,150) y:[0,80)想定。
    expected_offset_x, expected_offset_y = 0, 0

    # crop中心付近(ROI内であるはず)にdetectionを1件置く。
    local_bbox = (margin_w / 2 - 5, margin_h / 2 - 5, margin_w / 2 + 5, margin_h / 2 + 5)
    engine = _RecordingEngine([Detection(0, "5", 0.9, local_bbox)])
    scheduler, results = _build_scheduler(monkeypatch, settings, engine)
    scheduler._infer_latest()

    assert results, "推論結果が記録されること"
    detection = scheduler.latest_result.detections
    assert len(detection) == 1, "ROI内のdetectionは除外されず残ること"
    bx1, by1, bx2, by2 = detection[0].bbox
    assert bx1 == pytest.approx(expected_offset_x + local_bbox[0], abs=1.0)
    assert by1 == pytest.approx(expected_offset_y + local_bbox[1], abs=1.0)
    # 注: 何も除外されない(全検出がROI内)場合、value/confidenceの再計算はせず
    # engineが返した値をそのまま使う(実engineは常にinterpret_digits済みの値を返すため)。
    # このFakeEngineはvalueを設定しないため、ここではbbox復元とdetection保持のみを検証する。


def test_detection_outside_roi_is_filtered_out_and_value_recomputed(monkeypatch, tmp_path):
    """margin付きcropで拾った、ユーザー指定ROI外のdetectionは最終結果から除外され、
    value/confidenceが残った(ROI内の)検出だけから再計算されること。
    """
    settings = {"inference_fps": 10, "method": "object_detection", "roi": ROI, "preprocessing": {}}

    # 1件目: full-frame座標でROI(x:[50,100) y:[20,50))の中心付近 -> ROI内。
    # 2件目: full-frame座標で(150,70)付近 -> ROI外(margin crop内には入るが、tight ROI外)。
    # crop-local座標はmargin cropのオフセット分を引いて計算する必要があるため、
    # まずprobe engineでmargin crop(offset)を取得してから、その相対座標でdetectionを作る。
    probe, _ = _build_scheduler(monkeypatch, settings, _RecordingEngine([]))
    probe._infer_latest()

    inside_local = (80.0, 25.0, 90.0, 35.0)  # full-frame (80,25)-(90,35) は確実にROI内
    outside_local = (145.0, 65.0, 155.0, 75.0)  # full-frame (145,65)-(155,75) はROI外

    engine = _RecordingEngine([
        Detection(0, "3", 0.9, inside_local),
        Detection(0, "7", 0.8, outside_local),
    ])
    scheduler, results = _build_scheduler(monkeypatch, settings, engine)
    scheduler._infer_latest()

    assert results
    kept = scheduler.latest_result.detections
    assert len(kept) == 1, "ROI外のdetectionは除外されること"
    assert kept[0].class_name == "3"
    assert scheduler.latest_result.value == "3", "value はROI内の検出だけから再計算されること"
    assert scheduler.latest_result.error is None


def test_all_detections_outside_roi_results_in_no_detection(monkeypatch, tmp_path):
    settings = {"inference_fps": 10, "method": "object_detection", "roi": ROI, "preprocessing": {}}
    outside_local = (145.0, 65.0, 155.0, 75.0)
    engine = _RecordingEngine([Detection(0, "7", 0.8, outside_local)])
    scheduler, results = _build_scheduler(monkeypatch, settings, engine)
    scheduler._infer_latest()

    assert results
    assert scheduler.latest_result.detections == []
    assert scheduler.latest_result.value is None
    assert scheduler.latest_result.error == "NO_DETECTION"
