"""Issue #72: Backendの通常終了が、配信中の接続やworkerの状態に関係なくboundedで完了することを固定する。"""
import asyncio
import http.client
import os
import signal
import socket
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

from app.inference.base import ModelRegistry
from app.inference.cpp_worker_process import CppOnnxWorkerProcess
from app.routers import streams
from runtime import shutdown_signal
from runtime.runtime_manager import RuntimeManager


# ---- shutdown通知 ----------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_event():
    shutdown_signal.shutdown_requested.clear()
    yield
    shutdown_signal.shutdown_requested.clear()


def test_signal_hook_sets_event_and_still_calls_the_original_handler():
    sig = getattr(signal, "SIGBREAK", signal.SIGINT)
    called = []
    original = signal.getsignal(sig)
    signal.signal(sig, lambda signum, frame: called.append(signum))
    try:
        assert shutdown_signal.install_signal_hook()
        assert not shutdown_signal.shutdown_requested.is_set()
        signal.getsignal(sig)(sig, None)
        assert shutdown_signal.shutdown_requested.is_set()
        assert called == [sig]  # uvicorn本来のhandlerは必ず呼ばれる
    finally:
        signal.signal(sig, original)


def test_signal_hook_is_idempotent():
    sig = getattr(signal, "SIGBREAK", signal.SIGINT)
    original = signal.getsignal(sig)
    signal.signal(sig, lambda *_: None)
    try:
        shutdown_signal.install_signal_hook()
        first = signal.getsignal(sig)
        shutdown_signal.install_signal_hook()
        assert signal.getsignal(sig) is first
    finally:
        signal.signal(sig, original)


def test_signal_hook_is_skipped_outside_main_thread():
    result = []
    t = threading.Thread(target=lambda: result.append(shutdown_signal.install_signal_hook()))
    t.start()
    t.join()
    assert result == [[]]


# ---- MJPEG配信ループ ------------------------------------------------------

class _Buffer:
    def get(self):
        return b"jpeg", time.monotonic()


class _Runtime:
    state = "running"
    buffer = _Buffer()


def _drain(monitor_id: int, limit: float) -> list[bytes]:
    response = streams._stream_response(monitor_id)

    async def collect():
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)
        return chunks

    async def run():
        return await asyncio.wait_for(collect(), timeout=limit)

    return asyncio.run(run())


def test_stream_ends_when_shutdown_is_requested(monkeypatch):
    monkeypatch.setattr(streams.runtime_manager, "get_runtime", lambda _id: _Runtime())
    threading.Timer(0.5, shutdown_signal.request_shutdown).start()
    started = time.monotonic()
    chunks = _drain(2, limit=5)
    assert chunks  # 終了要求前は通常どおり配信している
    assert time.monotonic() - started < 3


def test_stream_still_ends_when_runtime_stops(monkeypatch):
    runtime = _Runtime()
    monkeypatch.setattr(streams.runtime_manager, "get_runtime", lambda _id: runtime)

    def stop():
        runtime.state = "stopped"

    threading.Timer(0.3, stop).start()
    assert _drain(2, limit=5)


# ---- cpp worker の段階停止 -------------------------------------------------

