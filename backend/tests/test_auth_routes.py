"""VIEWER / ADMINのAPI境界のテスト。全routeを列挙し、書き込みAPI・内部情報のAPIの保護漏れを検出する。"""
from __future__ import annotations

import re
import uuid
from datetime import datetime

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.core import auth
from app.core.database import SessionLocal
from app.main import app
from app.models import InferenceSettings, Monitor, ReadingRecord, VideoSource
from app.services.secret_store import encrypt

pytestmark = [pytest.mark.real_auth, pytest.mark.integration]

PASSWORD = "route-test-password"

# 認証なしで呼べる書き込みroute(ログイン/ログアウト自体と、条件付きで許可するExcel出力)。
PUBLIC_WRITES = {("POST", "/api/auth/login"), ("POST", "/api/auth/logout"), ("POST", "/api/records/export/excel")}
# VIEWERにも見せてよいGET(閲覧に必要なもの)。ここに無いGETは、ADMIN専用でなければならない(新しいGETは意識的にどちらかへ分類する)。
VIEWER_GETS = {
    "/api/health", "/api/auth/session",
    "/api/monitors", "/api/monitors/{monitor_id}", "/api/monitors/{monitor_id}/roi",
    "/api/monitors/{monitor_id}/reading/baseline", "/api/monitors/{monitor_id}/reading/baseline/events",
    "/api/monitors/{monitor_id}/snapshot", "/api/monitors/{monitor_id}/preview.jpg", "/api/monitors/{monitor_id}/overlay.jpg",
    "/api/monitors/{monitor_id}/runtime", "/api/monitors/{monitor_id}/stream", "/api/monitors/{monitor_id}/stream.mjpg",
    "/api/records", "/api/records/{record_id}", "/api/records/{record_id}/corrections", "/api/records/{record_id}/image/{kind}",
}


def _calls(dependant):
    for dep in dependant.dependencies:
        yield dep.call
        yield from _calls(dep)


def is_admin_only(route) -> bool:
    return auth.require_admin in set(_calls(route.dependant))


def api_routes() -> list:
    """全APIルート(path/methods/dependantを持つもの)。FastAPIの新しい版ではinclude_routerされたrouterが遅延展開されるため、展開済みの形も扱う。"""
    routes: list = []
    for r in app.routes:
        if hasattr(r, "effective_route_contexts"):
            routes.extend(r.effective_route_contexts())
        elif isinstance(r, APIRoute):
            routes.append(r)
    assert len(routes) > 40, "routeを列挙できていない(FastAPIの内部構造が変わった可能性)"
    return routes


def test_every_write_route_is_admin_only():
    unprotected = [(m, r.path) for r in api_routes() for m in r.methods if m not in {"GET", "HEAD", "OPTIONS"} and not is_admin_only(r) and (m, r.path) not in PUBLIC_WRITES]
    assert unprotected == [], f"ADMIN保護のない書き込みroute: {unprotected}"


def test_every_get_route_is_either_viewer_allowed_or_admin_only():
    gets = {r.path: r for r in api_routes() if "GET" in r.methods}
    unclassified = [p for p, r in gets.items() if not is_admin_only(r) and p not in VIEWER_GETS]
    assert unclassified == [], f"VIEWERに公開してよいか未分類の(保護されていない)GET: {unclassified}"
    stale = [p for p in VIEWER_GETS if p not in gets]
    assert stale == [], f"存在しないroute: {stale}"
    leaked = [p for p in VIEWER_GETS if is_admin_only(gets[p]) and p not in {"/api/records/{record_id}"}]
    assert leaked == [], f"VIEWER許可リストにADMIN専用routeがある: {leaked}"


def test_public_writes_are_exactly_the_documented_ones():
    public = {(m, r.path) for r in api_routes() for m in r.methods if m not in {"GET", "HEAD", "OPTIONS"} and not is_admin_only(r)}
    assert public == PUBLIC_WRITES


def test_admin_only_gets_are_the_internal_information_routes():
    admin_gets = {r.path for r in api_routes() if "GET" in r.methods and is_admin_only(r)}
    for required in ("/api/url-history", "/api/system/data-storage", "/api/system/csv-export", "/api/cameras",
                     "/api/monitors/{monitor_id}/reading/diagnostics", "/api/monitors/{monitor_id}/inference-input.jpg"):
        assert required in admin_gets, required


