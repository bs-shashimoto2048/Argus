from __future__ import annotations

from dataclasses import dataclass

from .base import Detection


@dataclass
class MeterValue:
    value: str | None
    confidence: float | None
    minimum_confidence: float | None = None


def _deduplicate_digits(detections: list[Detection], overlap_threshold: float = 0.65) -> list[Detection]:
    selected: list[Detection] = []
    for candidate in sorted(detections, key=lambda item: item.confidence or 0, reverse=True):
        if candidate.bbox is None:
            continue
        x1, y1, x2, y2 = candidate.bbox
        area = max(1.0, (x2 - x1) * (y2 - y1))
        duplicate = False
        for current in selected:
            if current.bbox is None:
                continue
            a1, b1, a2, b2 = current.bbox
            ix1, iy1, ix2, iy2 = max(x1, a1), max(y1, b1), min(x2, a2), min(y2, b2)
            intersection = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
            if intersection / area >= overlap_threshold:
                duplicate = True
                break
        if not duplicate:
            selected.append(candidate)
    return selected


def interpret_digits(detections: list[Detection], confidence_threshold: float = 0.0, decimal_position: int | None = None) -> MeterValue:
    digits = [item for item in detections if item.class_name is not None and item.class_name.strip() in set("0123456789") and (item.confidence or 0) >= confidence_threshold]
    digits = _deduplicate_digits(digits)
    digits.sort(key=lambda item: ((item.bbox[0] + item.bbox[2]) / 2) if item.bbox else 0)
    if not digits:
        return MeterValue(None, None, None)
    text = "".join(item.class_name.strip() for item in digits)
    if decimal_position is not None and 0 < decimal_position < len(text):
        text = text[:-decimal_position] + "." + text[-decimal_position:]
    values = [item.confidence for item in digits if item.confidence is not None]
    return MeterValue(text, sum(values) / len(values) if values else None, min(values) if values else None)


def normalize_meter_text(text: str, decimal_position: int | None = None) -> str | None:
    normalized = "".join(char for char in text.strip() if char.isdigit() or char == ".")
    if not normalized:
        return None
    if decimal_position is not None and "." not in normalized and 0 < decimal_position < len(normalized):
        normalized = normalized[:-decimal_position] + "." + normalized[-decimal_position:]
    return normalized
