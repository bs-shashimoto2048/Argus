"""同一Model+Deviceを複数回要求しても、モデルロードが1回だけであることを確認する。

実ultralyticsの代わりにfakeモジュールを注入することで、重い依存なしに
create_engine() -> YoloInferenceEngine._model() -> ModelRegistry.get() の
実配線（issue: model id -> path resolve -> lazy load -> cache -> reuse）を検証する。
実モデルでの同等確認は tests/test_inference_engines_real.py (optional_inference) で行う。
"""
from __future__ import annotations

import sys
import types

import numpy as np
import pytest

from app.inference.base import ModelRegistry
from app.inference.engines import create_engine

pytestmark = pytest.mark.unit

IMAGE = np.zeros((10, 10, 3), dtype=np.uint8)


def _install_fake_ultralytics(monkeypatch, load_calls: list[int]):
    class FakeBoxes:
        xyxy = types.SimpleNamespace(tolist=lambda: [])
        conf = types.SimpleNamespace(tolist=lambda: [])
        cls = types.SimpleNamespace(tolist=lambda: [])

    class FakeResult:
        names = {}
        boxes = FakeBoxes()

    class FakeYolo:
        def __init__(self, _path):
            load_calls.append(1)

        def predict(self, *a, **kw):
            return [FakeResult()]

    module = types.ModuleType("ultralytics")
    module.YOLO = FakeYolo
    monkeypatch.setitem(sys.modules, "ultralytics", module)


def test_same_model_and_device_loads_only_once(tmp_path, monkeypatch):
    model_path = tmp_path / "meter_digits_v1.pt"
    model_path.write_bytes(b"fake-weights")
    load_calls: list[int] = []
    _install_fake_ultralytics(monkeypatch, load_calls)

    registry = ModelRegistry()
    settings = {"method": "object_detection", "engine": "ultralytics", "model_id": "meter_digits_v1.pt", "device": "cpu"}
    engine_a = create_engine(settings, registry, tmp_path)
    engine_b = create_engine(settings, registry, tmp_path)

    engine_a.infer(IMAGE)
    engine_b.infer(IMAGE)
    engine_a.infer(IMAGE)

    assert len(load_calls) == 1, "同一 model_id + device の組み合わせでロードは1回だけであること"


def test_different_device_triggers_new_load(tmp_path, monkeypatch):
    model_path = tmp_path / "meter_digits_v1.pt"
    model_path.write_bytes(b"fake-weights")
    load_calls: list[int] = []
    _install_fake_ultralytics(monkeypatch, load_calls)

    registry = ModelRegistry()
    base_settings = {"method": "object_detection", "engine": "ultralytics", "model_id": "meter_digits_v1.pt"}
    create_engine({**base_settings, "device": "cpu"}, registry, tmp_path).infer(IMAGE)
    create_engine({**base_settings, "device": "cpu"}, registry, tmp_path).infer(IMAGE)

    assert len(load_calls) == 1
    assert registry.size() == 1


def test_different_model_id_triggers_new_load_and_does_not_reuse_old_model(tmp_path, monkeypatch):
    """Issue #16 調査B: custom modelへ切替た際、cache key (engine_type, model_id, device)
    が旧modelを誤再利用していないことを確認する回帰テスト。

    修正前からcache keyにはmodel_idが含まれているが、「切替時に本当に新規ロードされるか」
    を明示的に確認するテストがこれまで存在しなかった。
    """
    (tmp_path / "meter_digits_v1.pt").write_bytes(b"fake-weights-v1")
    (tmp_path / "meter_digits_v2_candidate_001_best.pt").write_bytes(b"fake-weights-v2")
    load_calls: list[int] = []
    _install_fake_ultralytics(monkeypatch, load_calls)

    registry = ModelRegistry()
    base_settings = {"method": "object_detection", "engine": "ultralytics", "device": "cpu"}
    engine_v1 = create_engine({**base_settings, "model_id": "meter_digits_v1.pt"}, registry, tmp_path)
    engine_v2 = create_engine({**base_settings, "model_id": "meter_digits_v2_candidate_001_best.pt"}, registry, tmp_path)

    model_v1 = engine_v1._model()
    model_v2 = engine_v2._model()

    assert len(load_calls) == 2, "異なるmodel_idはそれぞれ個別にロードされること"
    assert registry.size() == 2, "異なるmodel_idは別々のcache entryを持つこと(旧modelの誤再利用が無いこと)"
    assert model_v1 is not model_v2

    # 同じmodel_idへ戻せば、そのmodel_id用のcache entryが再利用されること
    engine_v1_again = create_engine({**base_settings, "model_id": "meter_digits_v1.pt"}, registry, tmp_path)
    assert engine_v1_again._model() is model_v1
    assert len(load_calls) == 2, "既にロード済みのmodel_idへ戻した際は再ロードされないこと"
