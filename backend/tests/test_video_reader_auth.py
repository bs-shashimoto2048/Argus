"""Basic/Digest認証付き映像接続の診断強化(Issue #14)に関する単体テスト。

- URLへの一時認証埋め込み(_temporary_auth_url)のencoding/二重埋め込み防止
- viewer URLのquery(imagepath等)から実stream URLを解決するresolve_stream_url
- HTTP(S)事前probe(probe_http_status)のWWW-Authenticateによるscheme判定とstatus分類
- HTTP MJPEG用の代替Reader(_AuthenticatedMjpegStream / _HttpMjpegCaptureAdapter)
  (認証方式を問わずcv2/FFmpegが読めない場合のfallback)
- check_detailed / _open のREAD_FAILED / STREAM_URL_INVALID_OR_UNSUPPORTED / fallback分岐
"""
from __future__ import annotations

from urllib.error import HTTPError, URLError

import numpy as np
import pytest

from runtime.video_reader import (
    AuthProbeResult,
    ReaderConfig,
    VideoReader,
    _AuthenticatedMjpegStream,
    _HttpMjpegCaptureAdapter,
    _detect_challenge_scheme,
    _temporary_auth_url,
    probe_http_status,
    resolve_stream_url,
)

pytestmark = pytest.mark.unit


# --- _temporary_auth_url ---

def test_temporary_auth_url_embeds_credentials():
    url = _temporary_auth_url("http://example.test/live", "user", "pass")
    assert url == "http://user:pass@example.test/live"


def test_temporary_auth_url_encodes_special_characters():
    url = _temporary_auth_url("http://example.test/live", "u@ser", "p@ss:word/1")
    assert url.startswith("http://u%40ser:p%40ss%3Aword%2F1@example.test/live")


def test_temporary_auth_url_does_not_double_embed_when_url_already_has_auth():
    url = _temporary_auth_url("http://already:there@example.test/live", "user", "pass")
    assert url == "http://already:there@example.test/live"


def test_temporary_auth_url_returns_unchanged_without_credentials():
    url = _temporary_auth_url("http://example.test/live", None, None)
    assert url == "http://example.test/live"


def test_temporary_auth_url_preserves_port():
    url = _temporary_auth_url("http://example.test:8080/live", "user", "pass")
    assert url == "http://user:pass@example.test:8080/live"


# --- resolve_stream_url ---

def test_resolve_stream_url_decodes_imagepath_query():
    url = "http://host/view/view.shtml?id=148&imagepath=%2Fmjpg%2Fvideo.mjpg%3Fcamera%3D1&size=1"
    assert resolve_stream_url(url) == "http://host/mjpg/video.mjpg?camera=1"


def test_resolve_stream_url_preserves_existing_auth_in_netloc():
    url = "http://user:pass@host/view/view.shtml?imagepath=%2Fmjpg%2Fvideo.mjpg"
    assert resolve_stream_url(url) == "http://user:pass@host/mjpg/video.mjpg"


def test_resolve_stream_url_leaves_unrelated_query_untouched():
    url = "http://host/mjpg/video.mjpg?camera=1"
    assert resolve_stream_url(url) == url


def test_resolve_stream_url_leaves_url_without_query_untouched():
    url = "http://host/mjpg/video.mjpg"
    assert resolve_stream_url(url) == url


def test_resolve_stream_url_rejects_non_absolute_path_value():
    url = "http://host/view/view.shtml?imagepath=not-a-path"
    assert resolve_stream_url(url) == url


def test_resolve_stream_url_rejects_value_with_scheme_or_host():
    url = "http://host/view/view.shtml?imagepath=http%3A%2F%2Fevil.test%2Fx"
    assert resolve_stream_url(url) == url


def test_resolve_stream_url_empty_input_returns_empty():
    assert resolve_stream_url("") == ""


# --- _detect_challenge_scheme ---

def test_detect_challenge_scheme_defaults_to_basic_when_no_header():
    assert _detect_challenge_scheme(None) == "basic"
    assert _detect_challenge_scheme({}) == "basic"


def test_detect_challenge_scheme_detects_digest():
    assert _detect_challenge_scheme({"WWW-Authenticate": 'Digest realm="cam", qop="auth"'}) == "digest"


