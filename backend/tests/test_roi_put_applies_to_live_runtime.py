"""ROI PUTが稼働中のInferenceSchedulerへ実際に反映されることを確認する回帰テスト。

修正前は `roi.py::update_roi` がDBを更新するだけで、稼働中の
`InferenceScheduler.settings`（Runtime起動時にスナップショットされた別dict）を
一切更新しないため、ROIをPUTしても次の推論には全く反映されなかった。
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from runtime.runtime_manager import runtime_manager


def test_roi_put_updates_the_running_inference_scheduler(monkeypatch):
    class FakeReader:
        def __init__(self, _config):
            self.source_fps = None

        def read(self):
            import numpy as np

            return True, np.zeros((20, 20, 3), dtype=np.uint8)

        def close(self):
            pass

    monkeypatch.setattr("runtime.monitor_runtime.VideoReader", FakeReader)

    with TestClient(app) as client:
        created = client.post("/api/monitors", json={"name": "roi_live_apply_test", "display_name": "テスト", "location": "試験室"})
        assert created.status_code == 201, created.text
        monitor_id = created.json()["id"]
        try:
            patched = client.patch(
                f"/api/monitors/{monitor_id}",
                json={
                    "source": {"source_type": "camera", "device_id": 0},
                    "inference": {"method": "object_detection", "engine": "ultralytics", "model_id": None, "video_fps": 5, "inference_fps": 5},
                },
            )
            assert patched.status_code == 200, patched.text

            runtime = runtime_manager.get_runtime(monitor_id)
            assert runtime is not None
            assert runtime.inference_scheduler.settings.get("roi") in (None, {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0})

            put_response = client.put(f"/api/monitors/{monitor_id}/roi", json={"x": 0.25, "y": 0.25, "width": 0.5, "height": 0.5})
            assert put_response.status_code == 200, put_response.text

            runtime_after = runtime_manager.get_runtime(monitor_id)
            assert runtime_after is not None
            assert runtime_after.inference_scheduler.settings["roi"] == {"x": 0.25, "y": 0.25, "width": 0.5, "height": 0.5}
        finally:
            client.delete(f"/api/monitors/{monitor_id}")
