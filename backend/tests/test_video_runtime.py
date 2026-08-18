from runtime.frame_buffer import LatestFrameBuffer
from runtime.monitor_runtime import MonitorRuntime
from runtime.video_reader import ReaderConfig, sanitize_url


def test_latest_frame_buffer_keeps_only_latest_value():
    buffer = LatestFrameBuffer()
    buffer.put(b"old")
    buffer.put(b"new")
    data, stamp = buffer.get()
    assert data == b"new"
    assert stamp is not None


def test_sanitize_url_removes_credentials():
    assert sanitize_url("rtsp://user:secret@example.test/live") == "rtsp://***@example.test/live"
    assert sanitize_url("http://example.test/live") == "http://example.test/live"


def test_runtime_start_stop_without_camera(monkeypatch):
    class FakeReader:
        def __init__(self, _config):
            self.closed = False

        def read(self):
            return False, None

        def close(self):
            self.closed = True

    monkeypatch.setattr("runtime.monitor_runtime.VideoReader", FakeReader)
    statuses: list[str] = []
    runtime = MonitorRuntime(1, ReaderConfig(source_type="camera"), lambda _id, value: statuses.append(value))
    runtime.start()
    runtime._stop.wait(0.1)
    runtime.stop()
    assert runtime.state == "stopped"
    assert "connecting" in statuses


def test_reader_config_accepts_local_camera():
    config = ReaderConfig(source_type="local_camera", device_id=2)
    assert config.source_type == "local_camera"
