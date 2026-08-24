"""method(推論方法)とengine(実行エンジン)の意味的整合性を保証する正規化のテスト(Issue #16)。

実UI確認で、method=object_detection / engine=tesseract という保存値が存在し得ることが
判明した(create_engine()はmethod=="object_detection" かつ engine=="ultralytics"の場合
のみYOLOへ分岐し、それ以外はengineの値だけでOCRエンジンを選ぶため)。
create_engine()自体・推論処理・ROI処理・安定化処理は変更せず、設定保存(update_monitor)の
時点でこの不変条件を保証する。
"""

from fastapi.testclient import TestClient
from app.main import app
from app.services.monitor_service import _normalize_engine


def test_normalize_engine_object_detection_always_ultralytics():
    assert _normalize_engine("object_detection", "ultralytics") == "ultralytics"
    assert _normalize_engine("object_detection", "tesseract") == "ultralytics"
    assert _normalize_engine("object_detection", "easyocr") == "ultralytics"


def test_normalize_engine_ocr_keeps_valid_ocr_engine():
    assert _normalize_engine("ocr", "tesseract") == "tesseract"
    assert _normalize_engine("ocr", "easyocr") == "easyocr"


def test_normalize_engine_ocr_falls_back_when_invalid():
    assert _normalize_engine("ocr", "ultralytics") == "easyocr"


def _create_monitor(client: TestClient, name: str) -> int:
    created = client.post("/api/monitors", json={"name": name, "display_name": name})
    assert created.status_code == 201, created.text
    return created.json()["id"]


def test_patch_object_detection_with_tesseract_engine_is_normalized_to_ultralytics():
    with TestClient(app) as client:
        monitor_id = _create_monitor(client, "test_engine_norm_od_tesseract")
        try:
            updated = client.patch(
                f"/api/monitors/{monitor_id}",
                json={"inference": {"method": "object_detection", "engine": "tesseract", "model_id": "dummy.pt"}},
            )
            assert updated.status_code == 200, updated.text
            assert updated.json()["inference"]["engine"] == "ultralytics"
            # DBへ保存された値も正規化されていること(APIレスポンスだけの見せかけではない)。
            fetched = client.get(f"/api/monitors/{monitor_id}")
            assert fetched.json()["inference"]["engine"] == "ultralytics"
        finally:
            client.delete(f"/api/monitors/{monitor_id}")


def test_patch_ocr_tesseract_and_easyocr_are_kept_as_is():
    with TestClient(app) as client:
        monitor_id = _create_monitor(client, "test_engine_norm_ocr")
        try:
            r1 = client.patch(f"/api/monitors/{monitor_id}", json={"inference": {"method": "ocr", "engine": "tesseract"}})
            assert r1.json()["inference"]["engine"] == "tesseract"
            r2 = client.patch(f"/api/monitors/{monitor_id}", json={"inference": {"method": "ocr", "engine": "easyocr"}})
            assert r2.json()["inference"]["engine"] == "easyocr"
        finally:
            client.delete(f"/api/monitors/{monitor_id}")


def test_method_switch_object_detection_ocr_object_detection_keeps_engine_synced():
    with TestClient(app) as client:
        monitor_id = _create_monitor(client, "test_engine_norm_switch")
        try:
            r1 = client.patch(f"/api/monitors/{monitor_id}", json={"inference": {"method": "object_detection", "engine": "ultralytics", "model_id": "dummy.pt"}})
            assert r1.json()["inference"]["engine"] == "ultralytics"

            r2 = client.patch(f"/api/monitors/{monitor_id}", json={"inference": {"method": "ocr", "engine": "tesseract"}})
            assert r2.json()["inference"]["engine"] == "tesseract"

            # methodだけをobject_detectionへ戻す(engineを明示的に送らないケース)。
            # 直前(ocr/tesseract)から戻すため、engineはultralyticsへ正規化されるべき。
            r3 = client.patch(f"/api/monitors/{monitor_id}", json={"inference": {"method": "object_detection"}})
            assert r3.json()["inference"]["engine"] == "ultralytics"
        finally:
            client.delete(f"/api/monitors/{monitor_id}")
