"""PoC向けの最小認証・権限制御(Issue #34 Phase 2: 社内LANの第三者へ閲覧専用で公開する)。

- 未ログイン = VIEWER(閲覧のみ)。ADMINだけがパスワードでログインし、Backendが発行するHttpOnly cookieのsessionで権限を持つ。
- 接続元IPでは判定しない(LAN利用者はVite proxy経由のため、Backendからは全員が127.0.0.1に見える)。FrontendのlocalStorage等も境界にしない。
- 書き込み系APIは `Depends(require_admin)` で共通に保護する(個別のif文を散らさない)。保護漏れは tests/test_auth_routes.py が全routeを列挙して検出する。
- 秘密は ARGUS_SECRET_KEY(カメラのパスワード暗号化用)とは分離する:
    ARGUS_ADMIN_PASSWORD_HASH ... ADMINのパスワードhash(`pbkdf2_sha256$<反復回数>$<salt>$<hash>`。平文は保存しない)
    ARGUS_SESSION_SECRET      ... cookieの署名専用(32文字以上)
  どちらかが未設定・不正なら、ADMIN認証は無効(全員VIEWER)になる。開発用の固定パスワードは用意しない。
- sessionはBackendのメモリ上で管理する(logoutで確実に失効。Backendを再起動するとADMINは再ログインが必要)。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import threading
import time

from fastapi import Depends, HTTPException, Request

ADMIN = "ADMIN"
VIEWER = "VIEWER"

COOKIE_NAME = "argus_session"
SESSION_TTL_SECONDS = 8 * 60 * 60  # ADMIN sessionの有効期間(絶対期限)
PBKDF2_ITERATIONS = 600_000
MIN_SESSION_SECRET_LENGTH = 32
# 簡易rate limit: 失敗が続いたら一定時間ログインを受け付けない(接続元IPは全員127.0.0.1に見えるため、全体で数える)。
MAX_FAILURES = 5
FAILURE_WINDOW_SECONDS = 60
LOCKOUT_SECONDS = 60
FAILURE_DELAY_SECONDS = 0.5


# --- password hash ---

def hash_password(password: str, iterations: int = PBKDF2_ITERATIONS) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "$".join(["pbkdf2_sha256", str(iterations), base64.b64encode(salt).decode(), base64.b64encode(digest).decode()])


def _parse_hash(stored: str) -> tuple[int, bytes, bytes] | None:
    try:
        scheme, iterations, salt, digest = stored.split("$")
        if scheme != "pbkdf2_sha256":
            return None
        count = int(iterations)
        if count < 1:
            return None
        return count, base64.b64decode(salt, validate=True), base64.b64decode(digest, validate=True)
    except Exception:
        return None


def verify_password(password: str, stored: str) -> bool:
    parsed = _parse_hash(stored)
    if parsed is None:
        return False
    iterations, salt, expected = parsed
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)  # 定数時間比較


# --- 設定(環境変数。毎回読む=テストや運用での差し替えを反映) ---

def admin_hash() -> str | None:
    value = os.getenv("ARGUS_ADMIN_PASSWORD_HASH", "").strip()
    return value if value and _parse_hash(value) else None


def _session_secret() -> bytes | None:
    value = os.getenv("ARGUS_SESSION_SECRET", "")
    return value.encode("utf-8") if len(value) >= MIN_SESSION_SECRET_LENGTH else None


def admin_login_available() -> bool:
    """ADMIN認証が有効(passwordのhashとsession secretの両方が正しく設定されている)か。"""
    return admin_hash() is not None and _session_secret() is not None


def cookie_secure() -> bool:
    """HTTPS化したときは ARGUS_COOKIE_SECURE=1 でSecure属性を付ける(PoCのHTTPでは付けない)。"""
    return os.getenv("ARGUS_COOKIE_SECURE", "").strip().lower() in {"1", "true", "yes"}


# --- session ---

class SessionStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, float] = {}  # session id -> 期限(epoch秒)

    def create(self) -> tuple[str, float]:
        sid = secrets.token_urlsafe(32)
        expires = time.time() + SESSION_TTL_SECONDS
        with self._lock:
            self._purge()
            self._sessions[sid] = expires
        return sid, expires

    def valid(self, sid: str) -> bool:
        with self._lock:
            expires = self._sessions.get(sid)
            if expires is None:
                return False
            if expires <= time.time():
                del self._sessions[sid]
                return False
            return True

    def expire_now(self, sid: str) -> None:
        """(テスト用)期限を過去にする。"""
        with self._lock:
            if sid in self._sessions:
                self._sessions[sid] = time.time() - 1

    def revoke(self, sid: str) -> None:
        with self._lock:
            self._sessions.pop(sid, None)

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()

    def _purge(self) -> None:
        now = time.time()
        for sid in [s for s, e in self._sessions.items() if e <= now]:
            del self._sessions[sid]


sessions = SessionStore()


def _sign(secret: bytes, sid: str) -> str:
    return base64.urlsafe_b64encode(hmac.new(secret, sid.encode(), hashlib.sha256).digest()).decode().rstrip("=")


def make_cookie_value(sid: str) -> str | None:
    secret = _session_secret()
    return None if secret is None else f"{sid}.{_sign(secret, sid)}"


def session_id_from_cookie(value: str | None) -> str | None:
    secret = _session_secret()
    if not value or secret is None or value.count(".") != 1:
        return None
    sid, signature = value.split(".")
    if not hmac.compare_digest(signature, _sign(secret, sid)):
        return None  # 改ざん・別secretで署名されたcookieは無効
    return sid if sessions.valid(sid) else None


def role_from_request(request: Request) -> str:
    return ADMIN if session_id_from_cookie(request.cookies.get(COOKIE_NAME)) else VIEWER


def current_role(request: Request) -> str:
    """現在のrole。cookieのsession(署名とBackend上の有効性)だけで決める。"""
    return role_from_request(request)


def require_admin(role: str = Depends(current_role)) -> str:
    """ADMIN専用APIの共通guard。VIEWER(未ログイン・session切れ)は403。"""
    if role != ADMIN:
        raise HTTPException(403, {"code": "ADMIN_REQUIRED", "message": "この操作には管理者ログインが必要です"})
    return role


# --- login rate limit ---

class LoginLimiter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._failures: list[float] = []
        self._locked_until = 0.0

    def retry_after(self) -> int:
        with self._lock:
            remaining = self._locked_until - time.time()
            return int(remaining) + 1 if remaining > 0 else 0

    def failed(self) -> None:
        now = time.time()
        with self._lock:
            self._failures = [t for t in self._failures if now - t < FAILURE_WINDOW_SECONDS] + [now]
            if len(self._failures) >= MAX_FAILURES:
                self._locked_until = now + LOCKOUT_SECONDS
                self._failures = []

    def succeeded(self) -> None:
        with self._lock:
            self._failures = []
            self._locked_until = 0.0


login_limiter = LoginLimiter()

# 書き込み・内部情報のAPIへ付ける共通dependency(route decoratorの dependencies= かAPIRouter(dependencies=) に渡す)。
ADMIN_ONLY = [Depends(require_admin)]
