import sqlite3

from fastapi.testclient import TestClient
from app.core.config import settings
from app.main import app


def _sqlite_path() -> str:
    # settings.database_url は "sqlite:///<path>" 形式。
    return settings.database_url.removeprefix("sqlite:///")


def test_monitor_crud():
    with TestClient(app) as client:
        created = client.post("/api/monitors", json={"name":"test_meter","display_name":"テストメーター","location":"試験室"})
        assert created.status_code == 201, created.text
        monitor = created.json()
        monitor_id = monitor["id"]
        assert client.get(f"/api/monitors/{monitor_id}").status_code == 200
        updated = client.patch(f"/api/monitors/{monitor_id}", json={"display_name":"更新メーター"})
        assert updated.status_code == 200
        assert updated.json()["display_name"] == "更新メーター"
        assert client.delete(f"/api/monitors/{monitor_id}").status_code == 204

def test_validation_and_url_error():
    with TestClient(app) as client:
        assert client.post("/api/monitors", json={"name":"bad name","display_name":"x"}).status_code == 422
        response = client.post("/api/sources/check", json={"source_type":"url","url":""})
        assert response.status_code == 200
        assert response.json()["success"] is False


def test_delete_monitor_stops_runtime(monkeypatch):
    # runtime_managerはプロセス全体で共有されるsingletonであり、appのlifespan shutdown
    # (stop_all)が他のテストで起動済みのmonitor idも一緒にstopし得るため、「対象monitor_idが
    # 含まれるか」のみを検証する(呼び出しリストの完全一致は他テストの影響で不安定になる)。
    stopped_ids = []
    monkeypatch.setattr("app.services.monitor_service.runtime_manager.stop_monitor", lambda monitor_id: stopped_ids.append(monitor_id))
    with TestClient(app) as client:
        created = client.post("/api/monitors", json={"name": "test_delete_runtime", "display_name": "削除テスト"})
        monitor_id = created.json()["id"]
        assert client.delete(f"/api/monitors/{monitor_id}").status_code == 204
    assert monitor_id in stopped_ids


def test_delete_monitor_removes_related_rows_but_keeps_url_history():
    from app.core.database import SessionLocal
    from app.models import UrlHistory

    db = SessionLocal()
    try:
        db.execute(UrlHistory.__table__.delete().where(UrlHistory.url == "http://cascade-test.invalid/live"))
        db.add(UrlHistory(url="http://cascade-test.invalid/live", username=None, encrypted_password=None))
        db.commit()
    finally:
        db.close()

    try:
        with TestClient(app) as client:
            created = client.post("/api/monitors", json={"name": "test_delete_cascade", "display_name": "削除カスケード"})
            monitor_id = created.json()["id"]
            assert client.delete(f"/api/monitors/{monitor_id}").status_code == 204

            conn = sqlite3.connect(_sqlite_path())
            try:
                cur = conn.cursor()
                for table in ("video_sources", "inference_settings", "latest_results", "inference_results"):
                    cur.execute(f"SELECT COUNT(*) FROM {table} WHERE monitor_id = ?", (monitor_id,))
                    assert cur.fetchone()[0] == 0, f"{table} に孤児レコードが残っている"
                cur.execute("SELECT COUNT(*) FROM url_histories WHERE url = ?", ("http://cascade-test.invalid/live",))
                assert cur.fetchone()[0] == 1, "url_historiesはMonitor削除で消えてはいけない"
            finally:
                conn.close()
    finally:
        # テスト用に作ったurl履歴を後片付けする。
        db = SessionLocal()
        try:
            db.execute(UrlHistory.__table__.delete().where(UrlHistory.url == "http://cascade-test.invalid/live"))
            db.commit()
        finally:
            db.close()


def test_delete_nonexistent_monitor_returns_404():
    with TestClient(app) as client:
        assert client.delete("/api/monitors/999999").status_code == 404


def test_double_delete_returns_404_without_crashing():
    with TestClient(app) as client:
        created = client.post("/api/monitors", json={"name": "test_double_delete", "display_name": "二重削除テスト"})
        monitor_id = created.json()["id"]
        assert client.delete(f"/api/monitors/{monitor_id}").status_code == 204
        second = client.delete(f"/api/monitors/{monitor_id}")
        assert second.status_code == 404
        # Backend自体は健全なままであること。
        assert client.get("/api/monitors").status_code == 200
