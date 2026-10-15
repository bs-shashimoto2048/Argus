"""毎時記録のsnapshot選択(Issue #77)。計測枠の基準時刻に最も近い「Rawと正式値が一致する正常snapshot」を使う。

実カメラ・実モデル・実運用DBは使わない(偽のEngine/フレーム/一時DBのみ)。
"""
from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

import cv2
import numpy as np
import pytest
from sqlalchemy import delete, select

from app.core.database import SessionLocal
from app.inference.base import Detection, InferenceResult
from app.models import InferenceSettings, LatestResult, Monitor, ReadingBaselineEvent, ReadingRecord, VideoSource
from app.services import reading_record_service as svc
from app.services import storage_settings_service as storage
from app.services.csv_export_service import JST
from runtime import inference_scheduler as scheduler_module
from runtime.hourly_record_worker import HourlyRecordWorker
from runtime.inference_scheduler import InferenceScheduler
from runtime.record_snapshot import InferenceRecordSnapshot, record_grade, select_record_snapshot

pytestmark = pytest.mark.integration

BUCKET = datetime(2026, 10, 15, 8, 0, 0, tzinfo=JST).astimezone(timezone.utc)  # 08:00 JST


def snap(offset: float, status="confirmed", raw="0216044", candidate="216044", matches=None, tick=None, **over) -> InferenceRecordSnapshot:
    """基準時刻(08:00:00 JST)からoffset秒のtickのsnapshot。"""
    at = BUCKET + timedelta(seconds=offset)
    accepted = status in ("confirmed", "low_confidence")
    base = dict(
        monitor_id=1, tick=tick if tick is not None else int((offset + 100) * 10), inference_at=at, captured_at=at,
        original_jpeg=f"ORIG@{offset}".encode(), overlay_jpeg=f"OVER@{offset}".encode(),
        raw_value=raw, raw_confidence=0.9, raw_error=None, detection_count=len(raw or ""),
        validation_status=status, candidate_value=candidate, agreement_count=3, raw_count=5,
        confirmed_value="216044" if accepted else "216025", confirmed_confidence=0.88, confirmed_at=at, inference_status="ok",
        engine="cpp_onnx", model_id="m.onnx", processing_time_ms=40.0,
        baseline_value=None, baseline_epoch=0, baseline_conflict=False, conflict_status=None, conflict_candidate=None, conflict_count=0,
        raw_matches_candidate=(accepted if matches is None else matches),
    )
    base.update(over)
    return InferenceRecordSnapshot(**base)


# ===================== 選択ルール(pure) =====================

def test_transient_invalid_format_between_two_good_ticks_is_not_chosen():
    # 07:59:59 confirmed / 08:00:00 invalid_format(最新Rawは6桁) / 08:00:01 confirmed
    ring = [snap(-1, raw="0216044"), snap(0, status="invalid_format", raw="021644", matches=False), snap(1, raw="0216044")]
    chosen = select_record_snapshot(ring, BUCKET)
    assert chosen.raw_value == "0216044" and chosen.validation_status == "confirmed"
    assert abs((chosen.inference_at - BUCKET).total_seconds()) == 1


def test_confirmed_by_vote_but_raw_disagrees_is_not_preferred_over_matching_tick():
    # 実record(id 224)の型: 最新Rawは6桁(021644)だが多数決で0216044がconfirmed。近い方でも、Rawが一致するtickを優先する。
    ring = [snap(-4, raw="0216044"), snap(0, raw="021644", matches=False), snap(3, raw="0216044")]
    chosen = select_record_snapshot(ring, BUCKET)
    assert chosen.raw_value == "0216044"
    assert abs((chosen.inference_at - BUCKET).total_seconds()) == 3


def test_nearest_matching_confirmed_wins_and_ties_go_to_the_earlier_tick():
    ring = [snap(-6), snap(-2), snap(2), snap(8)]
    assert select_record_snapshot(ring, BUCKET).inference_at == BUCKET - timedelta(seconds=2)


def test_confirmed_is_preferred_over_a_nearer_low_confidence():
    ring = [snap(0, status="low_confidence"), snap(5, status="confirmed")]
    assert select_record_snapshot(ring, BUCKET).validation_status == "confirmed"


