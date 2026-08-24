"""Monitor基本情報(display_name/location)編集(Issue #20)のテスト。

基本情報だけのPATCH(source/inference/enabledのいずれも含まない)では、
Runtime/VideoReader/InferenceSchedulerに一切触れないことを検証する
(修正前は、metaデータのみの変更でもupdate_monitor()が常にrestart_inference_only()を
呼び、稼働中のInferenceScheduler(=ReadingStabilizerの状態含む)を無条件に
作り直していた)。
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


def _create_running_monitor(client: TestClient, name: str) -> int:
    created = client.post("/api/monitors", json={"name": name, "display_name": "元の表示名", "location": "元の場所"})
    assert created.status_code == 201, created.text
    monitor_id = created.json()["id"]
    patched = client.patch(
        f"/api/monitors/{monitor_id}",
        json={
            "source": {"source_type": "camera", "device_id": 0},
            "inference": {"method": "object_detection", "engine": "ultralytics", "model_id": None, "video_fps": 5, "inference_fps": 5},
        },
    )
    assert patched.status_code == 200, patched.text
    return monitor_id


def test_basic_info_patch_updates_display_name_and_location():
    with TestClient(app) as client:
        monitor_id = _create_running_monitor(client, "basic_info_update_test")
        try:
            response = client.patch(f"/api/monitors/{monitor_id}", json={"display_name": "新しい表示名", "location": "新しい設置場所"})
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["display_name"] == "新しい表示名"
            assert body["location"] == "新しい設置場所"

            fetched = client.get(f"/api/monitors/{monitor_id}").json()
            assert fetched["display_name"] == "新しい表示名"
            assert fetched["location"] == "新しい設置場所"
        finally:
            client.delete(f"/api/monitors/{monitor_id}")


def test_basic_info_patch_rejects_empty_display_name():
    with TestClient(app) as client:
        monitor_id = _create_running_monitor(client, "basic_info_validation_test")
        try:
            response = client.patch(f"/api/monitors/{monitor_id}", json={"display_name": ""})
            assert response.status_code == 422
        finally:
            client.delete(f"/api/monitors/{monitor_id}")


def test_basic_info_patch_on_nonexistent_monitor_returns_error():
    """既存のPATCH /api/monitors/{id}は、ValueError(Monitor未存在を含む)を
    一律400として返す既存仕様(GET/DELETEの404とは異なる)。Issue #20でこの
    既存API自体の挙動は変更しないため、その仕様どおり400になることを確認する。"""
    with TestClient(app) as client:
        response = client.patch("/api/monitors/999999999", json={"display_name": "存在しない"})
        assert response.status_code == 400
        assert "見つかりません" in response.json()["detail"]


def test_basic_info_patch_does_not_change_source_or_inference_settings(monkeypatch):
    monkeypatch.setattr("runtime.monitor_runtime.VideoReader", _FakeReader)
    with TestClient(app) as client:
        monitor_id = _create_running_monitor(client, "basic_info_no_side_effect_test")
        try:
            db = SessionLocal()
            try:
                before = db.get(Monitor, monitor_id)
                source_before = (before.source.source_type, before.source.device_id, before.source.url, before.source.username)
                inference_before = (before.inference.method, before.inference.engine, before.inference.model_id, before.inference.video_fps, before.inference.inference_fps, before.inference.roi, before.inference.roi_mode)
            finally:
                db.close()

            response = client.patch(f"/api/monitors/{monitor_id}", json={"display_name": "変更後", "location": "変更後の場所"})
            assert response.status_code == 200, response.text

            db = SessionLocal()
            try:
                after = db.get(Monitor, monitor_id)
                source_after = (after.source.source_type, after.source.device_id, after.source.url, after.source.username)
                inference_after = (after.inference.method, after.inference.engine, after.inference.model_id, after.inference.video_fps, after.inference.inference_fps, after.inference.roi, after.inference.roi_mode)
            finally:
                db.close()

            assert source_after == source_before, "基本情報だけの変更でsource設定が変化しないこと"
            assert inference_after == inference_before, "基本情報だけの変更でinference設定が変化しないこと"
        finally:
            client.delete(f"/api/monitors/{monitor_id}")


def test_basic_info_patch_does_not_restart_runtime_or_recreate_inference_scheduler(monkeypatch):
    """基本情報だけのPATCHでは、稼働中のMonitorRuntime/VideoReader/InferenceSchedulerの
    どれも再生成・再接続されない(同一インスタンスのまま)ことを確認する回帰テスト。"""
    _FakeReader.instances = 0
    monkeypatch.setattr("runtime.monitor_runtime.VideoReader", _FakeReader)
    with TestClient(app) as client:
        monitor_id = _create_running_monitor(client, "basic_info_no_restart_test")
        try:
            runtime = runtime_manager.get_runtime(monitor_id)
            assert runtime is not None
            reader_before = runtime.reader
            scheduler_before = runtime.inference_scheduler
            instances_before = _FakeReader.instances

            response = client.patch(f"/api/monitors/{monitor_id}", json={"display_name": "変更後の名前", "location": "変更後の場所"})
            assert response.status_code == 200, response.text

            runtime_after = runtime_manager.get_runtime(monitor_id)
            assert runtime_after is runtime, "基本情報だけの変更でMonitorRuntimeインスタンス自体が置き換わらないこと"
            assert runtime_after.reader is reader_before, "基本情報だけの変更でVideoReaderが再接続されないこと"
            assert runtime_after.inference_scheduler is scheduler_before, "基本情報だけの変更でInferenceSchedulerが再生成されないこと(ReadingStabilizerの状態も保持される)"
            assert _FakeReader.instances == instances_before, "基本情報だけの変更でVideoReaderが追加生成されないこと"
        finally:
            client.delete(f"/api/monitors/{monitor_id}")


def test_enabled_change_still_restarts_runtime_as_before():
    """回帰確認: enabledの変更は引き続きrestart_runtime()経由でRuntimeの起動/停止を行う
    (Issue #20の分岐追加が既存のenabled切替挙動を壊していないこと)。"""
    with TestClient(app) as client:
        monitor_id = _create_running_monitor(client, "basic_info_enabled_still_restarts_test")
        try:
            assert runtime_manager.get_runtime(monitor_id) is not None

            response = client.patch(f"/api/monitors/{monitor_id}", json={"enabled": False})
            assert response.status_code == 200, response.text
            assert runtime_manager.get_runtime(monitor_id) is None, "enabled=falseでRuntimeが停止すること"
        finally:
            client.delete(f"/api/monitors/{monitor_id}")
