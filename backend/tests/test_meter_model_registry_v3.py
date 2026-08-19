"""実運用のdata/models/registry.jsonが、v3ラウンド後も期待どおりの構成になっているかを
検証する(Issue: Expand Meter Dataset and Retrain Production Candidate Model v3)。

- 既存のbaseline/candidate(v1/v2)エントリを壊していないこと。
- v3(rejected_candidate)が正しく追加され、v2のroleがcandidateのまま維持されていること。
- role=productionへ安易に昇格していないこと(今回は昇格見送りが正しい判断)。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.inference.model_catalog import get_model_entry, load_registry

pytestmark = pytest.mark.unit

REAL_MODEL_ROOT = Path(__file__).resolve().parents[2] / "data" / "models"


def test_real_registry_is_loadable():
    entries = load_registry(REAL_MODEL_ROOT)
    assert len(entries) >= 3


def test_v1_baseline_role_unchanged():
    entry = get_model_entry(REAL_MODEL_ROOT, "meter_digits_v1.pt")
    assert entry is not None
    assert entry["role"] == "baseline"


def test_v2_candidate_role_unchanged_after_v3_round():
    """v3がv2を明確に上回らなかったため、v2のroleはcandidateのまま維持される想定。"""
    entry = get_model_entry(REAL_MODEL_ROOT, "meter_digits_v2_candidate.pt")
    assert entry is not None
    assert entry["role"] == "candidate"


def test_v3_candidate_was_not_promoted_to_production():
    entry = get_model_entry(REAL_MODEL_ROOT, "meter_digits_v3_candidate.pt")
    assert entry is not None
    assert entry["role"] != "production"
    assert entry["role"] == "rejected_candidate"


def test_no_model_holds_production_role_yet():
    """今回の評価で無監督運用に足る精度は未達のため、role=productionは誰も保持しない。"""
    entries = load_registry(REAL_MODEL_ROOT)
    assert all(e["role"] != "production" for e in entries)


def test_v3_metrics_report_both_legacy_and_new_holdout_separately():
    entry = get_model_entry(REAL_MODEL_ROOT, "meter_digits_v3_candidate.pt")
    summary = entry["metrics_summary"]
    assert "legacy_golden_test" in summary
    assert "new_holdout_test" in summary
    assert summary["legacy_golden_test"]["test_set"].startswith("meter_test_set_v2")
    assert summary["new_holdout_test"]["test_set"].startswith("meter_holdout_v3")