def test_low_confidence_is_used_when_there_is_no_confirmed():
    ring = [snap(-3, status="invalid_format", raw="021644", matches=False), snap(2, status="low_confidence"), snap(4, status="pending", raw=None, candidate=None, matches=False)]
    chosen = select_record_snapshot(ring, BUCKET)
    assert chosen.validation_status == "low_confidence" and chosen.inference_at == BUCKET + timedelta(seconds=2)


def test_confirmed_with_disagreeing_raw_is_never_a_normal_candidate():
    # 業務仕様: Raw/画像/candidate/validationが一致するtickだけを正常採用する。多数決でconfirmedでも、そのtickのRawが食い違えば対象外(近さより合格が先)。
    mismatch = snap(-1, raw="021644", candidate="216044", matches=False)  # id 224型(Rawは6桁、多数決は7桁)
    assert mismatch.validation_status == "confirmed" and record_grade(mismatch) is None
    assert select_record_snapshot([mismatch, snap(1, status="invalid_format", raw="021644", matches=False)], BUCKET) is None


def test_case_a_matching_confirmed_is_adopted():
    chosen = select_record_snapshot([snap(0, raw="0216044", candidate="216044", matches=True)], BUCKET)
    assert chosen is not None and record_grade(chosen) == 0


def test_case_c_invalid_format_is_not_adopted():
    assert select_record_snapshot([snap(0, status="invalid_format", raw="0216025", candidate="21625", matches=False)], BUCKET) is None


def test_case_d_matching_snapshot_8s_away_beats_a_nearer_mismatching_confirmed():
    ring = [snap(1, raw="021644", candidate="216044", matches=False), snap(-8, raw="0216044", candidate="216044", matches=True)]
    chosen = select_record_snapshot(ring, BUCKET)
    assert chosen.raw_value == "0216044" and chosen.inference_at == BUCKET - timedelta(seconds=8)


def test_case_e_matching_low_confidence_beats_a_nearer_mismatching_confirmed():
    ring = [snap(1, raw="021644", candidate="216044", matches=False), snap(3, status="low_confidence", raw="0216044", candidate="216044", matches=True)]
    chosen = select_record_snapshot(ring, BUCKET)
    assert chosen.validation_status == "low_confidence" and chosen.inference_at == BUCKET + timedelta(seconds=3)


def test_no_acceptable_snapshot_in_range_returns_none():
    # 07:59:55 〜 08:00:10 がすべて invalid_format → None(呼び出し側が従来の安全側へ進む)
    ring = [snap(o, status="invalid_format", raw="021625", candidate="21625", matches=False) for o in (-5, -2, 0, 3, 7, 10)]
    assert select_record_snapshot(ring, BUCKET) is None


def test_snapshots_outside_the_range_are_ignored():
    ring = [snap(-10.5), snap(10.5)]
    assert select_record_snapshot(ring, BUCKET) is None
    assert select_record_snapshot([snap(-10), snap(10)], BUCKET) is not None  # 境界(±10秒)は範囲内


# ===================== Scheduler: snapshotのRaw一致判定とリングバッファ =====================

class _Buffer:
    def __init__(self) -> None:
        self.tick = 0
        self.lock = threading.Lock()

    def get(self):
        with self.lock:
            self.tick += 1
            ok, encoded = cv2.imencode(".jpg", np.full((48, 96, 3), 40 + self.tick % 150, dtype=np.uint8))
            return encoded.tobytes(), time.time()


class _Engine:
    def __init__(self, buffer: _Buffer, values: list[str]) -> None:
        self.buffer, self.values = buffer, values

    def infer(self, image, settings):
        value = self.values[min(self.buffer.tick - 1, len(self.values) - 1)]
        detections = [Detection(class_name=value[i], confidence=0.9, bbox=(4.0 + i * 11, 6.0, 12.0 + i * 11, 40.0)) for i in range(len(value))]
        return InferenceResult(value=value, confidence=0.9, detections=detections, engine="cpp_onnx", model_id="fake.onnx")


def make_scheduler(monkeypatch, values: list[str]):
    buffer = _Buffer()
    monkeypatch.setattr(scheduler_module, "create_engine", lambda settings, registry, root: _Engine(buffer, values))
    settings = {"inference_fps": 5, "method": "object_detection", "engine": "cpp_onnx", "model_id": "fake.onnx", "roi": {"x": 0, "y": 0, "width": 1, "height": 1},
                "reading": {"enabled": True, "window_size": 5, "required_matches": 3, "min_confidence": 0.0, "monotonic": False, "expected_digits": 7, "decimal_position": 0}}
    return InferenceScheduler(1, buffer, settings, object(), None, lambda monitor_id, confirmed: None), buffer


