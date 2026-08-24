"""Issue #16: ROIモード(filter_only既定 / crop_context詳細設定)の回帰テスト。

実機3台(Monitor 2/3/4)での比較検証により、object_detectionのROI既定挙動を
margin付きcrop(旧実装)からFull Frame + ROI Filter-only(filter_only)へ変更した。
このテストファイルは、InferenceScheduler._infer_latestが

  - filter_only(既定): Full Frameで推論し、tight ROIより広くcropしないこと
  - crop_context(詳細設定): ROIへcontext_margin分だけ広げてcropすること
    (margin<1.0では文脈不足で検出0件になり得ることを実機比較で確認済み。
    1.0を既定値とする)
  - いずれのモードでも、OCR(method='ocr')やengineがultralytics以外の場合は
    従来どおりタイトROIのままcropすること(この修正のスコープ外)
  - crop-local座標で返ったdetectionのbboxがfull-frame座標へ正しく復元されること
  - ユーザーが指定したROI外に中心があるdetectionは最終結果から除外され、
    value/confidenceがROI内の検出だけから再計算されること
  - pipeline diagnosticsにroi_mode/context_marginが正しく含まれること
  - Overlayがfilter_only/crop_contextいずれでも例外なく描画されること

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
    """受け取ったcrop画像の形状・実データを記録し、指定したdetections(crop-local座標)を返す。"""

    def __init__(self, detections: list[Detection]):
        self.detections = detections
        self.seen_shapes: list[tuple[int, int]] = []
        self.seen_images: list[np.ndarray] = []

    def infer(self, image, settings=None):
        self.seen_shapes.append(image.shape[:2])
        self.seen_images.append(image.copy())
        return InferenceResult(detections=list(self.detections), engine="fake", model_id="fake_model.pt")


def _build_scheduler(monkeypatch, settings: dict, engine):
    monkeypatch.setattr("runtime.inference_scheduler.create_engine", lambda *a, **kw: engine)
    buffer = LatestFrameBuffer()
    buffer.put(_make_frame(FULL_W, FULL_H))
    results = []
    scheduler = InferenceScheduler(
        1, buffer, settings, model_registry, ".", lambda _id, value: results.append(value)
    )
    return scheduler, results


def _od_settings(**overrides) -> dict:
    settings = {"inference_fps": 10, "method": "object_detection", "engine": "ultralytics", "roi": ROI, "preprocessing": {}}
    settings.update(overrides)
    return settings


def test_filter_only_is_the_default_and_uses_full_frame(monkeypatch, tmp_path):
    """roi_modeを指定しない場合、既定はfilter_onlyでFull Frame推論になること。"""
    engine = _RecordingEngine([])
    settings = _od_settings()  # roi_mode未指定
    scheduler, _ = _build_scheduler(monkeypatch, settings, engine)
    scheduler._infer_latest()

    assert engine.seen_shapes, "engineへ画像が渡っていること"
    seen_h, seen_w = engine.seen_shapes[0]
    assert (seen_w, seen_h) == (FULL_W, FULL_H), "filter_only(既定)ではFull Frameのまま推論すること"
    assert scheduler.latest_diagnostics["roi_mode"] == "filter_only"
    assert scheduler.latest_diagnostics["context_margin"] is None, "filter_onlyではcontext_marginは無関係(None)であること"


def test_crop_context_crops_with_margin_larger_than_tight_roi(monkeypatch, tmp_path):
    engine = _RecordingEngine([])
    settings = _od_settings(roi_mode="crop_context")
    scheduler, _ = _build_scheduler(monkeypatch, settings, engine)
    scheduler._infer_latest()

    assert engine.seen_shapes
    seen_h, seen_w = engine.seen_shapes[0]
    tight_w, tight_h = 50, 30  # ROIをそのままcropした場合のサイズ (x:50->100, y:20->50)
    assert seen_w > tight_w and seen_h > tight_h, "crop_contextではtight ROIより広くcropされること"
    assert seen_w < FULL_W or seen_h < FULL_H, "crop_contextはFull Frameより狭いこと(filter_onlyとの違い)"
    assert scheduler.latest_diagnostics["roi_mode"] == "crop_context"
    assert scheduler.latest_diagnostics["context_margin"] == pytest.approx(1.0), "context_margin既定値は1.0であること"


def test_crop_context_respects_custom_context_margin(monkeypatch, tmp_path):
    """context_marginを既定(1.0)以外に設定した場合、その値でcropが広がること。"""
    engine_small = _RecordingEngine([])
    scheduler_small, _ = _build_scheduler(monkeypatch, _od_settings(roi_mode="crop_context", context_margin=0.25), engine_small)
    scheduler_small._infer_latest()

    engine_large = _RecordingEngine([])
    scheduler_large, _ = _build_scheduler(monkeypatch, _od_settings(roi_mode="crop_context", context_margin=2.0), engine_large)
    scheduler_large._infer_latest()

    small_h, small_w = engine_small.seen_shapes[0]
    large_h, large_w = engine_large.seen_shapes[0]
    assert large_w > small_w and large_h > small_h, "context_marginが大きいほどcropが広くなること"
    assert scheduler_small.latest_diagnostics["context_margin"] == pytest.approx(0.25)
    assert scheduler_large.latest_diagnostics["context_margin"] == pytest.approx(2.0)


def test_non_object_detection_method_keeps_tight_roi_crop(monkeypatch, tmp_path):
    """OCR(method='ocr')は今回の修正対象外で、従来どおりタイトROIのままcropされること。
    roi_modeの影響も受けない(diagnosticsではNoneになる)。"""
    engine = _RecordingEngine([])
    settings = {"inference_fps": 10, "method": "ocr", "roi": ROI, "preprocessing": {}}
    scheduler, _ = _build_scheduler(monkeypatch, settings, engine)
    scheduler._infer_latest()

    seen_h, seen_w = engine.seen_shapes[0]
    assert (seen_w, seen_h) == (50, 30), "OCR系はfilter_only/crop_contextに関係なくtight ROIのままであること"
    assert scheduler.latest_diagnostics["roi_mode"] is None


def test_object_detection_method_with_non_ultralytics_engine_keeps_tight_roi_crop(monkeypatch, tmp_path):
    """実UI確認で発見: method='object_detection'のままengineをtesseract/easyocrへ
    切り替えた場合(create_engine()はこの組合せでTesseract/EasyOcrEngineを返す)、
    roi_mode(filter_only/crop_context)を適用してはいけない(YOLOのbboxベース検出専用の
    ロジックのため)。method単独ではなくengine=='ultralytics'も条件に含めて判定する。
    """
    engine = _RecordingEngine([])
    settings = _od_settings(engine="tesseract")
    scheduler, _ = _build_scheduler(monkeypatch, settings, engine)
    scheduler._infer_latest()

    seen_h, seen_w = engine.seen_shapes[0]
    assert (seen_w, seen_h) == (50, 30), "method=object_detectionでもengineがultralytics以外ならtight ROIのままであること"
    assert scheduler.latest_diagnostics["roi_mode"] is None


def test_detection_inside_roi_is_kept_and_bbox_restored_in_filter_only(monkeypatch, tmp_path):
    """filter_only(既定)ではcrop offset=(0,0)=full frameなので、crop-local座標は
    そのままfull-frame座標になる。ROI内のdetectionは結果に残ることを確認する。
    """
    local_bbox = (80.0, 25.0, 90.0, 35.0)  # full-frame (80,25)-(90,35) は確実にROI内
    engine = _RecordingEngine([Detection(0, "5", 0.9, local_bbox)])
    scheduler, results = _build_scheduler(monkeypatch, _od_settings(), engine)
    scheduler._infer_latest()

    assert results, "推論結果が記録されること"
    detection = scheduler.latest_result.detections
    assert len(detection) == 1, "ROI内のdetectionは除外されず残ること"
    assert detection[0].bbox == pytest.approx(local_bbox, abs=1.0)


def test_detection_inside_roi_is_kept_and_bbox_restored_with_margin_offset(monkeypatch, tmp_path):
    """crop_contextでは、crop-local座標で返ったdetectionが正しくfull-frame座標へ
    復元される(margin cropのオフセット基準)こと。
    """
    settings = _od_settings(roi_mode="crop_context")
    engine_probe = _RecordingEngine([])
    scheduler_probe, _ = _build_scheduler(monkeypatch, settings, engine_probe)
    scheduler_probe._infer_latest()
    margin_h, margin_w = engine_probe.seen_shapes[0]
    # ROI(x:50,y:20,w:50,h:30)に対しmargin=1.0(ROI自体のwidth/height分)を
    # 各方向へ広げるので、full-frame上のcropオフセットは(0,0)になる想定。
    expected_offset_x, expected_offset_y = 0, 0

    local_bbox = (margin_w / 2 - 5, margin_h / 2 - 5, margin_w / 2 + 5, margin_h / 2 + 5)
    engine = _RecordingEngine([Detection(0, "5", 0.9, local_bbox)])
    scheduler, results = _build_scheduler(monkeypatch, settings, engine)
    scheduler._infer_latest()

    assert results
    detection = scheduler.latest_result.detections
    assert len(detection) == 1, "ROI内のdetectionは除外されず残ること"
    bx1, by1, _, _ = detection[0].bbox
    assert bx1 == pytest.approx(expected_offset_x + local_bbox[0], abs=1.0)
    assert by1 == pytest.approx(expected_offset_y + local_bbox[1], abs=1.0)


@pytest.mark.parametrize("roi_mode", ["filter_only", "crop_context"])
def test_detection_outside_roi_is_filtered_out_and_value_recomputed(monkeypatch, tmp_path, roi_mode):
    """ユーザー指定ROI外のdetectionは最終結果から除外され、value/confidenceが
    残った(ROI内の)検出だけから再計算されること。filter_only/crop_context両方で確認する。
    """
    settings = _od_settings(roi_mode=roi_mode)

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
    outside_local = (145.0, 65.0, 155.0, 75.0)
    engine = _RecordingEngine([Detection(0, "7", 0.8, outside_local)])
    scheduler, results = _build_scheduler(monkeypatch, _od_settings(), engine)
    scheduler._infer_latest()

    assert results
    assert scheduler.latest_result.detections == []
    assert scheduler.latest_result.value is None
    assert scheduler.latest_result.error == "NO_DETECTION"


def test_latest_inference_input_is_the_exact_image_passed_to_engine(monkeypatch, tmp_path):
    """Issue #16追加要件: 表示用に別途再生成せず、実際にengine.infer()へ渡した画像そのものを
    保存していることを、pixel単位で一致することまで確認する(filter_only=既定でも成立)。
    """
    engine = _RecordingEngine([])
    scheduler, _ = _build_scheduler(monkeypatch, _od_settings(), engine)
    scheduler._infer_latest()

    assert engine.seen_images, "engineへ画像が渡っていること"
    assert scheduler.latest_inference_input is not None
    decoded = cv2.imdecode(np.frombuffer(scheduler.latest_inference_input, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert decoded.shape == engine.seen_images[0].shape
    # JPEGは可逆圧縮ではないため、engineへ渡した実データをJPEGへエンコードしたもの
    # (=latest_inference_input)を再デコードした結果と、僅かな差(圧縮誤差)以内で一致すること。
    assert np.abs(decoded.astype(int) - engine.seen_images[0].astype(int)).mean() < 5.0


def test_pipeline_diagnostics_in_filter_only_mode(monkeypatch, tmp_path):
    """filter_onlyでは、inference_crop_pixelがFull Frame全体になり、
    roi_mode='filter_only'/context_margin=Noneが報告されること。
    """
    inside_local = (80.0, 25.0, 90.0, 35.0)
    outside_local = (145.0, 65.0, 155.0, 75.0)
    engine = _RecordingEngine([Detection(0, "3", 0.9, inside_local), Detection(0, "7", 0.8, outside_local)])
    scheduler, results = _build_scheduler(monkeypatch, _od_settings(), engine)
    scheduler._infer_latest()

    assert results
    diag = scheduler.latest_diagnostics
    assert diag["frame_width"] == FULL_W
    assert diag["frame_height"] == FULL_H
    assert diag["roi_mode"] == "filter_only"
    assert diag["context_margin"] is None
    assert diag["roi_normalized"] == ROI
    assert diag["roi_pixel"] == [50, 20, 100, 50]
    assert diag["inference_crop_pixel"] == [0, 0, FULL_W, FULL_H], "filter_onlyの推論cropはFull Frame全体であること"
    assert diag["crop_shape"] == [FULL_H, FULL_W]
    assert diag["preprocess_output_shape"] == diag["crop_shape"]
    assert diag["model_input_shape"] == diag["preprocess_output_shape"]
    assert diag["raw_detection_count"] == 2, "ROI filter前の検出数(engineが返した全件)"
    assert diag["roi_filtered_detection_count"] == 1, "ROI内に絞り込んだ後の検出数"
    assert diag["engine"] == "fake"
    assert diag["model_id"] == "fake_model.pt"


def test_pipeline_diagnostics_in_crop_context_mode(monkeypatch, tmp_path):
    """crop_contextでは、inference_crop_pixelがtight ROIより広く、
    roi_mode='crop_context'/context_marginに実際の値が報告されること。
    """
    engine = _RecordingEngine([])
    scheduler, results = _build_scheduler(monkeypatch, _od_settings(roi_mode="crop_context", context_margin=0.5), engine)
    scheduler._infer_latest()

    assert results
    diag = scheduler.latest_diagnostics
    assert diag["roi_mode"] == "crop_context"
    assert diag["context_margin"] == pytest.approx(0.5)
    crop_x1, crop_y1, crop_x2, crop_y2 = diag["inference_crop_pixel"]
    assert (crop_x2 - crop_x1) > (100 - 50)
    assert (crop_y2 - crop_y1) > (50 - 20)
    assert diag["crop_shape"] == [crop_y2 - crop_y1, crop_x2 - crop_x1]


@pytest.mark.parametrize("roi_mode,extra", [("filter_only", {}), ("crop_context", {"roi_mode": "crop_context"})])
def test_overlay_draws_without_crashing_and_has_valid_jpeg_dimensions(monkeypatch, tmp_path, roi_mode, extra):
    """Issue #16追加要件: Overlay上にユーザー指定ROI(常時)と、crop_context時のみ
    内部推論crop範囲を破線で描画する処理が、例外なく動作し正しいJPEGを生成すること。
    """
    engine = _RecordingEngine([Detection(0, "3", 0.9, (10.0, 10.0, 20.0, 20.0))])
    scheduler, results = _build_scheduler(monkeypatch, _od_settings(**extra), engine)
    scheduler._infer_latest()

    assert results
    assert scheduler.latest_overlay is not None
    decoded = cv2.imdecode(np.frombuffer(scheduler.latest_overlay, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert decoded.shape == (FULL_H, FULL_W, 3)
    assert scheduler.latest_diagnostics["roi_mode"] == roi_mode
