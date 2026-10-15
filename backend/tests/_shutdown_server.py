"""test_graceful_shutdown用の隔離サーバー(pytestでは収集されない)。実Backendと同じstreams routerと
shutdown通知を使い、Monitor Runtimeだけを偽物にして起動する。"""
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main(port: int) -> None:
    import uvicorn
    from fastapi import FastAPI

    from app.routers import streams
    from runtime import shutdown_signal
    from runtime.runtime_manager import runtime_manager

    class Buffer:
        def get(self):
            return b"x" * 2000, time.monotonic()

    class FakeRuntime:
        state = "running"
        buffer = Buffer()

        def stop(self):
            self.state = "stopped"

    for monitor_id in (2, 3, 4):
        runtime_manager._runtimes[monitor_id] = FakeRuntime()

    @asynccontextmanager
    async def lifespan(_app):
        shutdown_signal.install_signal_hook()
        yield
        shutdown_signal.request_shutdown()
        runtime_manager.stop_all()

    app = FastAPI(lifespan=lifespan)
    app.include_router(streams.router)
    uvicorn.run(app, port=port, loop="app.event_loop:selector_loop_factory", log_level="warning")


if __name__ == "__main__":
    main(int(sys.argv[1]))