def run_ticks(scheduler, count):
    snapshots = []
    for _ in range(count):
        scheduler._infer_latest()
        snapshots.append(scheduler.get_record_snapshot())
    return snapshots


def test_raw_matches_candidate_flag_reflects_the_single_tick_raw(monkeypatch):
    # 実record id 224の型: 多数決は0216044(7桁)でconfirmedだが、ある1tickのRawだけ6桁(021644)
    values = ["0216044"] * 4 + ["021644"] + ["0216044"] * 3
    scheduler, _ = make_scheduler(monkeypatch, values)
    snaps = run_ticks(scheduler, len(values))
    by_raw = {}
    for s in snaps:
        by_raw.setdefault((s.raw_value, s.validation_status), []).append(s.raw_matches_candidate)
    assert by_raw[("021644", "confirmed")] == [False]  # 6桁Rawは、多数決でconfirmedでもRaw不一致
    assert all(by_raw[("0216044", "confirmed")])  # 7桁のRawは、候補と一致


def test_invalid_format_by_vote_is_not_marked_as_matching(monkeypatch):
    # 実record id 203の型: 最新Rawは7桁(0216025)だが、窓内の多数決が6桁(021625) → invalid_format
    values = ["021625"] * 3 + ["0216025"] * 2
    scheduler, _ = make_scheduler(monkeypatch, values)
    last = run_ticks(scheduler, len(values))[-1]
    assert (last.raw_value, last.validation_status, last.raw_matches_candidate) == ("0216025", "invalid_format", False)
    assert record_grade(last) is None


def test_scheduler_ring_selects_nearest_matching_snapshot_and_thins_ticks(monkeypatch):
    scheduler, _ = make_scheduler(monkeypatch, ["0216044"])
    for offset in (-12, -1.0, -0.9, 0.0, 0.1, 0.4, 1.0):  # 0.5秒未満の間隔のtickは間引かれる
        scheduler._publish_snapshot(snap(offset))
    ring_offsets = [(s.inference_at - BUCKET).total_seconds() for s in scheduler._ring]
    assert ring_offsets == [-12.0, -1.0, 0.0, 1.0]  # -12は保持期間(30秒)内で残る。-0.9/0.1/0.4は直前から0.5秒未満なので間引かれる
    # 異常tickは、間隔内に来た正常tickに押し出されない
    scheduler._publish_snapshot(snap(5.0))
    scheduler._publish_snapshot(snap(5.1, status="invalid_format", raw="021644", matches=False))
    assert scheduler.select_record_snapshot(BUCKET + timedelta(seconds=5)).inference_at == BUCKET + timedelta(seconds=5)
    scheduler._publish_snapshot(snap(60.0))
    assert all((BUCKET + timedelta(seconds=60) - s.inference_at).total_seconds() <= 30 for s in scheduler._ring)  # 古いものは落ちる


# ===================== 記録の作成(record_due) =====================

class FakeSelectingScheduler:
    def __init__(self, ring, latest):
        self.ring = list(ring)
        self.latest = latest
        self.latest_overlay = b"OTHER-TICK-OVERLAY"
        self.latest_overlay_source = b"OTHER-TICK-FRAME"
        self.latest_confirmed = None
        self.selected_for = []

    def get_record_snapshot(self):
        return self.latest

    def select_record_snapshot(self, target):
        self.selected_for.append(target)
        return select_record_snapshot(self.ring, target)


class FakeBuffer:
    def age(self):
        return 0.5

    def get(self):
        return b"LIVE-FRAME", time.time()


class FakeRuntime:
    def __init__(self, scheduler):
        self.inference_scheduler = scheduler
        self.buffer = FakeBuffer()


class RecordingWriter:
    def __init__(self):
        self.jobs = []

    def submit(self, job):
        self.jobs.append(job)
        return True


@pytest.fixture
def db():
    session = SessionLocal()
    session.info["created"] = []
    storage.update(session, save_original_image=True, save_overlay_image=True)
    yield session
    session.rollback()
    for monitor_id in session.info["created"]:
        monitor = session.get(Monitor, monitor_id)
        if monitor is not None:
            session.delete(monitor)
        session.execute(delete(ReadingRecord).where(ReadingRecord.monitor_id == monitor_id))
        session.execute(delete(ReadingBaselineEvent).where(ReadingBaselineEvent.monitor_id == monitor_id))
    session.commit()
    session.close()


