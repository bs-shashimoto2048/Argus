"""ROI crop内で検出した座標が、full-frame座標へ正しく復元されることを確認する。

Issue: ROIを設定した状態での推論結果overlayが正しい位置に描画されるための
座標変換ロジック(InferenceScheduler._infer_latest)の回帰テスト。
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


class _FakeEngine:
    """crop-local座標(0,0起点)で固定のDetectionを1件返すだけのFake Engine。"""

    def __init__(self, bbox):
        self.bbox = bbox

    def infer(self, image, settings=None):
        return InferenceResult(detections=[Detection(0, "1", 0.9, self.bbox)], engine="fake")


def _make_frame(width: int, height: int) -> bytes:
    image = np.zeros((height, width, 3), dtype=np.uint8)
    ok, encoded = cv2.imencode(".jpg", image)
    assert ok
    return encoded.tobytes()


def test_roi_detection_bbox_is_restored_to_full_frame_coordinates(tmp_path, monkeypatch):
    full_width, full_height = 200, 100
    roi = {"x": 0.25, "y": 0.2, "width": 0.5, "height": 0.5}
    # crop領域は full pixel換算で x:[50,150), y:[20,70) -> 100x50
    crop_local_bbox = (10.0, 10.0, 30.0, 30.0)
    expected_full_frame_bbox = (60.0, 30.0, 80.0, 50.0)

    buffer = LatestFrameBuffer()
    buffer.put(_make_frame(full_width, full_height))

    fake_engine = _FakeEngine(crop_local_bbox)
    monkeypatch.setattr("runtime.inference_scheduler.create_engine", lambda *a, **kw: fake_engine)

    results = []
    scheduler = InferenceScheduler(
        1,
        buffer,
        {"inference_fps": 10, "roi": roi, "preprocessing": {}},
        model_registry,
        tmp_path,
        lambda _id, value: results.append(value),
    )
    scheduler._infer_latest()

    assert results, "推論結果が記録されていること"
    detection = results[-1].detections[0]
    for actual, expected in zip(detection.bbox, expected_full_frame_bbox):
        assert actual == pytest.approx(expected, abs=0.5)
