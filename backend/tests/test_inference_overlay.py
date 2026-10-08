"""推論オーバーレイ(overlay.jpg)の描画内容のテスト。

overlay.jpgは「前処理後画像(inference-input.jpgと同じ見た目)のbbox周辺 + bbox + ラベル」。
検出がある場合は、bbox群の外接矩形(+余白)で切り出し、小さければ拡大して数字部分を大きく見せる
(表示だけの処理。Detectionのbbox自体はfull-frame座標へ復元され、Raw/Confirmedは変わらない)。
検出が無い場合は、前処理後の全体画像を表示する。bboxの枠線とラベルは蛍光緑、ラベルは「推論値/確信度」。
"""
from __future__ import annotations

import cv2
import numpy as np
import pytest

from app.inference.base import Detection, InferenceResult
from app.inference.registry import model_registry
from runtime import inference_scheduler as scheduler_module
from runtime.frame_buffer import LatestFrameBuffer
from runtime.inference_scheduler import InferenceScheduler, _overlay_view

pytestmark = pytest.mark.unit

NEON_GREEN = (20, 255, 57)  # BGR(#39FF14)
FULL_ROI = {"x": 0, "y": 0, "width": 1, "height": 1}


class _FakeEngine:
    def __init__(self, boxes, class_name="1", confidence=0.9):
        self.boxes, self.class_name, self.confidence = boxes, class_name, confidence

    def infer(self, image, settings=None):
        detections = [Detection(0, self.class_name, self.confidence, box) for box in self.boxes]
        return InferenceResult(value=self.class_name if detections else None, confidence=self.confidence, detections=detections, engine="fake")


def _frame(width, height, color=(0, 0, 0)):
    image = np.zeros((height, width, 3), dtype=np.uint8)
    image[:] = color
    ok, encoded = cv2.imencode(".png", image)  # 可逆形式でフレームを渡す
    assert ok
    return encoded.tobytes()


def _run(tmp_path, monkeypatch, settings, boxes, frame, **engine_kwargs):
    buffer = LatestFrameBuffer()
    buffer.put(frame)
    monkeypatch.setattr("runtime.inference_scheduler.create_engine", lambda *a, **kw: _FakeEngine(boxes, **engine_kwargs))
    scheduler = InferenceScheduler(1, buffer, settings, model_registry, tmp_path, lambda _id, value: None)
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


def _green_near(image, x, y, radius=3):
    h, w = image.shape[:2]
    return any(_is_neon_green(image[yy, xx]) for yy in range(max(0, y - radius), min(h, y + radius + 1)) for xx in range(max(0, x - radius), min(w, x + radius + 1)))


def _digital_like_boxes():
    # Digital(前処理後 640x360)の7桁: 数字は画像の一部分に小さく並ぶ
    return [(330.0 + 28.0 * i, 180.0, 330.0 + 28.0 * i + 22.0, 228.0) for i in range(7)]


def _drum_like_boxes():
    # Drum(前処理後 640x129)の7桁: 画像のほぼ全幅に大きく並ぶ
    return [(40.0 + 85.0 * i, 30.0, 40.0 + 85.0 * i + 60.0, 100.0) for i in range(7)]


# --- 表示範囲の計算(pure function) ---

def test_overlay_view_enlarges_small_digit_area_with_margin_and_label_headroom():
    boxes = _digital_like_boxes()
    x1, y1, x2, y2, scale = _overlay_view((360, 640, 3), boxes)
    union_x1, union_x2 = boxes[0][0], boxes[-1][2]
    assert x1 < union_x1 and x2 > union_x2  # 外接矩形より余白を含む
    assert 0.05 <= (union_x1 - x1) / (union_x2 - union_x1) <= 0.15  # 余白は外接矩形の5〜15%
    assert scale > 2.0 and (x2 - x1) * scale <= 960 + 2  # 数字部分が十分大きく見えるまで拡大する
    assert (180.0 - y1) * scale >= 20  # bbox上端より上にラベルを描く余白がある