def _worker(tmp_path: Path, body: str) -> CppOnnxWorkerProcess:
    script = tmp_path / "fake_worker.py"
    script.write_text(textwrap.dedent(body), encoding="utf-8")
    worker = CppOnnxWorkerProcess(Path(sys.executable), "cpu")
    worker._exe_path = Path(sys.executable)

    # exe_pathは実行ファイルだが、引数にscriptを渡すため起動処理だけ差し替える。
    def start():
        if worker._proc is not None and worker._proc.poll() is None:
            return
        worker._proc = subprocess.Popen([sys.executable, str(script)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    worker._ensure_started = start  # type: ignore[method-assign]
    return worker


CLEAN_EXIT = """
import sys
sys.stdin.buffer.read()   # stdin EOFで終了(実workerと同じ)
"""

IGNORES_EOF = """
import sys, time
while True:
    time.sleep(0.2)       # stdin EOFを無視して居座る
"""


def test_worker_stops_gracefully_without_terminate(tmp_path, monkeypatch):
    worker = _worker(tmp_path, CLEAN_EXIT)
    worker._ensure_started()
    proc = worker._proc
    terminated = []
    monkeypatch.setattr(proc, "terminate", lambda: terminated.append(1))
    monkeypatch.setattr(proc, "kill", lambda: terminated.append(2))
    started = time.monotonic()
    worker.stop()
    assert proc.poll() is not None
    assert terminated == []  # 正常系で強制終了は使わない
    assert worker._proc is None
    assert time.monotonic() - started < 3


def test_worker_that_ignores_eof_is_terminated_within_bound(tmp_path, monkeypatch):
    monkeypatch.setattr(CppOnnxWorkerProcess, "STOP_GRACEFUL_SECONDS", 0.5)
    worker = _worker(tmp_path, IGNORES_EOF)
    worker._ensure_started()
    proc = worker._proc
    started = time.monotonic()
    worker.stop()
    assert proc.poll() is not None  # orphanを残さない
    assert time.monotonic() - started < 5


def test_worker_stop_does_not_wait_forever_for_a_busy_infer_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(CppOnnxWorkerProcess, "STOP_LOCK_TIMEOUT_SECONDS", 0.3)
    worker = _worker(tmp_path, IGNORES_EOF)
    worker._ensure_started()
    proc = worker._proc
    worker._lock.acquire()  # infer()が応答待ちでlockを保持している状態
    try:
        done = []
        t = threading.Thread(target=lambda: (worker.stop(), done.append(1)))
        started = time.monotonic()
        t.start()
        t.join(timeout=10)
        assert done == [1]
        assert time.monotonic() - started < 8
        assert proc.poll() is not None
    finally:
        worker._lock.release()


def test_worker_already_dead_is_a_noop(tmp_path):
    worker = _worker(tmp_path, "pass\n")
    worker._ensure_started()
    worker._proc.wait(timeout=10)
    worker.stop()
    assert worker._proc is None
    worker.stop()  # 2回目も安全


def test_worker_never_started_is_a_noop():
    CppOnnxWorkerProcess(Path("missing.exe"), "cpu").stop()


def test_registry_close_stops_resources_and_continues_after_failure():
    registry = ModelRegistry()
    stopped = []

    class Boom:
        def stop(self):
            raise RuntimeError("boom")

    class Good:
        def stop(self):
            stopped.append("good")

    registry.get("a", "cpu", Boom, "x")
    registry.get("b", "cpu", Good, "y")
    registry.get("c", "cpu", lambda: object(), "z")  # stop()を持たないもの
    registry.close()
    assert stopped == ["good"]
    assert registry.size() == 0


# ---- Runtime停止 ----------------------------------------------------------

def test_stop_all_stops_three_monitors_and_is_repeatable():
    class Fake:
        def __init__(self):
            self.stopped = 0

        def stop(self):
            self.stopped += 1

    manager = RuntimeManager()
    for cycle in range(3):  # start/stopの繰り返し
        fakes = {i: Fake() for i in (2, 3, 4)}
        manager._runtimes.update(fakes)
        started = time.monotonic()
        manager.stop_all()
        assert time.monotonic() - started < 1
        assert all(f.stopped == 1 for f in fakes.values())
        assert manager.count() == 0


# ---- プロセス全体(隔離サーバーへ実際にCTRL_BREAK) ----------------------------

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _open_stream(port: int, stop: threading.Event):
    try:
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.request("GET", "/api/monitors/2/stream.mjpg")
        r = c.getresponse()
        while not stop.is_set() and r.read(4096):
            pass
    except Exception:
        pass


def _run_server_and_terminate(clients: int, db_dir: Path) -> float:
    port = _free_port()
    # CIはARGUS_DATABASE_URLで共有DBを指す。隔離サーバーがそのDBへ触れないよう、専用の一時DBへ向ける。
    env = dict(os.environ, ARGUS_DATABASE_URL=f"sqlite:///{(db_dir / 'shutdown_server.db').as_posix()}")
    server = Path(__file__).with_name("_shutdown_server.py")
    proc = subprocess.Popen([sys.executable, str(server), str(port)], creationflags=subprocess.CREATE_NEW_PROCESS_GROUP, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
    stop = threading.Event()
    try:
        for _ in range(60):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
                break
            except OSError:
                time.sleep(0.25)
        threads = [threading.Thread(target=_open_stream, args=(port, stop), daemon=True) for _ in range(clients)]
        for t in threads:
            t.start()
        time.sleep(1.5)
        started = time.monotonic()
        os.kill(proc.pid, signal.CTRL_BREAK_EVENT)
        proc.wait(timeout=15)
        return time.monotonic() - started
    finally:
        stop.set()
        if proc.poll() is None:
            proc.kill()


@pytest.mark.skipif(sys.platform != "win32", reason="CTRL_BREAK_EVENTはWindowsのみ")
@pytest.mark.parametrize("clients", [0, 3])
def test_process_exits_on_ctrl_break_even_with_active_streams(clients, tmp_path):
    assert _run_server_and_terminate(clients, tmp_path) < 10
