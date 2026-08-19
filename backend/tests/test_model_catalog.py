from __future__ import annotations

import json

import pytest

from app.inference.model_catalog import get_model_entry, load_registry

pytestmark = pytest.mark.unit


def test_load_registry_missing_file_returns_empty(tmp_path):
    assert load_registry(tmp_path) == []


def test_load_registry_corrupt_json_returns_empty(tmp_path):
    (tmp_path / "registry.json").write_text("{not valid json", encoding="utf-8")
    assert load_registry(tmp_path) == []


def test_load_registry_reports_file_existence(tmp_path):
    (tmp_path / "present.pt").write_bytes(b"fake")
    (tmp_path / "registry.json").write_text(json.dumps({"models": [
        {"model_id": "present.pt", "role": "baseline"},
        {"model_id": "missing.pt", "role": "candidate"},
    ]}), encoding="utf-8")

    entries = load_registry(tmp_path)
    by_id = {entry["model_id"]: entry for entry in entries}
    assert by_id["present.pt"]["exists"] is True
    assert by_id["missing.pt"]["exists"] is False


def test_get_model_entry_returns_none_when_not_found(tmp_path):
    (tmp_path / "registry.json").write_text(json.dumps({"models": []}), encoding="utf-8")
    assert get_model_entry(tmp_path, "nope.pt") is None


def test_get_model_entry_finds_matching_id(tmp_path):
    (tmp_path / "registry.json").write_text(json.dumps({"models": [{"model_id": "a.pt", "role": "baseline"}]}), encoding="utf-8")
    entry = get_model_entry(tmp_path, "a.pt")
    assert entry is not None
    assert entry["role"] == "baseline"
