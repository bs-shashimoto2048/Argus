"""Raw Reading列から時系列安定化・妥当性検証を経てConfirmed Readingを作る。

ReadingStabilizerは唯一状態(直近readingのbuffer、直前確定値、連続失敗回数)を
持つクラスだが、多数決/連続一致のロジック自体(`_vote`)や各Validationは
pure functionとして切り出してあり、単体テストしやすい構造にしている。

InferenceSchedulerが再構築される(Engine/Model/ROI/Preprocessing/Device変更、
Backend再起動)たびにReadingStabilizerも新規インスタンスになるため、
buffer resetは自然に満たされる(特別なreset検知ロジックは持たない)。
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone

from app.inference.base import InferenceResult

from .canonicalizer import canonical_value, to_numeric
from .models import CandidateStatus, ConfirmedReading, RawReading, ReadingSettings, StabilizationMode
from .validator import validate_format, validate_monotonic, validate_rate


def _vote(readings: "deque[RawReading]", settings: ReadingSettings) -> tuple[str, int, float | None] | None:
    """直近readingsから、多数決 or 連続一致でConfirmed候補を決める。

    Returns: (canonical_value, agreement_count, avg_confidence) または合意なしでNone。
    confidenceによる投票除外は行わない(値そのものはconfidenceに関わらず投票対象とし、
    低confidenceはConfirmed後のstatus判定(LOW_CONFIDENCE)で扱う。シンプルさを優先)。
    """
    candidates: list[tuple[str, RawReading]] = []
    for reading in readings:
        if reading.error is not None or not reading.value:
            continue
        canonical = canonical_value(reading.value, settings.decimal_position)
        if canonical is None:
            continue
        candidates.append((canonical, reading))
    if not candidates:
        return None

    if settings.mode == StabilizationMode.CONSECUTIVE:
        window = candidates[-settings.required_matches:]
        if len(window) < settings.required_matches:
            return None
        if len({canonical for canonical, _ in window}) != 1:
            return None
        canonical = window[0][0]
        group = [reading for _, reading in window]
    else:
        groups: dict[str, list[RawReading]] = {}
        for canonical, reading in candidates:
            groups.setdefault(canonical, []).append(reading)
        canonical, group = max(groups.items(), key=lambda item: (len(item[1]), item[1][-1].timestamp))
        if len(group) < settings.required_matches:
            return None

    confidences = [reading.confidence for reading in group if reading.confidence is not None]
    avg_confidence = sum(confidences) / len(confidences) if confidences else None
    return canonical, len(group), avg_confidence


class ReadingStabilizer:
    def __init__(self, settings: ReadingSettings) -> None:
        self.settings = settings
        self._buffer: deque[RawReading] = deque(maxlen=settings.window_size)
        self._consecutive_failures = 0
        self._previous_confirmed: ConfirmedReading | None = None

    @property
    def recent_raw(self) -> list[RawReading]:
        return list(self._buffer)

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures

    def update(self, raw: InferenceResult) -> ConfirmedReading:
        reading = RawReading(
            value=raw.value,
            confidence=raw.confidence,
            timestamp=raw.timestamp or datetime.now(timezone.utc),
            engine=raw.engine,
            error=raw.error,
            detection_count=len(raw.detections),
        )
        self._buffer.append(reading)

        if not self.settings.enabled:
            return self._passthrough(reading, raw.processing_time_ms)

        if reading.error is not None or not reading.value:
            self._consecutive_failures += 1
        else:
            self._consecutive_failures = 0

        if self._consecutive_failures >= self.settings.max_consecutive_failures:
            return self._carry_forward(CandidateStatus.NO_READING, reading)

        vote = _vote(self._buffer, self.settings)
        if vote is None:
            return self._carry_forward(CandidateStatus.PENDING, reading)
        canonical, agreement_count, avg_confidence = vote

        if not validate_format(canonical, self.settings.expected_digits):
            return self._carry_forward(CandidateStatus.INVALID_FORMAT, reading)

        numeric = to_numeric(canonical)
        previous = self._previous_confirmed
        previous_numeric = previous.numeric_value if previous else None
        previous_timestamp = previous.confirmed_at if previous else None

        if self.settings.monotonic and not validate_monotonic(numeric, previous_numeric, self.settings.allow_rollover):
            return self._carry_forward(CandidateStatus.DECREASE_DETECTED, reading)

        elapsed_seconds = None
        if previous_timestamp is not None and reading.timestamp is not None:
            elapsed_seconds = (reading.timestamp - previous_timestamp).total_seconds()
        if not validate_rate(numeric, previous_numeric, elapsed_seconds, self.settings.max_rate_per_minute, self.settings.allow_rollover, self.settings.rollover_max):
            return self._carry_forward(CandidateStatus.RATE_EXCEEDED, reading)

        status = CandidateStatus.CONFIRMED
        if self.settings.min_confidence is not None and avg_confidence is not None and avg_confidence < self.settings.min_confidence:
            status = CandidateStatus.LOW_CONFIDENCE

        confirmed = ConfirmedReading(
            validation_status=status,
            value=canonical,
            numeric_value=numeric,
            confidence=avg_confidence,
            confirmed_at=reading.timestamp,
            raw_count=len(self._buffer),
            agreement_count=agreement_count,
            engine=reading.engine,
            processing_time_ms=raw.processing_time_ms,
            raw_value=reading.value,
            raw_confidence=reading.confidence,
            raw_error=reading.error,
        )
        self._previous_confirmed = confirmed
        return confirmed

    def _carry_forward(self, status: CandidateStatus, reading: RawReading) -> ConfirmedReading:
        """Confirmed値を更新せず、直前の確定値を保持したまま今回のstatusだけ返す。"""
        previous = self._previous_confirmed
        return ConfirmedReading(
            validation_status=status,
            value=previous.value if previous else None,
            numeric_value=previous.numeric_value if previous else None,
            confidence=previous.confidence if previous else None,
            confirmed_at=reading.timestamp,
            raw_count=len(self._buffer),
            agreement_count=0,
            engine=reading.engine,
            processing_time_ms=0.0,
            raw_value=reading.value,
            raw_confidence=reading.confidence,
            raw_error=reading.error,
        )

    def _passthrough(self, reading: RawReading, processing_time_ms: float) -> ConfirmedReading:
        """安定化を無効化した場合の互換モード。単発結果をそのままConfirmed扱いにする。"""
        canonical = canonical_value(reading.value, self.settings.decimal_position) if reading.value else None
        numeric = to_numeric(canonical)
        if reading.error is not None:
            status = CandidateStatus.NO_READING
        elif canonical is not None:
            status = CandidateStatus.CONFIRMED
        else:
            status = CandidateStatus.PENDING
        confirmed = ConfirmedReading(
            validation_status=status,
            value=canonical if canonical is not None else (self._previous_confirmed.value if self._previous_confirmed else None),
            numeric_value=numeric if numeric is not None else (self._previous_confirmed.numeric_value if self._previous_confirmed else None),
            confidence=reading.confidence,
            confirmed_at=reading.timestamp,
            raw_count=len(self._buffer),
            agreement_count=1 if canonical is not None else 0,
            engine=reading.engine,
            processing_time_ms=processing_time_ms,
            raw_value=reading.value,
            raw_confidence=reading.confidence,
            raw_error=reading.error,
        )
        if canonical is not None:
            self._previous_confirmed = confirmed
        return confirmed
