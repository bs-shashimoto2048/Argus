"""baseline永続化/復元/reset/rebase/監査/conflict可視化のService・API・結合テスト(Issue #40)。

テストは一時DB(conftest)で動くため、実運用のDBや実カメラには触れない。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.database import SessionLocal
from app.inference.registry import model_registry
from app.main import app
from app.models import LatestResult, ReadingBaseline, ReadingBaselineEvent
from app.services import monitor_service, reading_baseline_service as svc
from app.services.result_store import save_result
from reading.baseline import CONFLICT_ALERT_SECONDS
from reading.models import CandidateStatus, ConfirmedReading, ConflictInfo, ReadingSettings
from reading.stabilizer import ReadingStabilizer
from runtime.frame_buffer import LatestFrameBuffer
from runtime.inference_scheduler import InferenceScheduler
from app.inference.base import InferenceResult

pytestmark = pytest.mark.integration

READING = {"enabled": True, "mode": "majority", "window_size": 3, "required_matches": 2, "min_confidence": 0.5,
           "expected_digits": 7, "decimal_position": 0, "monotonic": True, "max_consecutive_failures": 5}


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def monitor_id(client):
    name = "t_bl_" + uuid.uuid4().hex[:8]
    created = client.post("/api/monitors", json={"name": name, "display_name": name})
    assert created.status_code == 201, created.text
    mid = created.json()["id"]
    res = client.patch(f"/api/monitors/{mid}", json={"inference": {"method": "object_detection", "reading": READING}})
    assert res.status_code == 200, res.text
    yield mid
    client.delete(f"/api/monitors/{mid}")


def _confirmed(value="265754", epoch=0, status=CandidateStatus.CONFIRMED, persist=True, conflict=None, decimal_position=0, expected_digits=7, at=None):
    return ConfirmedReading(
        validation_status=status, value=value, numeric_value=Decimal(value), confidence=0.9,
        confirmed_at=at or datetime.now(timezone.utc), engine="mock", baseline_epoch=epoch, persist_baseline=persist,
        decimal_position=decimal_position, expected_digits=expected_digits, conflict=conflict,
    )


def _row(db, mid):
    db.expire_all()
    return db.scalar(select(ReadingBaseline).where(ReadingBaseline.monitor_id == mid))


def _events(mid):
    db = SessionLocal()
    try:
        return svc.list_events(db, mid)
    finally:
        db.close()


def _record(mid, confirmed):
    db = SessionLocal()
    try:
        svc.record_confirmed(db, mid, confirmed)
        db.commit()
    finally:
        db.close()


# --- 永続化(CONFIRMEDのみ) ---

def test_only_confirmed_is_persisted(monitor_id):
    _record(monitor_id, _confirmed(status=CandidateStatus.LOW_CONFIDENCE))
    _record(monitor_id, _confirmed(persist=False))  # reading.enabled=false(パススルー)相当
    db = SessionLocal()
    try:
        assert _row(db, monitor_id) is None
        _record(monitor_id, _confirmed("265754"))
        row = _row(db, monitor_id)
        assert (row.value, row.numeric_value, row.state, row.source) == ("265754", "265754", "active", "confirmed")
        assert (row.decimal_position, row.expected_digits, row.epoch) == (0, 7, 0)
        _record(monitor_id, _confirmed("265755"))
        assert _row(db, monitor_id).value == "265755"
        # LOW_CONFIDENCEはbaselineを書き換えない
        _record(monitor_id, _confirmed("265999", status=CandidateStatus.LOW_CONFIDENCE))
        assert _row(db, monitor_id).value == "265755"
    finally:
        db.close()


def test_new_monitor_has_no_baseline_row_and_latest_value_is_not_used(client, monitor_id):
    db = SessionLocal()
    try:
        latest = db.scalar(select(LatestResult).where(LatestResult.monitor_id == monitor_id))
        latest.value = "0290919"  # 過去の誤確定が残っている既存Monitor
        db.commit()
    finally:
        db.close()
    assert svc.restore_baseline(monitor_id, ReadingSettings.from_dict(READING)) == (None, 0, None)
    assert client.get(f"/api/monitors/{monitor_id}").json()["reading_baseline"] is None


# --- 復元と設定の指紋 ---

def test_restore_returns_persisted_baseline_and_epoch(monitor_id):
    _record(monitor_id, _confirmed("265754"))
    baseline, epoch, conflict = svc.restore_baseline(monitor_id, ReadingSettings.from_dict(READING))
    assert baseline.value == "265754" and baseline.numeric_value == Decimal("265754") and epoch == 0 and conflict is None
    assert baseline.confirmed_at.tzinfo is not None


def test_semantic_fingerprint_mismatch_clears_baseline_and_audits(monitor_id):
    _record(monitor_id, _confirmed("265754"))
    changed = ReadingSettings.from_dict({**READING, "decimal_position": 1})
    assert svc.restore_baseline(monitor_id, changed) == (None, 1, None)
    events = _events(monitor_id)
    assert [e["action"] for e in events] == ["auto_semantic_reset"]
    assert events[0]["old_value"] == "265754" and events[0]["operator"] == "system"
    db = SessionLocal()
    try:
        row = _row(db, monitor_id)
        assert (row.state, row.source, row.epoch) == ("pending_reset", "auto_semantic_reset", 1)
    finally:
        db.close()
    # 2回目以降は追加の監査イベントを作らない
    assert svc.restore_baseline(monitor_id, changed) == (None, 1, None)
    assert len(_events(monitor_id)) == 1


def test_restore_fails_open_on_error(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("db down")
    monkeypatch.setattr(svc, "_get_row", boom)
    assert svc.restore_baseline(999999, ReadingSettings()) == (None, 0, None)


# --- epochによる競合防止 ---

def test_stale_epoch_confirmed_does_not_overwrite_after_rebase(client, monitor_id):
    _record(monitor_id, _confirmed("265759"))
    res = client.post(f"/api/monitors/{monitor_id}/reading/baseline/rebase", json={"value": "265754", "reason": "実メーター確認", "operator": "tester", "force": True})
    assert res.status_code == 200, res.text
    _record(monitor_id, _confirmed("265759", epoch=0))  # rebase前の世代で計算されたConfirmed
    db = SessionLocal()
    try:
        row = _row(db, monitor_id)
        assert (row.value, row.epoch) == ("265754", 1)
    finally:
        db.close()


# --- conflictの永続化 ---

def test_conflict_is_persisted_and_cleared(client, monitor_id):
    _record(monitor_id, _confirmed("265759"))
    started = datetime.now(timezone.utc) - timedelta(seconds=CONFLICT_ALERT_SECONDS + 120)
    conflict = ConflictInfo(CandidateStatus.DECREASE_DETECTED, "265754", 500, started, datetime.now(timezone.utc))
    _record(monitor_id, _confirmed("265759", status=CandidateStatus.DECREASE_DETECTED, persist=False, conflict=conflict))
    summary = client.get(f"/api/monitors/{monitor_id}").json()["reading_baseline"]
    assert summary["conflict"] is True and summary["conflict_status"] == "decrease_detected"
    assert summary["conflict_candidate"] == "265754" and summary["conflict_seconds"] >= CONFLICT_ALERT_SECONDS
    status = client.get(f"/api/monitors/{monitor_id}/reading/baseline").json()
    assert status["conflict"]["alert"] is True and status["baseline"]["value"] == "265759"
    _record(monitor_id, _confirmed("265760"))
    assert client.get(f"/api/monitors/{monitor_id}").json()["reading_baseline"]["conflict"] is False


def test_short_conflict_is_not_an_alert(client, monitor_id):
    _record(monitor_id, _confirmed("265759"))
    now = datetime.now(timezone.utc)
    conflict = ConflictInfo(CandidateStatus.DECREASE_DETECTED, "265754", 3, now - timedelta(seconds=20), now)
    _record(monitor_id, _confirmed("265759", status=CandidateStatus.DECREASE_DETECTED, persist=False, conflict=conflict))
    summary = client.get(f"/api/monitors/{monitor_id}").json()["reading_baseline"]
    assert summary["conflict"] is False and summary["conflict_status"] == "decrease_detected"


# --- API: reset / rebase / events ---

def test_validation_errors(client, monitor_id):
    base = f"/api/monitors/{monitor_id}/reading/baseline"
    assert client.post(f"{base}/reset", json={"reason": "r"}).status_code == 422
    assert client.post(f"{base}/reset", json={"reason": "r", "operator": "   "}).status_code == 422
    assert client.post(f"{base}/reset", json={"reason": "  ", "operator": "o"}).status_code == 422
    assert client.post(f"{base}/rebase", json={"value": "abc", "reason": "r", "operator": "o"}).status_code == 422
    assert client.post(f"{base}/rebase", json={"value": "12345678", "reason": "r", "operator": "o"}).status_code == 422
    assert client.post("/api/monitors/999999/reading/baseline/reset", json={"reason": "r", "operator": "o"}).status_code == 404
    assert client.get("/api/monitors/999999/reading/baseline").status_code == 404
    assert _events(monitor_id) == []  # 拒否された操作は監査に残らない(変更が無いため)


def test_reading_disabled_returns_409(client, monitor_id):
    res = client.patch(f"/api/monitors/{monitor_id}", json={"inference": {"method": "object_detection", "reading": {**READING, "enabled": False}}})
    assert res.status_code == 200, res.text
    base = f"/api/monitors/{monitor_id}/reading/baseline"
    for path, body in (("reset", {}), ("rebase", {"value": "265754"})):
        res = client.post(f"{base}/{path}", json={**body, "reason": "r", "operator": "o"})
        assert res.status_code == 409 and res.json()["detail"]["code"] == "READING_DISABLED"


def test_rebase_updates_baseline_and_audit_but_not_display_value(client, monitor_id):
    db = SessionLocal()
    try:
        latest = db.scalar(select(LatestResult).where(LatestResult.monitor_id == monitor_id))
        latest.value = "265759"
        db.commit()
    finally:
        db.close()
    _record(monitor_id, _confirmed("265759"))
    res = client.post(f"/api/monitors/{monitor_id}/reading/baseline/rebase", json={"value": "0265754", "reason": "実表示を確認", "operator": "山田", "force": True})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["baseline"]["value"] == "265754" and body["baseline"]["source"] == "operator_rebase" and body["baseline"]["epoch"] == 1
    assert client.get(f"/api/monitors/{monitor_id}").json()["current_value"] == "265759"  # 表示値は直接書き換えない
    events = client.get(f"/api/monitors/{monitor_id}/reading/baseline/events").json()["events"]
    assert len(events) == 1
    event = events[0]
    assert (event["action"], event["old_value"], event["new_value"], event["reason"], event["operator"]) == ("rebase", "265759", "265754", "実表示を確認", "山田")
    assert event["client_host"] and event["occurred_at"].endswith("Z") and event["monitor_name"] and "reading" in event["context"]


def test_reset_sets_pending_and_next_confirmed_creates_baseline(client, monitor_id):
    _record(monitor_id, _confirmed("265759"))
    res = client.post(f"/api/monitors/{monitor_id}/reading/baseline/reset", json={"reason": "メーター交換", "operator": "o"})
    assert res.status_code == 200, res.text
    assert res.json()["baseline"]["state"] == "pending_reset"
    assert svc.restore_baseline(monitor_id, ReadingSettings.from_dict(READING))[0] is None
    _record(monitor_id, _confirmed("100", epoch=1))
    status = client.get(f"/api/monitors/{monitor_id}/reading/baseline").json()
    assert status["baseline"]["value"] == "100" and status["baseline"]["state"] == "active"
    assert client.get(f"/api/monitors/{monitor_id}/reading/baseline/events").json()["events"][0]["action"] == "reset"


def test_force_is_required_when_far_from_raw_candidate(client, monitor_id, monkeypatch):
    stabilizer = ReadingStabilizer(ReadingSettings.from_dict(READING))
    stabilizer.last_candidate = {"value": "265754", "agreement_count": 3}
    monkeypatch.setattr(svc, "_live_stabilizer", lambda _id: stabilizer)
    base = f"/api/monitors/{monitor_id}/reading/baseline/rebase"
    far = client.post(base, json={"value": "265800", "reason": "r", "operator": "o"})
    assert far.status_code == 409 and far.json()["detail"]["code"] == "FORCE_REQUIRED" and far.json()["detail"]["candidate"] == "265754"
    assert _events(monitor_id) == []
    assert client.post(base, json={"value": "265755", "reason": "r", "operator": "o"}).status_code == 200  # 許容範囲内
    assert client.post(base, json={"value": "265800", "reason": "r", "operator": "o", "force": True}).status_code == 200
    assert stabilizer.baseline_snapshot()["value"] == "265800" and stabilizer.epoch == 2  # 稼働中のStabilizerへ反映される


def test_events_survive_monitor_deletion(client):
    name = "t_bl_del_" + uuid.uuid4().hex[:6]
    mid = client.post("/api/monitors", json={"name": name, "display_name": name}).json()["id"]
    client.patch(f"/api/monitors/{mid}", json={"inference": {"method": "object_detection", "reading": READING}})
    assert client.post(f"/api/monitors/{mid}/reading/baseline/reset", json={"reason": "r", "operator": "o"}).status_code == 200
    assert client.delete(f"/api/monitors/{mid}").status_code == 204
    # 削除後はmonitor_idだけで検索する(IDは再利用され得るため、monitor_nameのスナップショットで区別できる)。
    events = [e for e in client.get(f"/api/monitors/{mid}/reading/baseline/events").json()["events"] if e["monitor_name"] == name]
    assert len(events) == 1 and events[0]["action"] == "reset"


def test_legacy_strip_leading_zero_in_request_is_ignored(client, monitor_id):
    res = client.patch(f"/api/monitors/{monitor_id}", json={"inference": {"method": "object_detection", "reading": {**READING, "strip_leading_zero": True}}})
    assert res.status_code == 200, res.text
    assert "strip_leading_zero" not in res.json()["inference"]["reading"]


# --- 結合: Scheduler再構築/Backend再起動をまたいだbaselineと、固着の復旧 ---

def _scheduler(monitor_id, tmp_path):
    return InferenceScheduler(monitor_id, LatestFrameBuffer(), {"reading": READING}, model_registry, tmp_path,
                              lambda _id, _result: None, svc.restore_baseline)


def _tick(scheduler, monitor_id, value, second):
    confirmed = scheduler.stabilizer.update(InferenceResult(value=value, confidence=0.9, engine="mock", timestamp=datetime.now(timezone.utc) + timedelta(seconds=second)))
    save_result(monitor_id, confirmed)
    return confirmed


def test_stuck_baseline_is_visible_survives_rebuild_and_is_fixed_by_rebase(client, monitor_id, tmp_path, monkeypatch):
    # 誤値265759が確定 -> baselineとして永続化
    first = _scheduler(monitor_id, tmp_path)
    for i in range(3):
        _tick(first, monitor_id, "0265759", i)
    # Backend再起動/Scheduler再構築: baselineが復元される(従来はここで空になっていた)
    second = _scheduler(monitor_id, tmp_path)
    assert second.stabilizer.baseline_snapshot()["value"] == "265759"
    # 正しい値265754が合意されても decrease_detected で棄却され、固着する
    result = None
    for i in range(3):
        result = _tick(second, monitor_id, "0265754", 10 + i)
    assert result.validation_status == CandidateStatus.DECREASE_DETECTED and result.value == "265759"
    assert second.stabilizer.conflict.candidate == "265754"
    # さらに再構築しても固着は自然には解消しない(baselineが復元される)
    third = _scheduler(monitor_id, tmp_path)
    assert third.stabilizer.baseline_snapshot()["value"] == "265759"
    # 運用者がrebase -> 即解消。表示値は次のConfirmedで自然に更新される
    monkeypatch.setattr(svc, "_live_stabilizer", lambda _id: third.stabilizer)
    res = client.post(f"/api/monitors/{monitor_id}/reading/baseline/rebase", json={"value": "265754", "reason": "実表示は0265754", "operator": "o"})
    assert res.status_code == 200, res.text
    assert client.get(f"/api/monitors/{monitor_id}").json()["current_value"] == "265759"
    for i in range(3):
        result = _tick(third, monitor_id, "0265754", 20 + i)
    assert result.validation_status == CandidateStatus.CONFIRMED
    after = client.get(f"/api/monitors/{monitor_id}").json()
    assert after["current_value"] == "265754" and after["reading_baseline"]["value"] == "265754"
    # reset: 次の正常なConfirmedが新しいbaselineになる
    assert client.post(f"/api/monitors/{monitor_id}/reading/baseline/reset", json={"reason": "メーター交換", "operator": "o"}).status_code == 200
    fourth = _scheduler(monitor_id, tmp_path)
    assert fourth.stabilizer.baseline_snapshot() is None
    monkeypatch.setattr(svc, "_live_stabilizer", lambda _id: fourth.stabilizer)
    for i in range(3):
        _tick(fourth, monitor_id, "0000100", 30 + i)
    db = SessionLocal()
    try:
        row = _row(db, monitor_id)
        assert (row.value, row.state) == ("100", "active")
    finally:
        db.close()


def test_existing_monitor_without_baseline_row_behaves_as_before(monitor_id, tmp_path):
    scheduler = _scheduler(monitor_id, tmp_path)
    assert scheduler.stabilizer.baseline_snapshot() is None and scheduler.stabilizer.epoch == 0
    for i in range(3):
        result = _tick(scheduler, monitor_id, "0265754", i)
    assert result.validation_status == CandidateStatus.CONFIRMED
    db = SessionLocal()
    try:
        assert _row(db, monitor_id).value == "265754"  # 最初のCONFIRMEDで初回baselineが作られる
    finally:
        db.close()
