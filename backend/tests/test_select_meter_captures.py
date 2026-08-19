"""select_meter_captures.py のnear-duplicate判定pure functionの単体テスト。"""
from __future__ import annotations

import numpy as np
import pytest

from scripts.select_meter_captures import dhash, hamming, mean_brightness, select

pytestmark = pytest.mark.unit


def test_hamming_distance_zero_for_identical_hash():
    assert hamming(0b1010, 0b1010) == 0


def test_hamming_distance_counts_differing_bits():
    assert hamming(0b1111, 0b0000) == 4


def test_dhash_identical_images_have_zero_distance():
    image = np.random.default_rng(0).integers(0, 255, (64, 64, 3), dtype=np.uint8)
    assert hamming(dhash(image), dhash(image.copy())) == 0


def test_mean_brightness_black_vs_white():
    black = np.zeros((10, 10, 3), dtype=np.uint8)
    white = np.full((10, 10, 3), 255, dtype=np.uint8)
    assert mean_brightness(black) < mean_brightness(white)


def test_select_skips_near_duplicate_directory(tmp_path):
    import cv2

    # 1枚目: 一様なグレー。2枚目: ほぼ同じ(near-duplicate)。3枚目: 明るさが大きく異なる。
    base = np.full((32, 32, 3), 120, dtype=np.uint8)
    near_dup = base.copy()
    near_dup[0, 0] = 121  # ごくわずかな差
    different = np.full((32, 32, 3), 220, dtype=np.uint8)

    for name, image in (("a_001.jpg", base), ("a_002.jpg", near_dup), ("a_003.jpg", different)):
        cv2.imwrite(str(tmp_path / name), image)

    selected = select(tmp_path, hash_threshold=6, brightness_threshold=8.0)
    files = [item["file"] for item in selected]
    assert "a_001.jpg" in files
    assert "a_002.jpg" not in files  # near-duplicateとして除外
    assert "a_003.jpg" in files  # 明るさが大きく異なるため採用
