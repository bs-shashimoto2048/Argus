"""時系列安定化層(reading)で使うデータ構造。

InferenceEngineが返す単発の`InferenceResult`(app.inference.base)とは別に、
「その1回の結果」を`RawReading`、「時系列安定化・妥当性検証を経た確定値」を
`ConfirmedReading`として明確に区別する。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any


class StabilizationMode(str, Enum):
    MAJORITY = "majority"
    CONSECUTIVE = "consecutive"


class CandidateStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    NO_READING = "no_reading"
    LOW_CONFIDENCE = "low_confidence"
    INVALID_FORMAT = "invalid_format"
    DECREASE_DETECTED = "decrease_detected"
    RATE_EXCEEDED = "rate_exceeded"


@dataclass
class RawReading:
    """1回のInferenceEngine実行結果を、安定化layer用に切り出したもの。"""

    value: str | None
    confidence: float | None
    timestamp: datetime
    engine: str = ""
    error: str | None = None
    detection_count: int = 0


@dataclass
class ConfirmedReading:
    """時系列安定化・Validationを経て運用値として採用された結果。

    ResultStoreはこのオブジェクトだけを見ればLatestResult/履歴を更新できる
    (Rawの生データを直接参照する必要がない)。
    """

    validation_status: CandidateStatus
    value: str | None = None
    numeric_value: Decimal | None = None
    confidence: float | None = None
    confirmed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    raw_count: int = 0
    agreement_count: int = 0
    engine: str = ""
    processing_time_ms: float = 0.0
    raw_value: str | None = None
    raw_confidence: float | None = None
    raw_error: str | None = None


@dataclass
class ReadingSettings:
    """Monitor単位の安定化・Validation設定。DBのJSON列(inference_settings.reading)と対応する。"""

    enabled: bool = True
    mode: StabilizationMode = StabilizationMode.MAJORITY
    window_size: int = 5
    required_matches: int = 3
    min_confidence: float | None = 0.60
    expected_digits: int | None = None
    decimal_position: int | None = None
    monotonic: bool = True
    max_rate_per_minute: float | None = None
    max_consecutive_failures: int = 5
    allow_rollover: bool = False
    rollover_max: int | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ReadingSettings":
        """既存Monitor(readingキー未設定)でも安全にDefaultへfallbackする。"""
        data = data or {}
        defaults = cls()
        mode = data.get("mode", defaults.mode)
        if not isinstance(mode, StabilizationMode):
            try:
                mode = StabilizationMode(mode)
            except ValueError:
                mode = StabilizationMode.MAJORITY
        return cls(
            enabled=bool(data.get("enabled", defaults.enabled)),
            mode=mode,
            window_size=max(1, int(data.get("window_size", defaults.window_size))),
            required_matches=max(1, int(data.get("required_matches", defaults.required_matches))),
            min_confidence=data.get("min_confidence", defaults.min_confidence),
            expected_digits=data.get("expected_digits", defaults.expected_digits),
            decimal_position=data.get("decimal_position", defaults.decimal_position),
            monotonic=bool(data.get("monotonic", defaults.monotonic)),
            max_rate_per_minute=data.get("max_rate_per_minute", defaults.max_rate_per_minute),
            max_consecutive_failures=max(1, int(data.get("max_consecutive_failures", defaults.max_consecutive_failures))),
            allow_rollover=bool(data.get("allow_rollover", defaults.allow_rollover)),
            rollover_max=data.get("rollover_max", defaults.rollover_max),
        )
