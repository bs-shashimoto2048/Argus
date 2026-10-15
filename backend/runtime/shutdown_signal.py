"""Backend終了要求の通知(Issue #72)。

uvicornは終了要求を受けると、接続中のレスポンスが完了するまで待ってからlifespanの終了処理
(Runtime停止)を呼ぶ。MJPEG配信はRuntime停止までループし続けるため、配信中の接続が1本でも残ると
「配信はRuntime停止待ち、Runtime停止は配信終了待ち」となり、プロセスが終了しなかった。
ここで終了要求そのものを検知し、配信ループ等が自分から抜けられるようにする。
"""
import logging
import signal
import threading

logger = logging.getLogger("argus.shutdown")

shutdown_requested = threading.Event()


def request_shutdown() -> None:
    shutdown_requested.set()


def install_signal_hook() -> list[str]:
    """uvicornが設定した終了シグナルのhandlerを包み、先にshutdown_requestedを立てる。

    uvicornはserve()の開始時にsignal handlerを設定してからlifespan startupを呼ぶ。
    元のhandler(uvicornのhandle_exit)は必ず呼び続けるため、uvicorn本来の終了処理は変わらない。
    main thread以外(テスト等)では何もしない。
    """
    shutdown_requested.clear()
    if threading.current_thread() is not threading.main_thread():
        return []
    hooked: list[str] = []
    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        previous = signal.getsignal(sig)
        if not callable(previous) or getattr(previous, "_argus_shutdown_hook", False):
            continue

        def handler(signum, frame, _previous=previous):
            shutdown_requested.set()
            _previous(signum, frame)

        handler._argus_shutdown_hook = True  # type: ignore[attr-defined]
        try:
            signal.signal(sig, handler)
            hooked.append(name)
        except (ValueError, OSError):
            logger.warning("終了シグナル %s へのhookを設定できませんでした", name)
    return hooked
