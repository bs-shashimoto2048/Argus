"""読取値の手動修正の安全確認: 前後の正式値・読取基準値・最大変化率から極端に乖離した補正値(桁落ち等)は、2段階確認(force)なしでは保存しない。

実例(Monitor 4 2026-10-13 13:00 record 96): 正式値 372457.6 を、invalid_formatのRaw 37245.7 で補正してしまい、14:00のusageが335214.1になった。
一時DBのみ使用する。
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import InferenceSettings, ReadingBaseline, ReadingBaselineEvent, ReadingRecord, ReadingRecordCorrection
from tests.test_record_corrections import add_record, client, correct, db, make_monitor  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration


def held(db, monitor, hour, value, **over):
    return add_record(db, monitor, hour, value, value_source="carried_forward", validation_status="invalid_format", usage=None, **over)


def scenario(db, **monitor_kw):
    """12:00=372454.2(confirmed) / 13:00=372457.6(carried_forward, 修正対象) / 14:00=372459.8(confirmed)。"""
    m = make_monitor(db, **monitor_kw)
    add_record(db, m, 12, "372454.2")
    r13 = held(db, m, 13, "372457.6", raw_value="37245.7")
    add_record(db, m, 14, "372459.8", usage=None)
    return m, r13


def corrections_of(db, record_id):
    db.expire_all()
    return db.scalars(select(ReadingRecordCorrection).where(ReadingRecordCorrection.record_id == record_id).order_by(ReadingRecordCorrection.id)).all()


def test_a_dropped_digit_is_not_saved_without_confirmation(client, db):
    _m, r13 = scenario(db, expected_digits=7, decimal_position=1)
    res = correct(client, r13.id, value="37245.7")  # 桁落ち(6桁相当)。expected_digitsの「超えていない」チェックは通る
    assert res.status_code == 409, res.text
    detail = res.json()["detail"]
    assert detail["code"] == "CORRECTION_FORCE_REQUIRED" and "桁落ち・小数点位置" in detail["message"]
    reasons = detail["details"]["reasons"]
    assert {r["reference"] for r in reasons} >= {"直前1時間の正式値", "次の1時間の正式値"}
    assert all(r["kind"] == "scale" and r["digit_shift"] for r in reasons)  # 約1/10倍=桁が1つ落ちたレベル
    db.expire_all()
    rec = db.get(ReadingRecord, r13.id)
    assert (rec.value, rec.correction_count) == ("372457.6", 0) and corrections_of(db, r13.id) == []  # 何も保存されない


@pytest.mark.parametrize("value", ["3724576", "37245.76"])
def test_ten_times_and_one_tenth_corrections_are_flagged(client, db, value):
    _m, r13 = scenario(db, expected_digits=None, decimal_position=None)
    res = correct(client, r13.id, value=value)
    assert res.status_code == 409 and res.json()["detail"]["code"] == "CORRECTION_FORCE_REQUIRED"
    assert any(r["digit_shift"] for r in res.json()["detail"]["details"]["reasons"])


def test_a_normal_correction_close_to_the_neighbors_is_saved_immediately(client, db):
    _m, r13 = scenario(db, expected_digits=7, decimal_position=1)
    res = correct(client, r13.id, value="372457.9")
    assert res.status_code == 200, res.text
    db.expire_all()
    assert db.get(ReadingRecord, r13.id).value == "372457.9"
    assert corrections_of(db, r13.id)[0].context["safety"] == {"deviation_confirmed": False, "reasons": []}


def test_a_confirmed_deviation_is_saved_and_audited_with_the_reasons(client, db):
    _m, r13 = scenario(db, expected_digits=7, decimal_position=1)
    res = correct(client, r13.id, value="37245.7", force=True)  # 確認のうえ保存(メーター交換等の正当な変動もあり得るためhard blockではない)
    assert res.status_code == 200, res.text
    rows = corrections_of(db, r13.id)
    assert len(rows) == 1 and (rows[0].old_value, rows[0].new_value) == ("372457.6", "37245.7")
    assert rows[0].context["safety"]["deviation_confirmed"] is True and rows[0].context["safety"]["reasons"]  # 乖離を確認して保存した記録が監査に残る


def test_a_same_value_correction_is_still_allowed_without_confirmation(client, db):
    _m, r13 = scenario(db, expected_digits=7, decimal_position=1)
    res = correct(client, r13.id, value="372457.6")
    assert res.status_code == 200, res.text
    rows = corrections_of(db, r13.id)
    assert len(rows) == 1 and (rows[0].old_value, rows[0].new_value) == ("372457.6", "372457.6")


def test_record_96_recovery_keeps_both_corrections_and_recomputes_the_following_usage(client, db):
    _m, r13 = scenario(db, expected_digits=7, decimal_position=1)
    assert correct(client, r13.id, value="37245.7", force=True).status_code == 200
    db.expire_all()
    wrong = db.get(ReadingRecord, r13.id)
    r14 = db.scalars(select(ReadingRecord).where(ReadingRecord.monitor_id == wrong.monitor_id, ReadingRecord.hour_bucket.like("%T14:%"))).one()
    assert r14.previous_value == "37245.7" and r14.usage == "335214.1"  # 実例の異常値
    # 保存画像で372457.6を確認 → 再補正(前後の正式値に近いので確認は不要)
    res = correct(client, r13.id, value="372457.6", reason="保存画像で正式値372457.6を確認。invalid_format Raw 37245.7を誤って採用したため")
    assert res.status_code == 200, res.text
    db.expire_all()
    assert db.get(ReadingRecord, r13.id).value == "372457.6"
    r14 = db.get(ReadingRecord, r14.id)
    assert (r14.previous_value, r14.usage) == ("372457.6", "2.2")  # 異常値ではなく正常な差分へ再計算
    rows = corrections_of(db, r13.id)
    assert [(r.old_value, r.new_value) for r in rows] == [("372457.6", "37245.7"), ("37245.7", "372457.6")]  # 誤補正の履歴も削除せず両方残る


def test_a_change_beyond_the_max_rate_requires_confirmation(client, db):
    m = make_monitor(db, expected_digits=None)
    m.inference.reading = {"enabled": True, "expected_digits": None, "decimal_position": None, "max_rate_per_minute": 1}  # 1分あたり最大1 = 1時間で60
    db.commit()
    add_record(db, m, 12, "100")
    r13 = held(db, m, 13, "110")
    assert correct(client, r13.id, value="150").status_code == 200  # +50 ≦ 60
    res = correct(client, r13.id, value="190")  # +90 > 60 (倍率は2倍未満なのでscaleではなくrate)
    assert res.status_code == 409
    reasons = res.json()["detail"]["details"]["reasons"]
    assert reasons[0]["kind"] == "rate" and reasons[0]["reference"] == "直前1時間の正式値"


def test_the_current_baseline_is_also_a_reference(client, db):
    m = make_monitor(db, expected_digits=None)
    r13 = held(db, m, 13, "372457.6")  # 前後のrecordなし
    db.add(ReadingBaseline(monitor_id=m.id, value="372457.6", numeric_value="372457.6", state="active", epoch=0))
    db.commit()
    res = correct(client, r13.id, value="37245.7")
    assert res.status_code == 409 and res.json()["detail"]["details"]["reasons"][0]["reference"] == "現在の読取基準値"
    assert db.scalars(select(ReadingBaselineEvent).where(ReadingBaselineEvent.monitor_id == m.id)).all() == []  # 確認の要求でbaselineは変えない


def test_no_neighbors_and_no_baseline_means_nothing_to_compare(client, db):
    m = make_monitor(db, expected_digits=None)
    r13 = held(db, m, 13, "372457.6")
    assert correct(client, r13.id, value="37245.7").status_code == 200  # 比較できる基準が無い場合は確認を要求しない
