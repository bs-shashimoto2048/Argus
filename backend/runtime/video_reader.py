from __future__ import annotations

import base64
import socket
import time
from dataclasses import dataclass, replace
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, quote, unquote, urlsplit, urlunsplit
from urllib.request import (
    HTTPDigestAuthHandler,
    HTTPPasswordMgrWithDefaultRealm,
    Request,
    build_opener,
    urlopen,
)

import cv2
import numpy as np

# 事前probe(probe_http_status)の対象とする既知scheme。それ以外はSTREAM_URL_INVALID_OR_UNSUPPORTED。
_KNOWN_SCHEMES = {"http", "https", "rtsp", "rtsps", "rtmp"}
_PROBE_SCHEMES = {"http", "https"}

# viewer URLのquery paramに実stream pathが埋め込まれている形式(例: ?imagepath=%2Fmjpg%2Fvideo.mjpg%3Fcamera%3D1)
# を検出するための、明示的に「stream path」を意味すると分かるquery key。
_STREAM_PATH_QUERY_KEYS = {"imagepath", "streampath", "stream_path", "streamurl", "stream_url"}

_DIGEST_FALLBACK_PROBE_TIMEOUT = 5.0
_CV2_USABILITY_PROBE_TIMEOUT = 2.0


@dataclass
class ReaderConfig:
    source_type: str
    device_id: int | None = None
    url: str | None = None
    username: str | None = None
    password: str | None = None
    video_fps: float = 15.0
    inference_settings: dict | None = None


@dataclass
class VideoCheckResult:
    connected: bool
    source_type: str
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    error_code: str | None = None
    message: str = ""
    resolved_url_sanitized: str | None = None


def is_local_camera(source_type: str) -> bool:
    return source_type in {"camera", "local_camera"}


def sanitize_url(url: str | None) -> str:
    """認証情報をログやエラーへ出さないための表示用URLを返す。"""
    if not url:
        return ""
    try:
        parts = urlsplit(url)
        if parts.username is None:
            return url
        host = parts.hostname or "***"
        if parts.port:
            host += f":{parts.port}"
        return urlunsplit((parts.scheme, "***@" + host, parts.path, parts.query, parts.fragment))
    except Exception:
        return "***"


def resolve_stream_url(url: str) -> str:
    """viewerページURLのquery parameterに実stream pathが埋め込まれている形式を検出し、
    同一host上の実stream URLへ解決する。

    例: `http://host/view/view.shtml?id=148&imagepath=%2Fmjpg%2Fvideo.mjpg%3Fcamera%3D1`
        -> `http://host/mjpg/video.mjpg?camera=1`

    特定機種専用にベタ書きせず、`imagepath`等の「明示的にstream pathを示すquery key」のみを
    汎用的に扱う。該当queryが無い場合や値が安全に解釈できない場合は、元のURLをそのまま返す
    (viewer URL直入力・stream URL直入力のどちらでも動作する)。host付き・scheme付きの値
    (オープンリダイレクト的な懸念がある値)は安全側で無視する。
    """
    if not url:
        return url
    try:
        parts = urlsplit(url)
    except Exception:
        return url
    if not parts.query:
        return url

    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key.lower() not in _STREAM_PATH_QUERY_KEYS:
            continue
        try:
            decoded = unquote(value)
        except Exception:
            continue
        if not decoded.startswith("/"):
            continue  # 絶対pathでなければ安全側で無視(malformedなpathを拒否)
        try:
            sub = urlsplit(decoded)
        except Exception:
            continue
        if sub.scheme or sub.netloc:
            continue  # host/scheme付きの値は想定外、安全側で無視
        return urlunsplit((parts.scheme, parts.netloc, sub.path, sub.query, ""))
    return url


def _temporary_auth_url(url: str, username: str | None, password: str | None) -> str:
    if not username or not password:
        return url
    parts = urlsplit(url)
    if parts.username:
        return url
    host = f"{quote(username, safe='')}:{quote(password, safe='')}@{parts.hostname or ''}"
    if parts.port:
        host += f":{parts.port}"
    return urlunsplit((parts.scheme, host, parts.path, parts.query, parts.fragment))


