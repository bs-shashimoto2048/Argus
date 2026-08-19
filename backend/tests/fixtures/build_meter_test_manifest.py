"""固定Test Set(meter_test_set_v1)のmanifestを生成する開発用スクリプト。

画像自体はRepositoryへcommitしない(data/eval/はgitignore対象)。
ファイル名一覧+SHA256だけをcommitし、Test Setの同一性(改ざん・入れ替え検知)と
再現性(#61 Test Dataset固定、#11 Data leakage確認)を担保する。

使い方:
    py backend/tests/fixtures/build_meter_test_manifest.py
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def build(version: str, source_note: str, dataset_dir_name: str | None = None) -> None:
    """dataset_dir_name省略時は従来通り meter_test_set_{version} を対象にする。
    meter_holdout_v3 のような別名Datasetの場合は dataset_dir_name を明示する。"""
    dir_name = dataset_dir_name or f"meter_test_set_{version}"
    test_set_dir = ROOT / "data" / "eval" / dir_name
    manifest_path = Path(__file__).resolve().parent / f"{dir_name}_manifest.json"
    images_dir = test_set_dir / "images"
    labels_dir = test_set_dir / "labels"
    if not images_dir.is_dir():
        print(f"test set images not found at {images_dir}", file=sys.stderr)
        sys.exit(1)

    entries = []
    for image_path in sorted(images_dir.glob("*")):
        label_path = labels_dir / f"{image_path.stem}.txt"
        entries.append({
            "stem": image_path.stem,
            "image_file": image_path.name,
            "image_sha256": sha256_of(image_path),
            "has_label": label_path.is_file(),
            "label_sha256": sha256_of(label_path) if label_path.is_file() else None,
        })

    manifest = {
        "dataset_version": dir_name,
        "source": source_note,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "image_count": len(entries),
        "labeled_count": sum(1 for e in entries if e["has_label"]),
        "entries": entries,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {manifest_path} ({len(entries)} entries)")


def main() -> None:
    build(
        "v2",
        "yolo_pipeline_studio/projects/meter/raw/images (capture_001+meter_001-004+src_001+src_002: "
        "same 7-segment digital meter style, different physical unit/session than training source src_003. "
        "PRIMARY fixed test set for baseline vs candidate accuracy comparison.)",
    )
    build(
        "v1",
        "yolo_pipeline_studio/projects/meter/raw/images (src_004: mechanical drum-counter gas meter, "
        "a DIFFERENT meter style/domain never included in training. SECONDARY out-of-domain evaluation only "
        "-- not used for the baseline-vs-candidate acceptance decision.)",
    )
    build(
        "v3",
        "yolo_pipeline_studio/projects/meter/raw/images src_001_v3+src_002_v3 (2026-08-19 additional live-camera "
        "capture of the SAME two physical units already held out in meter_test_set_v2's src_001/src_002, "
        "different session/time/lighting/framing than the original capture). NEW HOLDOUT TEST -- kept fully "
        "separate from meter_test_set_v2 (Legacy Golden Test) and NEVER used for training. Manually verified "
        "digit labels (v2 pseudo-label predictions were largely wrong for these two units and were NOT used "
        "as ground truth; box geometry reused from the fixed-camera reference labels already in "
        "meter_test_set_v2, class ids corrected by visual reading).",
        dataset_dir_name="meter_holdout_v3",
    )


if __name__ == "__main__":
    main()