def test_overlay_view_keeps_drum_like_image_unscaled():
    x1, y1, x2, y2, scale = _overlay_view((129, 640, 3), _drum_like_boxes())
    assert scale == 1.0  # 既に読みやすい大きさのため拡大しない(従来の見え方を維持)
    assert (x2 - x1) >= 480 and x1 >= 0 and x2 <= 640 and y1 >= 0 and y2 <= 129


def test_overlay_view_is_clamped_to_the_image():
    x1, y1, x2, y2, scale = _overlay_view((100, 200, 3), [(0.0, 0.0, 30.0, 20.0), (170.0, 80.0, 200.0, 100.0)])
    assert (x1, y1, x2, y2) == (0, 0, 200, 100)


# --- 実描画 ---

def test_label_is_value_slash_confidence_in_neon_green(tmp_path, monkeypatch):
    calls = _capture_drawing(monkeypatch)
    _run(tmp_path, monkeypatch, {"inference_fps": 10, "roi": FULL_ROI, "preprocessing": {}}, [(10.0, 30.0, 30.0, 48.0)], _frame(100, 60), class_name="3", confidence=0.98)
    assert [text for text, _org, _color in calls["text"]] == ["3/0.98"]
    assert calls["text"][0][2] == NEON_GREEN
    assert [color for _p1, _p2, color in calls["rectangle"]] == [NEON_GREEN]


def test_overlay_is_a_zoomed_view_of_the_preprocessed_image_with_green_bbox(tmp_path, monkeypatch):
    # フレームは赤。grayscale+resizeの前処理後は、グレー画像(200x100)になる。
    settings = {"inference_fps": 10, "roi": FULL_ROI, "preprocessing": {"grayscale": True, "resize": 200}}
    box = (20.0, 30.0, 60.0, 80.0)
    scheduler = _run(tmp_path, monkeypatch, settings, [box], _frame(400, 200, (40, 40, 200)))
    model_input = _decode(scheduler.latest_inference_input)
    assert model_input.shape == (100, 200, 3)
    vx1, vy1, vx2, vy2, scale = _overlay_view(model_input.shape, [box])
    overlay = _decode(scheduler.latest_overlay)
    assert overlay.shape[:2] == (round((vy2 - vy1) * scale), round((vx2 - vx1) * scale))  # アスペクト比を維持して拡大
    far = overlay[overlay.shape[0] - 3, overlay.shape[1] - 3]
    assert abs(int(far[0]) - int(far[2])) < 14  # 元映像の赤ではなく、グレー化された前処理後画像
    left, top = round((20 - vx1) * scale), round((30 - vy1) * scale)
    right, bottom = round((60 - vx1) * scale), round((80 - vy1) * scale)
    mid_x, mid_y = (left + right) // 2, (top + bottom) // 2
    assert all(_green_near(overlay, x, y) for x, y in ((left, mid_y), (right, mid_y), (mid_x, top), (mid_x, bottom)))
    blueish = (overlay[..., 2] > 200) & (overlay[..., 1] < 150) & (overlay[..., 0] < 100)
    assert not blueish.any()  # 以前のbbox色(青系)は使わない
    label_area = overlay[max(0, top - 16): max(1, top - 3), left: left + 40]
    assert sum(_is_neon_green(p) for row in label_area for p in row) > 15  # ラベルにも蛍光緑


def test_digital_like_labels_do_not_overlap_in_the_zoomed_overlay(tmp_path, monkeypatch):
    calls = _capture_drawing(monkeypatch)
    boxes = _digital_like_boxes()
    scheduler = _run(tmp_path, monkeypatch, {"inference_fps": 10, "roi": FULL_ROI, "preprocessing": {"resize": 640}}, boxes, _frame(1920, 1080), class_name="0", confidence=0.97)
    overlay = _decode(scheduler.latest_overlay)
    assert overlay.shape[1] >= 900  # 数字領域が大きく表示される(拡大)
    label_x = [org[0] for _text, org, _color in calls["text"]]
    assert len(label_x) == 7
    label_width = cv2.getTextSize("0/0.97", cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)[0][0]
    assert all(b - a > label_width for a, b in zip(label_x, label_x[1:]))  # 隣のラベルと重ならない
    assert all(org[1] >= 16 for _text, org, _color in calls["text"])


