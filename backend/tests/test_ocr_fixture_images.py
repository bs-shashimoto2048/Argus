"""OCR用数字画像fixtureジェネレータ自体の単体テスト（重い依存なし・高速）。"""
from __future__ import annotations

import pytest

from tests.fixtures.generate_digit_image import generate_digit_image

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("text", ["002560", "123.45"])
def test_generate_digit_image_returns_bgr_array_of_requested_size(text):
    image = generate_digit_image(text, width=320, height=120)
    assert image.shape == (120, 320, 3)
    # 白背景に黒文字を描いているため、単色(全て白)ではないこと。
    assert image.min() < 255
    assert image.max() == 255
