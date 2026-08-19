"""開発者向けData Collection機能(POST /api/monitors/{id}/reading/capture)のテスト。

既定で無効(誤操作防止)、有効時のみ保存され、secretを含まないことを確認する。
"""
from __future__ import annotations

import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app

pytestmark = pytest.mark.integration


class _FakeReader:
    def __init__(self, _config):
        self.source_fps = None

    def read(self):
        return True, np.zeros((20, 20, 3), dtype=np.uint8)

    def close(self):
        pass


def test_capture_disabled_by_default(monkeypatch):
    monkeypatch.delenv("ARGUS_ENABLE_DATASET_CAPTURE", raising=False)
    with TestClient(app) as client:
        created = client.post("/api/monitors", json={"name": "capture_disabled_test", "display_name": "テスト", "location": "試験室"})
        monitor_id = created.json()["id"]
        try:
            response = client.post(f"/api/monitors/{monitor_id}/reading/capture")
            assert response.status_code == 403
        finally:
            client.delete(f"/api/monitors/{monitor_id}")


def test_capture_saves_frame_and_metadata_without_secrets(monkeypatch, tmp_path):
    monkeypatch.setenv("ARGUS_ENABLE_DATASET_CAPTURE", "1")
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr("runtime.monitor_runtime.VideoReader", _FakeReader)

    with TestClient(app) as client:
        created = client.post("/api/monitors", json={"name": "capture_enabled_test", "display_name": "テスト", "location": "試験室"})
        monitor_id = created.json()["id"]
        try:
            patched = client.patch(
                f"/api/monitors/{monitor_id}",
                json={"source": {"source_type": "camera", "device_id": 0, "username": "someone", "password": "super-secret"}},
            )
            assert patched.status_code == 200, patched.text

            import time

            deadline = time.monotonic() + 5
            response = None
            while time.monotonic() < deadline:
                response = client.post(f"/api/monitors/{monitor_id}/reading/capture")
                if response.status_code == 200:
                    break
                time.sleep(0.1)

            assert response is not None and response.status_code == 200, response.text if response else "no response"
            body = response.json()
            assert body["saved"] is True

            capture_dir = tmp_path / "dataset_candidates" / str(monitor_id)
            saved_images = list(capture_dir.glob("*.jpg"))
            saved_meta = list(capture_dir.glob("*.json"))
            assert len(saved_images) == 1
            assert len(saved_meta) == 1
            meta = json.loads(saved_meta[0].read_text(encoding="utf-8"))
            dump = json.dumps(meta)
            assert "super-secret" not in dump
            assert "someone" not in dump
        finally:
            client.delete(f"/api/monitors/{monitor_id}")
