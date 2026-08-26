"""inference_results履歴が「Confirmed値変化時 + heartbeat」でのみ保存され、
毎回(Raw推論結果ごと)保存されるわけではないことを確認する。
"""
from __future__ import annotations

from sqlalchemy import select
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.models import InferenceResult as InferenceResultRow
from app.services.result_store import save_result
from reading.models import CandidateStatus, ConfirmedReading


def _history_count(monitor_id: int) -> int:
    db = SessionLocal()
    try:
        return len(db.scalars(select(InferenceResultRow).where(InferenceResultRow.monitor_id == monitor_id)).all())
    finally:
        db.close()


def _confirmed(value, confidence=0.9, engine="mock"):
    return ConfirmedReading(validation_status=CandidateStatus.CONFIRMED, value=value, confidence=confidence, engine=engine)


def test_history_is_not_written_on_every_unchanged_result():
    with TestClient(app) as client:
        created = client.post("/api/monitors", json={"name": "history_throttle_test", "display_name": "テスト", "location": "試験室"})
        assert created.status_code == 201, created.text
        monitor_id = created.json()["id"]
        try:
            # 同じConfirmed値を複数回保存しても、履歴(inference_results)は最初の1回しか増えない。
            for _ in range(5):
                save_result(monitor_id, _confirmed("100"))
            assert _history_count(monitor_id) == 1

            # 値が変化した場合は履歴が増える。
            save_result(monitor_id, _confirmed("101"))
            assert _history_count(monitor_id) == 2

            # 変化後、再び同じ値を繰り返しても増えない(60秒heartbeatの範囲内)。
            for _ in range(5):
                save_result(monitor_id, _confirmed("101"))
            assert _history_count(monitor_id) == 2
        finally:
            client.delete(f"/api/monitors/{monitor_id}")


def test_history_records_no_reading_transition_but_throttles_repeats():
    """連続失敗によるNO_READINGへの遷移は履歴に残すが、
    そのままの状態が続く間は(60秒heartbeatの範囲内)毎回は増やさない
    (Raw ReadingのたびにDB writeしない、という方針を維持する)。
    """
    with TestClient(app) as client:
        created = client.post("/api/monitors", json={"name": "history_throttle_no_reading_test", "display_name": "テスト", "location": "試験室"})
        assert created.status_code == 201, created.text
        monitor_id = created.json()["id"]
        try:
            for _ in range(3):
                save_result(monitor_id, ConfirmedReading(validation_status=CandidateStatus.NO_READING, raw_error="NO_DETECTION", engine="ultralytics"))
            assert _history_count(monitor_id) == 1

            # 復旧してConfirmed値が付いたら、再度履歴が増える。
            save_result(monitor_id, _confirmed("100"))
            assert _history_count(monitor_id) == 2
        finally:
            client.delete(f"/api/monitors/{monitor_id}")


def test_history_does_not_record_transient_rejections():
    """decrease_detected/rate_exceeded/invalid_format/pending等の一時的な棄却は
    履歴に一切記録しない(静かに棄却する設計)。
    """
    with TestClient(app) as client:
        created = client.post("/api/monitors", json={"name": "history_throttle_rejected_test", "display_name": "テスト", "location": "試験室"})
        assert created.status_code == 201, created.text
        monitor_id = created.json()["id"]
        try:
            save_result(monitor_id, _confirmed("100"))
            assert _history_count(monitor_id) == 1

            for status in (CandidateStatus.DECREASE_DETECTED, CandidateStatus.RATE_EXCEEDED, CandidateStatus.INVALID_FORMAT, CandidateStatus.PENDING, CandidateStatus.REJECTED):
                save_result(monitor_id, ConfirmedReading(validation_status=status, value="100", raw_value="999"))
            assert _history_count(monitor_id) == 1

            body = client.get(f"/api/monitors/{monitor_id}").json()
            assert body["current_value"] == "100"
            # Issue #29: 読取状態はinference_status(LatestResult.status)で表現する。
            # Monitor.status(映像Runtime接続状態専用)はこのテストではRuntime未起動のため既定値のまま。
            assert body["inference_status"] == "ok"
        finally:
            client.delete(f"/api/monitors/{monitor_id}")
