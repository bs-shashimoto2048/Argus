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