def test_detect_challenge_scheme_prefers_digest_when_multiple_challenges_present():
    class FakeHeaders:
        def get_all(self, name):
            if name == "WWW-Authenticate":
                return ['Basic realm="cam"', 'Digest realm="cam", qop="auth"']
            return None

    assert _detect_challenge_scheme(FakeHeaders()) == "digest"


# --- probe_http_status: scheme/no-op ---

def test_probe_http_status_skips_non_http_schemes():
    result = probe_http_status("rtsp://example.test/live", "user", "pass")
    assert result.error_code is None
    assert result.auth_scheme is None


def test_probe_http_status_returns_ok_when_unauthenticated_request_succeeds(monkeypatch):
    class FakeResponse:
        def close(self):
            pass

    monkeypatch.setattr("runtime.video_reader.urlopen", lambda *a, **k: FakeResponse())
    result = probe_http_status("http://example.test/live", "user", "pass")
    assert result.error_code is None


def test_probe_http_status_maps_404_to_source_not_found(monkeypatch):
    def fake_urlopen(*_a, **_k):
        raise HTTPError("http://example.test/live", 404, "Not Found", {}, None)

    monkeypatch.setattr("runtime.video_reader.urlopen", fake_urlopen)
    result = probe_http_status("http://example.test/live", None, None)
    assert result.error_code == "SOURCE_NOT_FOUND"


def test_probe_http_status_falls_back_to_get_when_head_not_allowed(monkeypatch):
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request.get_method())
        if request.get_method() == "HEAD":
            raise HTTPError("http://example.test/live", 405, "Method Not Allowed", {}, None)

        class FakeResponse:
            def close(self):
                pass

        return FakeResponse()

    monkeypatch.setattr("runtime.video_reader.urlopen", fake_urlopen)
    result = probe_http_status("http://example.test/live", None, None)
    assert result.error_code is None
    assert calls == ["HEAD", "GET"]


def test_probe_http_status_maps_timeout_to_connection_timeout(monkeypatch):
    import socket

    def fake_urlopen(*_a, **_k):
        raise URLError(socket.timeout("timed out"))

    monkeypatch.setattr("runtime.video_reader.urlopen", fake_urlopen)
    result = probe_http_status("http://example.test/live", None, None)
    assert result.error_code == "CONNECTION_TIMEOUT"


def test_probe_http_status_maps_connection_refused_to_connection_failed(monkeypatch):
    def fake_urlopen(*_a, **_k):
        raise URLError(ConnectionRefusedError("refused"))

    monkeypatch.setattr("runtime.video_reader.urlopen", fake_urlopen)
    result = probe_http_status("http://example.test/live", None, None)
    assert result.error_code == "CONNECTION_FAILED"


# --- probe_http_status: Basic ---

def test_probe_http_status_basic_challenge_wrong_credentials_is_auth_failed(monkeypatch):
    def fake_urlopen(*_a, **_k):
        raise HTTPError("http://example.test/live", 401, "Unauthorized", {}, None)

    monkeypatch.setattr("runtime.video_reader.urlopen", fake_urlopen)
    result = probe_http_status("http://example.test/live", "user", "wrong")
    assert result.error_code == "AUTH_FAILED"
    assert result.auth_scheme == "basic"


