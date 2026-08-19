"""Argus本番コード(YoloInferenceEngine, interpret_digits, ReadingStabilizer)を
直接呼び出し、meter digit検出モデルをFull Reading Exact Match中心に評価する。

通常CIでは実行しない(実データセット・実ultralytics依存)。ローカル/手動運用。

使い方:
    py -m scripts.evaluate_meter_model full \
        --model data/models/meter_digits_v1.pt --device cpu --label baseline \
        --out-json data/reports/baseline.json --out-md data/reports/baseline.md

    py -m scripts.evaluate_meter_model benchmark --model ... --device cuda:0
    py -m scripts.evaluate_meter_model temporal --model ... --device cpu
    py -m scripts.evaluate_meter_model conf-sweep --model ... --device cpu
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.inference.base import ModelRegistry  # noqa: E402
from app.inference.engines import YoloInferenceEngine  # noqa: E402
from evaluation.metrics import (  # noqa: E402
    aggregate_metrics,
    classify_reading_error,
    failure_examples,
    ground_truth_reading,
    load_yolo_label,
    match_digits,
    PerImageResult,
)
from reading.models import CandidateStatus, ReadingSettings  # noqa: E402
from reading.stabilizer import ReadingStabilizer  # noqa: E402

DEFAULT_TEST_DIR = ROOT.parent / "data" / "eval" / "meter_test_set_v2"


def _load_test_images(test_dir: Path) -> list[Path]:
    images_dir = test_dir / "images"
    if not images_dir.is_dir():
        raise SystemExit(f"test set images not found at {images_dir} (run backend/tests/fixtures/build_meter_test_manifest.py first, or copy the held-out set)")
    return sorted(images_dir.glob("*"))


def dataset_inventory(test_dir: Path) -> dict:
    """Issue #6: Dataset inventory (image count, class distribution, resolution, etc.)."""
    images = _load_test_images(test_dir)
    labels_dir = test_dir / "labels"
    resolutions: Counter[tuple[int, int]] = Counter()
    class_counts: Counter[str] = Counter()
    empty_labels = 0
    invalid_bboxes = 0
    missing_labels = 0
    digit_count_distribution: Counter[int] = Counter()

    for image_path in images:
        image = cv2.imread(str(image_path))
        if image is not None:
            resolutions[(image.shape[1], image.shape[0])] += 1
        label_path = labels_dir / f"{image_path.stem}.txt"
        if not label_path.is_file():
            missing_labels += 1
            continue
        detections = load_yolo_label(label_path, image.shape[1] if image is not None else 1, image.shape[0] if image is not None else 1)
        if not detections:
            empty_labels += 1
        digit_count_distribution[len(detections)] += 1
        for detection in detections:
            class_counts[detection.class_name or "?"] += 1
            if detection.bbox:
                x1, y1, x2, y2 = detection.bbox
                if x2 <= x1 or y2 <= y1:
                    invalid_bboxes += 1

    return {
        "image_count": len(images),
        "missing_label_count": missing_labels,
        "empty_annotation_count": empty_labels,
        "invalid_bbox_count": invalid_bboxes,
        "resolutions": {f"{w}x{h}": count for (w, h), count in resolutions.most_common()},
        "class_distribution": dict(class_counts.most_common()),
        "digit_count_distribution": dict(sorted(digit_count_distribution.items())),
    }


def _run_engine_over_test_set(model_path: str, device: str, conf: float, iou: float, imgsz: int, test_dir: Path) -> list[PerImageResult]:
    registry = ModelRegistry()
    engine = YoloInferenceEngine(Path(model_path).name, device, conf, iou, imgsz, registry, Path(model_path).parent)
    images = _load_test_images(test_dir)
    labels_dir = test_dir / "labels"

    results: list[PerImageResult] = []
    for image_path in images:
        image = cv2.imread(str(image_path))
        if image is None:
            continue
        label_path = labels_dir / f"{image_path.stem}.txt"
        gt_detections = load_yolo_label(label_path, image.shape[1], image.shape[0])
        gt_reading = ground_truth_reading(gt_detections)

        inference = engine.infer(image)
        pred_reading = inference.value if not inference.error else None
        category = classify_reading_error(gt_reading, pred_reading)
        digit_match = match_digits(gt_detections, inference.detections)
        results.append(PerImageResult(image_path.name, gt_reading, pred_reading, category, inference.processing_time_ms, digit_match, inference.error))
    return results


def run_full_evaluation(model_path: str, device: str, conf: float, iou: float, imgsz: int, test_dir: Path, label: str) -> dict:
    inventory = dataset_inventory(test_dir)
    results = _run_engine_over_test_set(model_path, device, conf, iou, imgsz, test_dir)
    metrics = aggregate_metrics(results)
    return {
        "label": label,
        "model_path": model_path,
        "device": device,
        "settings": {"conf": conf, "iou": iou, "imgsz": imgsz},
        "dataset_inventory": inventory,
        "metrics": metrics,
        "failure_examples": failure_examples(results),
    }


