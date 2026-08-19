"""Raw sequence -> ReadingStabilizer -> ResultStore -> API までの結合テスト。

実際のHTTP経路(PATCH /api/monitors/{id})でRuntimeを起動し、Engineの生の
読み取り列(揺れを含む)が最終的にConfirmed値としてMonitor APIへ反映される
ことを確認する。VideoReader/InferenceEngineのみFakeに差し替え、それ以外
(RuntimeManager, InferenceScheduler, ReadingStabilizer, ResultStore, Router)
はすべて本物の経路を通す。
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


class _SequenceEngine:
    """呼ばれるたびに、揺れを含む固定シーケンスを順番に返すFake Engine。"""

    def __init__(self, sequence: list[str]):
        self._sequence = sequence
        self._index = 0

    def infer(self, image, settings=None):
        value = self._sequence[min(self._index, len(self._sequence) - 1)]
        self._index += 1
        return InferenceResult(value=value, confidence=0.9, engine="fake")


def test_raw_sequence_converges_to_confirmed_value_via_http_api(monkeypatch):
    monkeypatch.setattr("runtime.monitor_runtime.VideoReader", _FakeReader)
    # 002560が優勢だが誤読(002580)も混じる、実運用に近い揺れを模したシーケンス。
    engine = _SequenceEngine(["002560", "002560", "002580", "002560", "002560", "002560"])
    monkeypatch.setattr("runtime.inference_scheduler.create_engine", lambda *a, **kw: engine)

    with TestClient(app) as client:
        created = client.post("/api/monitors", json={"name": "reading_pipeline_integration_test", "display_name": "テスト", "location": "試験室"})
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
                        "reading": {"window_size": 6, "required_matches": 3},
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
            assert body["current_value"] == "002560", body
            assert body["inference_status"] in ("ok", "low_confidence")
            assert body["status"] == "normal"
        finally:
            client.delete(f"/api/monitors/{monitor_id}")
