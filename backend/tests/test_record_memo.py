"""記録単位の運用メモ(reading_records.memo / PATCH /api/records/{id}/memo)のテスト。一時DBのみ使用する。"""
from __future__ import annotations

from sqlalchemy import create_engine, text

from tests.test_excel_export import add_record, client, db, make_monitor  # noqa: F401  fixtureの再利用
from fastapi.testclient import TestClient
from app.main import app

import pytest

pytestmark = pytest.mark.integration

# メモ以外の全フィールド(AI読取・正式値・usage・修正・baseline等)。メモ更新でこれが変わらないこと。
def _others(body: dict) -> dict:
    return {k: v for k, v in body.items() if k != "memo"}


def patch(client, record_id, memo):
    return client.patch(f"/api/records/{record_id}/memo", json={"memo": memo})


def test_existing_db_without_memo_column_is_migrated(monkeypatch, tmp_path):
    legacy = create_engine(f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}")
    # memo列追加前のDBを再現する(現行のテーブルからmemo列だけを外す)。
    from app.core.database import Base
    Base.metadata.create_all(legacy)
    with legacy.begin() as connection:
        connection.execute(text("ALTER TABLE reading_records DROP COLUMN memo"))
        connection.execute(text("INSERT INTO reading_records (id, monitor_id, monitor_name, hour_bucket, recorded_at, value, image_status, value_source, display_status, baseline_conflict, correction_count) VALUES (1, 1, 'm', 'h', '2026-10-08 00:00:00', '123', 'not_saved', 'confirmed', 'normal', 0, 0)"))
    monkeypatch.setattr("app.main.engine", legacy)
    with TestClient(app):
        pass
    with legacy.connect() as connection:
        assert "memo" in {row[1] for row in connection.execute(text("PRAGMA table_info(reading_records)")).all()}
        row = connection.execute(text("SELECT value, memo FROM reading_records WHERE id = 1")).one()
    assert tuple(row) == ("123", None)  # 既存データは書き換えない


def test_new_record_has_no_memo_and_get_includes_it(client, db):
    record = add_record(db, make_monitor(db, "メモ初期"))
    assert client.get(f"/api/records/{record.id}").json()["memo"] is None
    items = client.get("/api/records", params={"monitor_id": record.monitor_id, "limit": 10}).json()["items"]
    assert items[0]["memo"] is None


def test_save_change_and_clear_memo(client, db):
    record = add_record(db, make_monitor(db, "メモ保存"))
    res = patch(client, record.id, "現場確認済み")
    assert res.status_code == 200 and res.json()["memo"] == "現場確認済み"
    assert client.get(f"/api/records/{record.id}").json()["memo"] == "現場確認済み"
    assert patch(client, record.id, "  再確認  ").json()["memo"] == "再確認"  # 前後の空白は除く
    for empty in ("", "   "):
        patch(client, record.id, "x")
        res = patch(client, record.id, empty)
        assert res.status_code == 200 and res.json()["memo"] is None  # 空文字=削除(NULL)
    items = client.get("/api/records", params={"monitor_id": record.monitor_id}).json()["items"]
    assert items[0]["memo"] is None


def test_memo_length_limit(client, db):
    record = add_record(db, make_monitor(db, "メモ長"))
    assert patch(client, record.id, "あ" * 500).status_code == 200
    assert client.get(f"/api/records/{record.id}").json()["memo"] == "あ" * 500
    assert patch(client, record.id, "あ" * 501).status_code == 422
    assert client.get(f"/api/records/{record.id}").json()["memo"] == "あ" * 500  # 失敗しても変わらない


def test_memo_for_unknown_record_is_404(client):
    assert patch(client, 99999999, "x").status_code == 404


def test_memo_update_changes_nothing_else(client, db):
    record = add_record(db, make_monitor(db, "メモ不変"), previous_value="265800", usage="3", correction_count=2, original_value="265700", baseline_conflict=True)
    before = client.get(f"/api/records/{record.id}").json()
    corrections_before = client.get(f"/api/records/{record.id}/corrections").json()
    after = patch(client, record.id, "メモのみ").json()
    assert after["memo"] == "メモのみ" and _others(after) == _others(before)
    assert client.get(f"/api/records/{record.id}/corrections").json() == corrections_before