@pytest.fixture
def clients(monkeypatch):
    monkeypatch.setenv("ARGUS_ADMIN_PASSWORD_HASH", auth.hash_password(PASSWORD, iterations=2000))
    monkeypatch.setenv("ARGUS_SESSION_SECRET", "r" * 48)
    monkeypatch.setattr(auth, "FAILURE_DELAY_SECONDS", 0)
    auth.sessions.clear()
    auth.login_limiter.succeeded()
    with TestClient(app) as viewer, TestClient(app) as admin:
        assert admin.post("/api/auth/login", json={"password": PASSWORD}).status_code == 200
        yield viewer, admin
    auth.sessions.clear()


def _fill(path: str) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: "original" if m.group(1) == "kind" else "999999", path)


def test_viewer_gets_403_on_every_write_route_and_admin_is_not_blocked(clients):
    viewer, admin = clients
    checked = 0
    for route in api_routes():
        for method in route.methods:
            if method in {"GET", "HEAD", "OPTIONS"} or (method, route.path) in PUBLIC_WRITES:
                continue
            url = _fill(route.path)
            res = viewer.request(method, url, json={})
            assert res.status_code == 403, (method, route.path, res.status_code)
            assert res.json()["detail"]["code"] == "ADMIN_REQUIRED"
            checked += 1
    assert checked >= 18
    # ADMINは403にならない(中身の検証で422/404等になるのは別問題)
    res = admin.request("POST", "/api/sources/check", json={})
    assert res.status_code != 403
    assert admin.get("/api/system/csv-export").status_code == 200


def test_viewer_gets_403_on_internal_information_gets(clients):
    viewer, admin = clients
    for path in ("/api/url-history", "/api/system/data-storage", "/api/system/data-storage/status", "/api/system/csv-export", "/api/cameras",
                 "/api/monitors/1/reading/diagnostics", "/api/monitors/1/inference-input.jpg", "/api/records/status", "/api/system/inference", "/api/system/models", "/api/system/process"):
        assert viewer.get(path).status_code == 403, path
        assert admin.get(path).status_code != 403, path


def test_viewer_can_read_what_the_dashboard_needs(clients):
    viewer, _ = clients
    assert viewer.get("/api/health").status_code == 200
    assert viewer.get("/api/monitors").status_code == 200
    assert viewer.get("/api/records", params={"limit": 5}).status_code == 200
    for path in ("/api/monitors/999999/preview.jpg", "/api/monitors/999999/overlay.jpg", "/api/monitors/999999/stream.mjpg", "/api/monitors/999999/snapshot",
                 "/api/monitors/999999/runtime", "/api/monitors/999999/roi", "/api/records/999999", "/api/records/999999/image/original", "/api/records/999999/corrections"):
        assert viewer.get(path).status_code != 403, path  # 存在しないIDなので404でよい(403=権限で拒否ではない)


@pytest.fixture
def monitor_with_source():
    db = SessionLocal()
    monitor = Monitor(name="t_auth_" + uuid.uuid4().hex[:8], display_name="認証テスト", location="x", created_at=datetime(2026, 10, 1))
    db.add(monitor)
    db.flush()
    db.add(InferenceSettings(monitor_id=monitor.id))
    db.add(VideoSource(monitor_id=monitor.id, source_type="url", url="rtsp://10.9.8.7/secret-stream", username="camuser", encrypted_password=encrypt("camsecret")))
    db.commit()
    mid = monitor.id
    db.close()
    yield mid
    db = SessionLocal()
    m = db.get(Monitor, mid)
    if m is not None:
        db.delete(m)
        db.commit()
    db.close()


