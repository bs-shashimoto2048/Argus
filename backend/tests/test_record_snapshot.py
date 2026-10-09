"""1推論tick = 1 immutable snapshot と、定時計測recordの証跡の整合性のテスト。

実カメラ・実モデル・実運用DBは使わない(偽のEngine/フレーム/一時DBのみ)。
"""
from __future__ import annotations

import dataclasses
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
from runtime.inference_scheduler import InferenceScheduler
from runtime.record_snapshot import InferenceRecordSnapshot

pytestmark = pytest.mark.integration


# ===================== InferenceScheduler: snapshotの組み立て =====================

def jpeg_with_tick(tick: int) -> bytes:
    """デコードできる小さなJPEGの末尾に、tick番号の印を付ける(どのtickのフレームか判別するため)。"""
    image = np.full((48, 96, 3), 40 + (tick % 150), dtype=np.uint8)
    ok, encoded = cv2.imencode(".jpg", image)
    assert ok
    return encoded.tobytes() + b"|TICK:%d|" % tick


def tick_of(data: bytes | None) -> int | None:
    if not data or b"|TICK:" not in data:
        return None
    return int(data.rsplit(b"|TICK:", 1)[1].split(b"|")[0])


class FakeBuffer:
    """get()のたびに次のtickのフレームを返す(推論ループの1tickに1回呼ばれる)。"""

    def __init__(self) -> None:
        self.tick = 0
        self.lock = threading.Lock()

    def get(self):
        with self.lock:
            self.tick += 1
            return jpeg_with_tick(self.tick), time.time()


class FakeEngine:
    """直前にバッファから取得したtickに対応するRaw(値・信頼度)を返す。"""

    def __init__(self, buffer: FakeBuffer, values=None) -> None:
        self.buffer = buffer
        self.values = values  # tick -> Raw文字列(None: tick番号から生成)

    def infer(self, image, settings):
        tick = self.buffer.tick
        value = self.values(tick) if self.values else f"0215{tick % 1000:03d}"
        confidence = round(0.50 + (tick % 50) / 100, 3)
        detections = [Detection(class_name=value[i], confidence=confidence, bbox=(4.0 + i * 11, 6.0, 12.0 + i * 11, 40.0)) for i in range(len(value))]
        return InferenceResult(value=value, confidence=confidence, detections=detections, engine="cpp_onnx", model_id="fake.onnx")


def make_scheduler(monkeypatch, values=None, fps=5, results=None):
    buffer = FakeBuffer()
    monkeypatch.setattr(scheduler_module, "create_engine", lambda settings, registry, root: FakeEngine(buffer, values))
    settings = {"inference_fps": fps, "method": "object_detection", "engine": "cpp_onnx", "model_id": "fake.onnx", "roi": {"x": 0, "y": 0, "width": 1, "height": 1},
                "reading": {"enabled": True, "window_size": 3, "required_matches": 1, "min_confidence": 0.0, "monotonic": False}}
    log = results if results is not None else []

    def on_result(monitor_id, confirmed):
        log.append((confirmed.raw_value, scheduler.latest_overlay))  # 同じtick(同じスレッド)で、そのtickのoverlayを控える
        return {"value": confirmed.value, "confidence": confirmed.confidence, "confirmed_at": confirmed.confirmed_at, "status": "ok"}

    scheduler = InferenceScheduler(1, buffer, settings, object(), None, on_result)
    return scheduler, buffer, log


def test_snapshot_holds_one_tick_only(monkeypatch):
    scheduler, buffer, log = make_scheduler(monkeypatch)
    assert scheduler.get_record_snapshot() is None  # 推論前はsnapshotなし
    for expected_tick in (1, 2, 3, 4):
        scheduler._infer_latest()
        snap = scheduler.get_record_snapshot()
        assert snap is not None and snap.tick == expected_tick
        # 元画像: そのtickが推論に使ったフレームそのもの
        assert tick_of(snap.original_jpeg) == expected_tick
        # Raw・Raw信頼度: 同じtick
        assert snap.raw_value == f"0215{expected_tick:03d}"
        assert snap.raw_confidence == round(0.50 + (expected_tick % 50) / 100, 3)
        # overlay: そのtickで生成したもの(on_result時点のlatest_overlayと同一。直前tickのものではない)
        assert snap.overlay_jpeg is not None and snap.overlay_jpeg == log[-1][1] == scheduler.latest_overlay
        # 判定・運用値・engine/model・baseline情報も同じtick
        assert snap.validation_status == scheduler.latest_confirmed.validation_status.value
        assert snap.confirmed_value == scheduler.latest_confirmed.value
        assert snap.engine == "cpp_onnx" and snap.model_id == "fake.onnx"
        assert snap.processing_time_ms is not None and snap.processing_time_ms >= 0
        assert snap.inference_at.tzinfo is not None
        assert snap.captured_at is not None and abs((snap.inference_at - snap.captured_at).total_seconds()) < 5
    overlays = {tick_of(scheduler.get_record_snapshot().original_jpeg): scheduler.get_record_snapshot().overlay_jpeg}
    assert len(overlays) == 1


