"""usageは「その時刻に保存された正式値 - 直前1時間の正式値」で計算する(値の由来 confirmed / carried_forward・baseline conflictは問わない)。

連続性が切れる場合(直前record欠損・正式値なし・通信異常/read_error等・運用者のreset/別値rebase)は、次の正式値が新しい区間の開始点(usage 0)。
同じ値への手動補正も、運用者が画像等で確認した監査記録として許可する。一時DBのみ使用する。
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import ReadingBaselineEvent, ReadingRecord, ReadingRecordCorrection
from app.services.reading_correction_service import _recompute_usage
from app.services.reading_record_service import is_usage_eligible_record
from tests.test_record_corrections import add_record, client, correct, db, make_monitor  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration


def cf(db, monitor, hour, value, **over):
    return add_record(db, monitor, hour, value, value_source="carried_forward", validation_status="invalid_format", usage=None, **over)


def recompute_all(db, monitor):
    """バックフィルと同じ: 時系列順に previous_value / usage を再計算する。{hour: (previous_value, usage)}"""
    db.expire_all()
    rows = db.scalars(select(ReadingRecord).where(ReadingRecord.monitor_id == monitor.id).order_by(ReadingRecord.hour_bucket)).all()
    for row in rows:
        row.usage = _recompute_usage(db, row, monitor.created_at)
    db.commit()
    return {int(r.hour_bucket[11:13]): (r.previous_value, r.usage) for r in rows}


def usages(db, monitor):
    db.expire_all()
    rows = db.scalars(select(ReadingRecord).where(ReadingRecord.monitor_id == monitor.id).order_by(ReadingRecord.hour_bucket)).all()
    return {int(r.hour_bucket[11:13]): r.usage for r in rows}


def event(db, monitor, record, action, new_value=None, minutes=30):
    db.add(ReadingBaselineEvent(monitor_id=monitor.id, monitor_name="m", occurred_at=record.recorded_at - timedelta(minutes=minutes), action=action, old_value="100", new_value=new_value, reason="t", operator="o", client_host="h"))
    db.commit()


def test_case1_carried_forward_with_the_same_value_is_zero(db):
    m = make_monitor(db)
    add_record(db, m, 18, "100")
    cf(db, m, 19, "100")
    assert recompute_all(db, m)[19] == ("100", "0")


def test_case2_carried_forward_value_that_rose_uses_the_difference(db):
    m = make_monitor(db)
    add_record(db, m, 18, "100")
    cf(db, m, 19, "105")  # 18:30に正常Confirmedで105になった後、19:00はRaw異常で正式値105を保持
    assert recompute_all(db, m)[19] == ("100", "5")


def test_case3_consecutive_carried_forward(db):
    m = make_monitor(db)
    add_record(db, m, 18, "100")
    cf(db, m, 19, "105")
    cf(db, m, 20, "105")
    cf(db, m, 21, "105")
    result = recompute_all(db, m)
    assert (result[19][1], result[20][1], result[21][1]) == ("5", "0", "0")


def test_case4_carried_forward_without_a_previous_record_starts_a_section_at_zero(db):
    m = make_monitor(db)
    cf(db, m, 19, "105")
    assert recompute_all(db, m)[19] == (None, "0")


def test_case5_previous_record_without_a_value_makes_the_current_value_a_restart_point(db):
    m = make_monitor(db)
    add_record(db, m, 18, None, value_source="none", numeric_value=None, validation_status=None, display_status="error", usage=None)
    add_record(db, m, 19, "105", usage=None)
    assert recompute_all(db, m) == {18: (None, None), 19: (None, "0")}  # 値なし自身はnull、次の正式値は開始点


def test_case6_a_decreased_value_is_null(db):
    m = make_monitor(db)
    add_record(db, m, 18, "100")
    cf(db, m, 19, "95")
    assert recompute_all(db, m)[19] == ("100", None)


def test_case7_after_an_operator_reset_or_a_rebase_to_another_value_the_next_value_restarts(db):
    for action, new_value in (("reset", None), ("rebase", "999")):
        m = make_monitor(db)
        add_record(db, m, 18, "100")
        r19 = cf(db, m, 19, "105")
        event(db, m, r19, action, new_value)
        assert recompute_all(db, m)[19] == (None, "0"), action  # 差分5を計上しない


def test_a_rebase_to_a_confirmed_value_or_an_automatic_clear_does_not_break_continuity(db):
    for action, new_value in (("rebase", "105"), ("rebase", "100"), ("auto_semantic_reset", None)):
        m = make_monitor(db)
        add_record(db, m, 18, "100")
        r19 = cf(db, m, 19, "105")
        event(db, m, r19, action, new_value)
        assert recompute_all(db, m)[19] == ("100", "5"), (action, new_value)


def test_case8_baseline_conflict_does_not_nullify_the_held_value(db):
    m = make_monitor(db)
    add_record(db, m, 18, "100")
    cf(db, m, 19, "100", baseline_conflict=True)
    cf(db, m, 20, "100", baseline_conflict=True)
    result = recompute_all(db, m)
    assert (result[19][1], result[20][1]) == ("0", "0")


def test_a_missing_hour_and_communication_errors_are_restart_points(db):
    m = make_monitor(db)
    add_record(db, m, 14, "100")
    cf(db, m, 17, "110")  # 15・16時のrecordなし
    add_record(db, m, 18, "112", display_status="error", usage=None)  # 通信異常: 正式値は保持していても連続性を保証できない
    add_record(db, m, 19, "113", usage=None)
    result = recompute_all(db, m)
    assert result[17] == (None, "0") and result[18][1] is None and result[19] == (None, "0")


def test_eligibility_depends_on_the_formal_value_not_on_its_origin(db):
    m = make_monitor(db)
    assert is_usage_eligible_record(add_record(db, m, 14, "100"))
    assert is_usage_eligible_record(cf(db, m, 15, "100"))  # 未修正のcarried_forwardでも対象
    assert is_usage_eligible_record(cf(db, m, 16, "100", baseline_conflict=True))
    assert not is_usage_eligible_record(add_record(db, m, 17, "100", display_status="read_error"))  # 連続性を保証できない
    assert is_usage_eligible_record(add_record(db, m, 18, "100", display_status="read_error", correction_count=1))  # 運用者確認済み
    assert not is_usage_eligible_record(add_record(db, m, 19, None, numeric_value=None, value_source="none"))
    assert not is_usage_eligible_record(None)


def test_case9_a_correction_with_the_same_value_is_accepted_and_audited(client, db):
    m = make_monitor(db)
    add_record(db, m, 18, "100")
    r19 = cf(db, m, 19, "100", raw_value="0099", raw_confidence=0.7, baseline_conflict=True)
    evidence = {n: getattr(r19, n) for n in ("value", "numeric_value", "raw_value", "raw_confidence", "validation_status", "value_source", "baseline_conflict", "original_image_path", "overlay_image_path", "inference_at")}
    res = correct(client, r19.id, value="100")
    assert res.status_code == 200, res.text
    db.expire_all()
    rec = db.get(ReadingRecord, r19.id)
    assert rec.correction_count == 1 and rec.corrected_by and rec.corrected_at is not None and rec.original_value == "100"
    assert {n: getattr(rec, n) for n in evidence} == evidence  # 元証跡は不変
    rows = db.scalars(select(ReadingRecordCorrection).where(ReadingRecordCorrection.record_id == r19.id)).all()
    assert len(rows) == 1 and (rows[0].old_value, rows[0].new_value) == ("100", "100") and rows[0].reason and rows[0].operator  # 100 → 100 の監査履歴
    assert rec.usage == "0"
    assert correct(client, r19.id, value="100").status_code == 200  # 繰り返し確認しても履歴が追加される
    db.expire_all()
    assert db.get(ReadingRecord, r19.id).correction_count == 2


def test_a_same_value_correction_does_not_touch_the_baseline(client, db):
    m = make_monitor(db)
    add_record(db, m, 18, "100")
    r19 = cf(db, m, 19, "100")
    assert correct(client, r19.id, value="100").status_code == 200
    db.expire_all()
    assert db.scalars(select(ReadingBaselineEvent).where(ReadingBaselineEvent.monitor_id == m.id)).all() == []  # 明示しない限りbaseline操作はしない


def test_case10_after_a_correction_the_following_usage_is_recomputed_in_order(client, db):
    m = make_monitor(db)
    add_record(db, m, 17, "90")
    r18 = cf(db, m, 18, "99")  # 誤って保持されていた値(修正対象)
    cf(db, m, 19, "105")
    cf(db, m, 20, "105")
    add_record(db, m, 21, "110", usage=None)
    assert correct(client, r18.id, value="100").status_code == 200
    result = usages(db, m)
    assert (result[18], result[19], result[20], result[21]) == ("10", "5", "0", "5")  # 旧規則で保存されたnullの後続も、継続範囲まで順次再計算


def test_a_same_value_correction_recomputes_stale_following_usage(client, db):
    m = make_monitor(db)
    add_record(db, m, 18, "100")
    r19 = cf(db, m, 19, "100")
    cf(db, m, 20, "100")
    cf(db, m, 21, "100")  # usageは旧規則でnullのまま
    assert correct(client, r19.id, value="100").status_code == 200
    result = usages(db, m)
    assert (result[19], result[20], result[21]) == ("0", "0", "0")