@dataclass
class AuthProbeResult:
    """probe_http_statusの結果。error_codeがNoneなら接続・認証(あれば)に成功している。"""

    error_code: str | None
    auth_scheme: str | None = None  # "basic" | "digest" | None(認証不要 or 判定不可)


def _basic_auth_header(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def _classify_http_exception(exc: Exception) -> str:
    if isinstance(exc, HTTPError):
        if exc.code in (401, 403):
            return "AUTH_FAILED"
        if exc.code == 404:
            return "SOURCE_NOT_FOUND"
        return "CONNECTION_FAILED"
    if isinstance(exc, URLError):
        if isinstance(exc.reason, (socket.timeout, TimeoutError)):
            return "CONNECTION_TIMEOUT"
        return "CONNECTION_FAILED"
    if isinstance(exc, socket.timeout):
        return "CONNECTION_TIMEOUT"
    return "CONNECTION_FAILED"


def _detect_challenge_scheme(headers: object | None) -> str:
    """401応答のWWW-Authenticateヘッダから認証方式を判定する。
    情報が無い/判定できない場合はBasicを既定とする(従来動作との後方互換)。
    複数の`WWW-Authenticate`が返る場合(Basic/Digest両方提示等)も考慮する。
    """
    values: list[str] = []
    if headers is not None:
        get_all = getattr(headers, "get_all", None)
        if callable(get_all):
            values = get_all("WWW-Authenticate") or []
        else:
            get = getattr(headers, "get", None)
            single = get("WWW-Authenticate") if callable(get) else None
            if single:
                values = [single]
    combined = " ".join(values).lower()
    if "digest" in combined:
        return "digest"
    return "basic"


def _attempt_unauthenticated(url: str, timeout: float) -> tuple[str | None, object | None]:
    """認証情報を付けずに1回リクエストし、(結果コード|None, WWW-Authenticateヘッダ群)を返す。
    HEADが405/501で拒否された場合はGETへフォールバックする。
    """

    def _try(method: str) -> tuple[str | None, object | None, bool]:
        request = Request(url, method=method)
        response = None
        try:
            response = urlopen(request, timeout=timeout)
            return None, None, False
        except HTTPError as exc:
            code = _classify_http_exception(exc)
            if exc.code in (405, 501) and method == "HEAD":
                return code, exc.headers, True  # retry_get
            return code, exc.headers, False
        except Exception as exc:
            return _classify_http_exception(exc), None, False
        finally:
            if response is not None:
                response.close()

    result, headers, retry_get = _try("HEAD")
    if retry_get:
        result, headers, _ = _try("GET")
    return result, headers


def _attempt_authenticated(url: str, headers: dict[str, str], timeout: float) -> str | None:
    request = Request(url, headers=headers, method="GET")
    response = None
    try:
        response = urlopen(request, timeout=timeout)
        return None
    except Exception as exc:
        return _classify_http_exception(exc)
    finally:
        if response is not None:
            response.close()


def _attempt_digest_authenticated(url: str, username: str, password: str, timeout: float) -> str | None:
    password_mgr = HTTPPasswordMgrWithDefaultRealm()
    password_mgr.add_password(None, url, username, password)
    opener = build_opener(HTTPDigestAuthHandler(password_mgr))
    response = None
    try:
        response = opener.open(Request(url, method="GET"), timeout=timeout)
        return None
    except Exception as exc:
        return _classify_http_exception(exc)
    finally:
        if response is not None:
            response.close()


def probe_http_status(
    url: str, username: str | None, password: str | None, timeout: float = 5.0
) -> AuthProbeResult:
    """HTTP/HTTPSソースに限り、OpenCV/FFmpegでは取得できないHTTP status相当を事前確認する。

    まず無認証でアクセスし、401が返れば`WWW-Authenticate`からBasic/Digestを判定した上で
    実際にその方式で認証を試みる(ブラウザの自動ネゴシエーションに相当する動作)。
    Basic固定で判定すると、Digest認証カメラを正しい資格情報でもAUTH_FAILEDと誤判定するため、
    このスキーム判定は必須。

    認証はURLへ埋め込まず`Authorization`ヘッダ/HTTPDigestAuthHandlerで渡す
    (URL自体に平文credentialを含めない)。bodyは読み切らない。

    戻り値: AuthProbeResult。error_codeがNoneなら接続・認証に成功(2xx)、または
    probe対象外(http/https以外)。auth_schemeは検出できた場合のみ"basic"/"digest"。
    例外メッセージやURLをそのまま外部へ渡さない(credential/IPの露出防止)。
    """
    scheme = urlsplit(url).scheme.lower()
    if scheme not in _PROBE_SCHEMES:
        return AuthProbeResult(None, None)

    result, headers = _attempt_unauthenticated(url, timeout)
    if result is None:
        return AuthProbeResult(None, None)  # 認証不要で2xx
    if result == "SOURCE_NOT_FOUND":
        return AuthProbeResult("SOURCE_NOT_FOUND", None)
    if result != "AUTH_FAILED":
        return AuthProbeResult(result, None)  # timeout/その他エラー

    detected_scheme = _detect_challenge_scheme(headers)
    if not username or not password:
        return AuthProbeResult("AUTH_FAILED", detected_scheme)

    if detected_scheme == "digest":
        auth_result = _attempt_digest_authenticated(url, username, password, timeout)
    else:
        auth_result = _attempt_authenticated(url, _basic_auth_header(username, password), timeout)
    return AuthProbeResult(auth_result, detected_scheme)


class _DigestMjpegStream:
    """cv2.VideoCapture(FFmpeg)がDigest認証を扱えない環境向けの代替Reader。

    urllib(HTTPDigestAuthHandler)で認証済みHTTP接続を維持し、multipart/x-mixed-replace
    形式のMJPEGから逐次JPEGフレームを取り出す。単体JPEG(snapshot)応答の場合はread()の
    たびに再取得する。既存のRTSP経路やBasic認証HTTP経路には一切影響しない、追加のfallback。
    """

    def __init__(self, url: str, username: str, password: str, timeout: float = 8.0) -> None:
        self.url = url
        self.username = username
        self.password = password
        self.timeout = timeout
        self._opener = self._build_opener()
        self._response = None
        self._buffer = b""
        self._multipart = False

    def _build_opener(self):
        password_mgr = HTTPPasswordMgrWithDefaultRealm()
        password_mgr.add_password(None, self.url, self.username, self.password)
        return build_opener(HTTPDigestAuthHandler(password_mgr))

    def open(self) -> bool:
        try:
            self._response = self._opener.open(Request(self.url, method="GET"), timeout=self.timeout)
        except Exception:
            self._response = None
            return False
        content_type = ""
        try:
            content_type = (self._response.headers.get("Content-Type") or "") if self._response.headers else ""
        except Exception:
            content_type = ""
        self._multipart = "multipart" in content_type.lower()
        return True

    def isOpened(self) -> bool:  # noqa: N802 (cv2.VideoCapture互換のnaming)
        return self._response is not None

    def read(self):
        if self._response is None:
            return False, None
        try:
            if not self._multipart:
                data = self._response.read()
                if not data:
                    return False, None
                frame = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
                # 単体snapshotは毎回取り直すため接続を作り直す。
                self._response.close()
                self._response = None
                if not self.open():
                    return False, None
                return (frame is not None), frame

            deadline = time.monotonic() + self.timeout
            while time.monotonic() < deadline:
                start = self._buffer.find(b"\xff\xd8")
                if start != -1:
                    end = self._buffer.find(b"\xff\xd9", start + 2)
                    if end != -1:
                        jpeg_bytes = self._buffer[start : end + 2]
                        self._buffer = self._buffer[end + 2 :]
                        frame = cv2.imdecode(np.frombuffer(jpeg_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
                        if frame is not None:
                            return True, frame
                        continue
                chunk = self._response.read(8192)
                if not chunk:
                    return False, None
                self._buffer += chunk
                if len(self._buffer) > 8_000_000:
                    self._buffer = self._buffer[-1_000_000:]  # 暴走防止、直近のみ保持
            return False, None
        except Exception:
            return False, None

    def close(self) -> None:
        if self._response is not None:
            try:
                self._response.close()
            except Exception:
                pass
            self._response = None


class _DigestCaptureAdapter:
    """_DigestMjpegStreamを、既存コードが依存するcv2.VideoCapture最小interfaceで包むadapter。
    check_detailed/read/closeを変更せず両対応させるための互換層。
    """

    def __init__(self, stream: _DigestMjpegStream) -> None:
        self._stream = stream

    def isOpened(self) -> bool:  # noqa: N802
        return self._stream.isOpened()

    def read(self):
        return self._stream.read()

    def get(self, _prop) -> float:
        return 0.0  # probe単体ではFPSは不明。呼び出し側は0/Noneを許容する実装済み。

    def set(self, *_args) -> bool:
        return True  # BUFFERSIZE等の設定は無効(no-op)、例外にしない

    def release(self) -> None:
        self._stream.close()


class VideoReader:
    OPEN_TIMEOUT_MS = 8000
    READ_TIMEOUT_MS = 8000
    _PROBE_ERROR_MESSAGES = {
        "AUTH_FAILED": "認証に失敗しました（ユーザー名/パスワードを確認してください）",
        "SOURCE_NOT_FOUND": "映像URLが見つかりません（404）",
        "CONNECTION_TIMEOUT": "接続がタイムアウトしました",
        "CONNECTION_FAILED": "映像ソースへの接続に失敗しました",
    }

    def __init__(self, config: ReaderConfig) -> None:
        self.config = config
        self.capture = None
        self.source_fps: float | None = None

    def _open(self):
        if is_local_camera(self.config.source_type):
            backend = getattr(cv2, "CAP_DSHOW", 0)
            index = self.config.device_id if self.config.device_id is not None else 0
            self.capture = cv2.VideoCapture(index, backend) if backend else cv2.VideoCapture(index)
            try:
                self.capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except Exception:
                pass
            return self.capture

        resolved_url = resolve_stream_url(self.config.url or "")
        url = _temporary_auth_url(resolved_url, self.config.username, self.config.password)
        backend = getattr(cv2, "CAP_FFMPEG", 0)
        capture = cv2.VideoCapture(url, backend) if backend else cv2.VideoCapture(url)
        for name, value in (
            ("CAP_PROP_OPEN_TIMEOUT_MSEC", self.OPEN_TIMEOUT_MS),
            ("CAP_PROP_READ_TIMEOUT_MSEC", self.READ_TIMEOUT_MS),
        ):
            prop = getattr(cv2, name, 0)
            if prop:
                try:
                    capture.set(prop, value)
                except Exception:
                    pass
        try:
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass

        if self._should_try_digest_fallback(resolved_url) and not self._cv2_capture_usable(capture):
            digest_capture = self._try_digest_fallback(resolved_url)
            if digest_capture is not None:
                capture.release()
                capture = digest_capture

        self.capture = capture
        return self.capture

    def _should_try_digest_fallback(self, resolved_url: str) -> bool:
        return (
            urlsplit(resolved_url).scheme.lower() in _PROBE_SCHEMES
            and bool(self.config.username)
            and bool(self.config.password)
        )

    def _cv2_capture_usable(self, capture) -> bool:
        """cv2(FFmpeg)経由で実際にフレームを取得できるかを短時間だけ確認する。
        Digest認証カメラはisOpened()がTrueでも実フレームを一切返さないことがあるため、
        isOpened()だけでなく短い試し読みまで行う。成功時に読んだフレームは破棄してよい
        (直後にread()が呼ばれても、live streamなら次フレームを取得できるだけ)。
        """
        if not capture.isOpened():
            return False
        deadline = time.monotonic() + _CV2_USABILITY_PROBE_TIMEOUT
        while time.monotonic() < deadline:
            try:
                ok, frame = capture.read()
            except Exception:
                return False
            if ok and frame is not None and getattr(frame, "size", 0) > 0:
                return True
        return False

    def _try_digest_fallback(self, resolved_url: str):
        probe = probe_http_status(
            resolved_url, self.config.username, self.config.password, timeout=_DIGEST_FALLBACK_PROBE_TIMEOUT
        )
        if probe.error_code or probe.auth_scheme != "digest":
            return None
        stream = _DigestMjpegStream(resolved_url, self.config.username, self.config.password)
        if not stream.open():
            return None
        return _DigestCaptureAdapter(stream)

    def read(self):
        if self.capture is None or not self.capture.isOpened():
            self._open()
        if self.capture is None:
            return False, None
        result = self.capture.read()
        if self.source_fps is None:
            try:
                value = float(self.capture.get(cv2.CAP_PROP_FPS) or 0)
                self.source_fps = value if value > 0 else None
            except Exception:
                self.source_fps = None
        return result

    def close(self) -> None:
        if self.capture is not None:
            self.capture.release()
            self.capture = None

    def check_detailed(self, timeout: float = 8.0) -> VideoCheckResult:
        if not is_local_camera(self.config.source_type) and not (self.config.url or "").strip():
            return VideoCheckResult(False, self.config.source_type, error_code="SOURCE_NOT_CONFIGURED", message="映像URLを入力してください")

        raw_url = (self.config.url or "").strip()
        resolved_url = raw_url
        effective_config = self.config
        if not is_local_camera(self.config.source_type):
            resolved_url = resolve_stream_url(raw_url)
            scheme = urlsplit(resolved_url).scheme.lower()
            if scheme not in _KNOWN_SCHEMES:
                return VideoCheckResult(False, self.config.source_type, error_code="STREAM_URL_INVALID_OR_UNSUPPORTED", message="対応していない、または不正な映像URL形式です")

            resolved_sanitized = sanitize_url(resolved_url) if resolved_url != raw_url else None
            probe = probe_http_status(resolved_url, self.config.username, self.config.password, timeout=min(timeout, 5.0))
            if probe.error_code:
                return VideoCheckResult(False, self.config.source_type, error_code=probe.error_code, message=self._PROBE_ERROR_MESSAGES[probe.error_code], resolved_url_sanitized=resolved_sanitized)
            if resolved_url != raw_url:
                effective_config = replace(self.config, url=resolved_url)

        reader = VideoReader(effective_config)
        try:
            cap = reader._open()
            resolved_sanitized = sanitize_url(resolved_url) if resolved_url != raw_url else None
            if cap is None or not cap.isOpened():
                return VideoCheckResult(False, self.config.source_type, error_code="CONNECTION_FAILED", message="映像ソースを開けません", resolved_url_sanitized=resolved_sanitized)
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                ok, frame = cap.read()
                if ok and frame is not None and getattr(frame, "size", 0) > 0:
                    height, width = frame.shape[:2]
                    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0) or None
                    return VideoCheckResult(True, self.config.source_type, width, height, fps, message="接続成功", resolved_url_sanitized=resolved_sanitized)
            # 事前probe(またはlocal camera)を通過して開けはしたが、timeoutまで
            # 一度も有効フレームを取得できなかった -> 「開けない」ではなく「読めない」。
            return VideoCheckResult(False, self.config.source_type, error_code="READ_FAILED", message="映像を開けましたが、フレームを取得できません", resolved_url_sanitized=resolved_sanitized)
        except Exception:
            return VideoCheckResult(False, self.config.source_type, error_code="CONNECTION_FAILED", message="映像ソースへの接続に失敗しました")
        finally:
            reader.close()

    @staticmethod
    def check(config: ReaderConfig) -> tuple[bool, str]:
        result = VideoReader(config).check_detailed()
        return result.connected, result.message