def test_overlay_differs_per_tick_and_matches_the_tick_raw(monkeypatch):
    # tickごとにRawが違えば、overlay画像(bboxの数・位置・ラベル)も違う → 別tickのoverlayが混ざっていないことを確認できる
    scheduler, _buffer, _log = make_scheduler(monkeypatch, values=lambda t: "0215858" if t % 2 else "02158")
    snaps = []
    for _ in range(4):
        scheduler._infer_latest()
        snaps.append(scheduler.get_record_snapshot())
    by_len: dict[int, list[int]] = {}
    for snap in snaps:
        decoded = cv2.imdecode(np.frombuffer(snap.overlay_jpeg, np.uint8), cv2.IMREAD_COLOR)
        by_len.setdefault(len(snap.raw_value), []).append(int((decoded[:, :, 1] > 200).sum()))  # 蛍光緑(bbox)の画素数
    # 桁数(bboxの数)がRawと一致するtickのoverlayのはず: 7桁のtickの方が、5桁のtickより緑の画素が多い
    assert min(by_len[7]) > max(by_len[5])


def test_snapshot_is_immutable_and_replaced_as_a_whole(monkeypatch):
    scheduler, _buffer, _log = make_scheduler(monkeypatch)
    scheduler._infer_latest()
    first = scheduler.get_record_snapshot()
    with pytest.raises(dataclasses.FrozenInstanceError):
        first.raw_value = "tampered"  # type: ignore[misc]
    snapshot_before = dataclasses.asdict(first)
    scheduler._infer_latest()
    second = scheduler.get_record_snapshot()
    assert second is not first and second.tick == first.tick + 1
    assert dataclasses.asdict(first) == snapshot_before  # 取得済みのsnapshotは、次tickが来ても変わらない
    assert scheduler.get_record_snapshot() is second  # 公開されているのは常に完成した1つのsnapshot


def test_failed_tick_snapshot_has_no_overlay_from_another_tick(monkeypatch):
    scheduler, buffer, _log = make_scheduler(monkeypatch)
    scheduler._infer_latest()
    ok = scheduler.get_record_snapshot()
    assert ok.overlay_jpeg is not None

    def boom(image, settings):
        raise RuntimeError("engine crashed")

    scheduler.engine.infer = boom
    scheduler._infer_latest()
    failed = scheduler.get_record_snapshot()
    assert failed.tick == ok.tick + 1
    assert failed.overlay_jpeg is None  # 失敗したtickに、前のtickのoverlayを使わない
    assert tick_of(failed.original_jpeg) == failed.tick  # 元画像は、そのtickが取得したフレーム
    assert failed.raw_error == "INFERENCE_FAILED"


