"""ROI PUTが稼働中のInferenceSchedulerへ実際に反映されることを確認する回帰テスト。

修正前は `roi.py::update_roi` がDBを更新するだけで、稼働中の
`InferenceScheduler.settings`（Runtime起動時にスナップショットされた別dict）を
一切更新しないため、ROIをPUTしても次の推論には全く反映されなかった。

Issue #16: 上記を修正した後、実UI確認で新たな回帰が見つかった。ROIを保存すると
稼働中の映像ソース自体が「映像ソースを開けません」になる。原因は、ROI保存が
`restart_runtime()`(=RuntimeManager.start_monitor()経由でVideoReaderを含めて
丸ごと再接続)を呼んでいたため。ROIはInferenceSchedulerの設定であり、sourceとは
無関係なので、以下を追加で確認する:
  - ROI保存はVideoReaderを再接続しない(reader/runtimeインスタンスが同一のまま)
  - ROI保存でsource(url/username/encrypted_password等)がDB上で一切変化しない
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.models import Monitor
from runtime.runtime_manager import runtime_manager


class _FakeReader:
    instances = 0

    def __init__(self, _config):
        _FakeReader.instances += 1
        self.source_fps = None

    def read(self):
        import numpy as np

        return True, np.zeros((20, 20, 3), dtype=np.uint8)

    def close(self):
        pass


def test_roi_put_updates_the_running_inference_scheduler(monkeypatch):
    _FakeReader.instances = 0
    monkeypatch.setattr("runtime.monitor_runtime.VideoReader", _FakeReader)

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
            reader_before = runtime.reader
            # 他テストで作成済みのMonitor(共有DB)がapp起動時に併せて再接続される場合が
            # あるため、絶対値ではなくROI保存前後の差分(増分)で判定する。
            instances_before_roi_put = _FakeReader.instances

            put_response = client.put(f"/api/monitors/{monitor_id}/roi", json={"x": 0.25, "y": 0.25, "width": 0.5, "height": 0.5})
            assert put_response.status_code == 200, put_response.text

            runtime_after = runtime_manager.get_runtime(monitor_id)
            assert runtime_after is not None
            assert runtime_after.inference_scheduler.settings["roi"] == {"x": 0.25, "y": 0.25, "width": 0.5, "height": 0.5}
            # Issue #16の回帰: ROI保存でVideoReaderが再接続されていないこと
            # (同一Runtimeインスタンス・同一readerインスタンスのまま)。
            assert runtime_after is runtime, "ROI保存でRuntimeインスタンス自体が置き換わらないこと"
            assert runtime_after.reader is reader_before, "ROI保存でVideoReaderが再接続されないこと"
            assert _FakeReader.instances == instances_before_roi_put, "ROI保存でVideoReaderが追加生成されないこと"
        finally:
            client.delete(f"/api/monitors/{monitor_id}")


def test_roi_put_does_not_change_source_credentials_in_db(monkeypatch):
    """ROI保存前後でDB上のsource(url/username/encrypted_password等)が一切変化しないこと。

    テスト用のURL/username/passwordは架空の値(RFC 5737予約アドレス)を使用する。
    """
    monkeypatch.setattr("runtime.monitor_runtime.VideoReader", _FakeReader)

    with TestClient(app) as client:
        created = client.post("/api/monitors", json={"name": "roi_source_integrity_test", "display_name": "テスト", "location": "試験室"})
        assert created.status_code == 201, created.text
        monitor_id = created.json()["id"]
        try:
            patched = client.patch(
                f"/api/monitors/{monitor_id}",
                json={
                    "source": {"source_type": "url", "url": "http://198.51.100.10/mjpg/video.mjpg", "username": "roiuser", "password": "roi-test-pass"},
                    "inference": {"method": "object_detection", "engine": "ultralytics", "model_id": None, "video_fps": 5, "inference_fps": 5},
                },
            )
            assert patched.status_code == 200, patched.text

            db = SessionLocal()
            try:
                before = db.get(Monitor, monitor_id)
                source_snapshot_before = (
                    before.source.source_type,
                    before.source.url,
                    before.source.username,
                    before.source.encrypted_password,
                    before.source.device_id,
                )
            finally:
                db.close()

            put_response = client.put(f"/api/monitors/{monitor_id}/roi", json={"x": 0.1, "y": 0.1, "width": 0.3, "height": 0.3})
            assert put_response.status_code == 200, put_response.text

            db = SessionLocal()
            try:
                after = db.get(Monitor, monitor_id)
                source_snapshot_after = (
                    after.source.source_type,
                    after.source.url,
                    after.source.username,
                    after.source.encrypted_password,
                    after.source.device_id,
                )
            finally:
                db.close()

            assert source_snapshot_after == source_snapshot_before, "ROI保存でsource(url/username/encrypted_password等)が変化しないこと"

            detail = client.get(f"/api/monitors/{monitor_id}").json()
            assert detail["source"]["has_password"] is True, "ROI保存後もpasswordが保持されていること"
        finally:
            client.delete(f"/api/monitors/{monitor_id}")
