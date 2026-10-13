"""Issue #67: Windowsで、RSTで切られた接続によって待受socketが消えない(SelectorEventLoopで起動する)。"""
import asyncio
import socket
import struct
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from app.event_loop import selector_loop_factory

BACKEND_DIR = Path(__file__).resolve().parents[1]
START_SCRIPT = BACKEND_DIR.parent / "scripts" / "start_backend_dev.ps1"
TINY_APP = '''
async def app(scope, receive, send):
    if scope["type"] != "http":
        return
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/plain")]})
    await send({"type": "http.response.body", "body": b"ok"})
'''


def test_factory_returns_selector_event_loop():
    loop = selector_loop_factory()
    try:
        assert isinstance(loop, asyncio.SelectorEventLoop)
    finally:
        loop.close()


def test_start_script_uses_selector_loop_in_both_modes():
    lines = [line for line in START_SCRIPT.read_text(encoding="utf-8-sig").splitlines() if "uvicorn app.main:app" in line]
    assert len(lines) == 2  # -NoReload と --reload の両方
    assert all("--loop app.event_loop:selector_loop_factory" in line for line in lines)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _listening(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(1)
        try:
            s.connect(("127.0.0.1", port))
            return True
        except OSError:
            return False


@pytest.mark.skipif(sys.platform != "win32", reason="WinError 64はWindowsのProactorEventLoop固有")
def test_listener_survives_connections_reset_before_accept(tmp_path):
    (tmp_path / "tiny_app.py").write_text(TINY_APP, encoding="utf-8")
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "tiny_app:app", "--app-dir", str(tmp_path), "--port", str(port), "--loop", "app.event_loop:selector_loop_factory"],
        cwd=BACKEND_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(100):
            if _listening(port):
                break
            time.sleep(0.1)
        assert _listening(port)
        # Proactorでは30〜60回程度で待受が消える。接続直後にRSTを送る(SO_LINGER=0でclose)。
        for _ in range(300):
            with socket.socket() as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
                s.connect(("127.0.0.1", port))
        time.sleep(0.5)
        assert proc.poll() is None
        assert _listening(port)
        assert urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5).status == 200
    finally:
        proc.terminate()
        proc.wait(10)