def test_drum_like_overlay_keeps_its_original_size(tmp_path, monkeypatch):
    boxes = _drum_like_boxes()
    scheduler = _run(tmp_path, monkeypatch, {"inference_fps": 10, "roi": FULL_ROI, "preprocessing": {"resize": 640}}, boxes, _frame(640, 129))
    overlay = _decode(scheduler.latest_overlay)
    assert overlay.shape[1] >= 480 and overlay.shape[1] <= 640  # 拡大されない(従来どおりの大きさ)


def test_without_detections_the_whole_preprocessed_image_is_shown(tmp_path, monkeypatch):
    scheduler = _run(tmp_path, monkeypatch, {"inference_fps": 10, "roi": FULL_ROI, "preprocessing": {"resize": 200}}, [], _frame(400, 200, (60, 60, 60)))
    overlay = _decode(scheduler.latest_overlay)
    model_input = _decode(scheduler.latest_inference_input)
    assert overlay.shape == model_input.shape == (100, 200, 3)  # 従来どおり前処理後の全体画像(fallback)
    assert not any(_is_neon_green(p) for row in overlay for p in row)


def test_detection_bbox_is_still_restored_to_full_frame_coordinates(tmp_path, monkeypatch):
    calls = _capture_drawing(monkeypatch)
    settings = {"inference_fps": 10, "roi": FULL_ROI, "preprocessing": {"resize": 200}}
    box = (20.0, 30.0, 60.0, 80.0)
    scheduler = _run(tmp_path, monkeypatch, settings, [box], _frame(400, 200))
    assert scheduler.latest_result.detections[0].bbox == (40.0, 60.0, 120.0, 160.0)  # Raw/Confirmedの根拠となる座標は従来どおりfull-frame
    vx1, vy1, _vx2, _vy2, scale = _overlay_view((100, 200, 3), [box])
    assert calls["rectangle"][0][:2] == ((round((20 - vx1) * scale), round((30 - vy1) * scale)), (round((60 - vx1) * scale), round((80 - vy1) * scale)))


def test_roi_outline_is_drawn_in_the_view_coordinates_only_when_crop_is_wider(tmp_path, monkeypatch):
    # filter_only(ultralytics): Full Frameで推論するため、ROIは前処理後画像の一部として破線で示す
    calls = _capture_drawing(monkeypatch)
    settings = {"method": "object_detection", "engine": "ultralytics", "model_id": "x.pt", "inference_fps": 10,
                "roi": {"x": 0.25, "y": 0.2, "width": 0.5, "height": 0.5}, "preprocessing": {}}
    box = (60.0, 30.0, 80.0, 50.0)
    _run(tmp_path, monkeypatch, settings, [box], _frame(200, 100))
    vx1, vy1, _vx2, _vy2, scale = _overlay_view((100, 200, 3), [box])
    expected = ((round((50 - vx1) * scale), round((20 - vy1) * scale)), (round((150 - vx1) * scale), round((70 - vy1) * scale)), scheduler_module._ROI_COLOR)
    assert calls["dashed"] == [expected]
    # ROIそのものをcropする場合(tight crop)は、画像全体がROIのため破線を描かない
    calls = _capture_drawing(monkeypatch)
    tight = {"inference_fps": 10, "roi": {"x": 0.25, "y": 0.2, "width": 0.5, "height": 0.5}, "preprocessing": {}}
    _run(tmp_path, monkeypatch, tight, [(10.0, 10.0, 30.0, 30.0)], _frame(200, 100))
    assert calls["dashed"] == []
