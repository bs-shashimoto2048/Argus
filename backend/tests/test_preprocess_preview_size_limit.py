"""Issue #81: 前処理Previewは、巨大画像を確保する前に出力サイズを検証して弾く。

本番で、管理者のPreview操作の直後にBackendのRSSが約300MB→1.5GBへ跳ね、数十分残った。隔離再現で、
ROI幅2%(UIの最小値)×resize 4096が4096×116,413px(RGB 1.4GB)を確保し、JPEG保存失敗(422)後も例外tracebackが
巨大画像を保持し続けることを確認した。resize前に出力サイズを検証し、確保させない。
"""
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.schemas.inference import PreprocessSettings
from app.services import preprocess_service
from app.services.preprocess_service import (
    MAX_PREVIEW_DIMENSION,
    MAX_PREVIEW_PIXELS,
    PreviewTooLargeError,
    ensure_preview_size,
    output_size,
)
from runtime.runtime_manager import runtime_manager

FRAME_W, FRAME_H = 1920, 1080


def _frame_bytes() -> bytes:
    out = BytesIO()
    Image.new("RGB", (FRAME_W, FRAME_H), (120, 130, 140)).save(out, format="JPEG", quality=80)
    return out.getvalue()


class _Buffer:
    def get(self):
        return _frame_bytes(), 0.0


class _Runtime:
    state = "running"
    buffer = _Buffer()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(runtime_manager, "get_runtime", lambda _id: _Runtime())
    return TestClient(app)


@pytest.fixture
def forbid_resize(monkeypatch):
    """resizeが呼ばれたら失敗させる(=巨大画像を確保する前に弾けていることの確認)。"""
    def boom(self, *args, **kwargs):
        raise AssertionError("Image.resize must not be called for an oversized preview")
    monkeypatch.setattr(Image.Image, "resize", boom)


def _post(client, roi, resize, monitor_id=4):
    return client.post(f"/api/monitors/{monitor_id}/preprocess/preview", json={"settings": {"grayscale": True, "sharpen": True, "resize": resize}, "roi": roi})


# ---- サイズ計算(確保せずに判定できること) ----------------------------------

def test_output_size_matches_apply_for_resize_and_no_resize():
    image = Image.new("RGB", (519, 106))
    assert output_size(image.size, {"resize": 640}) == preprocess_service.apply(image, {"resize": 640}).size == (640, 131)
    assert output_size(image.size, {}) == (519, 106)


# ---- 上限と境界値 ------------------------------------------------------------

def test_limit_is_the_largest_square_the_ui_can_request():
    assert MAX_PREVIEW_PIXELS == 4096 * 4096  # resizeの上限(schema le=4096)の正方形


@pytest.mark.parametrize("size", [
    (519, 106),        # Monitor 4の保存ROI
    (1920, 1080),      # フレーム全体
    (1920, 1440),      # 4:3
    (1152, 1080),      # 幅60%・全高(縦横比 ~1:1)
])
@pytest.mark.parametrize("resize", [None, 640, 2048, 4096])
def test_normal_roi_and_resize_are_allowed_when_not_taller_than_wide(size, resize):
    ensure_preview_size(size, {"resize": resize})


@pytest.mark.parametrize("resize,max_height_ratio", [(4096, 1.0), (2048, 4.0), (640, 40.0)])
def test_allowed_tallness_depends_on_resize(resize, max_height_ratio):
    # 上限は総pixel数: 出力高さ = resize x (高さ/幅) <= 4096^2 / resize
    width = 100
    ensure_preview_size((width, int(width * max_height_ratio)), {"resize": resize})
    with pytest.raises(PreviewTooLargeError):
        ensure_preview_size((width, int(width * max_height_ratio * 1.05) + 1), {"resize": resize})


def test_exactly_at_the_pixel_limit_is_allowed_and_one_row_more_is_rejected():
    ensure_preview_size((4096, 4096), {"resize": 4096})                   # 4096 x 4096 = 上限ちょうど
    with pytest.raises(PreviewTooLargeError):
        ensure_preview_size((4096, 4097), {"resize": 4096})               # 1行超過


