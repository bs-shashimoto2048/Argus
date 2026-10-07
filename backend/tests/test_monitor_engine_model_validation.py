"""engine/model_idの組合せ検証のテスト(Issue #38)。

cpp_onnxはregistry.jsonでengine=cpp_onnx/profile=digital|drumとして登録されたモデルのみ許可し、
ultralyticsではcpp_onnx専用モデルを拒否する。ultralyticsの自由入力model pathは従来どおり許可する。
"""

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.services.monitor_service import _validate_engine_model


@pytest.fixture
def monitor_id():
    with TestClient(app) as client:
        created = client.post("/api/monitors", json={"name": "test_engine_model_validation", "display_name": "v"})
        assert created.status_code == 201, created.text
        yield client, created.json()["id"]
        client.delete(f"/api/monitors/{created.json()['id']}")


def _patch(client, mid, **inference):
    return client.patch(f"/api/monitors/{mid}", json={"inference": {"method": "object_detection", **inference}})


@pytest.mark.parametrize("model", ["digital_production_v1.onnx", "drum_production_v1.onnx"])
def test_cpp_onnx_with_registered_model_is_saved(monitor_id, model):
    client, mid = monitor_id
    res = _patch(client, mid, engine="cpp_onnx", model_id=model)
    assert res.status_code == 200, res.text
    fetched = client.get(f"/api/monitors/{mid}").json()["inference"]
    assert (fetched["engine"], fetched["model_id"]) == ("cpp_onnx", model)


@pytest.mark.parametrize("model", [None, "meter_digits_v1.pt", "unknown_model.onnx"])
def test_cpp_onnx_with_invalid_model_is_rejected_with_400(monitor_id, model):
    client, mid = monitor_id
    res = _patch(client, mid, engine="cpp_onnx", model_id=model)
    assert res.status_code == 400, res.text
    assert "INVALID_ENGINE_MODEL" in res.json()["detail"]
    # 拒否された保存はDBへ反映されない。
    assert client.get(f"/api/monitors/{mid}").json()["inference"]["engine"] == "ultralytics"


def test_ultralytics_with_cpp_onnx_model_is_rejected_with_400(monitor_id):
    client, mid = monitor_id
    res = _patch(client, mid, engine="ultralytics", model_id="digital_production_v1.onnx")
    assert res.status_code == 400, res.text
    assert "INVALID_ENGINE_MODEL" in res.json()["detail"]


def test_ultralytics_free_input_model_path_still_allowed(monitor_id):
    client, mid = monitor_id
    for model in ("meter_digits_v1.pt", "some/free/path/custom.pt", None):
        res = _patch(client, mid, engine="ultralytics", model_id=model)
        assert res.status_code == 200, res.text


def test_engine_only_patch_is_validated_against_existing_model(monitor_id):
    client, mid = monitor_id
    assert _patch(client, mid, engine="cpp_onnx", model_id="drum_production_v1.onnx").status_code == 200
    # model_idを変えずengineだけultralyticsへ戻すと、cpp_onnx専用モデルが残るため拒否される。
    assert _patch(client, mid, engine="ultralytics").status_code == 400
    assert _patch(client, mid, engine="ultralytics", model_id=None).status_code == 200


def test_validate_engine_model_ignores_ocr_engines():
    _validate_engine_model("easyocr", None)
    _validate_engine_model("tesseract", "anything")
