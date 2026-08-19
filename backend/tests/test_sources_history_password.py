"""URL履歴の保存済みパスワードが接続確認(check)でも再利用されることを確認するテスト
(Issue #14: 保存済みURL履歴を選んでパスワード再入力せずに接続確認できること)。
"""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.database import SessionLocal
from app.main import app
from app.models import UrlHistory
from app.services.monitor_service import resolve_check_password
from app.services.secret_store import decrypt
from app.schemas.video_source import VideoSourceInput

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture()
def saved_history():
    db = SessionLocal()
    try:
        db.execute(UrlHistory.__table__.delete().where(UrlHistory.url == "http://history-reuse-test.invalid/live"))
        db.commit()
        from app.services.secret_store import encrypt

        row = UrlHistory(url="http://history-reuse-test.invalid/live", username="saveduser", encrypted_password=encrypt("savedpass"))
        db.add(row)
        db.commit()
        db.refresh(row)
        yield row
    finally:
        db.execute(UrlHistory.__table__.delete().where(UrlHistory.url == "http://history-reuse-test.invalid/live"))
        db.commit()
        db.close()


def test_resolve_check_password_prefers_explicit_password(saved_history):
    db = SessionLocal()
    try:
        source = VideoSourceInput(source_type="url", url=saved_history.url, username="saveduser", password="typed-now", history_id=saved_history.id)
        assert resolve_check_password(db, source) == "typed-now"
    finally:
        db.close()


def test_resolve_check_password_falls_back_to_history_when_password_empty(saved_history):
    db = SessionLocal()
    try:
        source = VideoSourceInput(source_type="url", url=saved_history.url, username="saveduser", password=None, history_id=saved_history.id)
        assert resolve_check_password(db, source) == "savedpass"
    finally:
        db.close()


def test_resolve_check_password_returns_none_without_password_or_history():
    db = SessionLocal()
    try:
        source = VideoSourceInput(source_type="url", url="http://no-creds.invalid/live")
        assert resolve_check_password(db, source) is None
    finally:
        db.close()


def test_resolve_check_password_does_not_reuse_history_when_username_changed(saved_history):
    """usernameを変更した場合、保存済み(別username用)のpasswordを誤って使い回さない。"""
    db = SessionLocal()
    try:
        source = VideoSourceInput(source_type="url", url=saved_history.url, username="different-user", password=None, history_id=saved_history.id)
        assert resolve_check_password(db, source) is None
    finally:
        db.close()


def test_resolve_check_password_falls_back_to_monitor_saved_secret():
    """Monitor Detail画面でpasswordを再入力せず「接続確認」した場合、Monitor自身に
    保存済みのpasswordを復号して使う(history_idを介さないケース)。"""
    with TestClient(app) as client:
        created = client.post("/api/monitors", json={"name": "test_monitor_secret_reuse", "display_name": "secret reuse"})
        monitor_id = created.json()["id"]
        saved = client.patch(
            f"/api/monitors/{monitor_id}",
            json={"source": {"source_type": "url", "url": "http://monitor-secret-test.invalid/live", "username": "monuser", "password": "monpass"}},
        )
        assert saved.status_code == 200

        db = SessionLocal()
        try:
            from app.services.monitor_service import get_monitor

            monitor = get_monitor(db, monitor_id)
            source = VideoSourceInput(source_type="url", url="http://monitor-secret-test.invalid/live", username="monuser", password=None)
            assert resolve_check_password(db, source, monitor) == "monpass"

            # usernameを変更した場合は保存済みpasswordを使い回さない。
            changed_username_source = VideoSourceInput(source_type="url", url="http://monitor-secret-test.invalid/live", username="someone-else", password=None)
            assert resolve_check_password(db, changed_username_source, monitor) is None
        finally:
            db.close()
        client.delete(f"/api/monitors/{monitor_id}")


def test_monitor_source_test_endpoint_uses_monitor_saved_password(monkeypatch):
    """/api/monitors/{id}/source/test がpassword未入力でもMonitor保存済みpasswordを使うこと。"""
    captured = {}

    def fake_check_source_detailed(source, password):
        captured["password"] = password
        from runtime.video_reader import VideoCheckResult

        return VideoCheckResult(True, "url", 640, 480, 15.0, message="接続成功")

    monkeypatch.setattr("app.routers.sources.video_service.check_source_detailed", fake_check_source_detailed)
    with TestClient(app) as client:
        created = client.post("/api/monitors", json={"name": "test_monitor_secret_test_endpoint", "display_name": "secret reuse2"})
        monitor_id = created.json()["id"]
        client.patch(
            f"/api/monitors/{monitor_id}",
            json={"source": {"source_type": "url", "url": "http://monitor-secret-test2.invalid/live", "username": "monuser2", "password": "monpass2"}},
        )
        response = client.post(
            f"/api/monitors/{monitor_id}/source/test",
            json={"source_type": "url", "url": "http://monitor-secret-test2.invalid/live", "username": "monuser2"},
        )
        client.delete(f"/api/monitors/{monitor_id}")

    assert response.status_code == 200
    assert captured["password"] == "monpass2"
    assert "monpass2" not in response.text