@pytest.mark.parametrize("fps", [5, 15, 30])
def test_no_mixing_between_ticks_while_the_inference_loop_runs(monkeypatch, fps):
    """推論ループが動き続けている間に何度snapshotを取得しても、フィールドが別tickのものと混ざらない(5 FPS以上)。"""
    results: list = []
    scheduler, buffer, _ = make_scheduler(monkeypatch, fps=fps, results=results)
    overlay_by_raw: dict[str, bytes] = {}
    scheduler.on_result = lambda monitor_id, confirmed: (overlay_by_raw.__setitem__(confirmed.raw_value, scheduler.latest_overlay), {"value": confirmed.value, "confidence": confirmed.confidence, "confirmed_at": confirmed.confirmed_at, "status": "ok"})[1]
    scheduler.start()
    seen: dict[int, InferenceRecordSnapshot] = {}
    errors: list[str] = []
    deadline = time.monotonic() + (1.6 if fps >= 15 else 2.4)
    try:
        while time.monotonic() < deadline:
            snap = scheduler.get_record_snapshot()
            if snap is None:
                continue
            tick = snap.tick
            original_tick = tick_of(snap.original_jpeg)
            if original_tick is None or snap.raw_value != f"0215{original_tick % 1000:03d}":
                errors.append(f"raw/original mismatch tick={tick} raw={snap.raw_value} original_tick={original_tick}")
            if snap.raw_confidence != round(0.50 + (original_tick % 50) / 100, 3):
                errors.append(f"raw_confidence mismatch tick={tick}")
            # overlayは、そのRawのtickでon_result時点に控えたものと一致する(別tickのoverlayではない)
            if overlay_by_raw.get(snap.raw_value) != snap.overlay_jpeg:
                errors.append(f"overlay mismatch tick={tick}")
            if snap.confirmed_value is None or snap.validation_status not in ("confirmed", "low_confidence"):
                errors.append(f"status mismatch tick={tick}")
            if tick in seen and dataclasses.asdict(seen[tick]) != dataclasses.asdict(snap):
                errors.append(f"snapshot mutated tick={tick}")
            seen[tick] = snap
    finally:
        scheduler.stop()
    assert not errors, errors[:5]
    assert len(seen) >= 3  # 実際に複数tickを観測した


# ===================== 定時計測record: snapshotから作る =====================

class FakeBufferForRecord:
    def age(self):
        return 0.5

    def get(self):
        return b"LIVE-FRAME-FROM-BUFFER", time.time()


class FakeScheduler:
    """get_record_snapshot()の呼び出し回数を数え、呼ぶたびに(あれば)次のsnapshotへ進める偽のScheduler。"""

    def __init__(self, snapshots):
        self.snapshots = list(snapshots)
        self.calls = 0
        # 旧経路(個別のlatest_*)が呼ばれたら、別tickの値になっている想定で、あえて異なる値を持たせる
        self.latest_overlay = b"OTHER-TICK-OVERLAY"
        self.latest_overlay_source = b"OTHER-TICK-FRAME"
        self.latest_confirmed = None

    def get_record_snapshot(self):
        index = min(self.calls, len(self.snapshots) - 1)
        self.calls += 1
        return self.snapshots[index]


class FakeRuntime:
    def __init__(self, scheduler):
        self.inference_scheduler = scheduler
        self.buffer = FakeBufferForRecord()


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


def make_monitor(db, status="running", value="999999", confidence=0.11) -> Monitor:
    name = "t_snap_" + uuid.uuid4().hex[:8]
    monitor = Monitor(name=name, display_name=f"表示名{name[-4:]}", enabled=True, status=status, created_at=datetime(2026, 10, 1))
    monitor.inference = InferenceSettings(engine="easyocr", model_id="db-model")
    # DBのLatestResultは、snapshotとは別の(別tick相当の)値にしておく。recordがDBを読み直していれば、これが混ざって気付ける。
    monitor.latest_result = LatestResult(value=value, confidence=confidence, status="ok", engine="db-engine")
    monitor.source = VideoSource(source_type="url", url="http://example.invalid/x")
    db.add(monitor)
    db.commit()
    db.info["created"].append(monitor.id)
    return monitor


def jst(hour, minute=0, second=0):
    return datetime(2026, 10, 8, hour, minute, second, tzinfo=JST).astimezone(timezone.utc)


def make_snapshot(monitor_id, now, **over) -> InferenceRecordSnapshot:
    base = dict(
        monitor_id=monitor_id, tick=7, inference_at=now - timedelta(milliseconds=243), captured_at=now - timedelta(milliseconds=300),
        original_jpeg=b"ORIGINAL-OF-TICK-7", overlay_jpeg=b"OVERLAY-OF-TICK-7",
        raw_value="0215850", raw_confidence=0.881, raw_error=None, detection_count=7,
        validation_status="decrease_detected", candidate_value="215850", agreement_count=3, raw_count=5,
        confirmed_value="215858", confirmed_confidence=0.93, confirmed_at=now - timedelta(minutes=20), inference_status="ok",
        engine="cpp_onnx", model_id="digital_production_v1.onnx", processing_time_ms=41.5,
        baseline_value="215858", baseline_epoch=3, baseline_conflict=True, conflict_status="decrease_detected", conflict_candidate="215850", conflict_count=120,
    )
    base.update(over)
    return InferenceRecordSnapshot(**base)


