"""Monitorごとの測定単位(value_unit)のテスト。

value_unitは表示用メタデータ(例: m³ / kWh)。保存・変更してもRuntime(VideoReader/
InferenceScheduler)・source/inference設定・読取基準値は変化しない(基本情報だけのPATCH)。
"""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.core.database import SessionLocal
from app.main import app
from app.models import Monitor
from runtime.runtime_manager import runtime_manager


class _FakeReader:
    def __init__(self, _config):
        self.source_fps = None

    def read(self):
        import numpy as np

        return True, np.zeros((20, 20, 3), dtype=np.uint8)

    def close(self):
        pass


def test_create_saves_value_unit_and_defaults_to_empty_string():
    with TestClient(app) as client:
        ids = []
        try:
            with_unit = client.post("/api/monitors", json={"name": "unit_create_a", "display_name": "単位あり", "value_unit": "m³"})
            assert with_unit.status_code == 201, with_unit.text
            assert with_unit.json()["value_unit"] == "m³"
            without = client.post("/api/monitors", json={"name": "unit_create_b", "display_name": "単位なし"})
            assert without.status_code == 201, without.text
            assert without.json()["value_unit"] == ""  # 未指定は空文字(null不可)
            ids = [with_unit.json()["id"], without.json()["id"]]
            fetched = {m["id"]: m for m in client.get("/api/monitors").json()["monitors"]}
            assert fetched[ids[0]]["value_unit"] == "m³"
            assert fetched[ids[1]]["value_unit"] == ""
        finally:
            for monitor_id in ids:
                client.delete(f"/api/monitors/{monitor_id}")


def test_patch_changes_trims_and_clears_value_unit():
    with TestClient(app) as client:
        monitor_id = client.post("/api/monitors", json={"name": "unit_patch_test", "display_name": "単位変更"}).json()["id"]
        try:
            assert client.patch(f"/api/monitors/{monitor_id}", json={"value_unit": "  kWh  "}).json()["value_unit"] == "kWh"  # 前後空白はtrim
            assert client.patch(f"/api/monitors/{monitor_id}", json={"display_name": "別の表示名"}).json()["value_unit"] == "kWh"  # 未指定なら変更しない
            assert client.patch(f"/api/monitors/{monitor_id}", json={"value_unit": "℃"}).json()["value_unit"] == "℃"
            assert client.patch(f"/api/monitors/{monitor_id}", json={"value_unit": ""}).json()["value_unit"] == ""  # 空欄=単位なし
            assert client.patch(f"/api/monitors/{monitor_id}", json={"value_unit": "  "}).json()["value_unit"] == ""
            # nullを明示的に送ってもNULLにはならない(現在の値を維持する)
            client.patch(f"/api/monitors/{monitor_id}", json={"value_unit": "L"})
            assert client.patch(f"/api/monitors/{monitor_id}", json={"value_unit": None}).json()["value_unit"] == "L"
        finally:
            client.delete(f"/api/monitors/{monitor_id}")


def test_value_unit_length_limit_is_16_characters():
    with TestClient(app) as client:
        too_long = "あ" * 17
        assert client.post("/api/monitors", json={"name": "unit_len_test", "display_name": "長い単位", "value_unit": too_long}).status_code == 422
        created = client.post("/api/monitors", json={"name": "unit_len_ok", "display_name": "16文字", "value_unit": "a" * 16})
        assert created.status_code == 201, created.text
        monitor_id = created.json()["id"]
        try:
            assert client.patch(f"/api/monitors/{monitor_id}", json={"value_unit": too_long}).status_code == 422
            assert client.get(f"/api/monitors/{monitor_id}").json()["value_unit"] == "a" * 16
        finally:
            client.delete(f"/api/monitors/{monitor_id}")


def test_value_unit_change_does_not_touch_runtime_or_settings(monkeypatch):
    monkeypatch.setattr("runtime.monitor_runtime.VideoReader", _FakeReader)
    with TestClient(app) as client:
        monitor_id = client.post("/api/monitors", json={"name": "unit_runtime_test", "display_name": "Runtime無影響"}).json()["id"]
        try:
            patched = client.patch(
                f"/api/monitors/{monitor_id}",
                json={"source": {"source_type": "camera", "device_id": 0}, "inference": {"method": "object_detection", "engine": "ultralytics", "model_id": None, "video_fps": 5, "inference_fps": 5}},
            )
            assert patched.status_code == 200, patched.text
            runtime = runtime_manager.get_runtime(monitor_id)
            assert runtime is not None
            reader, scheduler = runtime.reader, runtime.inference_scheduler

            def snapshot():
                db = SessionLocal()
                try:
                    m = db.get(Monitor, monitor_id)
                    return (m.source.source_type, m.source.device_id, m.source.url, m.inference.method, m.inference.engine, m.inference.video_fps, m.inference.inference_fps, m.inference.reading, m.enabled)
                finally:
                    db.close()

            before = snapshot()
            response = client.patch(f"/api/monitors/{monitor_id}", json={"value_unit": "m³"})
            assert response.status_code == 200, response.text
            assert response.json()["value_unit"] == "m³"
            assert snapshot() == before, "測定単位の変更でsource/inference/reading設定が変化しない"
            runtime_after = runtime_manager.get_runtime(monitor_id)
            assert runtime_after is runtime, "MonitorRuntimeが置き換わらない"
            assert runtime_after.reader is reader, "VideoReaderが再接続されない"
            assert runtime_after.inference_scheduler is scheduler, "InferenceSchedulerが再構築されない"
        finally:
            client.delete(f"/api/monitors/{monitor_id}")


def test_existing_db_without_value_unit_column_is_migrated(monkeypatch, tmp_path):
    """旧DB(monitors.value_unit列なし)でも、起動時のPRAGMA table_info + ALTER TABLEで列が追加され、
    既存Monitorはvalue_unit=''になり、データは壊れない。"""
    legacy = create_engine(f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}")
    with legacy.begin() as connection:
        connection.execute(text("CREATE TABLE monitors (id INTEGER PRIMARY KEY, name VARCHAR(80) UNIQUE, display_name VARCHAR(160), location VARCHAR(160), enabled BOOLEAN, status VARCHAR(32), created_at DATETIME, updated_at DATETIME)"))
        connection.execute(text("INSERT INTO monitors (id, name, display_name, location, enabled, status) VALUES (1, 'legacy_meter', '旧メーター', '旧設置場所', 1, 'stopped')"))
    monkeypatch.setattr("app.main.engine", legacy)
    with TestClient(app):
        pass
    with legacy.connect() as connection:
        columns = {row[1]: row for row in connection.execute(text("PRAGMA table_info(monitors)")).all()}
        assert "value_unit" in columns
        row = connection.execute(text("SELECT name, display_name, location, value_unit FROM monitors WHERE id = 1")).one()
    assert tuple(row) == ("legacy_meter", "旧メーター", "旧設置場所", "")
