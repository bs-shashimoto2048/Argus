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

    def _ensure_started(self) -> None:
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

    def stop(self) -> None:
        with self._lock:
            if self._proc is None:
                return
            try:
                if self._proc.stdin:
                    self._proc.stdin.close()
                self._proc.wait(timeout=5)
            except Exception:
                self._proc.kill()
            finally:
                self._proc = None

    def is_running(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None