def test_viewer_monitor_responses_hide_connection_details_but_admin_is_unchanged(clients, monitor_with_source):
    viewer, admin = clients
    mid = monitor_with_source
    for client in (viewer,):
        body_list = client.get("/api/monitors").text
        body_one = client.get(f"/api/monitors/{mid}").text
        for text in (body_list, body_one):
            assert "10.9.8.7" not in text and "secret-stream" not in text and "camuser" not in text and "camsecret" not in text
    one = viewer.get(f"/api/monitors/{mid}").json()
    assert one["source"] == {"source_type": "url", "device_id": None, "url": None, "username": None, "has_password": False}
    # Dashboard表示に必要な項目は残る
    for key in ("id", "name", "display_name", "status", "current_value", "confidence", "last_updated", "inference_status", "value_unit", "display_order", "reading_baseline"):
        assert key in one
    # ADMINの応答は従来どおり(URL・username・has_passwordあり。passwordは返さない)
    source = admin.get(f"/api/monitors/{mid}").json()["source"]
    assert source["url"] == "rtsp://10.9.8.7/secret-stream" and source["username"] == "camuser" and source["has_password"] is True
    assert "camsecret" not in admin.get(f"/api/monitors/{mid}").text
    listed = [m for m in admin.get("/api/monitors").json()["monitors"] if m["id"] == mid][0]
    assert listed["source"]["url"] == "rtsp://10.9.8.7/secret-stream"


@pytest.fixture
def record():
    db = SessionLocal()
    monitor = Monitor(name="t_auth_r_" + uuid.uuid4().hex[:8], display_name="認証記録", location="x", created_at=datetime(2026, 10, 1))
    db.add(monitor)
    db.flush()
    rec = ReadingRecord(monitor_id=monitor.id, monitor_name="認証記録", hour_bucket="2026-10-08T10:00:00+09:00", recorded_at=datetime(2026, 10, 8, 1, 0), value="100", numeric_value="100",
                        value_source="confirmed", display_status="normal", baseline_conflict=False, image_status="not_saved")
    db.add(rec)
    db.commit()
    ids = (monitor.id, rec.id)
    db.close()
    yield ids
    db = SessionLocal()
    db.query(ReadingRecord).filter(ReadingRecord.monitor_id == ids[0]).delete()
    m = db.get(Monitor, ids[0])
    if m is not None:
        db.delete(m)
    db.commit()
    db.close()


def test_export_download_is_allowed_for_viewer_but_server_save_is_admin_only(clients, record):
    viewer, admin = clients
    mid, _ = record
    body = {"monitor_ids": [mid], "from": "2026-10-08T00:00:00+09:00", "to": "2026-10-09T00:00:00+09:00"}
    res = viewer.post("/api/records/export/excel", json={**body, "save_to_server": False})
    assert res.status_code == 200 and res.content[:2] == b"PK"  # ブラウザへのダウンロードはVIEWERも可
    res = viewer.post("/api/records/export/excel", json={**body, "save_to_server": True})
    assert res.status_code == 403 and res.json()["detail"]["code"] == "ADMIN_REQUIRED"
    res = viewer.post("/api/records/export/excel", json=body)  # save_to_server省略=false
    assert res.status_code == 200
    # ADMINはtrueでも403にならない(保存先設定により成功/失敗は変わる)
    assert admin.post("/api/records/export/excel", json={**body, "save_to_server": True}).status_code != 403


def test_viewer_cannot_change_memo_or_correct_but_can_read_records(clients, record):
    viewer, admin = clients
    mid, rid = record
    assert viewer.patch(f"/api/records/{rid}/memo", json={"memo": "x"}).status_code == 403
    assert viewer.post(f"/api/records/{rid}/correct", json={"value": "1", "reason": "r", "operator": "o"}).status_code == 403
    assert viewer.get(f"/api/records/{rid}").json()["memo"] is None  # 変更されていない
    assert admin.patch(f"/api/records/{rid}/memo", json={"memo": "管理者メモ"}).json()["memo"] == "管理者メモ"
    assert viewer.get(f"/api/records/{rid}").json()["memo"] == "管理者メモ"  # 閲覧はできる
    assert viewer.get("/api/records", params={"monitor_id": mid}).json()["items"][0]["memo"] == "管理者メモ"


def test_session_loss_returns_the_client_to_viewer_for_writes(clients, record):
    _, admin = clients
    _, rid = record
    assert admin.patch(f"/api/records/{rid}/memo", json={"memo": "a"}).status_code == 200
    assert admin.post("/api/auth/logout").status_code == 200
    assert admin.patch(f"/api/records/{rid}/memo", json={"memo": "b"}).status_code == 403
