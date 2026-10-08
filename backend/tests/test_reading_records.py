"""1時間ごとの正式な計測記録(reading_records)の作成・usage計算・APIのテスト(UI再設計 Phase 1)。

テストは一時DB(conftest)で動くため、実運用のDBや実カメラには触れない。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.core.database import SessionLocal
from app.main import app
from app.models import (InferenceSettings, LatestResult, Monitor, ReadingBaseline, ReadingBaselineEvent, ReadingRecord,
                        VideoSource)
from app.services import reading_record_service as svc
from app.services import storage_settings_service as storage
from app.services.csv_export_service import JST
from runtime.hourly_record_worker import HourlyRecordWorker, hourly_record_worker

pytestmark = pytest.mark.integration


def jst(hour: int, minute: int = 0, second: int = 0, day: int = 8) -> datetime:
    return datetime(2026, 10, day, hour, minute, second, tzinfo=JST).astimezone(timezone.utc)


@pytest.fixture
def db():
    session = SessionLocal()
    created: list[int] = []
    session.info["created"] = created
    # 画像保存はtest_record_images.pyで検証する。ここでは画像保存を無効にして、計測値の記録だけを検証する。
    storage.update(session, save_original_image=False, save_overlay_image=False)
    yield session
    storage.update(session, save_original_image=True, save_overlay_image=True)
    session.rollback()
    for monitor_id in created:
        monitor = session.get(Monitor, monitor_id)
        if monitor is not None:
            session.delete(monitor)
        session.execute(delete(ReadingRecord).where(ReadingRecord.monitor_id == monitor_id))
        session.execute(delete(ReadingBaselineEvent).where(ReadingBaselineEvent.monitor_id == monitor_id))
    session.commit()
    session.close()


def make_monitor(db, status="running", inference_status="ok", value="265754", confidence=0.95, enabled=True, with_source=True,
                 display_name=None, engine="cpp_onnx", model_id="digital_production_v1.onnx") -> Monitor:
    name = "t_rec_" + uuid.uuid4().hex[:8]
    # 記録の時刻はテスト内で固定(2026-10-08)のため、Monitorの作成時刻はそれより前にする(作成時刻以降の記録だけを対象にする規則のため)。
    monitor = Monitor(name=name, display_name=display_name or f"表示名{name[-4:]}", enabled=enabled, status=status, created_at=datetime(2026, 10, 1))
    monitor.inference = InferenceSettings(engine=engine, model_id=model_id)
    monitor.latest_result = LatestResult(value=value, confidence=confidence, status=inference_status, engine=engine)
    if with_source:
        monitor.source = VideoSource(source_type="url", url="http://example.invalid/x")
    db.add(monitor)
    db.commit()
    db.info["created"].append(monitor.id)
    return monitor


def set_latest(db, monitor, **kw):
    latest = db.get(LatestResult, monitor.latest_result.id)
    for key, val in kw.items():
        setattr(latest, key, val)
    db.commit()
    db.refresh(monitor)


def records_of(db, monitor_id):
    db.expire_all()
    return list(db.scalars(select(ReadingRecord).where(ReadingRecord.monitor_id == monitor_id).order_by(ReadingRecord.hour_bucket)).all())


# --- 計測枠ごとに1件 ---

def test_record_due_creates_one_record_per_enabled_monitor_with_source(db):
    ok = make_monitor(db, value="265754", confidence=0.95)
    make_monitor(db, enabled=False)
    make_monitor(db, with_source=False)
    outcomes = svc.record_due(db, jst(14, 0, 5))
    mine = [o for o in outcomes if o.monitor_id == ok.id]
    assert [o.status for o in mine] == ["created"]
    record = records_of(db, ok.id)[0]
    assert record.hour_bucket == "2026-10-08T14:00:00+09:00"  # 毎時00分の計測枠(JST)
    assert record.recorded_at == datetime(2026, 10, 8, 5, 0, 5)  # 実際の記録時刻(naive UTC)
    assert (record.value, record.numeric_value, record.display_status, record.baseline_conflict) == ("265754", "265754", "normal", False)
    assert (record.previous_value, record.usage) == (None, None)
    assert record.confidence == 0.95 and record.engine == "cpp_onnx" and record.model_id == "digital_production_v1.onnx"
    assert record.monitor_name == ok.display_name  # 記録時点の表示名のスナップショット
    assert (record.original_image_path, record.overlay_image_path, record.image_status) == (None, None, "disabled")  # 画像保存が無効の場合
    assert record.value_source == "confirmed"


def test_disabled_and_sourceless_monitors_are_skipped(db):
    disabled = make_monitor(db, enabled=False)
    sourceless = make_monitor(db, with_source=False)
    svc.record_due(db, jst(14, 0, 5))
    assert records_of(db, disabled.id) == [] and records_of(db, sourceless.id) == []


def test_record_due_is_idempotent_within_an_hour(db):
    monitor = make_monitor(db)
    svc.record_due(db, jst(14, 0, 5))
    svc.record_due(db, jst(14, 0, 40))
    svc.record_due(db, jst(14, 5, 0))
    assert len(records_of(db, monitor.id)) == 1


def test_late_records_after_grace_period_are_not_created(db):
    monitor = make_monitor(db)
    assert [o for o in svc.record_due(db, jst(14, 12, 0)) if o.monitor_id == monitor.id] == []
    assert records_of(db, monitor.id) == []


def test_record_can_be_created_late_within_grace_period(db):
    monitor = make_monitor(db)
    svc.record_due(db, jst(14, 4, 0))  # Backend再起動後など、毎時00分より少し遅れた場合
    record = records_of(db, monitor.id)[0]
    assert record.hour_bucket == "2026-10-08T14:00:00+09:00" and record.recorded_at == datetime(2026, 10, 8, 5, 4, 0)


def test_feature_can_be_disabled(db):
    monitor = make_monitor(db)
    svc.set_hourly_records_enabled(db, False)
    try:
        assert svc.record_due(db, jst(14, 0, 5)) == []
        assert records_of(db, monitor.id) == []
    finally:
        svc.set_hourly_records_enabled(db, True)
    assert svc.hourly_records_enabled(db) is True


# --- 状態ごとの記録 ---

@pytest.mark.parametrize("monitor_status,inference_status,expected", [
    ("running", "ok", "normal"), ("running", "pending", "normal"), ("running", "low_confidence", "warning"),
    ("running", "read_error", "read_error"), ("error", "ok", "error"), ("stopped", "ok", "stopped"), ("connecting", "ok", "connecting"),
])
def test_display_status_matches_the_frontend_rule(monitor_status, inference_status, expected):
    assert svc.display_status(monitor_status, inference_status) == expected


def test_unhealthy_monitor_waits_then_records_without_value(db):
    monitor = make_monitor(db, status="error", value="265754")
    started = jst(14, 0, 0)
    waiting = svc.record_due(db, jst(14, 0, 30), started_at=started)
    assert [o.status for o in waiting if o.monitor_id == monitor.id] == ["waiting"]  # 立ち上がりを待つ
    assert records_of(db, monitor.id) == []
    svc.record_due(db, jst(14, 3, 0), started_at=started)
    record = records_of(db, monitor.id)[0]
    assert (record.value, record.numeric_value, record.confidence, record.display_status, record.usage) == (None, None, None, "error", None)


def test_read_error_keeps_the_last_confirmed_value_as_carried_forward(db):
    # 読取不能(no_reading)でも、映像が稼働していれば直前の正常Confirmed値を保持して記録する。usageは従来どおりnull
    monitor = make_monitor(db, inference_status="read_error", value="265754")
    svc.record_due(db, jst(14, 3, 0), started_at=jst(13, 0, 0))
    record = records_of(db, monitor.id)[0]
    assert (record.value, record.value_source, record.display_status, record.usage) == ("265754", "carried_forward", "read_error", None)


def test_no_value_source_when_there_is_no_confirmed_value(db):
    monitor = make_monitor(db, value=None, inference_status="pending")
    svc.record_due(db, jst(14, 3, 0), started_at=jst(13, 0, 0))
    record = records_of(db, monitor.id)[0]
    assert (record.value, record.value_source) == (None, "none")


@pytest.mark.parametrize("validation,source", [
    ("confirmed", "confirmed"), ("low_confidence", "confirmed"),
    ("pending", "carried_forward"), ("invalid_format", "carried_forward"), ("decrease_detected", "carried_forward"),
    ("rate_exceeded", "carried_forward"), ("no_reading", "carried_forward"),
])
def test_value_source_follows_the_latest_validation_status(db, monkeypatch, validation, source):
    monitor = make_monitor(db, value="372413.8")
    monkeypatch.setattr(svc, "_live_raw_and_validation", lambda _id: ("372413.0", validation))
    svc.record_due(db, jst(14, 0, 5))
    record = records_of(db, monitor.id)[0]
    assert (record.value, record.raw_value, record.validation_status, record.value_source) == ("372413.8", "372413.0", validation, source)


def test_carried_forward_keeps_usage_calculation_when_the_series_is_continuous(db, monkeypatch):
    monitor = make_monitor(db, value="372412.4")
    svc.record_due(db, jst(14, 0, 5))
    set_latest(db, monitor, value="372413.8")
    monkeypatch.setattr(svc, "_live_raw_and_validation", lambda _id: ("372413.0", "decrease_detected"))  # 回転途中でRawが棄却されている
    svc.record_due(db, jst(15, 0, 5))
    second = records_of(db, monitor.id)[1]
    assert (second.value, second.value_source, second.previous_value, second.usage) == ("372413.8", "carried_forward", "372412.4", "1.4")


def test_backfill_value_source_sets_the_origin_of_existing_records():
    from sqlalchemy import create_engine, text
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE reading_records (id INTEGER PRIMARY KEY, value TEXT, validation_status TEXT, value_source TEXT DEFAULT 'none')"))
        connection.execute(text("INSERT INTO reading_records (id, value, validation_status) VALUES (1,'1','confirmed'),(2,'2','low_confidence'),(3,'3','invalid_format'),(4,NULL,NULL),(5,'5',NULL)"))
        svc.backfill_value_source(connection)
        rows = dict(connection.execute(text("SELECT id, value_source FROM reading_records")).all())
    assert rows == {1: "confirmed", 2: "confirmed", 3: "carried_forward", 4: "none", 5: "carried_forward"}


def test_low_confidence_is_recorded_as_warning(db):
    monitor = make_monitor(db, inference_status="low_confidence", confidence=0.4)
    svc.record_due(db, jst(14, 0, 5))
    record = records_of(db, monitor.id)[0]
    assert (record.value, record.display_status, record.validation_status, record.confidence) == ("265754", "warning", "low_confidence", 0.4)


# --- usage(使用量) ---

def test_usage_is_the_difference_from_the_previous_hourly_value(db):
    monitor = make_monitor(db, value="372411.9")
    svc.record_due(db, jst(14, 0, 5))
    set_latest(db, monitor, value="372412.4")
    svc.record_due(db, jst(15, 0, 5))
    first, second = records_of(db, monitor.id)
    assert (first.previous_value, first.usage) == (None, None)
    assert (second.previous_value, second.usage) == ("372411.9", "0.5")
    set_latest(db, monitor, value="372412.4")
    svc.record_due(db, jst(16, 0, 5))
    assert records_of(db, monitor.id)[2].usage == "0.0"  # 変化なしは0(欠損ではない)


def test_usage_is_null_without_a_previous_hour_record(db):
    monitor = make_monitor(db, value="265754")
    svc.record_due(db, jst(14, 0, 5))
    svc.record_due(db, jst(16, 0, 5))  # 15時の記録が無い(欠損)
    first, second = records_of(db, monitor.id)
    assert (second.previous_value, second.usage) == (None, None)


def test_usage_is_null_when_the_value_decreased(db):
    monitor = make_monitor(db, value="265759")
    svc.record_due(db, jst(14, 0, 5))
    set_latest(db, monitor, value="265754")
    svc.record_due(db, jst(15, 0, 5))
    second = records_of(db, monitor.id)[1]
    assert (second.previous_value, second.usage) == ("265759", None)


@pytest.mark.parametrize("action", ["reset", "rebase", "auto_semantic_reset"])
def test_usage_is_null_across_a_baseline_reset_or_rebase(db, action):
    monitor = make_monitor(db, value="265754")
    svc.record_due(db, jst(14, 0, 5))
    db.add(ReadingBaselineEvent(monitor_id=monitor.id, monitor_name=monitor.name, action=action, reason="t", operator="o",
                                occurred_at=datetime(2026, 10, 8, 5, 30, 0)))  # 14:30 JST(前回の記録以降)
    db.commit()
    set_latest(db, monitor, value="265760")
    svc.record_due(db, jst(15, 0, 5))
    second = records_of(db, monitor.id)[1]
    assert (second.previous_value, second.usage) == ("265754", None)


def test_baseline_event_before_the_previous_record_does_not_block_usage(db):
    monitor = make_monitor(db, value="265754")
    db.add(ReadingBaselineEvent(monitor_id=monitor.id, monitor_name=monitor.name, action="rebase", reason="t", operator="o",
                                occurred_at=datetime(2026, 10, 8, 4, 30, 0)))  # 13:30 JST(前回の記録より前)
    db.commit()
    svc.record_due(db, jst(14, 0, 5))
    set_latest(db, monitor, value="265760")
    svc.record_due(db, jst(15, 0, 5))
    assert records_of(db, monitor.id)[1].usage == "6"


def test_usage_is_null_when_either_hour_has_a_baseline_conflict(db):
    monitor = make_monitor(db, value="265759")
    svc.record_due(db, jst(14, 0, 5))
    now = datetime.utcnow()
    db.add(ReadingBaseline(monitor_id=monitor.id, value="265759", numeric_value="265759", state="active", epoch=0, conflict_status="decrease_detected",
                           conflict_candidate="265754", conflict_count=900, conflict_started_at=now - timedelta(minutes=30), conflict_last_at=now))
    db.commit()
    set_latest(db, monitor, value="265760")
    svc.record_due(db, jst(15, 0, 5))
    second = records_of(db, monitor.id)[1]
    assert second.baseline_conflict is True and second.usage is None


def test_usage_is_null_when_the_previous_hour_was_not_normal(db):
    monitor = make_monitor(db, status="error", value="265754")
    svc.record_due(db, jst(14, 3, 0), started_at=jst(13, 0, 0))  # 値なしの記録
    db_monitor = db.get(Monitor, monitor.id)
    db_monitor.status = "running"
    db.commit()
    svc.record_due(db, jst(15, 0, 5))
    second = records_of(db, monitor.id)[1]
    assert (second.value, second.previous_value, second.usage) == ("265754", None, None)


# --- Worker ---

def test_worker_tick_creates_records(db):
    monitor = make_monitor(db)
    worker = HourlyRecordWorker()
    outcomes = worker.tick(jst(14, 0, 5))
    assert any(o.monitor_id == monitor.id and o.status == "created" for o in outcomes)
    assert worker.last_error is None and worker.last_tick_at is not None


# --- API ---

@pytest.fixture
def client(monkeypatch):
    # lifespanのBackground Workerが、テストの実時刻の計測枠でも記録を作ってしまい、件数の検証が
    # 実行時刻(毎時00〜10分)に依存して不安定になるため、このテストではWorkerを起動しない。
    monkeypatch.setattr(hourly_record_worker, "start", lambda: None)
    with TestClient(app) as c:
        yield c


def test_records_api_lists_filters_and_paginates(client, db):
    a, b = make_monitor(db, value="100"), make_monitor(db, value="200")
    for hour in (13, 14, 15):
        svc.record_due(db, jst(hour, 0, 5))
    res = client.get("/api/records", params={"monitor_id": [a.id]})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] == 3 and [i["monitor_id"] for i in body["items"]] == [a.id] * 3
    assert [i["hour_bucket"][11:13] for i in body["items"]] == ["15", "14", "13"]  # 新しい順
    assert body["items"][0]["recorded_at"].endswith("Z")
    both = client.get("/api/records", params={"monitor_id": [a.id, b.id]}).json()
    assert both["total"] == 6
    page = client.get("/api/records", params={"monitor_id": [a.id], "limit": 2, "offset": 2}).json()
    assert page["total"] == 3 and len(page["items"]) == 1
    period = client.get("/api/records", params={"monitor_id": [a.id], "from": "2026-10-08T14:00:00", "to": "2026-10-08T15:00:00"}).json()  # 時刻はJST
    assert [i["hour_bucket"][11:13] for i in period["items"]] == ["14"]
    assert client.get("/api/records", params={"from": "not-a-date"}).status_code == 422
    assert client.get("/api/records", params={"limit": 0}).status_code == 422


def test_records_api_get_one_and_404(client, db):
    monitor = make_monitor(db, value="372412.4")
    svc.record_due(db, jst(14, 0, 5))
    record_id = records_of(db, monitor.id)[0].id
    res = client.get(f"/api/records/{record_id}")
    assert res.status_code == 200 and res.json()["value"] == "372412.4"
    assert client.get("/api/records/99999999").status_code == 404


def test_records_survive_monitor_deletion_and_are_hidden_from_a_reused_id(client, db):
    monitor = make_monitor(db, value="265754")
    svc.record_due(db, jst(14, 0, 5))
    monitor_id = monitor.id
    assert client.delete(f"/api/monitors/{monitor_id}").status_code == 204
    assert client.get("/api/records", params={"monitor_id": [monitor_id]}).json()["total"] == 1  # 削除後も証跡として残る
    created = client.post("/api/monitors", json={"name": "t_rec_reuse_" + uuid.uuid4().hex[:5], "display_name": "再利用"})
    new_id = created.json()["id"]
    try:
        if new_id == monitor_id:  # SQLiteがIDを再利用した場合、新しいMonitorには旧Monitorの記録を出さない
            assert client.get("/api/records", params={"monitor_id": [new_id]}).json()["total"] == 0
    finally:
        client.delete(f"/api/monitors/{new_id}")


def test_records_settings_api(client):
    assert client.get("/api/records/status").json()["enabled"] is True
    assert client.put("/api/records/settings", json={"enabled": False}).json() == {"enabled": False}
    assert client.get("/api/records/status").json()["enabled"] is False
    assert client.put("/api/records/settings", json={"enabled": True}).json() == {"enabled": True}
