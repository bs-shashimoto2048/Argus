from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote, urlsplit, urlunsplit
import time

import cv2


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


class VideoReader:
    OPEN_TIMEOUT_MS = 8000
    READ_TIMEOUT_MS = 8000

    def __init__(self, config: ReaderConfig) -> None:
        self.config = config
        self.capture = None
        self.source_fps: float | None = None

    def _open(self):
        if is_local_camera(self.config.source_type):
            backend = getattr(cv2, "CAP_DSHOW", 0)
            index = self.config.device_id if self.config.device_id is not None else 0
            self.capture = cv2.VideoCapture(index, backend) if backend else cv2.VideoCapture(index)
        else:
            url = _temporary_auth_url(self.config.url or "", self.config.username, self.config.password)
            backend = getattr(cv2, "CAP_FFMPEG", 0)
            self.capture = cv2.VideoCapture(url, backend) if backend else cv2.VideoCapture(url)
            for name, value in (
                ("CAP_PROP_OPEN_TIMEOUT_MSEC", self.OPEN_TIMEOUT_MS),
                ("CAP_PROP_READ_TIMEOUT_MSEC", self.READ_TIMEOUT_MS),
            ):
                prop = getattr(cv2, name, 0)
                if prop:
                    try:
                        self.capture.set(prop, value)
                    except Exception:
                        pass
        try:
            self.capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass
        return self.capture

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
        reader = VideoReader(self.config)
        try:
            cap = reader._open()
            if cap is None or not cap.isOpened():
                return VideoCheckResult(False, self.config.source_type, error_code="CONNECTION_FAILED", message="映像ソースを開けません")
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                ok, frame = cap.read()
                if ok and frame is not None and getattr(frame, "size", 0) > 0:
                    height, width = frame.shape[:2]
                    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0) or None
                    return VideoCheckResult(True, self.config.source_type, width, height, fps, message="接続成功")
            return VideoCheckResult(False, self.config.source_type, error_code="CONNECTION_TIMEOUT", message="映像フレームを取得できません（タイムアウト）")
        except Exception:
            return VideoCheckResult(False, self.config.source_type, error_code="CONNECTION_FAILED", message="映像ソースへの接続に失敗しました")
        finally:
            reader.close()

    @staticmethod
    def check(config: ReaderConfig) -> tuple[bool, str]:
        result = VideoReader(config).check_detailed()
        return result.connected, result.message
