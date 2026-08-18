from fastapi.testclient import TestClient
from app.main import app

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
