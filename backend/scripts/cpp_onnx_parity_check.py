"""Argus cpp_onnx engine vs yolo_pipeline_studio Python ONNX Runtime parity検証（Issue #37）。

yolo_pipeline_studio Issue #47で確立したparity検証方式（production_smoke_v1.json
fixtureの公式stem + 現行production manifestのTest/Hard-Val splitと非重複の追加stem、
各project 30件）を、Argus側の実`CppOnnxInferenceEngine.infer()`（= 実際にArgusの
Monitor/InferenceSchedulerが呼ぶのと同じコードパス、ModelRegistry経由の常駐worker
プロセスを含む）に対して実行する。Test/Hard-Valは一切使用しない。

このscriptは「既にproduction前処理済みのfixture画像」を直接`engine.infer()`へ渡す
（Argus自身のROI/preprocess_serviceはbypassする）。理由: Argusの既存preprocess
(PIL LANCZOS resize / 独自sharpen実装)はyolo_pipeline_studio productionの前処理
(PIL BICUBIC / UnsharpMask)と厳密には一致しないため、ONNX/NMS/reading parityの
主判定はletterbox以降のみを対象にする(docs/CPP_ONNX_INTEGRATION.md「既知の制約」参照)。

実行例（repo rootから、backend/.venvで）:
    backend\\.venv\\Scripts\\python.exe backend\\scripts\\cpp_onnx_parity_check.py --samples-per-project 30
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ARGUS_BACKEND = Path(__file__).resolve().parents[1]
_YPS_ROOT = Path(__file__).resolve().parents[3] / "yolo_pipeline_studio"
sys.path.insert(0, str(_ARGUS_BACKEND))
sys.path.insert(0, str(_YPS_ROOT / "scripts"))

import cv2  # noqa: E402

from app.inference.base import ModelRegistry  # noqa: E402
from app.inference.engines import create_engine  # noqa: E402
from app.core.config import settings as app_settings  # noqa: E402

import onnx_parity_check as pc  # noqa: E402 (yolo_pipeline_studio Issue #47)

CONF_TOLERANCE = 1e-3
BBOX_TOLERANCE_PX = 1.0

_MODEL_ID_BY_PROFILE = {"digital": "digital_production_v1.onnx", "drum": "drum_production_v1.onnx"}


def compare(py: dict, cpp_detections: list, cpp_reading: str) -> dict:
    import numpy as np

    py_reading, py_order = pc.reading_from(py["xyxy"], py["cls"])
    cpp_xyxy = np.array([d.bbox for d in cpp_detections]) if cpp_detections else np.zeros((0, 4))
    cpp_cls = np.array([d.class_id for d in cpp_detections])
    _, cpp_order = pc.reading_from(cpp_xyxy, cpp_cls)

    violations = []
    if len(py["cls"]) != len(cpp_detections):
        violations.append(f"count mismatch: py={len(py['cls'])} argus_cpp_onnx={len(cpp_detections)}")
    if py_reading != cpp_reading:
        violations.append(f"reading mismatch: py={py_reading!r} argus_cpp_onnx={cpp_reading!r}")

    max_conf_diff = 0.0
    max_bbox_diff = 0.0
    if not violations:
        for i in range(len(py_order)):
            pi, ci = py_order[i], cpp_order[i]
            conf_diff = abs(float(py["conf"][pi]) - float(cpp_detections[ci].confidence))
            bbox_diff = max(abs(float(a) - float(b)) for a, b in zip(py["xyxy"][pi], cpp_detections[ci].bbox))
            max_conf_diff = max(max_conf_diff, conf_diff)
            max_bbox_diff = max(max_bbox_diff, bbox_diff)
        if max_conf_diff > CONF_TOLERANCE:
            violations.append(f"confidence tolerance exceeded: {max_conf_diff:.6f}")
        if max_bbox_diff > BBOX_TOLERANCE_PX:
            violations.append(f"bbox tolerance exceeded: {max_bbox_diff:.3f}px")

    return {"ok": not violations, "violations": violations, "py_reading": py_reading,
            "argus_reading": cpp_reading, "max_conf_diff": max_conf_diff, "max_bbox_diff_px": max_bbox_diff}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples-per-project", type=int, default=30)
    args = ap.parse_args()

    cfg = pc.load_config()
    registry = ModelRegistry()
    overall_ok = True

    for key in ("digital", "drum"):
        entry = cfg[key]
        model_id = _MODEL_ID_BY_PROFILE[key]
        onnx_path = app_settings.data_dir / "models" / model_id
        source_dir = _YPS_ROOT / entry["source_dir"]
        stems = pc.select_stems(key, entry, args.samples_per_project)
        print(f"\n=== {key}: Argus cpp_onnx engine vs Python ONNX ({len(stems)} stems) ===")

        py_out = pc.run_onnx(onnx_path, entry["conf"], pc.STATIC_IMGSZ_HW[key], stems, source_dir,
                              "CPUExecutionProvider")

        engine = create_engine(
            {"method": "object_detection", "engine": "cpp_onnx", "model_id": model_id},
            registry, app_settings.data_dir / "models",
        )

        n_ok = 0
        for stem in stems:
            img_path = source_dir / f"{stem}.jpg"
            image = cv2.imread(str(img_path))
            result = engine.infer(image, {"confidence": entry["conf"]})
            if result.error:
                print(f"  FAIL {stem}: argus engine error={result.error}")
                continue
            r = compare(py_out[stem], result.detections, result.value or "")
            status = "OK  " if r["ok"] else "FAIL"
            print(f"  {status} {stem}: py={r['py_reading']!r} argus={r['argus_reading']!r} "
                  f"max_conf_diff={r['max_conf_diff']:.6f} max_bbox_diff_px={r['max_bbox_diff_px']:.3f}")
            for v in r["violations"]:
                print(f"       - {v}")
            if r["ok"]:
                n_ok += 1
        print(f"{key}: {n_ok}/{len(stems)} OK")
        if n_ok != len(stems):
            overall_ok = False

    print(f"\n=== overall: {'PASS' if overall_ok else 'FAIL'} ===")
    if not overall_ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
