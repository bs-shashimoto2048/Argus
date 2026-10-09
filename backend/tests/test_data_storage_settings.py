"""データ保存設定API・保存先テスト・保存状態APIのテスト(UI再設計 Phase 2)。一時DB・一時フォルダのみ使用する。"""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.routers import data_storage as router_module
from app.services import storage_settings_service as svc
from runtime.hourly_record_worker import hourly_record_worker

pytestmark = pytest.mark.integration


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(hourly_record_worker, "start", lambda: None)
    with TestClient(app) as c:
        yield c
        db = SessionLocal()
        try:  # 一時DBはテスト間で共有されるため、設定を既定へ戻す
            svc.update(db, image_root_folder="", excel_output_folder="", save_original_image=True, save_overlay_image=True,
                       storage_warn_free_gb=10, storage_stop_free_gb=5)
        finally:
            db.close()


def test_defaults(client):
    body = client.get("/api/system/data-storage").json()
    assert body["image_root_folder"] is None and body["effective_image_root"].endswith("images")
    assert (body["save_original_image"], body["save_overlay_image"]) == (True, True)
    assert (body["storage_warn_free_gb"], body["storage_stop_free_gb"]) == (10.0, 5.0)
    assert body["excel_output_folder"] is None


def test_partial_update_changes_only_the_given_fields(client, tmp_path):
    res = client.put("/api/system/data-storage", json={"image_root_folder": str(tmp_path), "save_overlay_image": False})
    assert res.status_code == 200, res.text
    body = client.get("/api/system/data-storage").json()
    assert body["image_root_folder"] == str(tmp_path) and body["effective_image_root"] == str(tmp_path)
    assert (body["save_original_image"], body["save_overlay_image"]) == (True, False)
    assert (body["storage_warn_free_gb"], body["storage_stop_free_gb"]) == (10.0, 5.0)
    cleared = client.put("/api/system/data-storage", json={"image_root_folder": ""}).json()
    assert cleared["image_root_folder"] is None  # 空文字は「未設定」(既定の保存先に戻る)


def test_thresholds_can_be_changed(client):
    body = client.put("/api/system/data-storage", json={"storage_warn_free_gb": 20, "storage_stop_free_gb": 8}).json()
    assert (body["storage_warn_free_gb"], body["storage_stop_free_gb"]) == (20.0, 8.0)


@pytest.mark.parametrize("payload", [
    {"image_root_folder": "relative/path"},
    {"image_root_folder": "C:\\data\\..\\secret"},
    {"excel_output_folder": "images"},
    {"storage_warn_free_gb": 3, "storage_stop_free_gb": 5},  # 停止 > 警告
    {"storage_warn_free_gb": -1},
])
def test_invalid_settings_are_rejected_and_not_saved(client, payload):
    before = client.get("/api/system/data-storage").json()
    assert client.put("/api/system/data-storage", json=payload).status_code == 422
    assert client.get("/api/system/data-storage").json() == before


@pytest.mark.parametrize("path", [r"\\server\share\argus", r"\\beans-f1\データ$\ガスメーター", r"D:\argus\images", "C:/argus/images"])
def test_local_and_unc_paths_are_accepted(client, path):
    assert svc.validate_folder(path) == path  # UNC共有もローカルパスも、設定として受け付ける(存在確認は保存先テストで行う)


def test_unc_setting_is_stored_without_touching_the_share(client):
    path = r"\\unreachable-host\share\argus"
    body = client.put("/api/system/data-storage", json={"image_root_folder": path}).json()
    assert body["image_root_folder"] == path  # 設定の保存では保存先へアクセスしない(不通でも設定できる)


def test_probe_succeeds_for_a_writable_folder(client, tmp_path):
    body = client.post("/api/system/data-storage/test", json={"target": "image", "path": str(tmp_path)}).json()
    assert body["ok"] is True and body["free_gb"] > 0
    assert list(tmp_path.iterdir()) == []  # 書き込みテストのファイルは削除される


def test_probe_reports_failures_without_raising(client, tmp_path):
    for path, expected in ((str(tmp_path / "missing"), "見つかりません"), ("relative", "絶対パス"), ("", "指定されていません")):
        res = client.post("/api/system/data-storage/test", json={"target": "excel", "path": path})
        body = res.json()
        assert res.status_code == 200 and body["ok"] is False and expected in body["message"]
    file_path = tmp_path / "a_file.txt"
    file_path.write_text("x")
    assert "フォルダではありません" in client.post("/api/system/data-storage/test", json={"target": "image", "path": str(file_path)}).json()["message"]
    assert client.post("/api/system/data-storage/test", json={"target": "bad"}).status_code == 422


