"""inference_results履歴が「値変化時 + heartbeat」でのみ保存され、
毎推論結果が保存されるわけではないことを確認する。
"""
from __future__ import annotations

from sqlalchemy import select
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.inference.base import InferenceResult
from app.main import app
from app.models import InferenceResult as InferenceResultRow
from app.services.result_store import save_result


def _history_count(monitor_id: int) -> int:
    db = SessionLocal()
    try:
        return len(db.scalars(select(InferenceResultRow).where(InferenceResultRow.monitor_id == monitor_id)).all())
    finally:
        db.close()


def test_history_is_not_written_on_every_unchanged_result():
    with TestClient(app) as client:
        created = client.post("/api/monitors", json={"name": "history_throttle_test", "display_name": "テスト", "location": "試験室"})
        assert created.status_code == 201, created.text
        monitor_id = created.json()["id"]
        try:
            # 同じ値を複数回保存しても、履歴(inference_results)は最初の1回しか増えない。
            for _ in range(5):
                save_result(monitor_id, InferenceResult(value="100", confidence=0.9, engine="mock"))
            assert _history_count(monitor_id) == 1

            # 値が変化した場合は履歴が増える。
            save_result(monitor_id, InferenceResult(value="101", confidence=0.9, engine="mock"))
            assert _history_count(monitor_id) == 2

            # 変化後、再び同じ値を繰り返しても増えない(60秒heartbeatの範囲内)。
            for _ in range(5):
                save_result(monitor_id, InferenceResult(value="101", confidence=0.9, engine="mock"))
            assert _history_count(monitor_id) == 2
        finally:
            client.delete(f"/api/monitors/{monitor_id}")


def test_history_is_written_on_every_error_result():
    with TestClient(app) as client:
        created = client.post("/api/monitors", json={"name": "history_throttle_error_test", "display_name": "テスト", "location": "試験室"})
        assert created.status_code == 201, created.text
        monitor_id = created.json()["id"]
        try:
            for _ in range(3):
                save_result(monitor_id, InferenceResult(error="NO_DETECTION", engine="ultralytics"))
            # エラーは(値の変化に関わらず)毎回履歴に残す設計になっている。
            assert _history_count(monitor_id) == 3
        finally:
            client.delete(f"/api/monitors/{monitor_id}")
