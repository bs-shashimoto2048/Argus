"""推論オーバーレイ(overlay.jpg)の描画内容のテスト。

overlay.jpgは「前処理後画像(inference-input.jpgと同じ見た目) + bbox + ラベル」で、bboxは
前処理後画像の座標系のまま描画する(Detectionのbbox自体はfull-frame座標へ復元される)。
bboxの枠線とラベルは蛍光緑、ラベルは「推論値/確信度」。
"""
from __future__ import annotations

import cv2
import numpy as np
import pytest

from app.inference.base import Detection, InferenceResult
from app.inference.registry import model_registry
from runtime import inference_scheduler as scheduler_module
from runtime.frame_buffer import LatestFrameBuffer
from runtime.inference_scheduler import InferenceScheduler

pytestmark = pytest.mark.unit

NEON_GREEN = (20, 255, 57)  # BGR(#39FF14)


class _FakeEngine:
    def __init__(self, bbox, class_name="1", confidence=0.9):
        self.bbox, self.class_name, self.confidence = bbox, class_name, confidence

    def infer(self, image, settings=None):
        return InferenceResult(value=self.class_name, confidence=self.confidence, detections=[Detection(0, self.class_name, self.confidence, self.bbox)], engine="fake")


def _frame(width, height, color=(0, 0, 0)):
    image = np.zeros((height, width, 3), dtype=np.uint8)
    image[:] = color
    ok, encoded = cv2.imencode(".png", image)  # 可逆形式でフレームを渡す
    assert ok
    return encoded.tobytes()


def _run(tmp_path, monkeypatch, settings, bbox, frame, **engine_kwargs):
    buffer = LatestFrameBuffer()
    buffer.put(frame)
    monkeypatch.setattr("runtime.inference_scheduler.create_engine", lambda *a, **kw: _FakeEngine(bbox, **engine_kwargs))
    results = []
    scheduler = InferenceScheduler(1, buffer, settings, model_registry, tmp_path, lambda _id, value: results.append(value))
    scheduler._infer_latest()
    return scheduler


def _capture_drawing(monkeypatch):
    calls = {"rectangle": [], "text": [], "dashed": []}
    real_rectangle, real_text, real_dashed = cv2.rectangle, cv2.putText, scheduler_module._draw_dashed_rect

    def rectangle(img, pt1, pt2, color, *args, **kwargs):
        calls["rectangle"].append((pt1, pt2, color))
        return real_rectangle(img, pt1, pt2, color, *args, **kwargs)

    def put_text(img, text, org, font, scale, color, *args, **kwargs):
        calls["text"].append((text, org, color))
        return real_text(img, text, org, font, scale, color, *args, **kwargs)

    def dashed(img, pt1, pt2, color, *args, **kwargs):
        calls["dashed"].append((pt1, pt2, color))
        return real_dashed(img, pt1, pt2, color, *args, **kwargs)

    monkeypatch.setattr(scheduler_module.cv2, "rectangle", rectangle)
    monkeypatch.setattr(scheduler_module.cv2, "putText", put_text)
    monkeypatch.setattr(scheduler_module, "_draw_dashed_rect", dashed)
    return calls


def _decode(data):
    return cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)


def _is_neon_green(pixel):
    b, g, r = (int(v) for v in pixel)
    return g > 180 and b < 120 and r < 140


def test_label_is_value_slash_confidence_in_neon_green(tmp_path, monkeypatch):
    calls = _capture_drawing(monkeypatch)
    _run(tmp_path, monkeypatch, {"inference_fps": 10, "roi": {"x": 0, "y": 0, "width": 1, "height": 1}, "preprocessing": {}},
         (10.0, 30.0, 30.0, 48.0), _frame(100, 60), class_name="3", confidence=0.98)
    assert [text for text, _org, _color in calls["text"]] == ["3/0.98"]
    assert calls["text"][0][2] == NEON_GREEN
    assert [color for _p1, _p2, color in calls["rectangle"]] == [NEON_GREEN]


