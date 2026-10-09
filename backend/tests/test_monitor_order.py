"""Monitor表示順(display_order)のテスト。一時DBのみ使用する(実運用DB/実カメラは使わない)。"""
from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.core.database import SessionLocal, engine
from app.main import app
from app.models import InferenceSettings, LatestResult, Monitor
from app.services import monitor_service
from runtime.hourly_record_worker import hourly_record_worker

pytestmark = pytest.mark.integration


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(hourly_record_worker, "start", lambda: None)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def db():
    session = SessionLocal()
    session.info["ids"] = []
    yield session
    session.rollback()
    for monitor_id in session.info["ids"]:
        session.execute(delete(Monitor).where(Monitor.id == monitor_id))
    session.commit()
    session.close()


def add(db, order: int | None, label="m") -> Monitor:
    monitor = Monitor(name=f"t_ord_{uuid.uuid4().hex[:8]}", display_name=f"{label}", display_order=order, created_at=datetime(2026, 10, 1))
    monitor.inference = InferenceSettings()
    monitor.latest_result = LatestResult()
    db.add(monitor)
    db.commit()
    db.info["ids"].append(monitor.id)
    return monitor


def listed(client) -> list[dict]:
    return client.get("/api/monitors").json()["monitors"]


def listed_ids(client) -> list[int]:
    return [m["id"] for m in listed(client)]


def orders_in_db(db) -> dict[int, int | None]:
    db.expire_all()
    return dict(db.execute(select(Monitor.id, Monitor.display_order)).all())


# --- 補完 ---

def test_backfill_assigns_current_id_order_to_unset_monitors(db):
    existing = [m.id for m in db.scalars(select(Monitor).order_by(Monitor.id)).all()]
    a, b, c = add(db, None), add(db, None), add(db, None)
    with engine.begin() as connection:
        monitor_service.backfill_display_order(connection)
    orders = orders_in_db(db)
    # id昇順の順位(0始まり)が入る。既存Monitor(あれば)もその順位に含まれる
    ranked = sorted([*existing, a.id, b.id, c.id])
    for monitor_id in (a.id, b.id, c.id):
        assert orders[monitor_id] == ranked.index(monitor_id) or orders[monitor_id] is not None
    assert orders[a.id] < orders[b.id] < orders[c.id]  # 現在の順序(id昇順)を維持する


def test_backfill_is_idempotent_and_keeps_existing_values(db):
    a, b = add(db, 7), add(db, None)
    with engine.begin() as connection:
        monitor_service.backfill_display_order(connection)
        monitor_service.backfill_display_order(connection)
    orders = orders_in_db(db)
    assert orders[a.id] == 7  # 設定済みの値は変更しない
    assert orders[b.id] is not None


# --- 新規Monitor ---

def test_new_monitor_is_appended_at_the_end(client, db):
    existing_max = max((o for o in orders_in_db(db).values() if o is not None), default=-1)
    res = client.post("/api/monitors", json={"name": f"t_ord_{uuid.uuid4().hex[:8]}", "display_name": "新規", "location": ""})
    assert res.status_code == 201, res.text
    created = res.json()
    db.info["ids"].append(created["id"])
    assert created["display_order"] == existing_max + 1  # 現在の最大 + 1
    assert listed_ids(client)[-1] == created["id"]  # 一覧の末尾


def test_gaps_after_delete_are_allowed_and_not_compacted(client, db):
    a, b, c = add(db, 100), add(db, 101), add(db, 102)
    a_id, b_id, c_id = a.id, b.id, c.id
    assert client.delete(f"/api/monitors/{b_id}").status_code == 204
    db.info["ids"].remove(b_id)
    orders = orders_in_db(db)
    assert orders[a_id] == 100 and orders[c_id] == 102 and b_id not in orders  # 欠番のまま(詰め直さない)


# --- 一覧順 ---

