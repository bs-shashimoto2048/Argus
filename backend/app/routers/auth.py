import time

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from ..core import auth

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginInput(BaseModel):
    password: str = Field(max_length=256)


def _session_body(role: str) -> dict:
    # admin_login_available: ADMIN認証が設定されているか(未設定なら、Frontendは「管理者ログイン」を出さない)。秘密は返さない。
    return {"role": role, "admin_login_available": auth.admin_login_available()}


@router.get("/session")
def get_session(request: Request):
    return _session_body(auth.role_from_request(request))


@router.post("/login")
def login(body: LoginInput, request: Request, response: Response):
    if not auth.admin_login_available():
        raise HTTPException(503, {"code": "ADMIN_AUTH_DISABLED", "message": "管理者ログインは設定されていません"})
    wait = auth.login_limiter.retry_after()
    if wait:
        raise HTTPException(429, {"code": "TOO_MANY_ATTEMPTS", "message": "ログインの失敗が続いたため、しばらく待ってからやり直してください"}, headers={"Retry-After": str(wait)})
    if not auth.verify_password(body.password, auth.admin_hash() or ""):
        auth.login_limiter.failed()
        time.sleep(auth.FAILURE_DELAY_SECONDS)  # 総当たりを遅くする(同期endpointのためworker threadだけが待つ)
        raise HTTPException(401, {"code": "INVALID_PASSWORD", "message": "パスワードが違います"})
    auth.login_limiter.succeeded()
    # 既存のsessionがあれば破棄してから新しいsessionを発行する(session固定化対策)。
    previous = auth.session_id_from_cookie(request.cookies.get(auth.COOKIE_NAME))
    if previous:
        auth.sessions.revoke(previous)
    sid, _expires = auth.sessions.create()
    response.set_cookie(auth.COOKIE_NAME, auth.make_cookie_value(sid) or "", max_age=auth.SESSION_TTL_SECONDS, path="/", httponly=True, samesite="strict", secure=auth.cookie_secure())
    return _session_body(auth.ADMIN)


@router.post("/logout")
def logout(request: Request, response: Response):
    sid = auth.session_id_from_cookie(request.cookies.get(auth.COOKIE_NAME))
    if sid:
        auth.sessions.revoke(sid)  # Backend側で失効(cookieを持ち続けても無効)
    response.delete_cookie(auth.COOKIE_NAME, path="/", httponly=True, samesite="strict", secure=auth.cookie_secure())
    return _session_body(auth.VIEWER)
