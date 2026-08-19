"""メーター読み取り精度評価のpure function群。

YOLOのmAP等の一般的な物体検出指標だけでなく、Argus本番と同じ
`interpret_digits`(app.inference.meter_interpreter)を使って
「メーター値を完全に正しく読み取れたか(Full Reading Exact Match)」を
中心に評価する。Evaluation専用の別ロジックでdigit sequenceを作らない
(Issue #19: Productionと同じ関数を使い、EvaluationとProductionの挙動差を防止)。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.inference.base import Detection
from app.inference.meter_interpreter import interpret_digits

_DIGIT_CONFUSION_LOOKALIKES = {"0", "1", "3", "5", "6", "7", "8", "9"}


def load_yolo_label(label_path: Path, image_width: int, image_height: int) -> list[Detection]:
    """YOLO形式ラベル(class x_center y_center width height、正規化)をpixel座標のDetectionへ変換する。

    Ground TruthをConfidence=1.0のDetectionとして表現することで、
    Predictionと全く同じ`interpret_digits`へ流し込める。
    """
    detections: list[Detection] = []
    if not label_path.is_file():
        return detections
    for line in label_path.read_text(encoding="utf-8-sig").splitlines():
        parts = line.strip().split()
        if len(parts) != 5:
            continue
        class_id_str, xc, yc, w, h = parts
        try:
            class_id = int(class_id_str)
            xc, yc, w, h = float(xc), float(yc), float(w), float(h)
        except ValueError:
            continue
        x1 = (xc - w / 2) * image_width
        y1 = (yc - h / 2) * image_height
        x2 = (xc + w / 2) * image_width
        y2 = (yc + h / 2) * image_height
        detections.append(Detection(class_id, str(class_id), 1.0, (x1, y1, x2, y2)))
    return detections


def ground_truth_reading(detections: list[Detection]) -> str | None:
    """GT Detection列からGround Truth Readingを、Productionと同じ`interpret_digits`で生成する。"""
    return interpret_digits(detections, confidence_threshold=0.0).value


def _iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


@dataclass
class DigitMatchResult:
    matched_count: int = 0
    gt_count: int = 0
    pred_count: int = 0
    correct_class_count: int = 0
    confusions: list[tuple[str, str]] = field(default_factory=list)  # (gt_class, pred_class)


def match_digits(gt_detections: list[Detection], pred_detections: list[Detection], iou_threshold: float = 0.5) -> DigitMatchResult:
    """GTとPredictionのdigit boxをIoUで対応付け、検出/分類精度を算出する。

    貪欲法: IoUが高い順にペアを確定していく(1つのGT/Predは1回だけ使用)。
    """
    result = DigitMatchResult(gt_count=len(gt_detections), pred_count=len(pred_detections))
    candidates = []
    for gi, gt in enumerate(gt_detections):
        if gt.bbox is None:
            continue
        for pi, pred in enumerate(pred_detections):
            if pred.bbox is None:
                continue
            iou = _iou(gt.bbox, pred.bbox)
            if iou >= iou_threshold:
                candidates.append((iou, gi, pi))
    candidates.sort(key=lambda item: item[0], reverse=True)

    used_gt: set[int] = set()
    used_pred: set[int] = set()
    for _iou_value, gi, pi in candidates:
        if gi in used_gt or pi in used_pred:
            continue
        used_gt.add(gi)
        used_pred.add(pi)
        result.matched_count += 1
        gt_class = (gt_detections[gi].class_name or "").strip()
        pred_class = (pred_detections[pi].class_name or "").strip()
        if gt_class == pred_class:
            result.correct_class_count += 1
        else:
            result.confusions.append((gt_class, pred_class))
    return result


def classify_reading_error(gt: str | None, pred: str | None) -> str:
    """1画像の読み取り結果を、Issue記載のエラーカテゴリへ分類する(互いに排他的)。

    exact_match / no_detection / extra_digit / missing_digit / order_error / wrong_value
    """
    if gt == pred:
        return "exact_match"
    if not pred:
        return "no_detection"
    gt_digits = list(gt or "")
    pred_digits = list(pred)
    if len(pred_digits) > len(gt_digits):
        return "extra_digit"
    if len(pred_digits) < len(gt_digits):
        return "missing_digit"
    # 同じ桁数だが不一致 -> 並び替えでGTと一致するなら順序エラー、それ以外は誤読
    if sorted(pred_digits) == sorted(gt_digits):
        return "order_error"
    return "wrong_value"


@dataclass
class PerImageResult:
    image: str
    gt_reading: str | None
    pred_reading: str | None
    error_category: str
    processing_time_ms: float
    digit_match: DigitMatchResult
    raw_error: str | None = None


def aggregate_metrics(results: list[PerImageResult]) -> dict:
    """画像単位の結果列から、Issue記載のメーター専用指標一式を集計する。"""
    n = len(results)
    if n == 0:
        return {"image_count": 0}

    category_counts: dict[str, int] = {}
    for r in results:
        category_counts[r.error_category] = category_counts.get(r.error_category, 0) + 1

    total_matched = sum(r.digit_match.matched_count for r in results)
    total_gt_digits = sum(r.digit_match.gt_count for r in results)
    total_correct_class = sum(r.digit_match.correct_class_count for r in results)

    confusion_counts: dict[tuple[str, str], int] = {}
    for r in results:
        for gt_class, pred_class in r.digit_match.confusions:
            key = (gt_class, pred_class)
            confusion_counts[key] = confusion_counts.get(key, 0) + 1
    top_confusions = sorted(confusion_counts.items(), key=lambda item: item[1], reverse=True)[:10]

    return {
        "image_count": n,
        "exact_match_accuracy": category_counts.get("exact_match", 0) / n,
        "no_detection_rate": category_counts.get("no_detection", 0) / n,
        "extra_digit_rate": category_counts.get("extra_digit", 0) / n,
        "missing_digit_rate": category_counts.get("missing_digit", 0) / n,
        "digit_order_error_rate": category_counts.get("order_error", 0) / n,
        "invalid_reading_rate": category_counts.get("wrong_value", 0) / n,
        "digit_detection_accuracy": (total_matched / total_gt_digits) if total_gt_digits else None,
        "digit_classification_accuracy": (total_correct_class / total_matched) if total_matched else None,
        "avg_processing_time_ms": sum(r.processing_time_ms for r in results) / n,
        "top_digit_confusions": [{"gt": gt_class, "pred": pred_class, "count": count} for (gt_class, pred_class), count in top_confusions],
        "category_counts": category_counts,
    }


def failure_examples(results: list[PerImageResult], limit: int = 20) -> list[dict]:
    """Report用のfailure example一覧(exact_match以外)を抽出する。大量画像をcommitする必要はない。"""
    failures = [r for r in results if r.error_category != "exact_match"]
    return [
        {
            "image": r.image,
            "gt": r.gt_reading,
            "pred": r.pred_reading,
            "category": r.error_category,
            "raw_error": r.raw_error,
        }
        for r in failures[:limit]
    ]