def run_conf_sweep(model_path: str, device: str, iou: float, imgsz: int, test_dir: Path, confs: list[float]) -> dict:
    sweep = []
    for conf in confs:
        results = _run_engine_over_test_set(model_path, device, conf, iou, imgsz, test_dir)
        metrics = aggregate_metrics(results)
        sweep.append({"conf": conf, "exact_match_accuracy": metrics.get("exact_match_accuracy"), "no_detection_rate": metrics.get("no_detection_rate"), "invalid_reading_rate": metrics.get("invalid_reading_rate")})
    best = max(sweep, key=lambda item: (item["exact_match_accuracy"] or 0))
    return {"model_path": model_path, "device": device, "sweep": sweep, "best_conf": best["conf"]}


def run_benchmark(model_path: str, device: str, conf: float, iou: float, imgsz: int, test_dir: Path, warmup: int = 3, samples: int = 30) -> dict:
    images = _load_test_images(test_dir)
    if not images:
        raise SystemExit("no test images available for benchmark")
    sample_image = cv2.imread(str(images[0]))

    registry = ModelRegistry()
    load_started = time.perf_counter()
    engine = YoloInferenceEngine(Path(model_path).name, device, conf, iou, imgsz, registry, Path(model_path).parent)
    engine.infer(sample_image)  # 初回呼び出しでモデルを実際にロードさせる
    load_ms = (time.perf_counter() - load_started) * 1000

    for _ in range(warmup):
        engine.infer(sample_image)

    latencies_ms = []
    for i in range(samples):
        image = cv2.imread(str(images[i % len(images)]))
        result = engine.infer(image)
        latencies_ms.append(result.processing_time_ms)

    vram_bytes = None
    if device.startswith("cuda"):
        try:
            import torch

            vram_bytes = torch.cuda.memory_allocated()
        except Exception:
            vram_bytes = None

    sorted_latencies = sorted(latencies_ms)
    p50 = sorted_latencies[len(sorted_latencies) // 2]
    p95 = sorted_latencies[min(len(sorted_latencies) - 1, int(len(sorted_latencies) * 0.95))]
    return {
        "model_path": model_path,
        "device": device,
        "load_time_ms": load_ms,
        "warm_avg_ms": statistics.mean(latencies_ms),
        "p50_ms": p50,
        "p95_ms": p95,
        "effective_fps": 1000.0 / statistics.mean(latencies_ms) if latencies_ms else None,
        "vram_bytes": vram_bytes,
        "samples": len(latencies_ms),
    }


def run_temporal_evaluation(model_path: str, device: str, conf: float, iou: float, imgsz: int, test_dir: Path, reading_settings: ReadingSettings | None = None, repeat: int = 1) -> dict:
    """Issue #43-46: 連続画像をタイムスタンプ順にReadingStabilizerへ流し、
    Raw/Confirmed Exact Match, False Confirmed Reading Rate, Time to Confirmationを測る。

    このテスト用画像列は数分間隔のinterval captureであり、値がほぼ毎回変化するため、
    そのまま流すと(実際の連続映像と違い)required_matches分の同一値が集まらず
    一度もConfirmedへ到達しない。`repeat`は、実運用の連続映像(同じ物理状態が
    複数フレームに渡って観測される)を模すため、各frameの推論結果をrepeat回
    Stabilizerへ投入してから次のframeへ進める簡易シミュレーションオプション。
    """
    images = _load_test_images(test_dir)
    labels_dir = test_dir / "labels"
    registry = ModelRegistry()
    engine = YoloInferenceEngine(Path(model_path).name, device, conf, iou, imgsz, registry, Path(model_path).parent)
    stabilizer = ReadingStabilizer(reading_settings or ReadingSettings())

    raw_correct = 0
    raw_total = 0
    confirmed_correct = 0
    confirmed_stale = 0  # 直近の(既に過ぎた)正しい値をまだ保持しているだけの「遅延」
    confirmed_wrong = 0  # 直近のGT履歴のどれとも一致しない、本当の誤確定
    confirmed_total = 0
    time_to_confirmation = None
    ticks = 0
    started_at = time.monotonic()
    recent_gt_readings: list[str] = []  # 直近数件のGT値(遅延と誤確定を区別するため)

    for image_path in images:
        image = cv2.imread(str(image_path))
        if image is None:
            continue
        label_path = labels_dir / f"{image_path.stem}.txt"
        gt_detections = load_yolo_label(label_path, image.shape[1], image.shape[0])
        gt_reading = ground_truth_reading(gt_detections)
        if gt_reading is not None:
            recent_gt_readings.append(gt_reading)
            recent_gt_readings = recent_gt_readings[-5:]

        raw = engine.infer(image)
        raw_total += 1
        if raw.value == gt_reading and gt_reading is not None:
            raw_correct += 1

        for _ in range(max(1, repeat)):
            ticks += 1
            confirmed = stabilizer.update(raw)
            if confirmed.validation_status in (CandidateStatus.CONFIRMED, CandidateStatus.LOW_CONFIDENCE):
                confirmed_total += 1
                if confirmed.value == gt_reading:
                    confirmed_correct += 1
                    if time_to_confirmation is None:
                        time_to_confirmation = time.monotonic() - started_at
                elif confirmed.value in recent_gt_readings:
                    # 直近の(既に更新済みの)正しい値をまだ表示しているだけ。
                    # 「一時的な遅延」であり、issue #45が問題視する「誤値の確定」ではない。
                    confirmed_stale += 1
                elif gt_reading is not None:
                    confirmed_wrong += 1

    return {
        "model_path": model_path,
        "image_count": raw_total,
        "repeat_per_frame": repeat,
        "raw_exact_match_rate": raw_correct / raw_total if raw_total else None,
        "confirmed_exact_match_rate": (confirmed_correct / confirmed_total) if confirmed_total else None,
        "confirmed_stale_rate": (confirmed_stale / confirmed_total) if confirmed_total else None,
        "false_confirmed_reading_rate": (confirmed_wrong / confirmed_total) if confirmed_total else None,
        "confirmed_tick_ratio": (confirmed_total / ticks) if ticks else None,
        "time_to_first_correct_confirmation_s": time_to_confirmation,
        "note": (
            "画像は個別撮影のinterval capture列であり、実映像のフレームレートではない。repeat>1は連続映像での"
            "同一値観測を模した簡易シミュレーション。false_confirmed_reading_rateは直近5件のGT履歴のどれとも"
            "一致しない『本当の誤確定』のみを数える(直近の正しい値をまだ保持しているだけの遅延はconfirmed_stale_rateへ分離)。"
            "Time to Confirmationは処理順の相対値。"
        ),
    }


def _write_outputs(payload: dict, out_json: str | None, out_md: str | None) -> None:
    if out_json:
        Path(out_json).parent.mkdir(parents=True, exist_ok=True)
        Path(out_json).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"wrote {out_json}")
    if out_md:
        Path(out_md).parent.mkdir(parents=True, exist_ok=True)
        Path(out_md).write_text(_to_markdown(payload), encoding="utf-8")
        print(f"wrote {out_md}")


