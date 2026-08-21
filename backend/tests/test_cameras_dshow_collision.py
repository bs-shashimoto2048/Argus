"""GET /api/cameras が、稼働中のlocal camera MonitorRuntimeと同じdeviceを
二重にopenしないことを確認するテスト(Issue #14: Backend安定性調査)。

実カメラで確認したところ、稼働中のMonitorRuntimeが使用中のdeviceを列挙APIが
並行してopen/closeすると、稼働中Monitor側でread失敗・reconnect stormが発生する
ことを再現した(実機DSHOWドライバではnative crashの引き金になり得る)。
稼働中deviceは実際にopenせずスキップすることで、この自己衝突を避ける。
"""
from __future__ import annotations

import pytest

from app.routers import cameras as cameras_router
from runtime.runtime_manager import RuntimeManager

pytestmark = pytest.mark.unit


def test_list_cameras_skips_device_in_use_by_active_runtime(monkeypatch):
    opened_indices = []

    class FakeCapture:
        def __init__(self, index, _backend):
            opened_indices.append(index)
            self._index = index

        def isOpened(self):
            return True

        def release(self):
            pass

    monkeypatch.setattr(cameras_router.cv2, "VideoCapture", FakeCapture)
    monkeypatch.setattr(cameras_router.runtime_manager, "active_local_camera_devices", lambda: {0})

    result = cameras_router.list_cameras()

    assert 0 not in opened_indices, "使用中のdeviceを実際にopenしてはいけない"
    by_id = {c["device_id"]: c for c in result["cameras"]}
    assert "使用中" in by_id[0]["label"]
    assert 1 in by_id  # 使用中でないdeviceは通常どおり列挙される


def test_list_cameras_probes_devices_not_in_use(monkeypatch):
    opened_indices = []

    class FakeCapture:
        def __init__(self, index, _backend):
            opened_indices.append(index)

        def isOpened(self):
            return True

        def release(self):
            pass

    monkeypatch.setattr(cameras_router.cv2, "VideoCapture", FakeCapture)
    monkeypatch.setattr(cameras_router.runtime_manager, "active_local_camera_devices", lambda: set())

    cameras_router.list_cameras()

    assert opened_indices == [0, 1, 2, 3, 4]


# --- RuntimeManager.active_local_camera_devices / count ---

class _FakeRuntime:
    def __init__(self, source_type, device_id):
        class _Config:
            pass
        self.config = _Config()
        self.config.source_type = source_type
        self.config.device_id = device_id

    def start(self):
        pass

    def stop(self):
        pass


def test_active_local_camera_devices_returns_only_camera_type_runtimes():
    manager = RuntimeManager()
    manager._runtimes[1] = _FakeRuntime("camera", 0)
    manager._runtimes[2] = _FakeRuntime("local_camera", 2)
    manager._runtimes[3] = _FakeRuntime("url", None)

    assert manager.active_local_camera_devices() == {0, 2}


def test_count_reflects_number_of_active_runtimes():
    manager = RuntimeManager()
    assert manager.count() == 0
    manager._runtimes[1] = _FakeRuntime("camera", 0)
    manager._runtimes[2] = _FakeRuntime("url", None)
    assert manager.count() == 2
