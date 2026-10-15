"""argus_cpp_onnx_worker（C++常駐プロセス）とのIPCクライアント（Issue #37）。

毎フレームprocess起動はしない。プロセスは遅延起動され、以後は同一プロセスへ
直列化されたリクエストを送り続ける(Issue #37 §7/§33/§34: 最初から並列化しない)。
プロセスが異常終了した場合は次回呼び出し時に再起動する(§15: ただしengine選択
(cpp_onnx/legacy_python)自体を黙って切り替えることはしない。再起動するのは
C++ workerプロセスのみで、Argus側のinference_backend設定は変更しない)。

protocol（cpp/src/worker_main.cppと対応、変更する場合は両方を同時に更新すること):
    request:  [4 bytes LE uint32 header_len][header JSON][4 bytes LE uint32 payload_len][raw BGR24 pixels]
    response: [4 bytes LE uint32 json_len][response JSON]

payloadは生のBGR24(HWC, uint8)ピクセルデータそのもの(JPEG等の圧縮を経由しない)。
当初JPEGフレーミングで試作したところ、カメラ由来の圧縮に加えて追加の非可逆劣化が
生じ、production parityの僅かな破れ(confidence差が最大0.015まで悪化)につながる
ことが実測で判明したため、可逆な生ピクセル転送に変更した(Issue #37)。
"""
from __future__ import annotations

import json
import struct
import subprocess
import threading
from pathlib import Path
from typing import Any


class CppWorkerError(Exception):
    """C++ workerプロセスとの通信・起動に関する基底エラー。"""


class CppWorkerProcessDiedError(CppWorkerError):
    """プロセスが応答を返す前に終了した(クラッシュ・強制終了等)。"""


class CppWorkerStartError(CppWorkerError):
    """プロセス自体の起動に失敗した(exeが無い等)。"""


class CppOnnxWorkerProcess:
    """1つの常駐C++ workerプロセスを管理する(onnx_pathごとのsession cacheはworker内部)。

    プロセス全体でリクエストを直列化する(同時に2フレームを投げない)。複数Monitorが
    同じprofile/異なるprofileを使っていても、この1プロセスが順番に処理する
    (Issue #37 §33: 最初から無理にparallel化しない)。
    """

    def __init__(self, exe_path: Path, provider: str = "cpu") -> None:
        self._exe_path = exe_path
        self._provider = provider
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._closed = False

    def _ensure_started(self) -> None:
        if self._closed:
            # stop()後に遅れて届いた推論要求でworkerを再起動しない(終了処理中のorphan防止、Issue #72)。
            raise CppWorkerStartError("WORKER_STOPPED: backend is shutting down")
        if self._proc is not None and self._proc.poll() is None:
            return
        if not self._exe_path.is_file():
            raise CppWorkerStartError(f"WORKER_EXECUTABLE_NOT_FOUND: {self._exe_path}")
        try:
            self._proc = subprocess.Popen(
                [str(self._exe_path), "--provider", self._provider],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except OSError as exc:
            raise CppWorkerStartError(f"WORKER_START_FAILED: {exc}") from exc

    def infer(self, onnx_path: Path, profile: str, frame_id: str, bgr_bytes: bytes,
              width: int, height: int) -> dict[str, Any]:
        """1フレーム(生のBGR24ピクセル、width*height*3 bytes)をworkerへ送り、応答JSONを
        dictで返す。

        プロセスが死んでいた場合は例外を送出する(呼び出し元がInferenceResult.errorへ
        変換する。黙ってlegacy_pythonへは切り替えない、Issue #37 §15)。次回呼び出し時は
        プロセスを再起動するため、一時的な異常終了からは自動的に回復し得る。
        """
        with self._lock:
            self._ensure_started()
            assert self._proc is not None
            assert self._proc.stdin is not None and self._proc.stdout is not None
            header = json.dumps({
                "profile": profile, "onnx_path": str(onnx_path), "frame_id": frame_id,
                "width": width, "height": height,
            }).encode("utf-8")
            try:
                self._proc.stdin.write(struct.pack("<I", len(header)))
                self._proc.stdin.write(header)
                self._proc.stdin.write(struct.pack("<I", len(bgr_bytes)))
                self._proc.stdin.write(bgr_bytes)
                self._proc.stdin.flush()

                raw_len = self._proc.stdout.read(4)
                if len(raw_len) < 4:
                    self._mark_dead()
                    raise CppWorkerProcessDiedError("WORKER_PROCESS_DIED: no response (stdout closed)")
                (resp_len,) = struct.unpack("<I", raw_len)
                raw_resp = self._proc.stdout.read(resp_len)
                if len(raw_resp) < resp_len:
                    self._mark_dead()
                    raise CppWorkerProcessDiedError("WORKER_PROCESS_DIED: truncated response")
                return json.loads(raw_resp.decode("utf-8"))
            except (BrokenPipeError, OSError) as exc:
                self._mark_dead()
                raise CppWorkerProcessDiedError(f"WORKER_PROCESS_DIED: {exc}") from exc
            except json.JSONDecodeError as exc:
                raise CppWorkerError(f"WORKER_INVALID_RESPONSE: {exc}") from exc

    def _mark_dead(self) -> None:
        if self._proc is not None:
            try:
                self._proc.kill()
            except Exception:
                pass
        self._proc = None

    # 段階停止の待ち時間(Issue #72)。workerはstdin EOFで常駐loopを抜け、ONNX sessionを解放して終了する。
    STOP_LOCK_TIMEOUT_SECONDS = 3.0   # 推論中のinfer()がlockを持つ間の待ち上限(推論1回=数百ms〜1秒程度)
    STOP_GRACEFUL_SECONDS = 3.0       # stdin close後、自力終了を待つ上限
    STOP_TERMINATE_SECONDS = 2.0      # terminate後の終了待ち上限

    def stop(self) -> None:
        """stdin close → 自力終了待ち → terminate → kill の順で、各段をboundedに停止する。

        正常系(workerが自力終了)ではterminate/killは呼ばない。応答しないworkerでもlockを
        無期限に待たない(infer()が応答待ちでlockを保持していてもstopは完了する)。
        """
        self._closed = True
        acquired = self._lock.acquire(timeout=self.STOP_LOCK_TIMEOUT_SECONDS)
        try:
            proc = self._proc
            self._proc = None
            if proc is None:
                return
            if acquired:
                try:
                    if proc.stdin:
                        proc.stdin.close()
                except Exception:
                    pass
                try:
                    proc.wait(timeout=self.STOP_GRACEFUL_SECONDS)
                    return
                except subprocess.TimeoutExpired:
                    pass
            for action, wait in ((proc.terminate, self.STOP_TERMINATE_SECONDS), (proc.kill, self.STOP_TERMINATE_SECONDS)):
                try:
                    action()
                    proc.wait(timeout=wait)
                    return
                except subprocess.TimeoutExpired:
                    continue
                except Exception:
                    return
        finally:
            if acquired:
                self._lock.release()

    def is_running(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None