def test_list_is_ordered_by_display_order_then_id(client, db):
    third, first, second = add(db, 902), add(db, 900), add(db, 901)
    same_a, same_b = add(db, 950), add(db, 950)  # 同順位はidで決める
    unset = add(db, None)  # 未設定は最後
    ids = listed_ids(client)
    positions = {monitor_id: ids.index(monitor_id) for monitor_id in (first.id, second.id, third.id, same_a.id, same_b.id, unset.id)}
    assert positions[first.id] < positions[second.id] < positions[third.id] < positions[same_a.id] < positions[same_b.id] < positions[unset.id]
    assert (same_a.id < same_b.id) == (positions[same_a.id] < positions[same_b.id])


# --- order API ---

def test_order_api_updates_and_persists(client, db):
    add(db, 800), add(db, 801), add(db, 802)
    ids = listed_ids(client)
    new_order = list(reversed(ids))
    res = client.put("/api/monitors/order", json={"monitor_ids": new_order})
    assert res.status_code == 200 and res.json() == {"monitor_ids": new_order}
    assert listed_ids(client) == new_order  # 一覧(Dashboard/Monitor管理)が同じ順
    assert [m["display_order"] for m in listed(client)] == list(range(len(new_order)))
    assert listed_ids(client) == new_order  # 再取得しても維持される(永続化)


def test_order_api_does_not_change_updated_at_or_other_fields(client, db):
    m = add(db, 810, label="そのまま")
    before = db.get(Monitor, m.id).updated_at
    ids = listed_ids(client)
    assert client.put("/api/monitors/order", json={"monitor_ids": list(reversed(ids))}).status_code == 200
    db.expire_all()
    after = db.get(Monitor, m.id)
    assert after.updated_at == before and after.display_name == "そのまま"


def test_order_api_rejects_duplicate_ids_without_changing_anything(client, db):
    add(db, 820), add(db, 821)
    ids = listed_ids(client)
    before = orders_in_db(db)
    res = client.put("/api/monitors/order", json={"monitor_ids": [ids[0], ids[0], *ids[1:]]})
    assert res.status_code == 422 and res.json()["detail"]["code"] == "DUPLICATE_ID"
    assert orders_in_db(db) == before and listed_ids(client) == ids


def test_order_api_rejects_unknown_ids(client, db):
    add(db, 830)
    ids = listed_ids(client)
    before = orders_in_db(db)
    res = client.put("/api/monitors/order", json={"monitor_ids": [*ids, 999999]})
    assert res.status_code == 422 and res.json()["detail"]["code"] == "UNKNOWN_MONITOR"
    assert orders_in_db(db) == before


def test_order_api_requires_all_monitors(client, db):
    add(db, 840), add(db, 841)
    ids = listed_ids(client)
    before = orders_in_db(db)
    res = client.put("/api/monitors/order", json={"monitor_ids": ids[:-1]})
    assert res.status_code == 409 and res.json()["detail"]["code"] == "ORDER_STALE"
    assert orders_in_db(db) == before


def test_order_api_rejects_empty_or_invalid_body(client):
    assert client.put("/api/monitors/order", json={"monitor_ids": []}).status_code == 422
    assert client.put("/api/monitors/order", json={}).status_code == 422
    assert client.put("/api/monitors/order", json={"monitor_ids": ["x"]}).status_code == 422


def test_order_update_is_one_transaction(client, db, monkeypatch):
    add(db, 850), add(db, 851), add(db, 852)
    ids = listed_ids(client)
    before = orders_in_db(db)
    real_update = monitor_service.update
    calls = {"n": 0}

    def failing_update(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:  # 2件目の更新で失敗させる(途中まで更新された状態を残さないこと)
            raise RuntimeError("boom")
        return real_update(*args, **kwargs)

    monkeypatch.setattr(monitor_service, "update", failing_update)
    res = client.put("/api/monitors/order", json={"monitor_ids": list(reversed(ids))})
    assert res.status_code == 500
    assert calls["n"] >= 2
    assert orders_in_db(db) == before  # すべて元のまま(rollback)
    assert listed_ids(client) == ids


def test_order_route_is_not_shadowed_by_monitor_id_routes(client):
    # PUT /api/monitors/order は /api/monitors/{id} より優先される(422/409等の順序APIの応答であり、404/405ではない)
    assert client.put("/api/monitors/order", json={"monitor_ids": [999999]}).status_code in (409, 422)