def _to_markdown(payload: dict) -> str:
    lines = [f"# Meter Model Evaluation: {payload.get('label', payload.get('model_path'))}", ""]
    lines.append("```json")
    lines.append(json.dumps(payload, indent=2, ensure_ascii=False))
    lines.append("```")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--model", required=True, help="モデルファイルへの絶対パス")
        p.add_argument("--device", default="cpu")
        p.add_argument("--conf", type=float, default=0.25)
        p.add_argument("--iou", type=float, default=0.7)
        p.add_argument("--imgsz", type=int, default=640)
        p.add_argument("--test-dir", default=str(DEFAULT_TEST_DIR))
        p.add_argument("--out-json")
        p.add_argument("--out-md")

    p_full = sub.add_parser("full")
    add_common(p_full)
    p_full.add_argument("--label", default="model")

    p_bench = sub.add_parser("benchmark")
    add_common(p_bench)
    p_bench.add_argument("--samples", type=int, default=30)

    p_temporal = sub.add_parser("temporal")
    add_common(p_temporal)
    p_temporal.add_argument("--repeat", type=int, default=1, help="各frameの推論結果をStabilizerへ何回投入するか(連続映像シミュレーション)")

    p_sweep = sub.add_parser("conf-sweep")
    add_common(p_sweep)
    p_sweep.add_argument("--confs", default="0.15,0.25,0.35,0.5")

    args = parser.parse_args()
    test_dir = Path(args.test_dir)

    if args.mode == "full":
        payload = run_full_evaluation(args.model, args.device, args.conf, args.iou, args.imgsz, test_dir, args.label)
    elif args.mode == "benchmark":
        payload = run_benchmark(args.model, args.device, args.conf, args.iou, args.imgsz, test_dir, samples=args.samples)
    elif args.mode == "temporal":
        payload = run_temporal_evaluation(args.model, args.device, args.conf, args.iou, args.imgsz, test_dir, repeat=args.repeat)
    elif args.mode == "conf-sweep":
        confs = [float(c) for c in args.confs.split(",")]
        payload = run_conf_sweep(args.model, args.device, args.iou, args.imgsz, test_dir, confs)
    else:
        raise SystemExit(f"unknown mode {args.mode}")

    print(json.dumps(payload, indent=2, ensure_ascii=False))
    _write_outputs(payload, args.out_json, args.out_md)


if __name__ == "__main__":
    main()
