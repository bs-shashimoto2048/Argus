"""GET /api/monitors/{id}/reading/diagnostics のレスポンス内容を確認する。

password/認証URL/secret/filesystem内部pathを含めないこと、
raw recent readings・confirmed値・agreement/consecutive_failuresが
返ることを確認する。
"""
from __future__ import annotations

import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.inference.base import InferenceResult
from app.main import app

pytestmark = pytest.mark.integration


class _FakeReader:
    def __init__(self, _config):
        self.source_fps = None

    def read(self):
        return True, np.zeros((20, 20, 3), dtype=np.uint8)

    def close(self):
        pass


class _ConstantEngine:
    def infer(self, image, settings=None):
        return InferenceResult(value="002560", confidence=0.85, engine="fake")


def test_reading_diagnostics_returns_raw_and_confirmed_without_secrets(monkeypatch):
    monkeypatch.setattr("runtime.monitor_runtime.VideoReader", _FakeReader)
    monkeypatch.setattr("runtime.inference_scheduler.create_engine", lambda *a, **kw: _ConstantEngine())

    with TestClient(app) as client:
        created = client.post("/api/monitors", json={"name": "reading_diagnostics_test", "display_name": "テスト", "location": "試験室"})
        monitor_id = created.json()["id"]
        try:
            client.patch(
                f"/api/monitors/{monitor_id}",
                json={
                    "source": {"source_type": "local_camera", "device_id": 0, "username": "someone", "password": "super-secret"},
                    "inference": {"method": "object_detection", "engine": "ultralytics", "model_id": "dummy.pt", "video_fps": 20, "inference_fps": 10, "reading": {"window_size": 3, "required_matches": 2}},
                },
            )

            deadline = time.monotonic() + 5
            body = None
            while time.monotonic() < deadline:
                response = client.get(f"/api/monitors/{monitor_id}/reading/diagnostics")
                if response.status_code == 200 and response.json()["confirmed"]["value"]:
                    body = response.json()
                    break
                time.sleep(0.1)

            assert body is not None, "diagnosticsがConfirmed値を返すまで待機できませんでした"
            assert body["confirmed"]["value"] == "002560"
            assert body["confirmed"]["validation_status"] in ("confirmed", "low_confidence")
            assert body["confirmed"]["agreement_count"] >= 2
            assert body["consecutive_failures"] == 0
            assert len(body["recent_raw"]) > 0
            assert all(reading["value"] == "002560" for reading in body["recent_raw"])

            dump = str(body)
            assert "super-secret" not in dump
            assert "someone" not in dump
        finally:
            client.delete(f"/api/monitors/{monitor_id}")


def test_reading_diagnostics_404_when_runtime_not_running():
    with TestClient(app) as client:
        created = client.post("/api/monitors", json={"name": "reading_diagnostics_stopped_test", "display_name": "テスト", "location": "試験室"})
        monitor_id = created.json()["id"]
        try:
            response = client.get(f"/api/monitors/{monitor_id}/reading/diagnostics")
            assert response.status_code == 409
        finally:
            client.delete(f"/api/monitors/{monitor_id}")