def test_overlay_is_drawn_on_the_preprocessed_image_with_green_bbox(tmp_path, monkeypatch):
    # フレームは赤。grayscale+resizeの前処理後は、グレー画像(幅200)になる。
    settings = {"inference_fps": 10, "roi": {"x": 0, "y": 0, "width": 1, "height": 1}, "preprocessing": {"grayscale": True, "resize": 200}}
    scheduler = _run(tmp_path, monkeypatch, settings, (20.0, 30.0, 60.0, 80.0), _frame(400, 200, (40, 40, 200)))
    overlay = _decode(scheduler.latest_overlay)
    model_input = _decode(scheduler.latest_inference_input)
    # 前処理後画像と同じ大きさ(400x200 -> 200x100)・同じ見た目(グレー)がベース
    assert overlay.shape == model_input.shape == (100, 200, 3)
    far_pixel = overlay[95, 190]
    assert abs(int(far_pixel[0]) - int(far_pixel[2])) < 12  # 元映像の赤ではなく、グレー化された前処理後画像
    # bboxは前処理後画像の座標系(20,30)-(60,80)で、蛍光緑の枠線が描かれる
    assert _is_neon_green(overlay[55, 20]) and _is_neon_green(overlay[55, 60]) and _is_neon_green(overlay[30, 40]) and _is_neon_green(overlay[80, 40])
    # 以前のbbox色(青系 #2563EB)は使わない
    blueish = (overlay[..., 2] > 200) & (overlay[..., 1] < 150) & (overlay[..., 0] < 100)
    assert not blueish.any()
    # ラベル(bbox上端より上の領域)にも蛍光緑のピクセルがある
    label_area = overlay[15:28, 20:55]
    assert sum(_is_neon_green(p) for row in label_area for p in row) > 15


def test_detection_bbox_is_still_restored_to_full_frame_coordinates(tmp_path, monkeypatch):
    calls = _capture_drawing(monkeypatch)
    settings = {"inference_fps": 10, "roi": {"x": 0, "y": 0, "width": 1, "height": 1}, "preprocessing": {"resize": 200}}
    scheduler = _run(tmp_path, monkeypatch, settings, (20.0, 30.0, 60.0, 80.0), _frame(400, 200))
    assert scheduler.latest_result.detections[0].bbox == (40.0, 60.0, 120.0, 160.0)  # Raw/Confirmedの根拠となる座標は従来どおりfull-frame
    assert calls["rectangle"][0][:2] == ((20, 30), (60, 80))  # 描画は前処理後画像の座標系


def test_roi_outline_is_drawn_in_preprocessed_coordinates_only_when_crop_is_wider(tmp_path, monkeypatch):
    # filter_only(ultralytics): Full Frameで推論するため、ROIは前処理後画像の一部として破線で示す
    calls = _capture_drawing(monkeypatch)
    settings = {"method": "object_detection", "engine": "ultralytics", "model_id": "x.pt", "inference_fps": 10,
                "roi": {"x": 0.25, "y": 0.2, "width": 0.5, "height": 0.5}, "preprocessing": {}}
    _run(tmp_path, monkeypatch, settings, (60.0, 30.0, 80.0, 50.0), _frame(200, 100))
    assert calls["dashed"] == [((50, 20), (150, 70), scheduler_module._ROI_COLOR)]
    # ROIそのものをcropする場合(tight crop)は、画像全体がROIのため破線を描かない
    calls = _capture_drawing(monkeypatch)
    tight = {"inference_fps": 10, "roi": {"x": 0.25, "y": 0.2, "width": 0.5, "height": 0.5}, "preprocessing": {}}
    _run(tmp_path, monkeypatch, tight, (10.0, 10.0, 30.0, 30.0), _frame(200, 100))
    assert calls["dashed"] == []
