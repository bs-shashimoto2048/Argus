"""uvicorn用のevent loop factory(Issue #67)。

Windows版Python 3.12のProactorEventLoopは、accept待ちの接続がRSTで切られると(終了するブラウザ/Vite proxyなど)
`[WinError 64]`でaccept処理が失敗し、待受socketを閉じてしまう。プロセスは生存したままLISTENだけが消え、再起動まで復旧しない。
uvicornはWindowsの`--reload`なしでProactorEventLoopを固定で選ぶため、`--loop app.event_loop:selector_loop_factory`で
SelectorEventLoopを指定する(SelectorEventLoopはaccept失敗でも待受socketを閉じない)。
本Backendはasyncioのsubprocessを使わない(CPP workerは同期の`subprocess.Popen`)ため、Selectorに切り替えても影響しない。
"""
import asyncio


def selector_loop_factory() -> asyncio.AbstractEventLoop:
    return asyncio.SelectorEventLoop()
