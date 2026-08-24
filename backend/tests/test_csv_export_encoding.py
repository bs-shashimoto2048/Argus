"""CSV出力のUTF-8 BOM対応(Issue #21)のテスト。

日本語display_nameがExcelで文字化けする問題への対応として、CSVファイルの先頭に
UTF-8 BOMを(1度だけ)付与する。既存のBOM無しUTF-8ファイルへの追記でも、内容を
壊さずBOMを後付けできることを確認する。

Issue #17の既存仕様(単一ファイル追記・本番/テスト分離・timestamp_jst表記・
dedup・locking)には回帰がないことも確認する。実DB(data/argus.db)は使用しない
(test_csv_export.pyと同じ、tmp_path上の専用SQLiteによる完全分離設計)。
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models import InferenceSettings, LatestResult, Monitor
from app.services import csv_export_service as svc

_UTF8_BOM = b"\xef\xbb\xbf"


@pytest.fixture
def isolated_session_factory(tmp_path):
    db_path = tmp_path / "isolated_csv_export_encoding_test.db"
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


def _make_monitor(db, name, display_name, *, value="100", confidence=0.9, status="ok", engine="ultralytics", model_id=None) -> Monitor:
    monitor = Monitor(name=name, display_name=display_name, location="test")
    monitor.inference = InferenceSettings(model_id=model_id)
    monitor.latest_result = LatestResult(value=value, confidence=confidence, status=status, engine=engine)
    db.add(monitor)
    db.commit()
    db.refresh(monitor)
    return monitor


# --- 新規ファイル: BOM付き・UTF-8として正しく復号できる -----------------------

def test_new_file_has_bom_prefix_and_decodes_as_utf8(tmp_path):
    row = ["2026/08/24 14:00:00", "1", "meter_1", "エネルギー計測器", "0025.60", "0.9000", "ok", "ultralytics", ""]
    svc._append_csv_row(str(tmp_path), "sample.csv", row)

    path = tmp_path / "sample.csv"
    raw = path.read_bytes()
    assert raw.startswith(_UTF8_BOM)

    # BOM込みでutf-8-sigとしてデコードすると正しく日本語が読める。
    text = raw.decode("utf-8-sig")
    assert "エネルギー計測器" in text
    lines = text.strip().splitlines()
    assert lines[0] == ",".join(svc.CSV_HEADER)
    assert lines[1].split(",")[3] == "エネルギー計測器"


def test_bom_appears_exactly_once_at_file_start_not_elsewhere(tmp_path):
    raw_before = None
    for i in range(3):
        row = [f"2026/08/24 1{i}:00:00", "1", "meter_1", "食洗機モニター", "100", "", "ok", "ultralytics", ""]
        svc._append_csv_row(str(tmp_path), "sample.csv", row)

    path = tmp_path / "sample.csv"
    raw = path.read_bytes()
    assert raw.count(_UTF8_BOM) == 1
    assert raw.startswith(_UTF8_BOM)
    # BOMを除いた本文中には出現しない。
    assert _UTF8_BOM not in raw[len(_UTF8_BOM):]

    text = raw.decode("utf-8-sig")
    lines = text.strip().splitlines()
    assert len(lines) == 4  # header + 3行
    for line in lines[1:]:
        assert "食洗機モニター" in line


# --- 既存BOM無しUTF-8ファイルへの安全な移行 ----------------------------------

def test_existing_bomless_utf8_file_is_migrated_and_preserves_data(tmp_path):
    path = tmp_path / "legacy.csv"
    # Issue #21修正前の挙動(BOM無しプレーンUTF-8)を再現する。
    legacy_content = ",".join(svc.CSV_HEADER) + "\r\n" + "2026/08/24 09:00:00,2,meter_2,ガス使用量,0100.00,0.8000,ok,ultralytics,\r\n"
    path.write_bytes(legacy_content.encode("utf-8"))
    assert not path.read_bytes().startswith(_UTF8_BOM)

    new_row = ["2026/08/24 10:00:00", "2", "meter_2", "ガス使用量", "0101.00", "0.8100", "ok", "ultralytics", ""]
    svc._append_csv_row(str(tmp_path), "legacy.csv", new_row)

    raw = path.read_bytes()
    assert raw.startswith(_UTF8_BOM)
    assert raw.count(_UTF8_BOM) == 1

    text = raw.decode("utf-8-sig")
    lines = text.strip().splitlines()
    assert lines[0] == ",".join(svc.CSV_HEADER)
    assert len(lines) == 3  # header + 旧1行 + 新1行(headerが重複していない)
    assert "0100.00" in lines[1] and "ガス使用量" in lines[1]  # 既存行のデータは壊れていない
    assert "0101.00" in lines[2] and "ガス使用量" in lines[2]  # 新規行も正しく追記される


def test_existing_ascii_only_bomless_file_is_migrated_without_corruption(tmp_path):
    """日本語を含まない既存データでも、BOM移行で値が変化しない(文字化け/破損しない)こと。"""
    path = tmp_path / "ascii_legacy.csv"
    legacy_content = ",".join(svc.CSV_HEADER) + "\r\n" + "2026/08/24 09:00:00,3,meter_3,Meter C,100,0.9000,ok,ultralytics,model.pt\r\n"
    path.write_bytes(legacy_content.encode("utf-8"))

    svc._append_csv_row(str(tmp_path), "ascii_legacy.csv", ["2026/08/24 10:00:00", "3", "meter_3", "Meter C", "101", "0.9100", "ok", "ultralytics", "model.pt"])

    raw = path.read_bytes()
    assert raw.startswith(_UTF8_BOM)
    text = raw.decode("utf-8-sig")
    lines = text.strip().splitlines()
    assert lines[1] == "2026/08/24 09:00:00,3,meter_3,Meter C,100,0.9000,ok,ultralytics,model.pt"
    assert lines[2] == "2026/08/24 10:00:00,3,meter_3,Meter C,101,0.9100,ok,ultralytics,model.pt"


def test_migration_uses_atomic_replace_leaving_no_temp_file(tmp_path):
    path = tmp_path / "legacy2.csv"
    path.write_bytes((",".join(svc.CSV_HEADER) + "\r\n").encode("utf-8"))
    svc._append_csv_row(str(tmp_path), "legacy2.csv", ["2026/08/24 10:00:00", "1", "m", "名前", "1", "", "ok", "ultralytics", ""])
    assert not (tmp_path / "legacy2.csv.bom-migrate.tmp").exists()
    assert (tmp_path / "legacy2.csv").exists()


# --- 本番/テストで同一encoding ------------------------------------------------

def test_production_and_test_files_use_identical_bom_encoding(db, tmp_path):
    monitor = _make_monitor(db, "meter_jp", "冷蔵庫電力計")
    hour = svc.hour_bucket_jst()
    svc.export_monitor_for_hour(db, monitor, hour, str(tmp_path))
    svc.export_monitor_for_test(monitor, hour, str(tmp_path))

    prod_raw = (tmp_path / svc.CSV_FILENAME_PRODUCTION).read_bytes()
    test_raw = (tmp_path / svc.CSV_FILENAME_TEST).read_bytes()
    assert prod_raw.startswith(_UTF8_BOM)
    assert test_raw.startswith(_UTF8_BOM)
    assert "冷蔵庫電力計" in prod_raw.decode("utf-8-sig")
    assert "冷蔵庫電力計" in test_raw.decode("utf-8-sig")


# --- Issue #17仕様への回帰がないこと ------------------------------------------

def test_dedup_and_timestamp_format_unaffected_by_bom_change(db, tmp_path):
    monitor = _make_monitor(db, "meter_regression", "エアコン室外機")
    hour = svc.hour_bucket_jst(datetime(2026, 8, 24, 5, 0, tzinfo=timezone.utc))  # JST 14:00
    first = svc.export_monitor_for_hour(db, monitor, hour, str(tmp_path))
    second = svc.export_monitor_for_hour(db, monitor, hour, str(tmp_path))
    assert first.status == "written"
    assert second.status == "skipped_already_exported"  # dedupは維持

    raw = (tmp_path / svc.CSV_FILENAME_PRODUCTION).read_bytes()
    text = raw.decode("utf-8-sig")
    lines = text.strip().splitlines()
    assert len(lines) == 2  # header + 1行のみ(二重出力なし)
    assert lines[1].split(",")[0] == "2026/08/24 14:00:00"  # timestamp_jst表記は不変


def test_concurrent_appends_still_produce_single_bom_and_no_corruption(tmp_path):
    """複数スレッドが同時に同一ファイルへ追記しても、BOMは1個だけ・行は破損しない
    (Issue #17のlocking回帰確認 + BOM追加後も排他が機能すること)。"""
    def write_once(i):
        row = [f"2026/08/24 1{i % 10}:00:00", "1", "meter_1", "同時書込テスト", str(i), "", "ok", "ultralytics", ""]
        return svc._append_csv_row(str(tmp_path), "concurrent.csv", row)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(write_once, range(20)))

    raw = (tmp_path / "concurrent.csv").read_bytes()
    assert raw.count(_UTF8_BOM) == 1
    assert raw.startswith(_UTF8_BOM)
    text = raw.decode("utf-8-sig")
    lines = text.strip().splitlines()
    assert lines.count(",".join(svc.CSV_HEADER)) == 1
    assert len(lines) - 1 == 20
    for line in lines[1:]:
        assert len(line.split(",")) == len(svc.CSV_HEADER)
