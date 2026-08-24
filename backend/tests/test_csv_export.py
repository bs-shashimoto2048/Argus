"""Confirmed値CSV出力(Issue #17)のテスト。

完全にDB分離されたテストであり、実DB(data/argus.db)は一切使用しない
(このファイル内で使うDBは全てtmp_path上に新規作成する専用SQLiteファイル)。
service層のテストはHTTPを経由せず、csv_export_serviceの関数を直接呼ぶ
(FastAPI/TestClient/lifespanを経由しないため、実Monitor Runtimeの起動等の
副作用も一切発生しない)。API層のテストのみ、csv_export.routerだけを積んだ
最小限のFastAPI appをisolatedなDBへdependency_overrideして使う。

ROI/前処理/InferenceEngine/ReadingStabilizer自体は一切変更していないため、
ここではcsv_export_service/csv_export_workerとAPI(/api/system/csv-export)の
挙動のみを検証する。出力対象は常にConfirmed値(LatestResult.value)であり、
Raw値は使わない。
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import runtime.csv_export_worker as csv_export_worker_module
from app.core.database import Base, get_db
from app.models import CsvExportLog, InferenceSettings, LatestResult, Monitor, SystemSettings
from app.routers import csv_export as csv_export_router_module
from app.services import csv_export_service as svc
from runtime.csv_export_worker import CsvExportWorker

pytestmark = pytest.mark.unit


# --- 実DB(data/argus.db)が一切変更されないことを保証する自動ガード -----------
# 前回、テストが実DBのMonitor/CsvExportLogへ書き込んでしまった問題の再発防止として、
# このテストファイル内の全テストの前後でMonitor一覧・CsvExportLog全件・SystemSettingsが
# 変化していないことを自動的にassertする(単なる手動確認ではなくCIで検証可能にする)。
# inference_results/latest_resultsは実際に稼働中のBackend(実カメラRuntime)が
# 常時更新するため対象外とする(本テストのDB分離とは無関係な既存の実運用の動き)。
@pytest.fixture(scope="module", autouse=True)
def _guard_real_db_untouched_by_this_test_module():
    from sqlalchemy.exc import OperationalError

    from app.core.database import SessionLocal as RealSessionLocal
    from app.models import CsvExportLog as RealCsvExportLog
    from app.models import Monitor as RealMonitor
    from app.models import SystemSettings as RealSystemSettings

    def _safe(real_db, query_fn):
        # CI等、実DB(data/argus.db)がまだ一度もBackend起動(lifespanのcreate_all)を
        # 経ていないフレッシュな環境では、テーブル自体が存在しない("no such table")。
        # その場合は「テーブルが無い」という状態そのものを前後で比較すればよいため、
        # Noneを返して継続する(テストを失敗させない。実際にこのテストモジュールが
        # 実DBへ書き込んだ場合は、前後でNone以外の値に変わり不一致として検出できる)。
        try:
            return query_fn()
        except OperationalError:
            real_db.rollback()
            return None

    def snapshot():
        real_db = RealSessionLocal()
        try:
            monitor_ids = _safe(real_db, lambda: sorted(row[0] for row in real_db.query(RealMonitor.id).all()))
            log_ids = _safe(real_db, lambda: sorted(row[0] for row in real_db.query(RealCsvExportLog.id).all()))
            settings_row = _safe(real_db, lambda: real_db.get(RealSystemSettings, 1))
            settings_snapshot = (settings_row.csv_export_enabled, settings_row.csv_output_folder) if settings_row else None
            return monitor_ids, log_ids, settings_snapshot
        finally:
            real_db.close()

    before = snapshot()
    yield
    after = snapshot()
    assert before == after, "test_csv_export.py が実DB(data/argus.db)のMonitor/CsvExportLog/SystemSettingsを変更しました"


# --- 完全分離DB fixture(実DBは一切使わない) ---------------------------------

@pytest.fixture
def isolated_session_factory(tmp_path):
    """tmp_path上の専用SQLiteファイルへ、このリポジトリの全モデルのテーブルを作成する。
    実DB(data/argus.db)には一切触れない。"""
    db_path = tmp_path / "isolated_csv_export_test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    yield factory
    engine.dispose()


@pytest.fixture
def db(isolated_session_factory):
    session = isolated_session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(isolated_session_factory, monkeypatch):
    """csv_export.routerのみを積んだ最小限のFastAPI app(実app.mainのlifespanは
    経由しない = 実Monitor Runtime起動等の副作用が一切発生しない)。get_dbと、
    csv_export_worker内部が直接呼ぶSessionLocalの両方を、isolatedなDBへ向ける。
    """
    monkeypatch.setattr(csv_export_worker_module, "SessionLocal", isolated_session_factory)
    worker = csv_export_worker_module.csv_export_worker
    worker.last_outcomes, worker.last_tick_at = [], None
    worker.last_test_outcomes, worker.last_test_run_at = [], None

    def override_get_db():
        session = isolated_session_factory()
        try:
            yield session
        finally:
            session.close()

    mini_app = FastAPI()
    mini_app.include_router(csv_export_router_module.router)
    mini_app.dependency_overrides[get_db] = override_get_db
    with TestClient(mini_app) as test_client:
        yield test_client


def _make_monitor(db, name, display_name=None, *, value=None, confidence=None, status="ok", engine="ultralytics", model_id=None) -> Monitor:
    monitor = Monitor(name=name, display_name=display_name or name, location="test")
    monitor.inference = InferenceSettings(model_id=model_id)
    monitor.latest_result = LatestResult(value=value, confidence=confidence, status=status, engine=engine)
    db.add(monitor)
    db.commit()
    db.refresh(monitor)
    return monitor


# --- hour_bucket_jst ---------------------------------------------------------

def test_hour_bucket_jst_truncates_to_hour_and_converts_from_utc():
    utc_time = datetime(2026, 8, 24, 0, 30, tzinfo=timezone.utc)  # UTC 00:30 -> JST 09:30 -> 09:00
    bucket = svc.hour_bucket_jst(utc_time)
    assert bucket.hour == 9
    assert bucket.minute == 0 and bucket.second == 0 and bucket.microsecond == 0
    assert bucket.utcoffset() == timedelta(hours=9)


def test_hour_bucket_jst_crosses_date_at_utc_15():
    utc_time = datetime(2026, 8, 24, 15, 5, tzinfo=timezone.utc)  # UTC 15:05 -> JST 翌日00:05 -> 00:00
    bucket = svc.hour_bucket_jst(utc_time)
    assert (bucket.year, bucket.month, bucket.day, bucket.hour) == (2026, 8, 25, 0)


# --- CSVのtimestamp_jst表記(Excel等で確認しやすい"YYYY/MM/DD HH:mm:ss") -------

def test_format_timestamp_jst_for_csv_uses_slash_format():
    hour = svc.hour_bucket_jst(datetime(2026, 8, 24, 5, 0, tzinfo=timezone.utc))  # JST 14:00
    assert svc.format_timestamp_jst_for_csv(hour) == "2026/08/24 14:00:00"


def test_format_timestamp_jst_for_csv_is_not_iso8601():
    hour = svc.hour_bucket_jst(datetime(2026, 8, 24, 5, 0, tzinfo=timezone.utc))
    formatted = svc.format_timestamp_jst_for_csv(hour)
    assert "T" not in formatted and "+" not in formatted  # ISO 8601形式(2026-08-24T14:00:00+09:00)ではない


def test_dedup_key_and_api_hour_bucket_representation_stays_iso8601():
    """CSV列の表記変更は内部のdedup key(CsvExportLog.hour_bucket)やAPIの
    last_exported_hourには影響しない(hour_bucket.isoformat()は変更していない)。"""
    hour = svc.hour_bucket_jst(datetime(2026, 8, 24, 5, 0, tzinfo=timezone.utc))
    assert hour.isoformat() == "2026-08-24T14:00:00+09:00"


# --- settings persistence ---------------------------------------------------

def test_settings_default_disabled_and_unset(db):
    settings = svc.get_settings(db)
    assert settings.csv_export_enabled is False
    assert settings.csv_output_folder is None


def test_update_settings_persists_and_strips_blank_folder(db):
    svc.update_settings(db, enabled=True, output_folder="  ")
    settings = svc.get_settings(db)
    assert settings.csv_export_enabled is True
    assert settings.csv_output_folder is None  # 空白のみは未設定として扱う


# --- production: export_monitor_for_hour(dedupあり、argus_hourly_readings.csv) -

def test_export_writes_fixed_production_filename_with_header(db, tmp_path):
    monitor = _make_monitor(db, "m1", value="0025.60", confidence=0.87, status="ok", engine="ultralytics")
    hour = svc.hour_bucket_jst()
    outcome = svc.export_monitor_for_hour(db, monitor, hour, str(tmp_path))
    assert outcome.status == "written"

    path = tmp_path / "argus_hourly_readings.csv"
    assert path.exists()
    assert not (tmp_path / "argus_hourly_readings_test.csv").exists()  # テスト用ファイルは作られない
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert lines[0] == ",".join(svc.CSV_HEADER)
    row = lines[1].split(",")
    assert row[0] == svc.format_timestamp_jst_for_csv(hour)  # "YYYY/MM/DD HH:mm:ss"形式(Excel等で確認しやすい表記)
    assert row[1] == str(monitor.id)
    assert row[4] == "0025.60"  # decimal_position適用済みのConfirmed値がそのまま出力される(row生成の再計算なし)
    assert row[6] == "ok"
    assert row[7] == "ultralytics"


def test_export_all_monitors_appends_one_row_each_to_same_production_file(db, tmp_path):
    """本番: 毎時、全Monitor分を1行ずつ同じargus_hourly_readings.csvへ追記する。"""
    m1 = _make_monitor(db, "m1", value="100")
    m2 = _make_monitor(db, "m2", value="200")
    hour = svc.hour_bucket_jst()
    outcomes = svc.export_all_monitors_for_hour(db, hour, str(tmp_path))
    assert {o.monitor_id for o in outcomes if o.status == "written"} == {m1.id, m2.id}

    files = list(tmp_path.glob("*.csv"))
    assert len(files) == 1 and files[0].name == "argus_hourly_readings.csv"
    data_lines = files[0].read_text(encoding="utf-8").strip().splitlines()[1:]
    assert len(data_lines) == 2
    ids_in_file = {line.split(",")[1] for line in data_lines}
    assert ids_in_file == {str(m1.id), str(m2.id)}


def test_export_same_hour_is_deduped_no_second_row(db, tmp_path):
    monitor = _make_monitor(db, "m1", value="100")
    hour = svc.hour_bucket_jst()
    first = svc.export_monitor_for_hour(db, monitor, hour, str(tmp_path))
    second = svc.export_monitor_for_hour(db, monitor, hour, str(tmp_path))
    assert first.status == "written"
    assert second.status == "skipped_already_exported"

    path = tmp_path / "argus_hourly_readings.csv"
    assert len(path.read_text(encoding="utf-8").strip().splitlines()[1:]) == 1  # 二重出力されていない


def test_export_different_hours_append_separate_rows(db, tmp_path):
    monitor = _make_monitor(db, "m1", value="100")
    hour1 = svc.hour_bucket_jst(datetime(2026, 8, 24, 0, 0, tzinfo=timezone.utc))
    hour2 = hour1 + timedelta(hours=1)
    svc.export_monitor_for_hour(db, monitor, hour1, str(tmp_path))
    svc.export_monitor_for_hour(db, monitor, hour2, str(tmp_path))

    path = tmp_path / "argus_hourly_readings.csv"
    assert len(path.read_text(encoding="utf-8").strip().splitlines()[1:]) == 2


def test_restart_equivalent_does_not_duplicate(isolated_session_factory, tmp_path):
    """Backend再起動相当: 新しいSession(=新しいDB接続)から実行しても、dedupはDBに
    永続化されているため二重出力されない。"""
    db1 = isolated_session_factory()
    monitor = _make_monitor(db1, "m1", value="100")
    hour = svc.hour_bucket_jst()
    outcome1 = svc.export_monitor_for_hour(db1, monitor, hour, str(tmp_path))
    db1.close()

    db2 = isolated_session_factory()
    monitor2 = db2.get(Monitor, monitor.id)
    outcome2 = svc.export_monitor_for_hour(db2, monitor2, hour, str(tmp_path))
    db2.close()

    assert outcome1.status == "written"
    assert outcome2.status == "skipped_already_exported"
    path = tmp_path / "argus_hourly_readings.csv"
    assert len(path.read_text(encoding="utf-8").strip().splitlines()) == 2  # header + 1行のみ


def test_read_error_status_is_recorded_with_empty_value(db, tmp_path):
    """read_error(NO_READING)時は「スキップ」ではなく、状態が分かる形(空値+status=read_error)
    で1行記録する(既存ResultStore仕様: NO_READINGはLatestResult.status="read_error"、
    valueはNoneのまま)。"""
    monitor = _make_monitor(db, "m1", value=None, confidence=None, status="read_error", engine="ultralytics")
    hour = svc.hour_bucket_jst()
    outcome = svc.export_monitor_for_hour(db, monitor, hour, str(tmp_path))
    assert outcome.status == "written"

    path = tmp_path / "argus_hourly_readings.csv"
    row = path.read_text(encoding="utf-8").strip().splitlines()[1].split(",")
    assert row[4] == ""  # confirmed_valueは空(Noneを出力しない)
    assert row[6] == "read_error"


def test_export_error_on_missing_folder_does_not_mark_hour_exported_and_allows_retry(db, tmp_path):
    monitor = _make_monitor(db, "m1", value="100")
    missing_folder = tmp_path / "does_not_exist"
    hour = svc.hour_bucket_jst()

    outcome = svc.export_monitor_for_hour(db, monitor, hour, str(missing_folder))
    assert outcome.status == "error"
    assert outcome.detail  # エラー内容が分かる
    assert db.query(CsvExportLog).count() == 0  # 予約行は残らない(不整合を避ける)

    # フォルダを作ってから同じhourで再試行すると、今度は書き込める
    # (エラー時にdedupの予約行を残さないため、再試行できる)。
    missing_folder.mkdir()
    retry = svc.export_monitor_for_hour(db, monitor, hour, str(missing_folder))
    assert retry.status == "written"


# --- test output: argus_hourly_readings_test.csv(dedupなし、本番に影響しない) --

def test_test_export_can_run_repeatedly_without_dedup(db, tmp_path):
    monitor = _make_monitor(db, "m1", value="100")
    hour = svc.hour_bucket_jst()
    first = svc.export_monitor_for_test(monitor, hour, str(tmp_path))
    second = svc.export_monitor_for_test(monitor, hour, str(tmp_path))
    assert first.status == "written"
    assert second.status == "written"  # dedupされない、何度でも追記できる

    path = tmp_path / "argus_hourly_readings_test.csv"
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert lines[0] == ",".join(svc.CSV_HEADER)  # headerは初回のみ
    assert len(lines) == 3  # header + 2行


def test_test_export_does_not_touch_production_dedup_or_file(db, tmp_path):
    """テスト出力は本番のCsvExportLog(dedup)・最終出力日時を消費/更新しない
    (production fileも作られない)。"""
    monitor = _make_monitor(db, "m1", value="100")
    hour = svc.hour_bucket_jst()
    svc.export_all_monitors_for_test(db, hour, str(tmp_path))

    assert db.query(CsvExportLog).count() == 0  # 本番dedupログは一切増えない
    assert not (tmp_path / "argus_hourly_readings.csv").exists()  # 本番ファイルは作られない
    assert (tmp_path / "argus_hourly_readings_test.csv").exists()

    # テスト出力後も、本番のdedupは通常どおり機能する(このhourはまだ本番未出力)。
    prod_outcome = svc.export_monitor_for_hour(db, monitor, hour, str(tmp_path))
    assert prod_outcome.status == "written"


def test_production_and_test_files_coexist_independently(db, tmp_path):
    monitor = _make_monitor(db, "m1", value="100")
    hour = svc.hour_bucket_jst()
    svc.export_monitor_for_hour(db, monitor, hour, str(tmp_path))
    svc.export_monitor_for_test(monitor, hour, str(tmp_path))
    svc.export_monitor_for_test(monitor, hour, str(tmp_path))

    prod_lines = (tmp_path / "argus_hourly_readings.csv").read_text(encoding="utf-8").strip().splitlines()
    test_lines = (tmp_path / "argus_hourly_readings_test.csv").read_text(encoding="utf-8").strip().splitlines()
    assert len(prod_lines) - 1 == 1  # 本番はdedupにより1行のみ
    assert len(test_lines) - 1 == 2  # テストは2回とも追記される


def test_changing_output_folder_leaves_old_file_untouched(db, tmp_path):
    """出力フォルダ変更時は新しいフォルダのCSVへ追記開始し、旧ファイルは変更しない。"""
    monitor = _make_monitor(db, "m1", value="100")
    folder_a = tmp_path / "folder_a"
    folder_b = tmp_path / "folder_b"
    folder_a.mkdir()
    folder_b.mkdir()
    hour = svc.hour_bucket_jst()

    svc.export_monitor_for_test(monitor, hour, str(folder_a))
    snapshot_a = (folder_a / "argus_hourly_readings_test.csv").read_text(encoding="utf-8")

    svc.export_monitor_for_test(monitor, hour, str(folder_b))

    assert (folder_a / "argus_hourly_readings_test.csv").read_text(encoding="utf-8") == snapshot_a  # 旧ファイルは不変
    assert (folder_b / "argus_hourly_readings_test.csv").exists()  # 新フォルダに新規作成


def test_output_path_never_escapes_output_folder_regardless_of_monitor_name(db, tmp_path):
    """本番/テストとも出力ファイル名は固定文字列("argus_hourly_readings.csv"/
    "_test.csv")であり、Monitor名を出力パスへ一切使わない設計になったため、
    Monitor名にpath traversalを狙った文字列("../../etc/passwd"等)が入っていても
    出力先は常にoutput_folder直下の固定ファイルのみになる(=path traversalの
    攻撃面がそもそも存在しない)。"""
    dangerous_names = ["../../etc/passwd", "..\\..\\windows\\system32\\evil", "a/b\\c"]
    for name in dangerous_names:
        monitor = Monitor(name=f"dangerous-{dangerous_names.index(name)}", display_name=name, location="test")
        monitor.inference = InferenceSettings()
        monitor.latest_result = LatestResult(value="1", status="ok", engine="ultralytics")
        db.add(monitor)
        db.commit()
        db.refresh(monitor)
        hour = svc.hour_bucket_jst()
        outcome = svc.export_monitor_for_test(monitor, hour, str(tmp_path))
        assert outcome.status == "written"

    # tmp_path配下に作られたファイルは固定名1つだけ(danger要素は単なる列の値として
    # そのまま出力され、パスとしては解釈されない)。
    csv_files = list(tmp_path.rglob("*.csv"))
    assert csv_files == [tmp_path / "argus_hourly_readings_test.csv"]
    # tmp_pathの外(親ディレクトリ)には何も作られていない。
    assert not (tmp_path.parent / "argus_hourly_readings_test.csv").exists()


# --- 排他(lock): workerと手動出力が重なっても壊れない -------------------------

def test_concurrent_appends_to_same_file_do_not_corrupt_or_duplicate_header(db, tmp_path):
    """複数スレッドが同時に同一ファイルへ追記しても(workerのtickと手動テスト出力が
    重なる状況を模す)、headerは1回だけ・行は破損せず全件書き込まれる。

    本番でも実際の並行アクセスはファイルI/O(_write_lockで直列化)にのみ発生し、
    DB Session自体は各entry point(tick/run_test_export)がそれぞれ自分専用の
    Sessionを新規作成して使う(=Sessionを複数スレッドで共有しない)。この検証観点を
    テストでも再現するため、関係属性(inference/latest_result)は事前に読み込んでおき
    (SQLAlchemy Sessionはスレッドセーフではないため)、スレッド間で実際に競合させるのは
    _write_lockで守られるファイル追記処理のみにする。
    """
    monitor = _make_monitor(db, "m1", value="100")
    _ = monitor.inference, monitor.latest_result  # 関係属性を事前にメモリへロードしておく
    hour = svc.hour_bucket_jst()

    def write_once(_):
        return svc.export_monitor_for_test(monitor, hour, str(tmp_path))

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(write_once, range(20)))

    assert all(o.status == "written" for o in outcomes)
    path = tmp_path / "argus_hourly_readings_test.csv"
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert lines.count(",".join(svc.CSV_HEADER)) == 1  # headerは1回だけ
    assert len(lines) - 1 == 20  # 20行とも欠落・重複なく書き込まれている
    for line in lines[1:]:
        assert len(line.split(",")) == len(svc.CSV_HEADER)  # 各行が壊れていない


# --- worker(tick/run_test_export)---------------------------------------------

def test_tick_noop_when_disabled(monkeypatch, isolated_session_factory, db, tmp_path):
    monkeypatch.setattr(csv_export_worker_module, "SessionLocal", isolated_session_factory)
    svc.update_settings(db, enabled=False, output_folder=str(tmp_path))
    worker = CsvExportWorker()
    assert worker.tick() == []
    assert list(tmp_path.glob("*.csv")) == []  # 無効時はCSVを一切書かない(tmp_pathには分離用DBファイルが別途存在する)


def test_tick_noop_when_folder_unset(monkeypatch, isolated_session_factory, db):
    monkeypatch.setattr(csv_export_worker_module, "SessionLocal", isolated_session_factory)
    svc.update_settings(db, enabled=True, output_folder=None)
    worker = CsvExportWorker()
    assert worker.tick() == []


def test_tick_writes_production_file_when_enabled(monkeypatch, isolated_session_factory, db, tmp_path):
    monkeypatch.setattr(csv_export_worker_module, "SessionLocal", isolated_session_factory)
    _make_monitor(db, "m1", value="100")
    svc.update_settings(db, enabled=True, output_folder=str(tmp_path))
    worker = CsvExportWorker()
    outcomes = worker.tick()
    assert any(o.status == "written" for o in outcomes)
    assert (tmp_path / "argus_hourly_readings.csv").exists()


def test_run_test_export_ignores_enabled_flag_and_skips_dedup(monkeypatch, isolated_session_factory, db, tmp_path):
    monkeypatch.setattr(csv_export_worker_module, "SessionLocal", isolated_session_factory)
    _make_monitor(db, "m1", value="100")
    svc.update_settings(db, enabled=False, output_folder=str(tmp_path))  # 本番は無効のまま
    worker = CsvExportWorker()
    first = worker.run_test_export()
    second = worker.run_test_export()
    assert all(o.status == "written" for o in first)
    assert all(o.status == "written" for o in second)  # dedupなし、2回とも書き込まれる
    assert db.query(CsvExportLog).count() == 0


def test_run_test_export_without_folder_raises_value_error(monkeypatch, isolated_session_factory, db):
    monkeypatch.setattr(csv_export_worker_module, "SessionLocal", isolated_session_factory)
    svc.update_settings(db, enabled=False, output_folder=None)
    worker = CsvExportWorker()
    with pytest.raises(ValueError):
        worker.run_test_export()


# --- API level(csv_export.routerのみを積んだ最小appをisolated DBへ向けて検証) --

def test_api_put_get_status_round_trip(client, tmp_path):
    put_response = client.put("/api/system/csv-export", json={"enabled": True, "output_folder": str(tmp_path)})
    assert put_response.status_code == 200, put_response.text
    assert put_response.json() == {"enabled": True, "output_folder": str(tmp_path)}

    status_response = client.get("/api/system/csv-export")
    assert status_response.status_code == 200
    body = status_response.json()
    assert body["enabled"] is True
    assert body["output_folder"] == str(tmp_path)
    assert isinstance(body["monitors"], list)
    # credential/URL相当のフィールドが応答に含まれていないことを確認する。
    assert "password" not in status_response.text.lower()
    assert "url" not in status_response.text.lower()


def test_api_run_now_without_folder_returns_400(client):
    client.put("/api/system/csv-export", json={"enabled": False, "output_folder": None})
    response = client.post("/api/system/csv-export/run-now")
    assert response.status_code == 400


def test_api_run_now_writes_test_file_and_does_not_affect_production_status(client, db, tmp_path):
    monitor = _make_monitor(db, "m1", value="0042.5")
    client.put("/api/system/csv-export", json={"enabled": False, "output_folder": str(tmp_path)})

    run_response = client.post("/api/system/csv-export/run-now")
    assert run_response.status_code == 200, run_response.text
    outcomes = run_response.json()["outcomes"]
    assert any(o["monitor_id"] == monitor.id and o["status"] == "written" for o in outcomes)

    assert (tmp_path / "argus_hourly_readings_test.csv").exists()
    assert not (tmp_path / "argus_hourly_readings.csv").exists()  # 本番ファイルは作られない

    status = client.get("/api/system/csv-export").json()
    row = next(m for m in status["monitors"] if m["monitor_id"] == monitor.id)
    assert row["last_exported_hour"] is None  # 本番のdedupログは更新されない
    assert row["last_exported_at"] is None
    assert status["last_test_run_at"] is not None  # テスト実行時刻はUI確認用に反映される

    # 何度でも実行できる(dedupされない)。
    run_response_2 = client.post("/api/system/csv-export/run-now")
    outcomes_2 = run_response_2.json()["outcomes"]
    assert any(o["monitor_id"] == monitor.id and o["status"] == "written" for o in outcomes_2)
    lines = (tmp_path / "argus_hourly_readings_test.csv").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) - 1 == 2  # header 1 + データ2行