def test_probe_http_status_sends_basic_auth_header_not_in_url(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        auth = request.get_header("Authorization")
        if not auth:
            raise HTTPError("http://example.test/live", 401, "Unauthorized", {}, None)

        captured["url"] = request.full_url
        captured["auth_header"] = auth

        class FakeResponse:
            def close(self):
                pass

        return FakeResponse()

    monkeypatch.setattr("runtime.video_reader.urlopen", fake_urlopen)
    result = probe_http_status("http://example.test/live", "user", "pass")
    assert result.error_code is None
    assert result.auth_scheme == "basic"
    assert "user" not in captured["url"] and "pass" not in captured["url"]
    assert captured["auth_header"] == "Basic dXNlcjpwYXNz"


def test_probe_http_status_basic_challenge_without_credentials_is_auth_failed(monkeypatch):
    def fake_urlopen(*_a, **_k):
        raise HTTPError("http://example.test/live", 401, "Unauthorized", {}, None)

    monkeypatch.setattr("runtime.video_reader.urlopen", fake_urlopen)
    result = probe_http_status("http://example.test/live", None, None)
    assert result.error_code == "AUTH_FAILED"
    assert result.auth_scheme == "basic"


# --- probe_http_status: Digest（ブラウザではOKなのにArgusがAUTH_FAILEDになる根本原因の修正） ---

def test_probe_http_status_detects_digest_and_authenticates_successfully(monkeypatch):
    def fake_urlopen(*_a, **_k):
        raise HTTPError("http://example.test/live", 401, "Unauthorized", {"WWW-Authenticate": 'Digest realm="cam"'}, None)

    calls = {}

    class FakeDigestResponse:
        def close(self):
            pass

    class FakeOpener:
        def open(self, request, timeout):
            calls["url"] = request.full_url
            return FakeDigestResponse()

    monkeypatch.setattr("runtime.video_reader.urlopen", fake_urlopen)
    monkeypatch.setattr("runtime.video_reader.build_opener", lambda *a, **k: FakeOpener())

    result = probe_http_status("http://example.test/live", "user", "pass")
    assert result.error_code is None
    assert result.auth_scheme == "digest"
    assert "user" not in calls["url"] and "pass" not in calls["url"]


def test_probe_http_status_digest_wrong_credentials_is_auth_failed(monkeypatch):
    def fake_urlopen(*_a, **_k):
        raise HTTPError("http://example.test/live", 401, "Unauthorized", {"WWW-Authenticate": 'Digest realm="cam"'}, None)

    class FakeOpener:
        def open(self, request, timeout):
            raise HTTPError("http://example.test/live", 401, "Unauthorized", {}, None)

    monkeypatch.setattr("runtime.video_reader.urlopen", fake_urlopen)
    monkeypatch.setattr("runtime.video_reader.build_opener", lambda *a, **k: FakeOpener())

    result = probe_http_status("http://example.test/live", "user", "wrongpass")
    assert result.error_code == "AUTH_FAILED"
    assert result.auth_scheme == "digest"


def test_probe_http_status_digest_challenge_without_credentials_is_auth_failed(monkeypatch):
    def fake_urlopen(*_a, **_k):
        raise HTTPError("http://example.test/live", 401, "Unauthorized", {"WWW-Authenticate": 'Digest realm="cam"'}, None)

    monkeypatch.setattr("runtime.video_reader.urlopen", fake_urlopen)
    result = probe_http_status("http://example.test/live", None, None)
    assert result.error_code == "AUTH_FAILED"
    assert result.auth_scheme == "digest"


# --- _AuthenticatedMjpegStream / _HttpMjpegCaptureAdapter ---

def test_authenticated_mjpeg_stream_reads_frame_from_multipart(monkeypatch):
    jpeg = b"\xff\xd8" + b"fake-jpeg-bytes" + b"\xff\xd9"

    class FakeResponse:
        def __init__(self):
            self.headers = {"Content-Type": "multipart/x-mixed-replace; boundary=frame"}
            self._sent = False

        def read(self, _n=None):
            if self._sent:
                return b""
            self._sent = True
            return jpeg

        def close(self):
            pass

    class FakeOpener:
        def open(self, request, timeout):
            return FakeResponse()

    monkeypatch.setattr("runtime.video_reader.build_opener", lambda *a, **k: FakeOpener())
    monkeypatch.setattr("cv2.imdecode", lambda *_a, **_k: np.zeros((2, 2, 3), dtype=np.uint8))

    stream = _AuthenticatedMjpegStream("http://example.test/mjpg", "user", "pass")
    assert stream.open() is True
    assert stream.isOpened() is True
    # open()時点で1フレーム確認済みのものがread()で返る(pending frame)。
    ok, frame = stream.read()
    assert ok is True
    assert frame is not None


def test_authenticated_mjpeg_stream_works_without_credentials(monkeypatch):
    """無認証のMJPEGソースでもfallbackとして機能すること(認証方式を問わない)。"""
    jpeg = b"\xff\xd8" + b"fake-jpeg-bytes" + b"\xff\xd9"

    class FakeResponse:
        def __init__(self):
            self.headers = {"Content-Type": "multipart/x-mixed-replace; boundary=frame"}
            self._sent = False

        def read(self, _n=None):
            if self._sent:
                return b""
            self._sent = True
            return jpeg

        def close(self):
            pass

    class FakeOpener:
        def open(self, request, timeout):
            return FakeResponse()

    monkeypatch.setattr("runtime.video_reader.build_opener", lambda *a, **k: FakeOpener())
    monkeypatch.setattr("cv2.imdecode", lambda *_a, **_k: np.zeros((2, 2, 3), dtype=np.uint8))

    stream = _AuthenticatedMjpegStream("http://example.test/mjpg", None, None)
    assert stream.open() is True


def test_authenticated_mjpeg_stream_open_failure_returns_false(monkeypatch):
    class FakeOpener:
        def open(self, request, timeout):
            raise HTTPError("http://example.test/mjpg", 401, "Unauthorized", {}, None)

    monkeypatch.setattr("runtime.video_reader.build_opener", lambda *a, **k: FakeOpener())
    stream = _AuthenticatedMjpegStream("http://example.test/mjpg", "user", "wrong")
    assert stream.open() is False
    assert stream.isOpened() is False
    ok, frame = stream.read()
    assert ok is False and frame is None


def test_authenticated_mjpeg_stream_open_fails_when_connected_but_no_frame_available(monkeypatch):
    """HTTP接続自体は張れても映像データが得られない場合は「開けた」扱いにしない。"""
    class FakeResponse:
        def __init__(self):
            self.headers = {"Content-Type": "multipart/x-mixed-replace; boundary=frame"}

        def read(self, _n=None):
            return b""  # 即EOF、フレームは一切来ない

        def close(self):
            pass

    class FakeOpener:
        def open(self, request, timeout):
            return FakeResponse()

    monkeypatch.setattr("runtime.video_reader.build_opener", lambda *a, **k: FakeOpener())
    stream = _AuthenticatedMjpegStream("http://example.test/mjpg", None, None)
    assert stream.open() is False
    assert stream.isOpened() is False


def test_http_mjpeg_capture_adapter_proxies_to_stream():
    class FakeStream:
        def __init__(self):
            self.closed = False

        def isOpened(self):
            return True

        def read(self):
            return True, "frame"

        def close(self):
            self.closed = True

    fake = FakeStream()
    adapter = _HttpMjpegCaptureAdapter(fake)
    assert adapter.isOpened() is True
    assert adapter.read() == (True, "frame")
    assert adapter.set(1, 2) is True
    assert adapter.get(1) == 0.0
    adapter.release()
    assert fake.closed is True


# --- check_detailed: 新しいerror_code分岐 & viewer URL解決 ---

def test_check_detailed_rejects_unsupported_scheme():
    reader = VideoReader(ReaderConfig(source_type="url", url="ftp://example.test/video"))
    result = reader.check_detailed()
    assert result.connected is False
    assert result.error_code == "STREAM_URL_INVALID_OR_UNSUPPORTED"


def test_check_detailed_short_circuits_on_probe_auth_failure(monkeypatch):
    monkeypatch.setattr("runtime.video_reader.probe_http_status", lambda *a, **k: AuthProbeResult("AUTH_FAILED", "digest"))
    reader = VideoReader(ReaderConfig(source_type="url", url="http://example.test/live", username="u", password="wrong"))
    result = reader.check_detailed()
    assert result.connected is False
    assert result.error_code == "AUTH_FAILED"


def test_check_detailed_returns_read_failed_when_open_succeeds_but_no_frame(monkeypatch):
    class FakeCapture:
        def isOpened(self):
            return True

        def read(self):
            return False, None

        def get(self, _prop):
            return 0

        def set(self, *_a):
            return True

        def release(self):
            pass

    monkeypatch.setattr("runtime.video_reader.probe_http_status", lambda *a, **k: AuthProbeResult(None, None))
    monkeypatch.setattr("cv2.VideoCapture", lambda *a, **k: FakeCapture())
    monkeypatch.setattr(VideoReader, "_try_http_mjpeg_fallback", lambda self, resolved_url: None)
    reader = VideoReader(ReaderConfig(source_type="url", url="http://example.test/live"))
    result = reader.check_detailed(timeout=0.05)
    assert result.connected is False
    assert result.error_code == "READ_FAILED"


def test_check_detailed_resolves_viewer_url_before_probing_and_reports_hint(monkeypatch):
    captured = {}

    def fake_probe(url, username, password, timeout=5.0):
        captured["url"] = url
        return AuthProbeResult("AUTH_FAILED", "basic")

    monkeypatch.setattr("runtime.video_reader.probe_http_status", fake_probe)

    viewer_url = "http://example.test/view/view.shtml?imagepath=%2Fmjpg%2Fvideo.mjpg%3Fcamera%3D1"
    reader = VideoReader(ReaderConfig(source_type="url", url=viewer_url, username="u", password="p"))
    result = reader.check_detailed()

    assert captured["url"] == "http://example.test/mjpg/video.mjpg?camera=1"
    assert result.resolved_url_sanitized == "http://example.test/mjpg/video.mjpg?camera=1"


# --- _open: HTTP MJPEG fallback（cv2/FFmpegが開けない/読めない場合のみ発動） ---

def test_open_does_not_try_http_mjpeg_fallback_when_cv2_already_works(monkeypatch):
    class FakeCv2Capture:
        def isOpened(self):
            return True

        def read(self):
            return True, np.zeros((2, 2, 3), dtype=np.uint8)

        def get(self, _p):
            return 0

        def set(self, *_a):
            return True

        def release(self):
            pass

    monkeypatch.setattr("cv2.VideoCapture", lambda *a, **k: FakeCv2Capture())
    called = {"count": 0}

    def fake_try_fallback(self, resolved_url):
        called["count"] += 1
        return None

    monkeypatch.setattr(VideoReader, "_try_http_mjpeg_fallback", fake_try_fallback)
    reader = VideoReader(ReaderConfig(source_type="url", url="http://example.test/mjpg", username="u", password="p"))
    reader._open()
    assert called["count"] == 0


def test_open_tries_http_mjpeg_fallback_even_without_credentials(monkeypatch):
    """機種差でcv2が読めない場合、認証情報の有無に関わらずfallbackを試す
    (Issue #14: 3台目のような無認証/未検証の認証方式でも同様の問題が起こりうるため)。"""
    class FakeCv2Capture:
        def isOpened(self):
            return False

        def read(self):
            return False, None

        def get(self, _p):
            return 0

        def set(self, *_a):
            return True

        def release(self):
            pass

    monkeypatch.setattr("cv2.VideoCapture", lambda *a, **k: FakeCv2Capture())
    called = {"count": 0}

    def fake_try_fallback(self, resolved_url):
        called["count"] += 1
        return None

    monkeypatch.setattr(VideoReader, "_try_http_mjpeg_fallback", fake_try_fallback)
    reader = VideoReader(ReaderConfig(source_type="url", url="http://example.test/mjpg"))
    reader._open()
    assert called["count"] == 1


def test_open_skips_http_mjpeg_fallback_for_local_camera(monkeypatch):
    called = {"count": 0}

    def fake_try_fallback(self, resolved_url):
        called["count"] += 1
        return None

    monkeypatch.setattr(VideoReader, "_try_http_mjpeg_fallback", fake_try_fallback)

    class FakeLocalCapture:
        def set(self, *_a):
            return True

    monkeypatch.setattr("cv2.VideoCapture", lambda *a, **k: FakeLocalCapture())
    reader = VideoReader(ReaderConfig(source_type="camera", device_id=0))
    reader._open()
    assert called["count"] == 0


def test_open_falls_back_to_http_mjpeg_reader_when_cv2_cannot_open_and_fallback_confirmed(monkeypatch):
    class FakeCv2Capture:
        def isOpened(self):
            return False

        def read(self):
            return False, None

        def get(self, _p):
            return 0

        def set(self, *_a):
            return True

        def release(self):
            pass

    monkeypatch.setattr("cv2.VideoCapture", lambda *a, **k: FakeCv2Capture())

    fake_fallback_capture = object()
    monkeypatch.setattr(VideoReader, "_try_http_mjpeg_fallback", lambda self, resolved_url: fake_fallback_capture)

    reader = VideoReader(ReaderConfig(source_type="url", url="http://example.test/mjpg", username="u", password="p"))
    cap = reader._open()
    assert cap is fake_fallback_capture