def make_monitor(db) -> Monitor:
    name = "t_sel_" + uuid.uuid4().hex[:8]
    monitor = Monitor(name=name, display_name=f"表示名{name[-4:]}", enabled=True, status="running", created_at=datetime(2026, 10, 1))
    monitor.inference = InferenceSettings(engine="cpp_onnx", model_id="db-model")
    monitor.latest_result = LatestResult(value="999999", confidence=0.11, status="ok", engine="db-engine")
    monitor.source = VideoSource(source_type="url", url="http://example.invalid/x")
    db.add(monitor)
    db.commit()
    db.info["created"].append(monitor.id)
    return monitor


def install(monkeypatch, monitor_id, scheduler):
    runtime = FakeRuntime(scheduler)
    monkeypatch.setattr(svc.runtime_manager, "get_runtime", lambda mid: runtime if mid == monitor_id else None)


def only_record(db, monitor) -> ReadingRecord:
    db.expire_all()
    return db.scalars(select(ReadingRecord).where(ReadingRecord.monitor_id == monitor.id)).one()


def test_record_waits_for_the_after_window_then_uses_the_nearest_good_tick(db, monkeypatch):
    monitor = make_monitor(db)
    ring = [snap(-1, raw="0216044"), snap(0, status="invalid_format", raw="021644", matches=False), snap(1, raw="0216044", tick=777)]
    scheduler = FakeSelectingScheduler(ring, latest=ring[1])  # 最新のtickはinvalid_format(従来の経路ならこれが記録されていた)
    install(monkeypatch, monitor.id, scheduler)
    writer = RecordingWriter()
    early = svc.record_due(db, BUCKET + timedelta(seconds=0.5), writer=writer)
    assert [o.status for o in early if o.monitor_id == monitor.id] == ["waiting"]  # 基準時刻直後は、後ろ側の探索範囲が揃うまで待つ
    assert db.scalars(select(ReadingRecord).where(ReadingRecord.monitor_id == monitor.id)).first() is None
    late = svc.record_due(db, BUCKET + timedelta(seconds=11), writer=writer)
    assert [o.status for o in late if o.monitor_id == monitor.id] == ["created"]
    record = only_record(db, monitor)
    assert (record.raw_value, record.validation_status, record.value, record.value_source) == ("0216044", "confirmed", "216044", "confirmed")
    assert record.candidate_value == "216044"
    assert scheduler.selected_for == [BUCKET]  # 探索の基準は計測枠の開始時刻


def test_record_evidence_comes_from_the_single_selected_snapshot(db, monkeypatch):
    monitor = make_monitor(db)
    chosen = snap(-1, raw="0216044", tick=555, raw_confidence=0.9123, confirmed_confidence=0.8712, engine="cpp_onnx", model_id="selected.onnx")
    ring = [chosen, snap(0, status="invalid_format", raw="021644", matches=False), snap(4, raw="0216044", tick=556)]
    scheduler = FakeSelectingScheduler(ring, latest=ring[1])
    install(monkeypatch, monitor.id, scheduler)
    writer = RecordingWriter()
    svc.record_due(db, BUCKET + timedelta(seconds=11), writer=writer)
    record = only_record(db, monitor)
    assert (record.raw_value, record.raw_confidence, record.validation_status, record.candidate_value) == ("0216044", 0.9123, "confirmed", "216044")
    assert (record.value, record.confidence, record.engine, record.model_id) == ("216044", 0.8712, "cpp_onnx", "selected.onnx")
    assert record.inference_at == (chosen.inference_at).replace(tzinfo=None)  # 選んだsnapshotの推論時刻
    (job,) = writer.jobs
    assert (job.original, job.overlay) == (b"ORIG@-1", b"OVER@-1")  # 画像も同じsnapshot(別tickのlatest_overlayでもライブフレームでもない)
    assert svc.serialize(record)["snapshot_consistent"] is True and svc.serialize(record)["candidate_value"] == "216044"


