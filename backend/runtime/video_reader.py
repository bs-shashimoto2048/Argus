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
    def __init__(self, config: ReaderConfig) -> None:
        self.config = config
        self.capture = None
    def _open(self):
        if self.config.source_type == "camera":
            backend = getattr(cv2, "CAP_DSHOW", 0)
            self.capture = cv2.VideoCapture(self.config.device_id or 0, backend) if backend else cv2.VideoCapture(self.config.device_id or 0)
        else:
            url = _temporary_auth_url(self.config.url or "", self.config.username, self.config.password)
            backend = getattr(cv2, "CAP_FFMPEG", 0)
            self.capture = cv2.VideoCapture(url, backend) if backend else cv2.VideoCapture(url)
            for prop, value in ((getattr(cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC", 0), 8000), (getattr(cv2, "CAP_PROP_READ_TIMEOUT_MSEC", 0), 8000)):
                if prop:
                    try: self.capture.set(prop, value)
                    except Exception: pass
        try: self.capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception: pass
        return self.capture
    def read(self):
        if self.capture is None or not self.capture.isOpened():
            self._open()
        return self.capture.read() if self.capture is not None else (False, None)
    def close(self) -> None:
        if self.capture is not None:
            self.capture.release()
            self.capture = None
    @staticmethod
    def check(config: ReaderConfig) -> tuple[bool, str]:
        reader = VideoReader(config)
        try:
            cap = reader._open()
            if cap is None or not cap.isOpened(): return False, "映像ソースを開けません"
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                ok, frame = cap.read()
                if ok and frame is not None and getattr(frame, "size", 0) > 0: return True, "接続成功"
            return False, "映像フレームを取得できません（タイムアウト）"
        except Exception:
            return False, "映像ソースへの接続に失敗しました"
        finally:
            reader.close()