def test_check_source_uses_history_password_without_client_resending_it(monkeypatch, saved_history):
    captured = {}

    def fake_check_source(source, password):
        captured["password"] = password
        return True, "接続成功"

    monkeypatch.setattr("app.routers.sources.video_service.check_source", fake_check_source)
    with TestClient(app) as client:
        response = client.post(
            "/api/sources/check",
            json={"source_type": "url", "url": saved_history.url, "username": "saveduser", "history_id": saved_history.id},
        )
    assert response.status_code == 200
    assert response.json()["success"] is True
    assert captured["password"] == "savedpass"


def test_check_source_response_never_includes_plaintext_password(monkeypatch, saved_history):
    monkeypatch.setattr("app.routers.sources.video_service.check_source", lambda source, password: (True, "接続成功"))
    with TestClient(app) as client:
        response = client.post(
            "/api/sources/check",
            json={"source_type": "url", "url": saved_history.url, "username": "saveduser", "history_id": saved_history.id},
        )
    assert "savedpass" not in response.text


# --- Monitor保存時のpassword永続化(Issue #14追加要件) ---

def test_saving_password_marks_has_password_true_and_never_returns_plaintext():
    with TestClient(app) as client:
        created = client.post("/api/monitors", json={"name": "test_password_persist", "display_name": "password persist"})
        monitor_id = created.json()["id"]

        saved = client.patch(
            f"/api/monitors/{monitor_id}",
            json={"source": {"source_type": "url", "url": "http://persist-test.invalid/live", "username": "u1", "password": "secret1"}},
        )
        assert saved.status_code == 200
        assert saved.json()["source"]["has_password"] is True
        assert "secret1" not in saved.text

        # 再表示(GET)でもhas_password=trueを維持し、平文は含まれない。
        fetched = client.get(f"/api/monitors/{monitor_id}")
        assert fetched.json()["source"]["has_password"] is True
        assert "secret1" not in fetched.text

        client.delete(f"/api/monitors/{monitor_id}")


def test_saving_without_password_key_preserves_previously_saved_password():
    """passwordフィールド自体を送らない更新(例: 他の項目だけ変更)では、
    保存済みpasswordが消えないこと(空欄=削除にしない)。"""
    with TestClient(app) as client:
        created = client.post("/api/monitors", json={"name": "test_password_preserve", "display_name": "password preserve"})
        monitor_id = created.json()["id"]
        client.patch(
            f"/api/monitors/{monitor_id}",
            json={"source": {"source_type": "url", "url": "http://preserve-test.invalid/live", "username": "u1", "password": "secret2"}},
        )

        # username・password両方とも変更しない別の更新(例: display_nameのみ変更)。
        updated = client.patch(f"/api/monitors/{monitor_id}", json={"display_name": "renamed"})
        assert updated.status_code == 200

        fetched = client.get(f"/api/monitors/{monitor_id}")
        assert fetched.json()["source"]["has_password"] is True

        db = SessionLocal()
        try:
            from app.services.monitor_service import get_monitor

            monitor = get_monitor(db, monitor_id)
            assert decrypt(monitor.source.encrypted_password) == "secret2"
        finally:
            db.close()
        client.delete(f"/api/monitors/{monitor_id}")


def test_changing_username_without_new_password_clears_old_password():
    """usernameだけを別の値へ変更し、新しいpassword/history_idを指定しない場合、
    古いusernameに対応していたpasswordを新usernameへ誤って流用しない(クリアする)。"""
    with TestClient(app) as client:
        created = client.post("/api/monitors", json={"name": "test_username_change_clears", "display_name": "username change"})
        monitor_id = created.json()["id"]
        client.patch(
            f"/api/monitors/{monitor_id}",
            json={"source": {"source_type": "url", "url": "http://username-change-test.invalid/live", "username": "olduser", "password": "oldpass"}},
        )

        changed = client.patch(
            f"/api/monitors/{monitor_id}",
            json={"source": {"source_type": "url", "url": "http://username-change-test.invalid/live", "username": "newuser"}},
        )
        assert changed.status_code == 200
        assert changed.json()["source"]["has_password"] is False

        db = SessionLocal()
        try:
            from app.services.monitor_service import get_monitor

            monitor = get_monitor(db, monitor_id)
            assert monitor.source.encrypted_password is None
        finally:
            db.close()
        client.delete(f"/api/monitors/{monitor_id}")


def test_resaving_with_same_username_preserves_password():
    """usernameを同じ値で送り直した場合は変更とみなさず、passwordを維持する。"""
    with TestClient(app) as client:
        created = client.post("/api/monitors", json={"name": "test_same_username_preserve", "display_name": "same username"})
        monitor_id = created.json()["id"]
        client.patch(
            f"/api/monitors/{monitor_id}",
            json={"source": {"source_type": "url", "url": "http://same-username-test.invalid/live", "username": "sameuser", "password": "samepass"}},
        )

        resaved = client.patch(
            f"/api/monitors/{monitor_id}",
            json={"source": {"source_type": "url", "url": "http://same-username-test.invalid/live", "username": "sameuser"}},
        )
        assert resaved.status_code == 200
        assert resaved.json()["source"]["has_password"] is True
        client.delete(f"/api/monitors/{monitor_id}")
