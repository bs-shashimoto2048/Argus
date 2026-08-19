"""新規撮影画像から、near-duplicateを除外し実質的な多様性(meter値の変化・明るさ等)がある
サンプルのみを選別するツール。500枚化のための重複水増しを避け、質を優先する。

使い方:
    py -m scripts.select_meter_captures --images-dir <path> --out-json selected.json

判定基準:
  - 直前に選んだ画像とのdHash(差分ハッシュ)距離が閾値未満 -> near-duplicate(除外)
  - 明るさ(平均輝度)が直前の選択画像と近すぎ、かつdHashも近い -> 除外
  - 最初の1枚は常に採用
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def dhash(image: np.ndarray, hash_size: int = 8) -> int:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    resized = cv2.resize(gray, (hash_size + 1, hash_size), interpolation=cv2.INTER_AREA)
    diff = resized[:, 1:] > resized[:, :-1]
    value = 0
    for bit in diff.flatten():
        value = (value << 1) | int(bit)
    return value


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def mean_brightness(image: np.ndarray) -> float:
    return float(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).mean())


def select(images_dir: Path, hash_threshold: int = 6, brightness_threshold: float = 8.0) -> list[dict]:
    paths = sorted(images_dir.glob("*"))
    selected: list[dict] = []
    last_hash: int | None = None
    last_brightness: float | None = None
    for path in paths:
        image = cv2.imread(str(path))
        if image is None:
            continue
        h = dhash(image)
        b = mean_brightness(image)
        is_duplicate = False
        if last_hash is not None:
            hash_distance = hamming(h, last_hash)
            brightness_delta = abs(b - last_brightness) if last_brightness is not None else 999
            if hash_distance < hash_threshold and brightness_delta < brightness_threshold:
                is_duplicate = True
        if not is_duplicate:
            selected.append({"file": path.name, "dhash": h, "brightness": round(b, 2)})
            last_hash, last_brightness = h, b
    return selected


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images-dir", required=True)
    parser.add_argument("--out-json")
    parser.add_argument("--hash-threshold", type=int, default=6)
    parser.add_argument("--brightness-threshold", type=float, default=8.0)
    args = parser.parse_args()

    images_dir = Path(args.images_dir)
    all_count = len(list(images_dir.glob("*")))
    selected = select(images_dir, args.hash_threshold, args.brightness_threshold)
    print(f"total images: {all_count}")
    print(f"selected (non-near-duplicate): {len(selected)}")
    if args.out_json:
        Path(args.out_json).write_text(json.dumps({"total": all_count, "selected_count": len(selected), "selected": selected}, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"wrote {args.out_json}")


if __name__ == "__main__":
    main()