def test_dimension_limit_of_jpeg_is_enforced():
    # 総pixel数は上限内でも、JPEGが扱えない辺(65,500超)は必ず保存に失敗するので先に弾く
    with pytest.raises(PreviewTooLargeError):
        ensure_preview_size((1, 70000), {})
    ensure_preview_size((1, MAX_PREVIEW_DIMENSION), {})


@pytest.mark.parametrize("width_ratio,expected_rejected", [(0.60, False), (0.20, True), (0.10, True), (0.05, True), (0.02, True), (0.01, True)])
def test_thin_full_height_roi_at_max_resize(width_ratio, expected_rejected):
    crop_w = max(1, round(width_ratio * FRAME_W))
    if expected_rejected:
        with pytest.raises(PreviewTooLargeError):
            ensure_preview_size((crop_w, FRAME_H), {"resize": 4096})
    else:
        ensure_preview_size((crop_w, FRAME_H), {"resize": 4096})


def test_message_tells_the_user_what_to_change():
    with pytest.raises(PreviewTooLargeError) as excinfo:
        ensure_preview_size((38, 1080), {"resize": 4096})
    assert "ROIの幅を広げる" in str(excinfo.value) and "Resize width" in str(excinfo.value)
    assert "4096x116413" in str(excinfo.value)


# ---- API経路 -------------------------------------------------------------------

def test_api_normal_preview_still_works_and_response_is_compatible(client):
    response = _post(client, {"x": 0.4348958333, "y": 0.3462962963, "width": 0.2703125, "height": 0.0981481481}, 640)
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["cache-control"] == "no-store"
    assert Image.open(BytesIO(response.content)).size == (640, 131)


@pytest.mark.parametrize("monitor_id,roi,resize", [
    (2, {"x": 0, "y": 0, "width": 1, "height": 1}, 640),
    (3, {"x": 0, "y": 0, "width": 1, "height": 1}, None),
    (4, {"x": 0.4348958333, "y": 0.3462962963, "width": 0.2703125, "height": 0.0981481481}, 640),
])
def test_current_saved_settings_of_monitors_2_3_4_are_not_affected(client, monitor_id, roi, resize):
    assert _post(client, roi, resize, monitor_id).status_code == 200


def test_api_without_roi_is_allowed(client):
    response = client.post("/api/monitors/4/preprocess/preview", json={"settings": {"resize": 4096}})
    assert response.status_code == 200
    assert Image.open(BytesIO(response.content)).size == (4096, 2304)


def test_api_tall_roi_is_allowed_at_a_smaller_resize(client):
    # 幅20%の縦長ROIは resize 4096 では拒否されるが、resize 640 なら通常どおり成功する
    roi = {"x": 0.5, "y": 0.0, "width": 0.20, "height": 1.0}
    assert _post(client, roi, 640).status_code == 200


@pytest.mark.parametrize("width", [0.05, 0.02, 0.01])
def test_api_rejects_thin_roi_with_max_resize_before_allocating(client, forbid_resize, width):
    response = _post(client, {"x": 0.5, "y": 0.0, "width": width, "height": 1.0}, 4096)
    assert response.status_code == 422
    assert "上限を超えます" in response.json()["detail"]


def test_api_rejection_does_not_chain_the_exception_so_no_reference_cycle_keeps_images(client, forbid_resize):
    # `raise ... from None`: 上限超過は通常の入力エラー。巨大画像を保持するtraceback連鎖を作らない。
    response = _post(client, {"x": 0.5, "y": 0.0, "width": 0.02, "height": 1.0}, 4096)
    assert response.status_code == 422


def test_repeated_previews_do_not_accumulate_pil_images(client):
    import gc
    roi = {"x": 0.2, "y": 0.0, "width": 0.60, "height": 1.0}
    _post(client, roi, 4096)
    gc.collect()
    before = sum(1 for o in gc.get_objects() if isinstance(o, Image.Image))
    for _ in range(15):
        assert _post(client, roi, 4096).status_code == 200
    gc.collect()
    after = sum(1 for o in gc.get_objects() if isinstance(o, Image.Image))
    assert after - before <= 2


def test_settings_validation_is_unchanged(client):
    assert client.post("/api/monitors/4/preprocess/preview", json={"settings": {"resize": 31}}).status_code == 422
    assert client.post("/api/monitors/4/preprocess/preview", json={"settings": {"resize": 4097}}).status_code == 422
    assert PreprocessSettings(resize=4096).resize == 4096
