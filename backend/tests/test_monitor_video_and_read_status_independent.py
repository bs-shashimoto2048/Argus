"""Issue #29: 映像Runtime状態(Monitor.status)と読取・推論状態(inference_status)が
互いを上書きしない独立した概念として表現できることを確認する結合テスト。

実際のHTTP経路(PATCH /api/monitors/{id})でRuntimeを起動し、VideoReader/InferenceEngineの
みFakeに差し替える(RuntimeManager, InferenceScheduler, ReadingStabilizer, ResultStore,
Routerはすべて本物の経路を通す)。
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
    """常にframe読み取りに成功するFake VideoReader(映像は常にrunning)。"""

    def __init__(self, _config):
        self.source_fps = None

    def read(self):
        return True, np.zeros((20, 20, 3), dtype=np.uint8)

    def close(self):
        pass


class _AlwaysNoDetectionEngine:
    """常に検出0件を返すFake Engine(推論だけがread_errorへ収束する)。"""

    def infer(self, image, settings=None):
        return InferenceResult(value=None, confidence=None, error="NO_DETECTION", engine="fake")


def test_video_running_and_read_error_are_reported_independently(monkeypatch):
    monkeypatch.setattr("runtime.monitor_runtime.VideoReader", _FakeReader)
    engine = _AlwaysNoDetectionEngine()
    monkeypatch.setattr("runtime.inference_scheduler.create_engine", lambda *a, **kw: engine)

    with TestClient(app) as client:
        created = client.post("/api/monitors", json={"name": "video_read_independent_test", "display_name": "テスト", "location": "試験室"})
        assert created.status_code == 201, created.text
        monitor_id = created.json()["id"]
        try:
            patched = client.patch(
                f"/api/monitors/{monitor_id}",
                json={
                    "source": {"source_type": "local_camera", "device_id": 0},
                    "inference": {
                        "method": "object_detection",
                        "engine": "ultralytics",
                        "model_id": "dummy.pt",
                        "video_fps": 30,
                        "inference_fps": 20,
                        "reading": {"max_consecutive_failures": 3},
                    },
                },
            )
            assert patched.status_code == 200, patched.text

            deadline = time.monotonic() + 5
            body = None
            while time.monotonic() < deadline:
                body = client.get(f"/api/monitors/{monitor_id}").json()
                if body["inference_status"] == "read_error":
                    break
                time.sleep(0.1)

            assert body is not None
            # 推論側は検出0件が続きread_errorへ収束する。
            assert body["inference_status"] == "read_error"
            # 映像取得自体はFakeReaderが常に成功しているため、read_errorに巻き込まれず running のまま
            # (Issue #29: read_errorが発生しても「映像停止」と誤認させない)。
            assert body["status"] == "running"
        finally:
            client.delete(f"/api/monitors/{monitor_id}")


def test_video_stopped_retains_previous_confirmed_value_and_read_status(monkeypatch):
    monkeypatch.setattr("runtime.monitor_runtime.VideoReader", _FakeReader)

    class _FixedValueEngine:
        def infer(self, image, settings=None):
            return InferenceResult(value="123", confidence=0.95, engine="fake")

    monkeypatch.setattr("runtime.inference_scheduler.create_engine", lambda *a, **kw: _FixedValueEngine())

    with TestClient(app) as client:
        created = client.post("/api/monitors", json={"name": "video_stopped_retains_value_test", "display_name": "テスト", "location": "試験室"})
        assert created.status_code == 201, created.text
        monitor_id = created.json()["id"]
        try:
            patched = client.patch(
                f"/api/monitors/{monitor_id}",
                json={
                    "source": {"source_type": "local_camera", "device_id": 0},
                    "inference": {
                        "method": "object_detection",
                        "engine": "ultralytics",
                        "model_id": "dummy.pt",
                        "video_fps": 30,
                        "inference_fps": 20,
                        "reading": {"window_size": 3, "required_matches": 2},
                    },
                },
            )
            assert patched.status_code == 200, patched.text

            deadline = time.monotonic() + 5
            body = None
            while time.monotonic() < deadline:
                body = client.get(f"/api/monitors/{monitor_id}").json()
                if body["current_value"] is not None:
                    break
                time.sleep(0.1)
            assert body is not None
            assert body["current_value"] == "123"
            assert body["inference_status"] in ("ok", "low_confidence")
            assert body["status"] == "running"

            # Monitorを無効化して映像Runtimeを止める(source/推論設定自体には触れない)。
            disabled = client.patch(f"/api/monitors/{monitor_id}", json={"enabled": False})
            assert disabled.status_code == 200, disabled.text

            body = client.get(f"/api/monitors/{monitor_id}").json()
            # 映像Runtimeは停止するが、直前のConfirmed値・読取状態はそのまま保持される
            # (Issue #29: 映像stopped + 過去Confirmed値ありの組合せを壊さない)。
            assert body["status"] == "stopped"
            assert body["current_value"] == "123"
            assert body["inference_status"] in ("ok", "low_confidence")
        finally:
            client.delete(f"/api/monitors/{monitor_id}")
