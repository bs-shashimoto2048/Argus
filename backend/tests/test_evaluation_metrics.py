"""backend/evaluation/metrics.py のpure function単体テスト。

実データセット・実モデルに依存せず通常CIで実行できる
(Issue: 通常CIでModel Trainingを行わない、Evaluation Unit Testのみ通常CIへ)。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.inference.base import Detection
from evaluation.metrics import (
    DigitMatchResult,
    PerImageResult,
    aggregate_metrics,
    classify_reading_error,
    failure_examples,
    ground_truth_reading,
    load_yolo_label,
    match_digits,
)

pytestmark = pytest.mark.unit


def _digit(class_name: str, bbox, confidence: float = 1.0) -> Detection:
    return Detection(int(class_name), class_name, confidence, bbox)


def test_load_yolo_label_converts_normalized_to_pixel_bbox(tmp_path):
    label_path = tmp_path / "sample.txt"
    label_path.write_text("5 0.5 0.5 0.2 0.4\n", encoding="utf-8")
    detections = load_yolo_label(label_path, image_width=100, image_height=200)
    assert len(detections) == 1
    detection = detections[0]
    assert detection.class_name == "5"
    assert detection.confidence == 1.0
    x1, y1, x2, y2 = detection.bbox
    assert x1 == pytest.approx(40.0)
    assert x2 == pytest.approx(60.0)
    assert y1 == pytest.approx(60.0)
    assert y2 == pytest.approx(140.0)


def test_load_yolo_label_skips_malformed_lines(tmp_path):
    label_path = tmp_path / "bad.txt"
    label_path.write_text("not-a-valid-line\n5 0.5 0.5 0.1 0.1\n", encoding="utf-8")
    detections = load_yolo_label(label_path, 100, 100)
    assert len(detections) == 1


def test_load_yolo_label_missing_file_returns_empty(tmp_path):
    assert load_yolo_label(tmp_path / "missing.txt", 100, 100) == []


def test_ground_truth_reading_matches_leading_zero_and_order():
    # x-center昇順: 0,0,2,5,6,0 -> "002560"
    detections = [
        _digit("0", (0, 0, 10, 10)),
        _digit("0", (10, 0, 20, 10)),
        _digit("2", (20, 0, 30, 10)),
        _digit("5", (30, 0, 40, 10)),
        _digit("6", (40, 0, 50, 10)),
        _digit("0", (50, 0, 60, 10)),
    ]
    assert ground_truth_reading(detections) == "002560"


def test_classify_reading_error_categories():
    assert classify_reading_error("002560", "002560") == "exact_match"
    assert classify_reading_error("002560", None) == "no_detection"
    assert classify_reading_error("002560", "") == "no_detection"
    assert classify_reading_error("002560", "0025603") == "extra_digit"
    assert classify_reading_error("002560", "02560") == "missing_digit"
    assert classify_reading_error("002560", "002650") == "order_error"  # 同じ桁の並び替えで一致
    assert classify_reading_error("002560", "002580") == "wrong_value"


def test_match_digits_counts_detection_and_classification_accuracy():
    gt = [_digit("5", (0, 0, 10, 10)), _digit("6", (10, 0, 20, 10))]
    # 1件目は正しい位置・正しいclass、2件目は正しい位置だが誤classification
    pred = [_digit("5", (0, 0, 10, 10)), _digit("8", (10, 0, 20, 10))]
    result = match_digits(gt, pred, iou_threshold=0.5)
    assert result.matched_count == 2
    assert result.correct_class_count == 1
    assert result.confusions == [("6", "8")]


def test_match_digits_no_overlap_means_no_match():
    gt = [_digit("5", (0, 0, 10, 10))]
    pred = [_digit("5", (50, 50, 60, 60))]
    result = match_digits(gt, pred, iou_threshold=0.5)
    assert result.matched_count == 0


def test_aggregate_metrics_computes_rates():
    results = [
        PerImageResult("a.jpg", "002560", "002560", "exact_match", 10.0, DigitMatchResult(6, 6, 6, 6, [])),
        PerImageResult("b.jpg", "002560", None, "no_detection", 5.0, DigitMatchResult(0, 6, 0, 0, [])),
        PerImageResult("c.jpg", "002560", "002580", "wrong_value", 12.0, DigitMatchResult(5, 6, 6, 5, [("6", "8")])),
    ]
    metrics = aggregate_metrics(results)
    assert metrics["image_count"] == 3
    assert metrics["exact_match_accuracy"] == pytest.approx(1 / 3)
    assert metrics["no_detection_rate"] == pytest.approx(1 / 3)
    assert metrics["invalid_reading_rate"] == pytest.approx(1 / 3)
    assert metrics["digit_detection_accuracy"] == pytest.approx(11 / 18)  # matched(6+0+5) / gt_total(6+6+6)
    assert metrics["top_digit_confusions"][0] == {"gt": "6", "pred": "8", "count": 1}


def test_aggregate_metrics_empty_results():
    assert aggregate_metrics([]) == {"image_count": 0}


def test_failure_examples_excludes_exact_matches_and_respects_limit():
    results = [
        PerImageResult("a.jpg", "1", "1", "exact_match", 1.0, DigitMatchResult()),
        PerImageResult("b.jpg", "2", "3", "wrong_value", 1.0, DigitMatchResult()),
        PerImageResult("c.jpg", "4", None, "no_detection", 1.0, DigitMatchResult()),
    ]
    failures = failure_examples(results, limit=1)
    assert len(failures) == 1
    assert failures[0]["image"] == "b.jpg"
