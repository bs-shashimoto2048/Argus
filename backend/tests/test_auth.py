"""PoC向け認証(未ログイン=VIEWER / ADMINのみパスワードでcookie session)のテスト。一時DB・テスト用のpasswordだけを使う。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core import auth
from app.main import app

pytestmark = [pytest.mark.real_auth, pytest.mark.unit]

PASSWORD = "correct horse battery"
SECRET = "s" * 48


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("ARGUS_ADMIN_PASSWORD_HASH", auth.hash_password(PASSWORD, iterations=2000))
    monkeypatch.setenv("ARGUS_SESSION_SECRET", SECRET)
    monkeypatch.delenv("ARGUS_COOKIE_SECURE", raising=False)
    monkeypatch.setattr(auth, "FAILURE_DELAY_SECONDS", 0)
    auth.sessions.clear()
    auth.login_limiter.succeeded()
    yield
    auth.sessions.clear()
    auth.login_limiter.succeeded()


@pytest.fixture
def client(configured):
    with TestClient(app) as c:
        yield c


def login(client, password=PASSWORD):
    return client.post("/api/auth/login", json={"password": password})


def role(client) -> str:
    return client.get("/api/auth/session").json()["role"]


def test_unauthenticated_is_viewer_and_no_login_screen_is_forced(client):
    res = client.get("/api/auth/session")
    assert res.status_code == 200
    assert res.json() == {"role": "VIEWER", "admin_login_available": True}


def test_correct_password_becomes_admin_and_session_persists(client):
    res = login(client)
    assert res.status_code == 200 and res.json()["role"] == "ADMIN"
    assert role(client) == "ADMIN"
    assert role(client) == "ADMIN"  # 続けて使える


def test_wrong_password_is_401_and_stays_viewer(client):
    res = login(client, "wrong")
    assert res.status_code == 401
    assert res.json()["detail"]["code"] == "INVALID_PASSWORD"
    assert "set-cookie" not in res.headers
    assert role(client) == "VIEWER"


def test_cookie_attributes(client):
    res = login(client)
    header = res.headers["set-cookie"].lower()
    assert header.startswith("argus_session=")
    assert "httponly" in header and "samesite=strict" in header and "path=/" in header
    assert "secure" not in header.replace("samesite", "")  # PoCのHTTPではSecureを付けない
    assert "max-age=28800" in header
    value = res.cookies.get("argus_session")
    assert PASSWORD not in value and SECRET not in value  # 秘密・パスワードはcookieに入らない


def test_cookie_secure_can_be_enabled_for_https(client, monkeypatch):
    monkeypatch.setenv("ARGUS_COOKIE_SECURE", "1")
    parts = [p.strip().lower() for p in login(client).headers["set-cookie"].split(";")]
    assert "secure" in parts


def test_logout_revokes_the_session_even_if_the_cookie_is_kept(client):
    cookie = login(client).cookies.get("argus_session")
    assert role(client) == "ADMIN"
    res = client.post("/api/auth/logout")
    assert res.status_code == 200 and res.json()["role"] == "VIEWER"
    assert role(client) == "VIEWER"
    # 盗まれた/残ったcookieを再送しても、Backend側で失効済み
    other = TestClient(app)
    other.cookies.set("argus_session", cookie)
    assert role(other) == "VIEWER"


def test_tampered_or_foreign_cookie_is_ignored(client):
    cookie = login(client).cookies.get("argus_session")
    sid, signature = cookie.split(".")
    for bad in (f"{sid}.{'A' * len(signature)}", f"{sid}x.{signature}", sid, "", "a.b.c", f"{sid}.{signature}x"):
        other = TestClient(app)
        other.cookies.set("argus_session", bad)
        assert role(other) == "VIEWER", bad


def test_cookie_signed_with_another_secret_is_ignored(client, monkeypatch):
    cookie = login(client).cookies.get("argus_session")
    monkeypatch.setenv("ARGUS_SESSION_SECRET", "z" * 48)
    other = TestClient(app)
    other.cookies.set("argus_session", cookie)
    assert role(other) == "VIEWER"


def test_expired_session_returns_to_viewer(client):
    cookie = login(client).cookies.get("argus_session")
    auth.sessions.expire_now(cookie.split(".")[0])
    assert role(client) == "VIEWER"


def test_relogin_replaces_the_previous_session(client):
    first = login(client).cookies.get("argus_session")
    second = login(client).cookies.get("argus_session")
    assert first != second
    other = TestClient(app)
    other.cookies.set("argus_session", first)
    assert role(other) == "VIEWER"  # 古いsessionは破棄される
    assert role(client) == "ADMIN"


def test_rate_limit_after_repeated_failures(client):
    for _ in range(auth.MAX_FAILURES):
        assert login(client, "bad").status_code == 401
    locked = login(client, PASSWORD)  # 正しいpasswordでもロック中は受け付けない
    assert locked.status_code == 429 and int(locked.headers["retry-after"]) >= 1
    assert role(client) == "VIEWER"
    auth.login_limiter.succeeded()  # ロック解除(時間経過の代わり)
    assert login(client, PASSWORD).status_code == 200


def test_admin_auth_is_disabled_when_not_configured(monkeypatch):
    monkeypatch.delenv("ARGUS_ADMIN_PASSWORD_HASH", raising=False)
    monkeypatch.delenv("ARGUS_SESSION_SECRET", raising=False)
    with TestClient(app) as c:
        assert c.get("/api/auth/session").json() == {"role": "VIEWER", "admin_login_available": False}
        res = c.post("/api/auth/login", json={"password": "anything"})
        assert res.status_code == 503 and res.json()["detail"]["code"] == "ADMIN_AUTH_DISABLED"
        assert c.get("/api/monitors").status_code == 200  # VIEWERとしては利用できる


@pytest.mark.parametrize("hash_value,secret", [("pbkdf2_sha256$bad", SECRET), ("", SECRET), ("x", SECRET)])
def test_invalid_hash_disables_admin(monkeypatch, hash_value, secret):
    monkeypatch.setenv("ARGUS_ADMIN_PASSWORD_HASH", hash_value)
    monkeypatch.setenv("ARGUS_SESSION_SECRET", secret)
    assert auth.admin_login_available() is False


def test_short_session_secret_disables_admin(monkeypatch):
    monkeypatch.setenv("ARGUS_ADMIN_PASSWORD_HASH", auth.hash_password(PASSWORD, iterations=1000))
    monkeypatch.setenv("ARGUS_SESSION_SECRET", "short")
    assert auth.admin_login_available() is False


def test_password_hash_format_and_verification():
    stored = auth.hash_password(PASSWORD)
    scheme, iterations, salt, digest = stored.split("$")
    assert scheme == "pbkdf2_sha256" and int(iterations) >= 600_000
    assert PASSWORD not in stored
    assert auth.verify_password(PASSWORD, stored) and not auth.verify_password(PASSWORD + "x", stored)
    assert auth.hash_password(PASSWORD) != stored  # saltが毎回異なる
    assert not auth.verify_password(PASSWORD, "garbage")


def test_session_secret_is_separate_from_the_secret_store_key():
    import inspect
    assert 'getenv("ARGUS_SECRET_KEY' not in inspect.getsource(auth)  # 認証はカメラ認証情報の暗号鍵(ARGUS_SECRET_KEY)を使わない
    assert "ARGUS_SESSION_SECRET" in inspect.getsource(auth)


def test_responses_never_contain_secrets(client):
    body = login(client).text + client.get("/api/auth/session").text + login(client, "bad").text
    assert SECRET not in body and "pbkdf2" not in body and PASSWORD not in body


def test_password_and_cookie_are_not_logged(client, caplog):
    caplog.set_level("DEBUG")
    res = login(client)
    login(client, "wrong-password-xyz")
    cookie = res.cookies.get("argus_session")
    assert PASSWORD not in caplog.text and "wrong-password-xyz" not in caplog.text and cookie not in caplog.text
