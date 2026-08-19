"""Raw Reading列に対し、安定化(Stabilizer)適用前後を比較するレポートを出力する。

用途:
  1. 実カメラ運用中のMonitorから直近のRaw Readingを記録しJSON化したものを分析する
     (`GET /api/monitors/{id}/reading/diagnostics`のrecent_rawを蓄積する運用を想定)。
  2. 手動で用意したシーケンス(下記--sequence-preset等)でStabilizerの挙動を確認する。

使い方:
    py -m scripts.reading_stabilizer_report --sequence-preset noisy_meter
    py -m scripts.reading_stabilizer_report --input-json readings.json

readings.jsonの形式: [{"value": "002560", "confidence": 0.9, "error": null}, ...]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.inference.base import InferenceResult
from reading.models import CandidateStatus, ReadingSettings
from reading.stabilizer import ReadingStabilizer

# 物理的な実メーターがまだ用意できない環境向けの、代表的な揺れを模したサンプル。
# 実データが手に入り次第、--input-jsonでの実測値置き換えを推奨する。
PRESETS: dict[str, list[dict]] = {
    "noisy_meter": [
        {"value": "002560", "confidence": 0.91}, {"value": "002560", "confidence": 0.88},
        {"value": "002580", "confidence": 0.62}, {"value": "002560", "confidence": 0.9},
        {"value": "002560", "confidence": 0.93}, {"value": None, "confidence": None, "error": "NO_DETECTION"},
        {"value": "002560", "confidence": 0.89}, {"value": "0Q2560", "confidence": 0.4},
        {"value": "002560", "confidence": 0.92}, {"value": "002561", "confidence": 0.55},
        {"value": "002560", "confidence": 0.9}, {"value": "002560", "confidence": 0.87},
        {"value": "002570", "confidence": 0.58}, {"value": "002560", "confidence": 0.91},
        {"value": "002560", "confidence": 0.94},
    ],
}


def _load_sequence(args: argparse.Namespace) -> list[dict]:
    if args.input_json:
        return json.loads(Path(args.input_json).read_text(encoding="utf-8"))
    return PRESETS[args.sequence_preset]


def _replay(sequence: list[dict], settings: ReadingSettings) -> list:
    stabilizer = ReadingStabilizer(settings)
    base_time = datetime.now(timezone.utc)
    outcomes = []
    for index, item in enumerate(sequence):
        raw = InferenceResult(value=item.get("value"), confidence=item.get("confidence"), error=item.get("error"), engine=item.get("engine", "report"), timestamp=base_time + timedelta(seconds=index))
        outcomes.append(stabilizer.update(raw))
    return outcomes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-json", help="Raw Reading列のJSONファイル")
    parser.add_argument("--sequence-preset", default="noisy_meter", choices=sorted(PRESETS))
    args = parser.parse_args()

    sequence = _load_sequence(args)
    valid = [item for item in sequence if item.get("value") and not item.get("error")]
    counts = Counter(item["value"] for item in valid)
    dominant_value, dominant_count = (counts.most_common(1) or [(None, 0)])[0]

    print(f"Raw readings: {len(sequence)}")
    print(f"Valid readings: {len(valid)}")
    print(f"Unique values: {len(counts)}")
    print(f"Dominant value: {dominant_value}")
    print(f"Dominant ratio: {(dominant_count / len(valid) * 100):.0f}%" if valid else "Dominant ratio: n/a")

    before = _replay(sequence, ReadingSettings(enabled=False))
    after = _replay(sequence, ReadingSettings())  # 推奨Default

    before_values = [outcome.value for outcome in before]
    before_changes = sum(1 for a, b in zip(before_values, before_values[1:]) if a != b)
    after_confirmed_values = [outcome.value for outcome in after if outcome.validation_status in (CandidateStatus.CONFIRMED, CandidateStatus.LOW_CONFIDENCE)]
    after_changes = sum(1 for a, b in zip(after_confirmed_values, after_confirmed_values[1:]) if a != b)
    rejected = sum(1 for outcome in after if outcome.validation_status in (CandidateStatus.REJECTED, CandidateStatus.DECREASE_DETECTED, CandidateStatus.RATE_EXCEEDED, CandidateStatus.INVALID_FORMAT))

    print()
    print("[Before: Stabilizerなし(単発結果をそのまま採用)]")
    print(f"  Displayed value changes: {before_changes} (誤読が即座に反映される)")
    print(f"  Final value: {before_values[-1] if before_values else None}")
    print()
    print("[After: Stabilizerあり(既定設定 majority window=5 required_matches=3)]")
    print(f"  Confirmed value changes: {after_changes}")
    print(f"  Rejected/filtered spikes: {rejected}")
    print(f"  Final confirmed value: {after[-1].value if after else None}")


if __name__ == "__main__":
    main()
