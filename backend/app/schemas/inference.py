from typing import Literal
from pydantic import BaseModel, Field, model_validator

class Roi(BaseModel):
    x: float = Field(0, ge=0, le=1)
    y: float = Field(0, ge=0, le=1)
    width: float = Field(1, gt=0, le=1)
    height: float = Field(1, gt=0, le=1)

    @model_validator(mode="after")
    def fits_frame(self):
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("ROI must fit within the normalized frame")
        return self


class PreprocessSettings(BaseModel):
    grayscale: bool = False
    binary: bool = False
    threshold: int = Field(128, ge=0, le=255)
    invert: bool = False
    brightness: float = Field(1.0, ge=0.1, le=3.0)
    contrast: float = Field(1.0, ge=0.1, le=3.0)
    clahe: bool = False
    sharpen: bool = False
    resize: int | None = Field(default=None, ge=32, le=4096)

class ReadingSettings(BaseModel):
    """Raw Reading -> Confirmed Readingへの時系列安定化・Validation設定。"""

    enabled: bool = True
    mode: Literal["majority", "consecutive"] = "majority"
    window_size: int = Field(5, ge=1, le=50)
    required_matches: int = Field(3, ge=1, le=50)
    min_confidence: float | None = Field(0.60, ge=0, le=1)
    expected_digits: int | None = Field(default=None, ge=1, le=32)
    decimal_position: int | None = Field(default=None, ge=0, le=32)
    monotonic: bool = True
    max_rate_per_minute: float | None = Field(default=None, ge=0)
    max_consecutive_failures: int = Field(5, ge=1, le=100)
    allow_rollover: bool = False
    rollover_max: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def matches_within_window(self):
        if self.required_matches > self.window_size:
            raise ValueError("required_matches must be <= window_size")
        return self


class InferenceSettingsInput(BaseModel):
    method: Literal["object_detection", "ocr"] = "object_detection"
    engine: Literal["ultralytics", "easyocr", "tesseract"] = "ultralytics"
    model_id: str | None = None
    device: str = "auto"
    video_fps: int = Field(15, gt=0, le=60)
    inference_fps: int = Field(5, gt=0, le=60)
    confidence: float = Field(0.25, ge=0, le=1)
    iou: float = Field(0.7, ge=0, le=1)
    image_size: int = Field(640, gt=0, le=4096)
    preprocessing: PreprocessSettings = Field(default_factory=PreprocessSettings)
    roi: Roi = Field(default_factory=Roi)
    reading: ReadingSettings = Field(default_factory=ReadingSettings)
    engine_options: dict = Field(default_factory=dict)
    @model_validator(mode="after")
    def fps_order(self):
        if self.inference_fps > self.video_fps:
            raise ValueError("inference_fps must be <= video_fps")
        return self

class InferenceSettingsResponse(InferenceSettingsInput):
    model_config = {"from_attributes": True}