def install(monkeypatch, monitor_id, snapshots):
    scheduler = FakeScheduler(snapshots)
    runtime = FakeRuntime(scheduler)
    monkeypatch.setattr(svc.runtime_manager, "get_runtime", lambda mid: runtime if mid == monitor_id else None)
    return scheduler


def test_record_uses_only_the_one_snapshot_and_fetches_it_once(db, monkeypatch):
    monitor = make_monitor(db)
    now = jst(8, 0, 1)
    first, later = make_snapshot(monitor.id, now), make_snapshot(monitor.id, now, tick=8, raw_value="0215860", raw_confidence=0.5, validation_status="confirmed", confirmed_value="215860",
                                                                  original_jpeg=b"ORIGINAL-OF-TICK-8", overlay_jpeg=b"OVERLAY-OF-TICK-8")
    scheduler = install(monkeypatch, monitor.id, [first, later])  # 取得のたびに次tickへ進む(2回取得すると別tickが混ざる)
    writer = RecordingWriter()
    outcomes = svc.record_due(db, now, writer=writer)
    assert [o.status for o in outcomes if o.monitor_id == monitor.id] == ["created"]
    assert scheduler.calls == 1  # snapshotは記録ごとに1回だけ取得する
    record = db.scalars(select(ReadingRecord).where(ReadingRecord.monitor_id == monitor.id)).one()
    # 記録の全フィールドが、同じsnapshot(tick 7)から。DBのLatestResult(999999 / 0.11 / db-engine)は使っていない
    assert (record.value, record.numeric_value, record.value_source) == ("215858", "215858", "carried_forward")
    assert (record.raw_value, record.raw_confidence, record.validation_status) == ("0215850", 0.881, "decrease_detected")
    assert record.confidence == 0.93  # 正式値側のconfidence(Rawのconfidenceとは別)
    assert (record.engine, record.model_id) == ("cpp_onnx", "digital_production_v1.onnx")
    assert record.baseline_conflict is True
    assert record.inference_at == datetime(2026, 10, 7, 23, 0, 0, 757000)  # snapshotの推論時刻(naive UTC)。08:00:01(JST)の243ms前
    assert record.recorded_at == datetime(2026, 10, 7, 23, 0, 1)  # 定時計測をDBへ保存した時刻(recorded_atとは別)
    # 画像ジョブも同じsnapshotの元画像・overlay(別tickのlatest_overlayやバッファのライブフレームではない)
    (job,) = writer.jobs
    assert (job.original, job.overlay) == (b"ORIGINAL-OF-TICK-7", b"OVERLAY-OF-TICK-7")
    assert job.record_id == record.id and record.image_status == "pending"


def test_record_content_does_not_change_while_the_image_writer_is_slow(db, monkeypatch):
    monitor = make_monitor(db)
    now = jst(9, 0, 1)
    snap = make_snapshot(monitor.id, now)
    scheduler = install(monkeypatch, monitor.id, [snap])

    class SlowWriter(RecordingWriter):
        def submit(self, job):
            # 画像保存が遅い間に、推論は次のtickへ進み、LatestResult等も別の値になる
            scheduler.snapshots.append(make_snapshot(monitor.id, now, tick=99, raw_value="0999999", original_jpeg=b"X", overlay_jpeg=b"Y"))
            scheduler.calls = 1
            other = db.get(LatestResult, monitor.latest_result.id)
            other.value = "123456"
            db.commit()
            return super().submit(job)

    writer = SlowWriter()
    svc.record_due(db, now, writer=writer)
    db.expire_all()
    record = db.scalars(select(ReadingRecord).where(ReadingRecord.monitor_id == monitor.id)).one()
    assert (record.raw_value, record.value, record.confidence, record.raw_confidence) == ("0215850", "215858", 0.93, 0.881)
    assert (writer.jobs[0].original, writer.jobs[0].overlay) == (b"ORIGINAL-OF-TICK-7", b"OVERLAY-OF-TICK-7")


