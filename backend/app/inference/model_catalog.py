"""data/models/registry.json を読み込む軽量Model Catalog。

Issue #1-3/#51-52: モデルに`role`(baseline/candidate/production/deprecated)等の
metadataを持たせる。Argusには重い実験管理システムは不要なため、
1ファイルのJSON manifestで完結させる(yolo_pipeline_studioのような
project/train-job単位の管理システムを重複実装しない)。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_registry(model_root: Path) -> list[dict[str, Any]]:
    """model_root(通常data/models/)直下のregistry.jsonを読み込む。

    ファイルが無い、壊れている場合は空リストを返す(Backendを落とさない)。
    """
    registry_path = model_root / "registry.json"
    if not registry_path.is_file():
        return []
    try:
        data = json.loads(registry_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    models = data.get("models", []) if isinstance(data, dict) else []
    result = []
    for entry in models:
        if not isinstance(entry, dict) or "model_id" not in entry:
            continue
        entry = dict(entry)
        entry["exists"] = (model_root / str(entry["model_id"])).is_file()
        result.append(entry)
    return result


def get_model_entry(model_root: Path, model_id: str) -> dict[str, Any] | None:
    for entry in load_registry(model_root):
        if entry.get("model_id") == model_id:
            return entry
    return None
