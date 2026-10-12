"""overlay再生成スクリプト(scripts/regenerate_record_overlays.py)のテスト。

一時DBと一時フォルダだけを使い、推論はFake schedulerへ差し替える(実モデル・実カメラ・実画像保存先には触れない)。
"""
from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from app.models import ReadingRecord
from scripts import regenerate_record_overlays as script

from tests.test_record_images import config_for, db, make_monitor, make_record  # noqa: F401  (dbはfixture)

pytestmark = pytest.mark.integration

ORIGINAL = b"\xff\xd8\xff\xe0original\xff\xd9"
OVERLAY = b"\xff\xd8\xff\xe0regenerated-overlay\xff\xd9"
PROTECTED = ("value", "numeric_value", "raw_value", "value_source", "previous_value", "usage", "confidence", "raw_confidence",
             "validation_status", "display_status", "baseline_conflict", "engine", "model_id", "original_value", "original_image_path", "image_status")


class FakeScheduler:
    """InferenceSchedulerの代わり。mode: ok / error / raise。"""

    mode = "ok"

    def __init__(self, *_args, **_kwargs) -> None:
        self.engine = object()
        self.buffer = None
        self.latest_overlay = None
        self.latest_result = None

    def _infer_latest(self) -> None:
        if FakeScheduler.mode == "raise":
            raise RuntimeError("inference crashed")
        if FakeScheduler.mode == "error":
            self.latest_result = SimpleNamespace(value=None, error="model error")
            return
        self.latest_overlay = OVERLAY
        self.latest_result = SimpleNamespace(value="999999", error=None)

    def stop(self) -> None:
        pass


@pytest.fixture
def env(db, tmp_path, monkeypatch):  # noqa: F811
    FakeScheduler.mode = "ok"
    monkeypatch.setattr(script, "InferenceScheduler", FakeScheduler)
    monkeypatch.setattr(script, "load_config", lambda _db: config_for(tmp_path))
    monkeypatch.setattr(script, "SessionLocal", lambda: db)
    return SimpleNamespace(db=db, root=tmp_path, monitor=make_monitor(db))


def make_target(env, *, with_original=True, overlay=None, original_name="20261008_180015_265799_original.jpg"):
    record = make_record(env.db, env.monitor, value="265799")
    record.raw_value, record.numeric_value, record.usage, record.previous_value = "0265799", "265799", "12", "265787"
    record.validation_status, record.confidence, record.raw_confidence = "confirmed", 0.9, 0.8
    relative = f"m__{env.monitor.id}/2026/10/08/{original_name}"
    record.original_image_path = relative
    record.overlay_image_path = overlay
    if with_original:
        path = env.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(ORIGINAL)
    env.db.commit()
    return record, relative


def snapshot(record):
    return {name: getattr(record, name) for name in PROTECTED}


def run(monkeypatch, *args) -> int:
    monkeypatch.setattr(sys, "argv", ["regenerate_record_overlays", *args])
    return script.main()


def test_dry_run_changes_nothing(env, monkeypatch, capsys):
    record, _ = make_target(env)
    before = snapshot(record)
    assert run(monkeypatch) == 0
    env.db.expire_all()
    assert "dry-run" in capsys.readouterr().out
    assert record.overlay_image_path is None and snapshot(record) == before
    assert list(env.root.rglob("*_overlay_regenerated.jpg")) == []


def test_apply_updates_only_overlay_image_path(env, monkeypatch):
    record, relative = make_target(env)
    before = snapshot(record)
    assert run(monkeypatch, "--apply") == 0
    env.db.expire_all()
    expected = relative.replace("_original.jpg", "_overlay_regenerated.jpg")
    assert record.overlay_image_path == expected
    assert (env.root / expected).read_bytes() == OVERLAY
    assert (env.root / relative).read_bytes() == ORIGINAL  # 元画像は変更しない
    assert snapshot(record) == before


def test_record_without_original_file_is_skipped(env, monkeypatch, capsys):
    record, _ = make_target(env, with_original=False)
    before = snapshot(record)
    assert run(monkeypatch, "--apply") == 0
    env.db.expire_all()
    assert "SKIP" in capsys.readouterr().out
    assert record.overlay_image_path is None and snapshot(record) == before


def test_record_without_original_path_is_not_a_target(env, monkeypatch):
    record = make_record(env.db, env.monitor)
    assert run(monkeypatch, "--apply") == 0
    env.db.expire_all()
    assert record.original_image_path is None and record.overlay_image_path is None


def test_existing_overlay_is_not_overwritten(env, monkeypatch):
    record, relative = make_target(env, overlay="existing_overlay.jpg")
    existing = env.root / "existing_overlay.jpg"
    existing.write_bytes(b"keep")
    assert run(monkeypatch, "--apply") == 0
    env.db.expire_all()
    assert record.overlay_image_path == "existing_overlay.jpg"
    assert existing.read_bytes() == b"keep"
    assert list(env.root.rglob("*_overlay_regenerated.jpg")) == []


@pytest.mark.parametrize("mode", ["error", "raise"])
def test_inference_failure_keeps_the_original_record(env, monkeypatch, capsys, mode):
    record, relative = make_target(env)
    before = snapshot(record)
    FakeScheduler.mode = mode
    assert run(monkeypatch, "--apply") == 1  # 失敗があれば終了コード1
    env.db.expire_all()
    assert "FAIL" in capsys.readouterr().out
    assert record.overlay_image_path is None and snapshot(record) == before
    assert (env.root / relative).read_bytes() == ORIGINAL
    assert list(env.root.rglob("*_overlay_regenerated.jpg")) == []
