"""Dashboard表示FPS(Frontendのみで制御するpreview.jpg polling頻度)が、Backend側の
video_fps/inference_fps設定やMonitor Runtime設定を一切書き換えないことを確認する
(Issue #14: Dashboard負荷対策の独立性検証)。

Dashboard表示FPSはlocalStorageにのみ保存されるFrontend-only設定であり、
preview.jpg/overlay.jpgへのGETリクエスト頻度を変えるだけで、リクエスト自体に
bodyは無く、Backend側のMonitor/InferenceSettingsを変更するAPIは一切呼ばれない。
ここではBackend側の実際の保証(preview.jpg/overlay.jpgを何度呼んでも
video_fps/inference_fps/その他のinference設定が変化しないこと)を検証する。
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from runtime.frame_buffer import LatestFrameBuffer
from runtime.runtime_manager import runtime_manager

import pytest

pytestmark = pytest.mark.unit


class _FakeRuntime:
    """実cv2/FFmpeg接続を伴わず、preview.jpg/overlay.jpgの疎通確認だけを行うための
    最小限のRuntime代替。"""

    def __init__(self) -> None:
        self.buffer = LatestFrameBuffer()
        self.buffer.put(b"\xff\xd8fake-jpeg\xff\xd9")
        self.inference_scheduler = None
        self.state = "running"


def test_preview_and_overlay_polling_never_changes_video_fps_or_inference_fps():
    with TestClient(app) as client:
        created = client.post("/api/monitors", json={"name": "test_dashboard_fps_independence", "display_name": "fps independence"})
        monitor_id = created.json()["id"]

        # video_fps/inference_fpsを明示的な既知の値に設定する(enabled=falseで実Runtimeは起動しない)。
        client.patch(
            f"/api/monitors/{monitor_id}",
            json={"source": {"source_type": "url", "url": "http://fps-independence-test.invalid/live"}, "inference": {"video_fps": 7, "inference_fps": 3}, "enabled": False},
        )
        before = client.get(f"/api/monitors/{monitor_id}").json()
        assert before["inference"]["video_fps"] == 7
        assert before["inference"]["inference_fps"] == 3

        # Dashboard側が「表示FPSを上げた」状況を模して、preview.jpg/overlay.jpgを
        # 何度も(高頻度を想定して)連続で取得する。テスト用に実Runtimeをmanagerへ直接登録する
        # (実cv2/FFmpeg接続は不要、Dashboard pollingがVideoCaptureを新規作成しないことは
        # 別テスト・調査で確認済み)。
        fake_runtime = _FakeRuntime()
        runtime_manager._runtimes[monitor_id] = fake_runtime
        try:
            for _ in range(30):
                assert client.get(f"/api/monitors/{monitor_id}/preview.jpg").status_code == 200
                assert client.get(f"/api/monitors/{monitor_id}/overlay.jpg").status_code == 200
        finally:
            runtime_manager._runtimes.pop(monitor_id, None)

        after = client.get(f"/api/monitors/{monitor_id}").json()
        assert after["inference"]["video_fps"] == 7
        assert after["inference"]["inference_fps"] == 3
        # sourceやその他inference設定も変化していないこと(Dashboard pollingは無関係)。
        assert after["inference"] == before["inference"]
        assert after["source"] == before["source"]

        client.delete(f"/api/monitors/{monitor_id}")


def test_preview_and_overlay_endpoints_accept_no_request_body_that_could_mutate_settings():
    """preview.jpg/overlay.jpgはGET・パスパラメータのみで、video_fps/inference_fpsを
    変更できるフィールドを一切受け付けないことをOpenAPI schemaで確認する
    (Dashboard表示FPSの値がどのような形であれBackendへ送られる余地が無いことの裏付け)。
    """
    with TestClient(app) as client:
        schema = client.get("/openapi.json").json()
    for path in ("/api/monitors/{monitor_id}/preview.jpg", "/api/monitors/{monitor_id}/overlay.jpg"):
        get_op = schema["paths"][path]["get"]
        assert "requestBody" not in get_op
        param_names = {p["name"] for p in get_op.get("parameters", [])}
        assert param_names <= {"monitor_id"}
