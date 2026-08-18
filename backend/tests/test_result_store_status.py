"""result_store.save_result がMonitor.status(Dashboardのバッジ)を
推論エラー時にも正しく更新することを確認する回帰テスト。

修正前は`if monitor and not result.error:`の条件により、推論エラー時に
Monitor.statusが更新されず、Dashboard側で「読取不能」バッジが表示されなかった。
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.inference.base import InferenceResult
from app.main import app
from app.services.result_store import save_result


def test_monitor_status_becomes_read_error_on_inference_error():
    with TestClient(app) as client:
        created = client.post("/api/monitors", json={"name": "result_store_status_test", "display_name": "テスト", "location": "試験室"})
        assert created.status_code == 201, created.text
        monitor_id = created.json()["id"]
        try:
            save_result(monitor_id, InferenceResult(value="123", confidence=0.9, engine="mock"))
            assert client.get(f"/api/monitors/{monitor_id}").json()["status"] == "normal"

            save_result(monitor_id, InferenceResult(error="MODEL_NOT_CONFIGURED", engine="ultralytics"))
            body = client.get(f"/api/monitors/{monitor_id}").json()
            assert body["status"] == "read_error"
            assert body["last_inference_error"] == "MODEL_NOT_CONFIGURED"
            # previous_valueは推論失敗を挟んでも失われないこと。
            assert body["current_value"] == "123"
        finally:
            client.delete(f"/api/monitors/{monitor_id}")
