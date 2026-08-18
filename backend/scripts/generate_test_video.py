"""開発用のローカル映像ソースを生成する。実運用のsource_typeは追加しない。"""
from pathlib import Path
import argparse

import cv2
import numpy as np


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="data/runtime/test-source.mp4")
    parser.add_argument("--seconds", type=int, default=20)
    args = parser.parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(output), cv2.VideoWriter_fourcc(*"mp4v"), 15.0, (640, 360))
    if not writer.isOpened():
        raise RuntimeError("テスト動画を書き込めません")
    try:
        for frame_no in range(max(1, args.seconds * 15)):
            frame = np.full((360, 640, 3), 245, dtype=np.uint8)
            x = 40 + (frame_no * 4) % 520
            cv2.rectangle(frame, (x, 130), (x + 80, 210), (37, 99, 235), -1)
            cv2.putText(frame, f"ARGUS TEST {frame_no / 15:.1f}s", (24, 48), cv2.FONT_HERSHEY_SIMPLEX, 1, (15, 31, 70), 2)
            writer.write(frame)
    finally:
        writer.release()


if __name__ == "__main__":
    main()
