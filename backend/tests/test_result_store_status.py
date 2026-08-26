"""result_store.save_result が読取・推論状態(inference_status、DB上はLatestResult.status)を
推論エラー時にも正しく更新すること、かつMonitor.status(映像Runtime接続状態専用の
カラム)には一切書き込まないことを確認する回帰テスト。

元々(Issue #29以前)は`if monitor and not result.error:`の条件により、推論エラー時に
Monitor.statusが更新されず、Dashboard側で「読取不能」バッジが表示されなかった。その後の
修正でMonitor.statusにも読取状態(normal/warning/read_error)を書き込むようにしたが、これは
RuntimeManager/MonitorRuntimeが書き込む映像Runtime接続状態(connecting/running/
reconnecting/stopped/error)と同じカラムを奪い合う形になり、Runtime再構築時に旧Runtimeの
callbackが書き込んだ古い状態と競合する不整合を招いた(Issue #29)。現在はMonitor.statusを
映像Runtime接続状態専用とし、読取・推論状態はLatestResult.status(API: inference_status)
だけで表現する。
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.services.result_store import save_result
from reading.models import CandidateStatus, ConfirmedReading


def test_inference_status_becomes_read_error_on_inference_error_without_touching_video_status():
    with TestClient(app) as client:
        created = client.post("/api/monitors", json={"name": "result_store_status_test", "display_name": "テスト", "location": "試験室"})
        assert created.status_code == 201, created.text
        monitor_id = created.json()["id"]
        try:
            # Runtimeを起動していないため、Monitor.status(映像状態)は既定値のまま。
            # save_result()の呼び出し前後でこの値が変わらないことをもって、
            # 読取状態の更新がMonitor.statusへ波及しないことを確認する。
            baseline_status = client.get(f"/api/monitors/{monitor_id}").json()["status"]

            save_result(monitor_id, ConfirmedReading(validation_status=CandidateStatus.CONFIRMED, value="123", confidence=0.9, engine="mock"))
            body = client.get(f"/api/monitors/{monitor_id}").json()
            assert body["inference_status"] == "ok"
            assert body["status"] == baseline_status

            # 連続失敗が閾値へ到達しNO_READINGへ遷移した状態を模す。
            save_result(monitor_id, ConfirmedReading(validation_status=CandidateStatus.NO_READING, raw_error="MODEL_NOT_CONFIGURED", engine="ultralytics"))
            body = client.get(f"/api/monitors/{monitor_id}").json()
            assert body["inference_status"] == "read_error"
            assert body["last_inference_error"] == "MODEL_NOT_CONFIGURED"
            assert body["status"] == baseline_status
            # previous_valueは推論失敗を挟んでも失われないこと。
            assert body["current_value"] == "123"
        finally:
            client.delete(f"/api/monitors/{monitor_id}")


def test_current_inference_error_clears_on_recovery_while_last_inference_error_stays_sticky():
    """Issue #32: last_inference_error(値が変わるまで残り続ける「粘着性」の履歴値)とは別に、
    current_inference_errorは直近のRaw Readingが成功した時点(まだConfirmedへ再確定していない
    PENDING中でも)で即座にnullへクリアされ、「現在は実際にエラー状態ではない」ことを
    正しく表現できることを確認する。last_inference_error/inference_status(status)の
    既存の粘着的な更新条件・タイミングは一切変更しない。"""
    with TestClient(app) as client:
        created = client.post("/api/monitors", json={"name": "current_error_recovery_test", "display_name": "テスト", "location": "試験室"})
        assert created.status_code == 201, created.text
        monitor_id = created.json()["id"]
        try:
            save_result(monitor_id, ConfirmedReading(validation_status=CandidateStatus.CONFIRMED, value="10", confidence=0.9, engine="mock"))
            body = client.get(f"/api/monitors/{monitor_id}").json()
            assert body["current_inference_error"] is None
            assert body["last_inference_error"] is None

            # 連続失敗が閾値へ到達しNO_READINGへ遷移(MODEL_NOT_CONFIGURED)。
            save_result(monitor_id, ConfirmedReading(validation_status=CandidateStatus.NO_READING, raw_error="MODEL_NOT_CONFIGURED", engine="ultralytics"))
            body = client.get(f"/api/monitors/{monitor_id}").json()
            assert body["inference_status"] == "read_error"
            assert body["last_inference_error"] == "MODEL_NOT_CONFIGURED"
            assert body["current_inference_error"] == "MODEL_NOT_CONFIGURED"

            # Raw Reading自体は既に成功しているが、まだ多数決の合意が取れておらずPENDING
            # (validation_statusはstabilizer._carry_forward()経由でCONFIRMEDにはまだ遷移しない)。
            # このときlatest.valueは既に"10"で存在するため、result_storeのPENDING分岐は
            # status/last_inference_errorを一切更新しない(粘着的に"read_error"/
            # "MODEL_NOT_CONFIGURED"のまま)。しかしcurrent_inference_errorは
            # raw_error=Noneを見て即座にクリアされ、「今はエラーではない」ことを表現する。
            save_result(monitor_id, ConfirmedReading(validation_status=CandidateStatus.PENDING, raw_error=None, engine="ultralytics"))
            body = client.get(f"/api/monitors/{monitor_id}").json()
            assert body["inference_status"] == "read_error"
            assert body["last_inference_error"] == "MODEL_NOT_CONFIGURED"
            assert body["current_inference_error"] is None
            assert body["current_value"] == "10"
        finally:
            client.delete(f"/api/monitors/{monitor_id}")


def test_previous_value_confidence_and_confirmed_at_are_recorded_on_value_change():
    """Issue #28: 前回確定値の文字列(previous_value)だけでなく、その値が確定した
    時点の信頼度(previous_confidence)・確定日時(previous_confirmed_at)も、値が
    入れ替わる瞬間にLatestResultへ退避されることを確認する。ReadingStabilizer/
    Validatorの判定ロジックには一切触れない(save_resultの保存処理のみの検証)。"""
    from datetime import datetime, timezone

    with TestClient(app) as client:
        created = client.post("/api/monitors", json={"name": "previous_value_history_test", "display_name": "テスト", "location": "試験室"})
        assert created.status_code == 201, created.text
        monitor_id = created.json()["id"]
        try:
            first_confirmed_at = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
            save_result(monitor_id, ConfirmedReading(validation_status=CandidateStatus.CONFIRMED, value="100", confidence=0.7, confirmed_at=first_confirmed_at, engine="mock"))
            body = client.get(f"/api/monitors/{monitor_id}").json()
            # 1回目のConfirmedでは、まだ「前回値」は存在しない。
            assert body["current_value"] == "100"
            assert body["confidence"] == 0.7
            assert body["previous_value"] is None
            assert body["previous_confidence"] is None
            assert body["previous_confirmed_at"] is None

            second_confirmed_at = datetime(2026, 1, 1, 0, 5, 0, tzinfo=timezone.utc)
            save_result(monitor_id, ConfirmedReading(validation_status=CandidateStatus.CONFIRMED, value="101", confidence=0.9, confirmed_at=second_confirmed_at, engine="mock"))
            body = client.get(f"/api/monitors/{monitor_id}").json()
            # 値が入れ替わった瞬間、旧値(100)側の信頼度・確定日時がprevious_*へ退避される。
            assert body["current_value"] == "101"
            assert body["confidence"] == 0.9
            assert body["previous_value"] == "100"
            assert body["previous_confidence"] == 0.7
            assert body["previous_confirmed_at"].startswith("2026-01-01T00:00:00")
        finally:
            client.delete(f"/api/monitors/{monitor_id}")


def test_previous_value_history_untouched_by_no_reading_between_confirms():
    """NO_READING(read_error)を挟んでも、前回値側の信頼度・確定日時は上書きされず、
    直前のConfirmed時点の値のまま保持されることを確認する(Issue #28)。"""
    with TestClient(app) as client:
        created = client.post("/api/monitors", json={"name": "previous_value_no_reading_test", "display_name": "テスト", "location": "試験室"})
        assert created.status_code == 201, created.text
        monitor_id = created.json()["id"]
        try:
            save_result(monitor_id, ConfirmedReading(validation_status=CandidateStatus.CONFIRMED, value="200", confidence=0.8, engine="mock"))
            save_result(monitor_id, ConfirmedReading(validation_status=CandidateStatus.CONFIRMED, value="201", confidence=0.6, engine="mock"))
            before = client.get(f"/api/monitors/{monitor_id}").json()
            assert before["previous_value"] == "200"
            assert before["previous_confidence"] == 0.8

            save_result(monitor_id, ConfirmedReading(validation_status=CandidateStatus.NO_READING, raw_error="NO_DETECTION", engine="mock"))
            after = client.get(f"/api/monitors/{monitor_id}").json()
            assert after["inference_status"] == "read_error"
            # current_value/previous_valueともにNO_READINGでは変化しないこと。
            assert after["current_value"] == "201"
            assert after["previous_value"] == "200"
            assert after["previous_confidence"] == 0.8
        finally:
            client.delete(f"/api/monitors/{monitor_id}")
