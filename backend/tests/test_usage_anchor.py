"""手動修正済みrecordを「trusted anchor」とした、同じ値のcarried_forwardの継続(usage=0)と、その再計算のテスト。一時DBのみ使用する。"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import ReadingRecord
from app.services.reading_correction_service import _recompute_usage
from tests.test_record_corrections import add_record, client, correct, db, make_monitor  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration


def cf(db, monitor, hour, value, **over):
    return add_record(db, monitor, hour, value, value_source="carried_forward", validation_status="decrease_detected", usage=None, **over)


def corrected(db, monitor, hour, value):
    return add_record(db, monitor, hour, value, value_source="carried_forward", validation_status="decrease_detected", correction_count=1, original_value="0")


def recompute_all(db, monitor):
    """バックフィルと同じ: 時系列順に usage / previous_value を再計算する。"""
    db.expire_all()
    rows = db.scalars(select(ReadingRecord).where(ReadingRecord.monitor_id == monitor.id).order_by(ReadingRecord.hour_bucket)).all()
    for row in rows:
        row.usage = _recompute_usage(db, row, monitor.created_at)
    db.commit()
    return {int(r.hour_bucket[11:13]): (r.previous_value, r.usage) for r in rows}


def test_caseA_first_trusted_record_has_zero_usage(db):
    m = make_monitor(db)
    add_record(db, m, 14, "100", usage=None)
    assert recompute_all(db, m)[14] == (None, "0")


def test_caseB_carried_forward_continuing_a_corrected_value_is_zero(db):
    m = make_monitor(db)
    add_record(db, m, 14, "95")
    corrected(db, m, 15, "100")
    cf(db, m, 16, "100")
    assert recompute_all(db, m) == {14: (None, "0"), 15: ("95", "5"), 16: ("100", "0")}


def test_caseC_continuation_then_new_confirmed_value(db):
    m = make_monitor(db)
    add_record(db, m, 14, "95")
    corrected(db, m, 15, "100")
    cf(db, m, 16, "100")
    cf(db, m, 17, "100")
    add_record(db, m, 18, "105", usage=None)
    result = recompute_all(db, m)
    assert (result[15][1], result[16][1], result[17][1], result[18][1]) == ("5", "0", "0", "5")
    assert result[17][0] == "100" and result[18][0] == "100"  # previous_valueは直前1時間の正式値


def test_caseD_plain_carried_forward_without_an_anchor_stays_null(db):
    m = make_monitor(db)
    add_record(db, m, 14, "100")
    cf(db, m, 15, "100")
    cf(db, m, 16, "100")
    result = recompute_all(db, m)
    assert (result[14][1], result[15][1], result[16][1]) == ("0", None, None)


def test_caseE_gap_after_the_anchor_starts_a_new_continuous_section(db):
    m = make_monitor(db)
    corrected(db, m, 14, "100")
    cf(db, m, 15, "100")
    add_record(db, m, 18, "110", usage=None)  # 16・17時のrecordなし
    result = recompute_all(db, m)
    assert result[15][1] == "0" and result[18] == (None, "0")  # 10は計上しない


def test_continuation_ends_when_the_value_differs_or_there_is_no_value(db):
    m = make_monitor(db)
    corrected(db, m, 14, "100")
    cf(db, m, 15, "100")
    cf(db, m, 16, "103")  # anchorと異なる値のcarried_forward → 信頼しない
    cf(db, m, 17, "103")  # 継続元(16)がanchorに繋がらない → null
    add_record(db, m, 18, None, value_source="none", numeric_value=None, validation_status=None, display_status="error", usage=None)
    cf(db, m, 19, "100")  # 値なしrecordの後 → anchorへ繋がらない
    result = recompute_all(db, m)
    assert [result[h][1] for h in (15, 16, 17, 18, 19)] == ["0", None, None, None, None]


def test_continuation_ends_at_a_baseline_reset(db):
    from datetime import timedelta
    from app.models import ReadingBaselineEvent
    m = make_monitor(db)
    corrected(db, m, 14, "100")
    cf(db, m, 15, "100")
    r16 = cf(db, m, 16, "100")
    cf(db, m, 17, "100")
    db.add(ReadingBaselineEvent(monitor_id=m.id, action="reset", occurred_at=r16.recorded_at - timedelta(minutes=30), old_value="100", new_value=None, reason="t", operator="t"))
    db.commit()
    result = recompute_all(db, m)
    assert (result[15][1], result[16][1], result[17][1]) == ("0", None, None)  # resetでanchorの継続が終わり、以後は未修正のcarried_forward


def test_caseF_correction_recomputes_the_whole_continuation_range(client, db):
    m = make_monitor(db)
    add_record(db, m, 14, "95")
    r15 = cf(db, m, 15, "99")  # 誤って保持された値(修正対象)
    cf(db, m, 16, "100")
    cf(db, m, 17, "100")
    cf(db, m, 18, "100")
    add_record(db, m, 19, "104", usage=None)
    assert correct(client, r15.id, value="100").status_code == 200
    db.expire_all()
    rows = {int(r.hour_bucket[11:13]): r for r in db.scalars(select(ReadingRecord).where(ReadingRecord.monitor_id == m.id)).all()}
    assert [rows[h].usage for h in (15, 16, 17, 18, 19)] == ["5", "0", "0", "0", "4"]  # 先頭の次で止まらず、継続範囲と直後のConfirmedまで再計算


def test_caseG_audit_evidence_is_not_changed_by_the_recompute(client, db):
    m = make_monitor(db)
    add_record(db, m, 14, "95")
    r15 = cf(db, m, 15, "99")
    r16 = cf(db, m, 16, "100", baseline_conflict=True, raw_value="0100", raw_confidence=0.7)
    before = {n: getattr(r16, n) for n in ("value_source", "raw_value", "raw_confidence", "validation_status", "baseline_conflict", "original_image_path", "overlay_image_path", "display_status", "value")}
    assert correct(client, r15.id, value="100").status_code == 200
    db.expire_all()
    after = db.get(ReadingRecord, r16.id)
    assert {n: getattr(after, n) for n in before} == before
    assert after.usage == "0" and after.value_source == "carried_forward"  # 証跡はcarried_forwardのまま、usage計算上だけ継続扱い


def test_auto_semantic_reset_does_not_end_the_continuation_but_operator_reset_does(db):
    """設定変更(expected_digits等)による自動クリアは値を変えないので継続を切らない(実データの10/09 17:38の例)。運用者のresetは切る(別テスト)。"""
    from datetime import timedelta
    from app.models import ReadingBaselineEvent
    m = make_monitor(db)
    corrected(db, m, 14, "100")
    cf(db, m, 15, "100")
    r16 = cf(db, m, 16, "100")
    cf(db, m, 17, "100")
    db.add(ReadingBaselineEvent(monitor_id=m.id, action="auto_semantic_reset", occurred_at=r16.recorded_at - timedelta(minutes=30), old_value="100", new_value=None, reason="t", operator="system"))
    db.commit()
    result = recompute_all(db, m)
    assert [result[h][1] for h in (15, 16, 17)] == ["0", "0", "0"]
