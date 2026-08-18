"""inference_fps制御とバックログ非発生（常に最新フレームを使う）ことの確認。"""
from __future__ import annotations

import threading
import time

import cv2
import numpy as np
import pytest

from app.inference.base import InferenceResult
from app.inference.registry import model_registry
from runtime.frame_buffer import LatestFrameBuffer
from runtime.inference_scheduler import InferenceScheduler

pytestmark = pytest.mark.integration


def _encode_frame(counter: int) -> bytes:
    image = np.full((20, 20, 3), counter % 256, dtype=np.uint8)
    ok, encoded = cv2.imencode(".jpg", image)
    assert ok
    return encoded.tobytes()


def _start_producer(buffer: LatestFrameBuffer, video_fps: float, stop: threading.Event) -> threading.Thread:
    def run():
        counter = 0
        interval = 1.0 / video_fps
        while not stop.is_set():
            buffer.put(_encode_frame(counter))
            counter += 1
            time.sleep(interval)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


def test_effective_inference_fps_stays_at_or_below_configured_rate():
    call_count = 0
    lock = threading.Lock()

    class FastFakeEngine:
        def infer(self, image, settings=None):
            nonlocal call_count
            with lock:
                call_count += 1
            return InferenceResult(value="1", confidence=0.9, engine="fake")

    buffer = LatestFrameBuffer()
    stop_producer = threading.Event()
    producer = _start_producer(buffer, video_fps=15, stop=stop_producer)

    scheduler = InferenceScheduler(1, buffer, {"inference_fps": 5, "roi": {"x": 0, "y": 0, "width": 1, "height": 1}, "preprocessing": {}}, model_registry, ".", lambda *_: None)
    scheduler.engine = FastFakeEngine()
    duration = 2.0
    scheduler.start()
    time.sleep(duration)
    scheduler.stop()
    stop_producer.set()
    producer.join(timeout=1)

    # video_fps=15 > inference_fps=5 なので、実測FPSはおおむね5以下であること。
    assert call_count <= 5 * duration + 3  # スケジューラのtick誤差を許容
    assert call_count >= 1


def test_slow_inference_always_uses_latest_frame_without_backlog():
    seen_values = []

    class SlowFakeEngine:
        def infer(self, image, settings=None):
            time.sleep(0.5)
            # imageの値(全画素同一)を最新frame counterの代わりに使う
            seen_values.append(int(image[0, 0, 0]))
            return InferenceResult(value=str(image[0, 0, 0]), confidence=0.9, engine="fake")

    buffer = LatestFrameBuffer()
    stop_producer = threading.Event()
    producer = _start_producer(buffer, video_fps=30, stop=stop_producer)

    scheduler = InferenceScheduler(1, buffer, {"inference_fps": 10, "roi": {"x": 0, "y": 0, "width": 1, "height": 1}, "preprocessing": {}}, model_registry, ".", lambda *_: None)
    scheduler.engine = SlowFakeEngine()
    scheduler.start()
    time.sleep(1.6)
    scheduler.stop()
    stop_producer.set()
    producer.join(timeout=1)

    # 推論が500msかかる間にvideo側は30fpsで大量にフレームを積むが、
    # bufferは単一slotのため毎回「その時点の最新フレーム」だけが処理される。
    # -> 処理回数はごく少数(1.6秒 / 0.5秒 ~= 3回程度)で、backlogとして
    #    大量のフレームを後追い処理することはない。
    assert 1 <= len(seen_values) <= 5
    # 常に単調増加(=常に新しいフレームを見ている。古いフレームの後追い処理が無い)。
    assert seen_values == sorted(seen_values)