def test_when_no_good_tick_exists_the_record_keeps_the_safe_carried_forward_behavior(db, monkeypatch):
    monitor = make_monitor(db)
    ring = [snap(o, status="invalid_format", raw="021625", candidate="21625", matches=False) for o in (-5, -2, 0, 3, 7, 10)]
    scheduler = FakeSelectingScheduler(ring, latest=ring[-1])
    install(monkeypatch, monitor.id, scheduler)
    svc.record_due(db, BUCKET + timedelta(seconds=10.5), writer=RecordingWriter())  # 最新tick(+10s)は鮮度の範囲内
    record = only_record(db, monitor)
    assert (record.validation_status, record.value_source, record.value, record.raw_value) == ("invalid_format", "carried_forward", "216025", "021625")


def test_case_f_without_a_matching_snapshot_a_mismatching_confirmed_is_never_stored_as_confirmed(db, monkeypatch):
    # ±10秒に、Rawが候補と食い違うconfirmed(id 224型)しか無い。最新snapshotもそれ。fallback経路でもvalue_source=confirmedにしない。
    monitor = make_monitor(db)
    mismatch = [snap(o, raw="021644", candidate="216044", matches=False) for o in (-3, 0, 4, 10)]
    scheduler = FakeSelectingScheduler(mismatch, latest=mismatch[-1])
    assert scheduler.select_record_snapshot(BUCKET) is None
    install(monkeypatch, monitor.id, scheduler)
    svc.record_due(db, BUCKET + timedelta(seconds=10.5), writer=RecordingWriter())
    record = only_record(db, monitor)
    assert record.value_source == "carried_forward" and record.value_source != "confirmed"
    assert (record.raw_value, record.candidate_value) == ("021644", "216044")  # 食い違いは証跡に残る
    assert svc.serialize(record)["correctable"] is True  # 運用者の確認対象になる


def test_fallback_latest_snapshot_that_is_consistent_is_still_confirmed(db, monkeypatch):
    # Schedulerが選択機能を持たない(従来経路)場合でも、Rawが一致するconfirmedは従来どおりconfirmed。
    monitor = make_monitor(db)
    latest = snap(0.2, raw="0216044", candidate="216044", matches=True)

    class LegacyScheduler:
        latest_overlay = latest_overlay_source = latest_confirmed = None

        def get_record_snapshot(self):
            return latest

    install(monkeypatch, monitor.id, LegacyScheduler())
    svc.record_due(db, BUCKET + timedelta(seconds=0.5), writer=RecordingWriter())
    assert only_record(db, monitor).value_source == "confirmed"


def test_low_confidence_only_is_recorded_as_low_confidence(db, monkeypatch):
    monitor = make_monitor(db)
    ring = [snap(-3, status="invalid_format", raw="021644", matches=False), snap(2, status="low_confidence", tick=901)]
    scheduler = FakeSelectingScheduler(ring, latest=ring[0])
    install(monkeypatch, monitor.id, scheduler)
    svc.record_due(db, BUCKET + timedelta(seconds=11), writer=RecordingWriter())
    record = only_record(db, monitor)
    assert (record.validation_status, record.value_source, record.raw_value) == ("low_confidence", "confirmed", "0216044")


def test_one_record_per_monitor_hour_even_with_fast_polling(db, monkeypatch):
    monitor = make_monitor(db)
    ring = [snap(1, raw="0216044")]
    install(monkeypatch, monitor.id, FakeSelectingScheduler(ring, latest=ring[0]))
    for second in (11, 12, 13):
        svc.record_due(db, BUCKET + timedelta(seconds=second), writer=RecordingWriter())
    assert len(db.scalars(select(ReadingRecord).where(ReadingRecord.monitor_id == monitor.id)).all()) == 1


def test_worker_polls_fast_only_right_after_the_hour():
    worker = HourlyRecordWorker(poll_interval_seconds=30.0)
    assert worker._next_wait(BUCKET + timedelta(seconds=3)) == 1.0
    assert worker._next_wait(BUCKET + timedelta(seconds=19)) == 1.0
    assert worker._next_wait(BUCKET + timedelta(seconds=25)) == 30.0
    assert worker._next_wait(BUCKET + timedelta(minutes=30)) == 30.0


def test_passthrough_mode_ticks_are_consistent_so_they_stay_confirmed(monkeypatch):
    # 安定化を無効にした互換モードは多数決の候補が無いが、単発のRawが運用値そのもの。全記録がcarried_forwardにならないこと。
    scheduler, _ = make_scheduler(monkeypatch, ["0216044"])
    scheduler.stabilizer.settings.enabled = False
    last = run_ticks(scheduler, 2)[-1]
    assert (last.validation_status, last.raw_matches_candidate) == ("confirmed", True)
