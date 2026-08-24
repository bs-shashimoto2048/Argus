"""Monitor基本情報(name/display_name/location)編集(Issue #20/#25)のテスト。

基本情報だけのPATCH(source/inference/enabledのいずれも含まない)では、
Runtime/VideoReader/InferenceSchedulerに一切触れないことを検証する
(修正前は、metaデータのみの変更でもupdate_monitor()が常にrestart_inference_only()を
呼び、稼働中のInferenceScheduler(=ReadingStabilizerの状態含む)を無条件に
作り直していた)。

Issue #25では内部識別名(name)も編集可能にした。実行時の識別には常にMonitor ID
(id)が使われ、name自体はRuntimeManager/ルーティング/ファイルパス生成のいずれにも
使われないことを事前調査で確認済み(名前の役割はDB UNIQUE制約とCSV出力の
monitor_name列/画面表示のみ)。
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


# --- Issue #25: 内部識別名(name)の編集 ---------------------------------------

def test_name_patch_updates_successfully_and_reflects_in_api():
    with TestClient(app) as client:
        monitor_id = _create_running_monitor(client, "name_update_test_before")
        try:
            response = client.patch(f"/api/monitors/{monitor_id}", json={"name": "name_update_test_after"})
            assert response.status_code == 200, response.text
            assert response.json()["name"] == "name_update_test_after"

            fetched = client.get(f"/api/monitors/{monitor_id}").json()
            assert fetched["name"] == "name_update_test_after"
            assert fetched["id"] == monitor_id  # Monitor IDは不変
        finally:
            client.delete(f"/api/monitors/{monitor_id}")


def test_name_patch_rejects_duplicate_name(monkeypatch):
    # 2つのMonitorを同時に稼働させるテストなので、実カメラ(device_id=0)への
    # 二重接続を避けるためVideoReaderをモック化する(name一意性の確認にVideoReader
    # の実挙動は不要)。
    monkeypatch.setattr("runtime.monitor_runtime.VideoReader", _FakeReader)
    with TestClient(app) as client:
        id_a = _create_running_monitor(client, "name_dup_test_a")
        id_b = _create_running_monitor(client, "name_dup_test_b")
        try:
            response = client.patch(f"/api/monitors/{id_b}", json={"name": "name_dup_test_a"})
            assert response.status_code == 400
            assert "既に使用されています" in response.json()["detail"]

            # 重複拒否後もMonitor Bのnameは変化していないこと。
            fetched_b = client.get(f"/api/monitors/{id_b}").json()
            assert fetched_b["name"] == "name_dup_test_b"
        finally:
            client.delete(f"/api/monitors/{id_a}")
            client.delete(f"/api/monitors/{id_b}")


def test_name_patch_allows_setting_same_name_as_before():
    """自分自身の現在のnameと同じ値への「変更」はUNIQUE違反にならず許容される。"""
    with TestClient(app) as client:
        monitor_id = _create_running_monitor(client, "name_noop_test")
        try:
            response = client.patch(f"/api/monitors/{monitor_id}", json={"name": "name_noop_test", "location": "更新"})
            assert response.status_code == 200, response.text
            assert response.json()["name"] == "name_noop_test"
        finally:
            client.delete(f"/api/monitors/{monitor_id}")


def test_name_patch_rejects_invalid_characters():
    with TestClient(app) as client:
        monitor_id = _create_running_monitor(client, "name_invalid_char_test")
        try:
            for bad_name in ("bad name", "名前", "bad/name", "", "a" * 81):
                response = client.patch(f"/api/monitors/{monitor_id}", json={"name": bad_name})
                assert response.status_code == 422, f"{bad_name!r} should be rejected"

            # 拒否後もnameは変化していないこと。
            fetched = client.get(f"/api/monitors/{monitor_id}").json()
            assert fetched["name"] == "name_invalid_char_test"
        finally:
            client.delete(f"/api/monitors/{monitor_id}")


def test_name_patch_on_nonexistent_monitor_returns_error():
    with TestClient(app) as client:
        response = client.patch("/api/monitors/999999999", json={"name": "does_not_matter"})
        assert response.status_code == 400
        assert "見つかりません" in response.json()["detail"]


def test_name_patch_does_not_change_source_or_inference_settings(monkeypatch):
    monkeypatch.setattr("runtime.monitor_runtime.VideoReader", _FakeReader)
    with TestClient(app) as client:
        monitor_id = _create_running_monitor(client, "name_no_side_effect_test")
        try:
            db = SessionLocal()
            try:
                before = db.get(Monitor, monitor_id)
                source_before = (before.source.source_type, before.source.device_id, before.source.url, before.source.username)
                inference_before = (before.inference.method, before.inference.engine, before.inference.model_id, before.inference.roi)
            finally:
                db.close()

            response = client.patch(f"/api/monitors/{monitor_id}", json={"name": "name_no_side_effect_test_renamed"})
            assert response.status_code == 200, response.text

            db = SessionLocal()
            try:
                after = db.get(Monitor, monitor_id)
                source_after = (after.source.source_type, after.source.device_id, after.source.url, after.source.username)
                inference_after = (after.inference.method, after.inference.engine, after.inference.model_id, after.inference.roi)
            finally:
                db.close()

            assert source_after == source_before, "nameだけの変更でsource設定が変化しないこと"
            assert inference_after == inference_before, "nameだけの変更でinference設定が変化しないこと(ROI含む)"
        finally:
            client.delete(f"/api/monitors/{monitor_id}")


def test_name_patch_does_not_restart_runtime_or_recreate_inference_scheduler(monkeypatch):
    _FakeReader.instances = 0
    monkeypatch.setattr("runtime.monitor_runtime.VideoReader", _FakeReader)
    with TestClient(app) as client:
        monitor_id = _create_running_monitor(client, "name_no_restart_test")
        try:
            runtime = runtime_manager.get_runtime(monitor_id)
            assert runtime is not None
            reader_before = runtime.reader
            scheduler_before = runtime.inference_scheduler
            instances_before = _FakeReader.instances

            response = client.patch(f"/api/monitors/{monitor_id}", json={"name": "name_no_restart_test_renamed"})
            assert response.status_code == 200, response.text

            runtime_after = runtime_manager.get_runtime(monitor_id)
            assert runtime_after is runtime, "nameだけの変更でMonitorRuntimeインスタンス自体が置き換わらないこと"
            assert runtime_after.reader is reader_before, "nameだけの変更でVideoReaderが再接続されないこと"
            assert runtime_after.inference_scheduler is scheduler_before, "nameだけの変更でInferenceSchedulerが再生成されないこと"
            assert _FakeReader.instances == instances_before, "nameだけの変更でVideoReaderが追加生成されないこと"
        finally:
            client.delete(f"/api/monitors/{monitor_id}")


def test_name_change_does_not_affect_other_monitor(monkeypatch):
    # 2つのMonitorを同時に稼働させるテストなので、実カメラ(device_id=0)への
    # 二重接続を避けるためVideoReaderをモック化する(他Monitorへの非影響確認に
    # VideoReaderの実挙動は不要)。
    monkeypatch.setattr("runtime.monitor_runtime.VideoReader", _FakeReader)
    with TestClient(app) as client:
        id_a = _create_running_monitor(client, "name_isolation_test_a")
        id_b = _create_running_monitor(client, "name_isolation_test_b")
        try:
            response = client.patch(f"/api/monitors/{id_a}", json={"name": "name_isolation_test_a_renamed"})
            assert response.status_code == 200, response.text

            fetched_b = client.get(f"/api/monitors/{id_b}").json()
            assert fetched_b["name"] == "name_isolation_test_b", "他Monitorのnameが変化しないこと"
        finally:
            client.delete(f"/api/monitors/{id_a}")
            client.delete(f"/api/monitors/{id_b}")


def test_csv_export_uses_new_name_only_for_new_rows_after_rename(tmp_path):
    """monitor_id列は不変、monitor_name列は変更後の新しい名前を出力し、
    過去に書き込んだ行は書き換えないことを確認する(Issue #17/#21の単一ファイル
    追記方式・dedupには一切触れない、export_monitor_for_test()を直接呼ぶ単体確認)。"""
    from app.services import csv_export_service as csv_svc

    with TestClient(app) as client:
        monitor_id = _create_running_monitor(client, "csv_rename_test_before")
        try:
            db = SessionLocal()
            try:
                monitor = db.get(Monitor, monitor_id)
                hour = csv_svc.hour_bucket_jst()
                outcome_before = csv_svc.export_monitor_for_test(monitor, hour, str(tmp_path))
                assert outcome_before.status == "written"
            finally:
                db.close()

            rename_response = client.patch(f"/api/monitors/{monitor_id}", json={"name": "csv_rename_test_after"})
            assert rename_response.status_code == 200, rename_response.text

            db = SessionLocal()
            try:
                renamed_monitor = db.get(Monitor, monitor_id)
                outcome_after = csv_svc.export_monitor_for_test(renamed_monitor, hour, str(tmp_path))
                assert outcome_after.status == "written"
            finally:
                db.close()

            path = tmp_path / csv_svc.CSV_FILENAME_TEST
            lines = path.read_text(encoding="utf-8-sig").strip().splitlines()
            data_lines = lines[1:]
            assert len(data_lines) == 2
            row_before = data_lines[0].split(",")
            row_after = data_lines[1].split(",")
            assert row_before[1] == row_after[1] == str(monitor_id)  # monitor_idは不変
            assert row_before[2] == "csv_rename_test_before"  # 過去行は書き換えない
            assert row_after[2] == "csv_rename_test_after"  # 新しい追記行は新名称
        finally:
            client.delete(f"/api/monitors/{monitor_id}")
