"""Basic認証付き映像接続の診断強化(Issue #14)に関する単体テスト。

- URLへの一時認証埋め込み(_temporary_auth_url)のencoding/二重埋め込み防止
- HTTP(S)事前probe(probe_http_status)のstatus分類
- check_detailedのREAD_FAILED / STREAM_URL_INVALID_OR_UNSUPPORTED分岐
"""
from __future__ import annotations

from urllib.error import HTTPError, URLError

import pytest

from runtime.video_reader import (
    ReaderConfig,
    VideoReader,
    _temporary_auth_url,
    probe_http_status,
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


# --- probe_http_status ---

def test_probe_http_status_skips_non_http_schemes():
    assert probe_http_status("rtsp://example.test/live", "user", "pass") is None


def test_probe_http_status_returns_none_on_success(monkeypatch):
    class FakeResponse:
        def close(self):
            pass

    monkeypatch.setattr("runtime.video_reader.urlopen", lambda *a, **k: FakeResponse())
    assert probe_http_status("http://example.test/live", "user", "pass") is None


def test_probe_http_status_maps_401_to_auth_failed(monkeypatch):
    def fake_urlopen(*_a, **_k):
        raise HTTPError("http://example.test/live", 401, "Unauthorized", {}, None)

    monkeypatch.setattr("runtime.video_reader.urlopen", fake_urlopen)
    assert probe_http_status("http://example.test/live", "user", "wrong") == "AUTH_FAILED"


def test_probe_http_status_maps_403_to_auth_failed(monkeypatch):
    def fake_urlopen(*_a, **_k):
        raise HTTPError("http://example.test/live", 403, "Forbidden", {}, None)

    monkeypatch.setattr("runtime.video_reader.urlopen", fake_urlopen)
    assert probe_http_status("http://example.test/live", "user", "pass") == "AUTH_FAILED"


def test_probe_http_status_maps_404_to_source_not_found(monkeypatch):
    def fake_urlopen(*_a, **_k):
        raise HTTPError("http://example.test/live", 404, "Not Found", {}, None)

    monkeypatch.setattr("runtime.video_reader.urlopen", fake_urlopen)
    assert probe_http_status("http://example.test/live", None, None) == "SOURCE_NOT_FOUND"


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
    assert probe_http_status("http://example.test/live", None, None) is None
    assert calls == ["HEAD", "GET"]


def test_probe_http_status_maps_timeout_to_connection_timeout(monkeypatch):
    import socket

    def fake_urlopen(*_a, **_k):
        raise URLError(socket.timeout("timed out"))

    monkeypatch.setattr("runtime.video_reader.urlopen", fake_urlopen)
    assert probe_http_status("http://example.test/live", None, None) == "CONNECTION_TIMEOUT"


def test_probe_http_status_maps_connection_refused_to_connection_failed(monkeypatch):
    def fake_urlopen(*_a, **_k):
        raise URLError(ConnectionRefusedError("refused"))

    monkeypatch.setattr("runtime.video_reader.urlopen", fake_urlopen)
    assert probe_http_status("http://example.test/live", None, None) == "CONNECTION_FAILED"


def test_probe_http_status_sends_basic_auth_header_not_in_url(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["auth_header"] = request.get_header("Authorization")

        class FakeResponse:
            def close(self):
                pass

        return FakeResponse()

    monkeypatch.setattr("runtime.video_reader.urlopen", fake_urlopen)
    probe_http_status("http://example.test/live", "user", "pass")
    assert "user" not in captured["url"] and "pass" not in captured["url"]
    assert captured["auth_header"] == "Basic dXNlcjpwYXNz"


# --- check_detailed: 新しいerror_code分岐 ---

def test_check_detailed_rejects_unsupported_scheme():
    reader = VideoReader(ReaderConfig(source_type="url", url="ftp://example.test/video"))
    result = reader.check_detailed()
    assert result.connected is False
    assert result.error_code == "STREAM_URL_INVALID_OR_UNSUPPORTED"


def test_check_detailed_short_circuits_on_probe_auth_failure(monkeypatch):
    monkeypatch.setattr("runtime.video_reader.probe_http_status", lambda *a, **k: "AUTH_FAILED")
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

    monkeypatch.setattr("runtime.video_reader.probe_http_status", lambda *a, **k: None)
    monkeypatch.setattr("cv2.VideoCapture", lambda *a, **k: FakeCapture())
    reader = VideoReader(ReaderConfig(source_type="url", url="http://example.test/live"))
    result = reader.check_detailed(timeout=0.05)
    assert result.connected is False
    assert result.error_code == "READ_FAILED"
