"""1時間記録の画像保存(RecordWriter、保存先、画像取得API、失敗時の挙動)のテスト(UI再設計 Phase 2)。

テストは一時DBと一時フォルダで動くため、実運用のDB・画像保存先・実カメラには触れない。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.core.database import SessionLocal
from app.main import app
from app.models import InferenceSettings, LatestResult, Monitor, ReadingRecord, VideoSource
from app.services import reading_record_service as records
from app.services import record_image_service as images
from app.services import storage_settings_service as storage
from app.services.csv_export_service import JST
from runtime.record_writer import RecordWriter

pytestmark = pytest.mark.integration

JPEG = b"\xff\xd8\xff\xe0fake-jpeg-bytes\xff\xd9"
OVERLAY = b"\xff\xd8\xff\xe0fake-overlay\xff\xd9"


def jst(hour, minute=0, second=0, day=8) -> datetime:
    return datetime(2026, 10, day, hour, minute, second, tzinfo=JST).astimezone(timezone.utc)


def naive(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


class FakeWriter:
    def __init__(self, accept=True, error=None):
        self.jobs, self.accept, self.error = [], accept, error

    def submit(self, job):
        if self.error:
            raise self.error
        self.jobs.append(job)
        return self.accept


@pytest.fixture
def db():
    session = SessionLocal()
    session.info["created"] = []
    yield session
    session.rollback()
    for monitor_id in session.info["created"]:
        monitor = session.get(Monitor, monitor_id)
        if monitor is not None:
            session.delete(monitor)
        session.execute(delete(ReadingRecord).where(ReadingRecord.monitor_id == monitor_id))
    session.commit()
    # 設定を既定へ戻す(一時DBはテスト間で共有される)
    storage.update(session, image_root_folder="", save_original_image=True, save_overlay_image=True, storage_warn_free_gb=10, storage_stop_free_gb=5)
    session.close()


def make_monitor(db, display_name="エネセン内ガスメータ用１", value="265754") -> Monitor:
    name = "t_img_" + uuid.uuid4().hex[:8]
    monitor = Monitor(name=name, display_name=display_name, enabled=True, status="running", created_at=datetime(2026, 10, 1))
    monitor.inference = InferenceSettings(engine="cpp_onnx", model_id="digital_production_v1.onnx")
    monitor.latest_result = LatestResult(value=value, confidence=0.95, status="ok", engine="cpp_onnx")
    monitor.source = VideoSource(source_type="url", url="http://example.invalid/x")
    db.add(monitor)
    db.commit()
    db.info["created"].append(monitor.id)
    return monitor


def make_record(db, monitor, value="265754", recorded_at=None) -> ReadingRecord:
    record = ReadingRecord(monitor_id=monitor.id, monitor_name=monitor.display_name, hour_bucket=f"2026-10-08T18:00:00+09:00#{uuid.uuid4().hex[:6]}",
                           recorded_at=recorded_at or naive(jst(18, 0, 15)), value=value, image_status="pending")
    db.add(record)
    db.commit()
    return record


def config_for(root: Path, *, default=False, original=True, overlay=True, warn_gb=0.001, stop_gb=0.0005) -> storage.StorageConfig:
    return storage.StorageConfig(image_root=root, image_root_is_default=default, save_original=original, save_overlay=overlay,
                                 warn_free_bytes=int(warn_gb * storage.GIB), stop_free_bytes=int(stop_gb * storage.GIB))


def job_for(monitor, record, **kw) -> images.ImageJob:
    base = dict(record_id=record.id, monitor_id=monitor.id, monitor_name=monitor.display_name, recorded_at=record.recorded_at, value=record.value,
                original=JPEG, overlay=OVERLAY, want_original=True, want_overlay=True)
    base.update(kw)
    return images.ImageJob(**base)


# --- 名前・パス ---

@pytest.mark.parametrize("text,expected", [
    ("エネセン内ガスメータ用１", "エネセン内ガスメータ用１"),
    ("食堂前機械室内メータ用\t", "食堂前機械室内メータ用"),  # 末尾のタブ(実データにある)
    ('a<b>c:d"e/f\\g|h?i*j', "a_b_c_d_e_f_g_h_i_j"),
    ("name. ", "name"),
    ("CON", "_CON"), ("con.txt", "_con.txt"), ("LPT1", "_LPT1"),
    ("", "monitor"), (None, "monitor"), ("   ", "monitor"), ("...", "monitor"),
])
def test_sanitize_name(text, expected):
    assert images.sanitize_name(text) == expected


def test_sanitize_name_limits_length():
    assert len(images.sanitize_name("あ" * 200)) == 60


def test_monitor_folder_contains_the_monitor_id_so_same_names_do_not_collide():
    assert images.monitor_folder_name("同じ名前", 2) == "同じ名前__2"
    assert images.monitor_folder_name("同じ名前", 3) == "同じ名前__3"
    assert images.monitor_folder_name("a/b", 7) == "a_b__7"


def test_paths_use_the_jst_date_of_the_recorded_time():
    recorded = naive(datetime(2026, 10, 8, 15, 0, 15, tzinfo=timezone.utc))  # 2026-10-09 00:00:15 JST(UTCでは前日)
    assert images.relative_dir("名前", 4, recorded) == "名前__4/2026/10/09"
    assert images.file_stem(recorded, "372413.7") == "20261009_000015_372413.7"
    assert images.file_stem(recorded, None) == "20261009_000015_none"
    assert images.value_for_filename("a/b") == "a_b"


# --- 保存 ---

def test_save_job_writes_both_images_with_relative_paths(db, tmp_path):
    monitor = make_monitor(db)
    record = make_record(db, monitor, value="265799")
    result = images.save_job(job_for(monitor, record), config_for(tmp_path))
    assert result.status == "ok" and result.error is None
    assert result.original_path == f"エネセン内ガスメータ用１__{monitor.id}/2026/10/08/20261008_180015_265799_original.jpg"
    assert result.overlay_path == f"エネセン内ガスメータ用１__{monitor.id}/2026/10/08/20261008_180015_265799_overlay.jpg"
    assert (tmp_path / result.original_path).read_bytes() == JPEG and (tmp_path / result.overlay_path).read_bytes() == OVERLAY
    assert list(tmp_path.rglob("*.tmp")) == []  # 一時ファイルを残さない


def test_save_job_never_overwrites_an_existing_file(db, tmp_path):
    monitor = make_monitor(db)
    record = make_record(db, monitor)
    first = images.save_job(job_for(monitor, record), config_for(tmp_path))
    second = images.save_job(job_for(monitor, record, original=b"\xff\xd8second", overlay=b"\xff\xd8second-o"), config_for(tmp_path))
    assert second.original_path != first.original_path and second.original_path.endswith("_2_original.jpg")
    assert (tmp_path / first.original_path).read_bytes() == JPEG  # 1件目は保たれる


def test_save_job_respects_the_per_image_switches(db, tmp_path):
    monitor = make_monitor(db)
    record = make_record(db, monitor)
    result = images.save_job(job_for(monitor, record, want_original=False), config_for(tmp_path, original=False))
    assert result.status == "ok" and result.original_path is None and result.overlay_path is not None


def test_save_job_reports_missing_frames_and_keeps_the_saved_side(db, tmp_path):
    monitor = make_monitor(db)
    record = make_record(db, monitor)
    result = images.save_job(job_for(monitor, record, overlay=None), config_for(tmp_path))
    assert result.status == "failed" and result.overlay_path is None and result.original_path is not None
    assert "推論オーバーレイ" in result.error


def test_save_job_fails_when_a_user_configured_root_is_missing(db, tmp_path):
    monitor = make_monitor(db)
    record = make_record(db, monitor)
    result = images.save_job(job_for(monitor, record), config_for(tmp_path / "no_such_dir"))
    assert result.status == "failed" and result.io_failure is True and "見つかりません" in result.error
    assert not (tmp_path / "no_such_dir").exists()  # 設定ミスのパスを勝手に作らない


def test_save_job_creates_the_default_root(db, tmp_path):
    monitor = make_monitor(db)
    record = make_record(db, monitor)
    result = images.save_job(job_for(monitor, record), config_for(tmp_path / "images", default=True))
    assert result.status == "ok" and (tmp_path / "images").is_dir()


def test_save_job_is_dropped_below_the_stop_threshold(db, tmp_path, monkeypatch):
    monitor = make_monitor(db)
    record = make_record(db, monitor)
    config = config_for(tmp_path, warn_gb=10, stop_gb=5)
    monkeypatch.setattr(images, "free_bytes", lambda _p: int(4.9 * storage.GIB))
    result = images.save_job(job_for(monitor, record), config)
    assert result.status == "dropped" and "停止しきい値" in result.error and result.original_path is None
    assert list(tmp_path.rglob("*.jpg")) == []
    monkeypatch.setattr(images, "free_bytes", lambda _p: int(5.0 * storage.GIB))
    assert images.save_job(job_for(monitor, record), config).status == "ok"  # ちょうどしきい値は保存する


def test_space_state_levels(tmp_path, monkeypatch):
    config = config_for(tmp_path, warn_gb=10, stop_gb=5)
    for free_gb, expected in ((50, "ok"), (9.9, "warning"), (4.9, "stopped")):
        monkeypatch.setattr(images, "free_bytes", lambda _p, g=free_gb: int(g * storage.GIB))
        assert images.space_state(tmp_path, config)[1] == expected


def test_save_job_rejects_too_long_paths(db, tmp_path):
    monitor = make_monitor(db, display_name="x" * 60)
    record = make_record(db, monitor)
    deep = tmp_path
    for _ in range(3):
        deep = deep / ("d" * 40)
        deep.mkdir()
    result = images.save_job(job_for(monitor, record), config_for(deep))
    assert result.status == "failed" and "長すぎます" in result.error


def test_resolve_image_path_blocks_traversal(tmp_path):
    (tmp_path / "ok").mkdir()
    (tmp_path / "ok" / "a.jpg").write_bytes(JPEG)
    assert images.resolve_image_path(tmp_path, "ok/a.jpg") == (tmp_path / "ok" / "a.jpg").resolve()
    assert images.resolve_image_path(tmp_path, "../outside.jpg") is None
    assert images.resolve_image_path(tmp_path, "ok/../../outside.jpg") is None


# --- RecordWriter ---

def test_writer_saves_images_and_updates_the_record(db, tmp_path):
    monitor = make_monitor(db)
    record = make_record(db, monitor, value="372413.7")
    storage.update(db, image_root_folder=str(tmp_path))
    writer = RecordWriter()
    result = writer.process(job_for(monitor, record))
    db.expire_all()
    row = db.get(ReadingRecord, record.id)
    assert result.status == "ok" and row.image_status == "ok" and row.image_error is None
    assert row.original_image_path.endswith("_372413.7_original.jpg") and (tmp_path / row.original_image_path).exists()
    assert writer.status()["counts"]["ok"] == 1 and writer.status()["last_success_at"] is not None


def test_writer_records_failures_without_raising_and_opens_the_circuit(db, tmp_path):
    monitor = make_monitor(db)
    storage.update(db, image_root_folder=str(tmp_path / "unreachable"))  # 存在しない保存先(不通のUNC相当)
    writer = RecordWriter()
    statuses = []
    for _ in range(5):
        record = make_record(db, monitor)
        statuses.append(writer.process(job_for(monitor, record)).status)
    assert statuses == ["failed", "failed", "failed", "dropped", "dropped"]  # 3回連続のI/O失敗で一時停止
    status = writer.status()
    assert status["circuit_open"] is True and status["counts"]["failed"] == 3 and status["counts"]["dropped"] == 2
    assert status["last_error"] and status["last_error_at"]
    db.expire_all()
    assert {r.image_status for r in db.query(ReadingRecord).filter(ReadingRecord.monitor_id == monitor.id)} == {"failed", "dropped"}


def test_writer_submit_drops_when_the_queue_is_full(db, tmp_path):
    monitor = make_monitor(db)
    record = make_record(db, monitor)
    writer = RecordWriter(queue_size=1)  # スレッドを開始しないので、キューは消費されない
    assert writer.submit(job_for(monitor, record)) is True
    assert writer.submit(job_for(monitor, record)) is False
    assert writer.status()["queue_length"] == 1 and writer.status()["counts"]["dropped"] == 1


# --- 1時間記録との結合 ---

def run_record(db, monkeypatch, writer, frames=(JPEG, OVERLAY), now=None):
    monkeypatch.setattr(records, "_capture_frames", lambda _id: frames)
    return records.record_due(db, now or jst(18, 0, 15), writer=writer)


def test_hourly_record_enqueues_one_image_job_with_the_captured_frames(db, monkeypatch):
    monitor = make_monitor(db, value="372413.8")
    writer = FakeWriter()
    run_record(db, monkeypatch, writer)
    mine = [job for job in writer.jobs if job.monitor_id == monitor.id]
    assert len(mine) == 1
    job = mine[0]
    assert (job.value, job.original, job.overlay, job.want_original, job.want_overlay) == ("372413.8", JPEG, OVERLAY, True, True)
    record = db.get(ReadingRecord, job.record_id)
    assert record.image_status == "pending" and record.value == "372413.8"


def test_missing_frames_are_recorded_as_failed_but_the_value_is_kept(db, monkeypatch):
    monitor = make_monitor(db, value="265754")
    writer = FakeWriter()
    run_record(db, monkeypatch, writer, frames=(None, None))
    record = db.query(ReadingRecord).filter(ReadingRecord.monitor_id == monitor.id).one()
    assert (record.value, record.image_status) == ("265754", "failed") and "フレーム" in record.image_error
    assert [j for j in writer.jobs if j.monitor_id == monitor.id] == []


def test_image_saving_can_be_disabled(db, monkeypatch):
    monitor = make_monitor(db)
    storage.update(db, save_original_image=False, save_overlay_image=False)
    writer = FakeWriter()
    run_record(db, monkeypatch, writer)
    record = db.query(ReadingRecord).filter(ReadingRecord.monitor_id == monitor.id).one()
    assert record.image_status == "disabled" and [j for j in writer.jobs if j.monitor_id == monitor.id] == []


def test_overlay_only_setting_skips_the_original(db, monkeypatch):
    monitor = make_monitor(db)
    storage.update(db, save_original_image=False)
    writer = FakeWriter()
    run_record(db, monkeypatch, writer)
    job = [j for j in writer.jobs if j.monitor_id == monitor.id][0]
    assert (job.want_original, job.want_overlay) == (False, True)


def test_a_full_writer_queue_marks_the_record_dropped_and_keeps_the_value(db, monkeypatch):
    monitor = make_monitor(db, value="265754")
    run_record(db, monkeypatch, FakeWriter(accept=False))
    record = db.query(ReadingRecord).filter(ReadingRecord.monitor_id == monitor.id).one()
    assert (record.value, record.image_status) == ("265754", "dropped")


def test_a_broken_writer_never_prevents_the_measurement_record(db, monkeypatch):
    monitor = make_monitor(db, value="265754")
    outcomes = run_record(db, monkeypatch, FakeWriter(error=RuntimeError("boom")))
    assert any(o.monitor_id == monitor.id and o.status == "created" for o in outcomes)
    db.expire_all()
    record = db.query(ReadingRecord).filter(ReadingRecord.monitor_id == monitor.id).one()
    assert record.value == "265754" and record.image_status == "failed"


# --- 画像取得API ---

@pytest.fixture
def client(monkeypatch):
    from runtime.hourly_record_worker import hourly_record_worker
    monkeypatch.setattr(hourly_record_worker, "start", lambda: None)
    with TestClient(app) as c:
        yield c


def saved_record(db, tmp_path):
    monitor = make_monitor(db)
    record = make_record(db, monitor, value="265799")
    storage.update(db, image_root_folder=str(tmp_path))
    result = images.save_job(job_for(monitor, record), config_for(tmp_path))
    images.finalize_record(record.id, result)
    db.expire_all()
    return record


def test_image_api_returns_the_saved_files(client, db, tmp_path):
    record = saved_record(db, tmp_path)
    original = client.get(f"/api/records/{record.id}/image/original")
    overlay = client.get(f"/api/records/{record.id}/image/overlay")
    assert original.status_code == 200 and original.content == JPEG and original.headers["content-type"] == "image/jpeg"
    assert overlay.status_code == 200 and overlay.content == OVERLAY
    body = client.get(f"/api/records/{record.id}").json()
    assert body["image_status"] == "ok" and body["original_image_path"].endswith("_original.jpg")


def test_image_api_errors(client, db, tmp_path):
    record = saved_record(db, tmp_path)
    assert client.get(f"/api/records/{record.id}/image/other").status_code == 404
    assert client.get("/api/records/99999999/image/original").status_code == 404
    unsaved = make_record(db, db.get(Monitor, record.monitor_id))
    unsaved.image_status, unsaved.image_error = "failed", "保存先にアクセスできません"
    db.commit()
    res = client.get(f"/api/records/{unsaved.id}/image/original")
    assert res.status_code == 404 and res.json()["detail"]["code"] == "IMAGE_NOT_SAVED" and res.json()["detail"]["image_status"] == "failed"
    # ファイルが消えている/保存先を変更した場合
    (tmp_path / db.get(ReadingRecord, record.id).original_image_path).unlink()
    assert client.get(f"/api/records/{record.id}/image/original").json()["detail"]["code"] == "IMAGE_FILE_MISSING"


def test_image_api_blocks_paths_outside_the_image_root(client, db, tmp_path):
    outside = tmp_path.parent / "outside_secret.jpg"
    outside.write_bytes(b"secret")
    record = saved_record(db, tmp_path)
    row = db.get(ReadingRecord, record.id)
    row.original_image_path = "../outside_secret.jpg"
    db.commit()
    res = client.get(f"/api/records/{record.id}/image/original")
    assert res.status_code == 404 and res.json()["detail"]["code"] == "IMAGE_PATH_INVALID"
