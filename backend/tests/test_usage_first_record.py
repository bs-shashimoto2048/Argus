"""usageの「前回recordが存在しない」ケース(計測開始・停止後の再開・期間内の最初)のテスト。

previous recordが存在しない + 今回がtrusted → usage=0(新しい連続区間の開始点)。
previous recordが存在するのにuntrusted、または今回がuntrusted → null(従来どおり)。
一時DBのみ使用する。
"""
from __future__ import annotations

import io

import pytest
from openpyxl import load_workbook

from app.services import reading_record_service as svc
from tests.test_reading_records import jst, make_monitor, records_of, set_latest
from tests.test_reading_records import db as records_db  # noqa: F401  (fixture)
from tests.test_record_corrections import add_record, client, make_monitor as make_monitor_for_export  # noqa: F401
from tests.test_record_corrections import db as corrections_db  # noqa: F401

pytestmark = pytest.mark.integration


def untrusted(monkeypatch):
    """記録時の最新Rawが棄却中(回転途中)=未修正のcarried_forwardになる。"""
    monkeypatch.setattr(svc, "_live_raw_and_validation", lambda _id: ("0.0", "decrease_detected"))


@pytest.fixture
def db(records_db):  # noqa: F811
    return records_db


def test_case1_first_trusted_record_has_zero_usage(db):
    monitor = make_monitor(db, value="100")
    svc.record_due(db, jst(10, 0, 5))
    (first,) = records_of(db, monitor.id)
    assert (first.previous_value, first.usage) == (None, "0")


def test_case2_second_record_uses_difference(db):
    monitor = make_monitor(db, value="100")
    svc.record_due(db, jst(10, 0, 5))
    set_latest(db, monitor, value="105")
    svc.record_due(db, jst(11, 0, 5))
    first, second = records_of(db, monitor.id)
    assert first.usage == "0" and (second.previous_value, second.usage) == ("100", "5")


def test_case3_resume_after_a_gap_does_not_count_the_gap(db):
    monitor = make_monitor(db, value="100")
    svc.record_due(db, jst(8, 0, 5))
    set_latest(db, monitor, value="110")
    svc.record_due(db, jst(13, 0, 5))  # 9〜12時のrecordなし
    first, resumed = records_of(db, monitor.id)
    assert (resumed.previous_value, resumed.usage) == (None, "0")  # 08:00との差10を計上しない


def test_case4_untrusted_first_record_stays_null(db, monkeypatch):
    monitor = make_monitor(db, value="100")
    untrusted(monkeypatch)
    svc.record_due(db, jst(10, 0, 5))
    (first,) = records_of(db, monitor.id)
    assert first.value_source == "carried_forward" and (first.previous_value, first.usage) == (None, None)


def test_case5_untrusted_previous_record_still_blocks_usage(db, monkeypatch):
    monitor = make_monitor(db, value="100")
    svc.record_due(db, jst(10, 0, 5))
    untrusted(monkeypatch)
    set_latest(db, monitor, value="105")
    svc.record_due(db, jst(11, 0, 5))
    monkeypatch.undo()
    set_latest(db, monitor, value="110")
    svc.record_due(db, jst(12, 0, 5))
    r10, r11, r12 = records_of(db, monitor.id)
    assert (r10.usage, r11.usage, r12.usage) == ("0", None, None)  # previousは存在するがuntrusted → null


def test_case7_excel_first_record_has_blank_previous_and_zero_usage(client, corrections_db):  # noqa: F811
    m = make_monitor_for_export(corrections_db)
    add_record(corrections_db, m, 14, "100", previous_value=None, usage="0")
    add_record(corrections_db, m, 15, "105", previous_value="100", usage="5")
    res = client.post("/api/records/export/excel", json={"monitor_ids": [m.id], "from": "2026-10-09T00:00:00+09:00", "to": "2026-10-10T00:00:00+09:00"})
    assert res.status_code == 200
    ws = load_workbook(io.BytesIO(res.content)).worksheets[0]
    rows = {r[0].value.hour: [c.value for c in r] for r in ws.iter_rows(min_row=2)}
    assert rows[14][4] in (None, "") and rows[14][5] == 0
    assert rows[15][4] == 100 and rows[15][5] == 5