def test_raw_and_overlay_and_original_come_from_the_same_tick(db, monkeypatch):
    # recordのRaw(0215850)と、保存するoverlay/元画像は、同じsnapshot(同じtickのjob)から作られる
    monitor = make_monitor(db)
    now = jst(10, 0, 1)
    snap = make_snapshot(monitor.id, now, raw_value="0215850", original_jpeg=jpeg_with_tick(7), overlay_jpeg=jpeg_with_tick(7) + b"-overlay")
    install(monkeypatch, monitor.id, [snap])
    writer = RecordingWriter()
    svc.record_due(db, now, writer=writer)
    record = db.scalars(select(ReadingRecord).where(ReadingRecord.monitor_id == monitor.id)).one()
    job = writer.jobs[0]
    assert tick_of(job.original) == tick_of(job.overlay) == snap.tick
    assert record.raw_value == snap.raw_value and record.inference_at is not None


def test_confirmed_tick_is_confirmed_and_the_formal_value_is_the_snapshot_value(db, monkeypatch):
    monitor = make_monitor(db)
    now = jst(11, 0, 1)
    snap = make_snapshot(monitor.id, now, validation_status="confirmed", raw_value="0215860", raw_confidence=0.9, confirmed_value="215860", confirmed_confidence=0.9, baseline_conflict=False)
    install(monkeypatch, monitor.id, [snap])
    svc.record_due(db, now, writer=RecordingWriter())
    record = db.scalars(select(ReadingRecord).where(ReadingRecord.monitor_id == monitor.id)).one()
    assert (record.value_source, record.value, record.validation_status, record.baseline_conflict) == ("confirmed", "215860", "confirmed", False)
    assert record.confidence == record.raw_confidence == 0.9


def test_stale_snapshot_is_not_used_and_legacy_records_have_no_inference_at(db, monkeypatch):
    monitor = make_monitor(db, value="777777", confidence=0.7)
    now = jst(12, 0, 1)
    stale = make_snapshot(monitor.id, now, inference_at=now - timedelta(seconds=60))  # 推論が止まって古い
    install(monkeypatch, monitor.id, [stale])
    writer = RecordingWriter()
    svc.record_due(db, now, writer=writer)
    record = db.scalars(select(ReadingRecord).where(ReadingRecord.monitor_id == monitor.id)).one()
    assert record.value == "777777"  # 従来の経路(DBの運用値)
    assert record.inference_at is None and record.raw_confidence is None  # 同一tick保証なし(推測で補わない)
    assert svc.serialize(record)["snapshot_consistent"] is False


def test_not_running_monitor_does_not_use_the_snapshot(db, monkeypatch):
    monitor = make_monitor(db, status="error")
    now = jst(13, 0, 1)
    install(monkeypatch, monitor.id, [make_snapshot(monitor.id, now)])
    svc.record_due(db, now + timedelta(minutes=3), started_at=now - timedelta(minutes=5), writer=RecordingWriter())  # 立ち上がりの待ち(2分)を過ぎる
    record = db.scalars(select(ReadingRecord).where(ReadingRecord.monitor_id == monitor.id)).one()
    assert record.value is None and record.value_source == "none" and record.inference_at is None


def test_serialize_exposes_snapshot_fields(db, monkeypatch):
    monitor = make_monitor(db)
    now = jst(14, 0, 1)
    install(monkeypatch, monitor.id, [make_snapshot(monitor.id, now)])
    svc.record_due(db, now, writer=RecordingWriter())
    record = db.scalars(select(ReadingRecord).where(ReadingRecord.monitor_id == monitor.id)).one()
    data = svc.serialize(record)
    assert data["raw_confidence"] == 0.881 and data["confidence"] == 0.93
    assert data["inference_at"].endswith("Z") and data["snapshot_consistent"] is True
    assert data["recorded_at"] != data["inference_at"]


def test_existing_records_are_left_untouched(db):
    monitor = make_monitor(db)
    old = ReadingRecord(monitor_id=monitor.id, monitor_name="x", hour_bucket="2026-10-07T08:00:00+09:00", recorded_at=datetime(2026, 10, 6, 23, 0, 5), value="100", numeric_value="100",
                        raw_value="0100", value_source="carried_forward", validation_status="decrease_detected", display_status="normal", confidence=0.5, image_status="ok")
    db.add(old)
    db.commit()
    db.expire_all()
    again = db.get(ReadingRecord, old.id)
    assert again.inference_at is None and again.raw_confidence is None and again.correction_count == 0
    assert svc.serialize(again)["snapshot_consistent"] is False  # 既存データは「厳密な同一tick保証が無かった記録」としてそのまま