def test_probe_uses_the_configured_folder_when_no_path_is_given(client, tmp_path):
    client.put("/api/system/data-storage", json={"image_root_folder": str(tmp_path), "excel_output_folder": str(tmp_path / "nope")})
    assert client.post("/api/system/data-storage/test", json={"target": "image"}).json()["ok"] is True
    assert client.post("/api/system/data-storage/test", json={"target": "excel"}).json()["ok"] is False


def test_probe_gives_up_when_the_share_does_not_respond(client, tmp_path, monkeypatch):
    # 不通のUNC共有ではI/Oが長時間ブロックする。APIは固まらず、タイムアウトの失敗として返す。
    monkeypatch.setattr(svc, "PROBE_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setattr(svc, "run_with_timeout", lambda func, timeout=0.2, _orig=svc.run_with_timeout: _orig(func, 0.2))
    monkeypatch.setattr(svc, "free_bytes", lambda _p: time.sleep(2) or 0)
    started = time.monotonic()
    body = client.post("/api/system/data-storage/test", json={"target": "image", "path": str(tmp_path)}).json()
    assert body["ok"] is False and "応答" in body["message"] and time.monotonic() - started < 1.5


def test_status_reports_the_state(client, tmp_path, monkeypatch):
    client.put("/api/system/data-storage", json={"image_root_folder": str(tmp_path)})
    gib = svc.GIB
    cases = [((50 * gib, "ok"), "ok"), ((9 * gib, "warning"), "warning"), ((3 * gib, "stopped"), "stopped")]
    for (free, space), expected in cases:
        monkeypatch.setattr(router_module, "space_state", lambda _root, _config, f=free, s=space: (f, s))
        body = client.get("/api/system/data-storage/status").json()
        assert body["state"] == expected and body["space"] == space and body["free_gb"] == round(free / gib, 2)
        assert body["warn_free_gb"] == 10.0 and body["stop_free_gb"] == 5.0 and "queue_length" in body and "counts" in body
    client.put("/api/system/data-storage", json={"save_original_image": False, "save_overlay_image": False})
    assert client.get("/api/system/data-storage/status").json()["state"] == "disabled"


def test_status_does_not_hang_when_the_share_is_unreachable(client, tmp_path, monkeypatch):
    client.put("/api/system/data-storage", json={"image_root_folder": str(tmp_path)})
    monkeypatch.setattr(router_module, "space_state", lambda _root, _config: time.sleep(3))
    monkeypatch.setattr(router_module.svc, "run_with_timeout", lambda func, timeout=5.0, _orig=svc.run_with_timeout: _orig(func, 0.2))
    started = time.monotonic()
    body = client.get("/api/system/data-storage/status").json()
    assert body["state"] == "failing" and body["space"] == "unreachable" and time.monotonic() - started < 2.0


def test_excel_default_folder_is_probed_and_created_when_unset(client, tmp_path, monkeypatch):
    default = tmp_path / "exports"
    monkeypatch.setattr(svc, "default_excel_root", lambda: default)
    body = client.get("/api/system/data-storage").json()
    assert body["excel_output_folder"] is None and body["effective_excel_output_folder"] == str(default)
    result = client.post("/api/system/data-storage/test", json={"target": "excel"}).json()
    assert result["ok"] is True and default.is_dir()


def test_new_settings_row_defaults_to_overlay_on(client):
    from app.models.system_settings import SystemSettings

    db = SessionLocal()
    try:
        row = SystemSettings()  # 値を指定しない新規環境の行
        assert row.save_overlay_image is None or row.save_overlay_image is True
        assert SystemSettings.__table__.c.save_overlay_image.default.arg is True
    finally:
        db.close()


def test_existing_overlay_off_is_kept_across_restart_and_old_images_are_not_deleted(client, tmp_path):
    old_image = tmp_path / "old_overlay.jpg"
    old_image.write_bytes(b"jpeg")
    client.put("/api/system/data-storage", json={"image_root_folder": str(tmp_path), "save_overlay_image": False})
    with TestClient(app) as restarted:  # 再起動(lifespanのDB初期化)しても既存の保存値を勝手に変えない
        body = restarted.get("/api/system/data-storage").json()
        assert body["save_overlay_image"] is False
        restarted.put("/api/system/data-storage", json={"save_overlay_image": True})
        assert restarted.get("/api/system/data-storage").json()["save_overlay_image"] is True
    assert old_image.read_bytes() == b"jpeg"  # 設定の切り替えで保存済み画像は削除されない
