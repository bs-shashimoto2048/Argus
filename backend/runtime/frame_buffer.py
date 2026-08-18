from threading import Lock
import time

class LatestFrameBuffer:
    def __init__(self) -> None:
        self._lock = Lock()
        self._jpeg: bytes | None = None
        self._updated_at: float | None = None
    def put(self, jpeg: bytes) -> None:
        with self._lock:
            self._jpeg = jpeg
            self._updated_at = time.time()
    def get(self) -> tuple[bytes | None, float | None]:
        with self._lock:
            return self._jpeg, self._updated_at

    def age(self, now: float | None = None) -> float | None:
        with self._lock:
            if self._updated_at is None:
                return None
            return max(0.0, (now if now is not None else time.time()) - self._updated_at)
