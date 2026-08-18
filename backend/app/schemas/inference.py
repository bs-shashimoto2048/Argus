from typing import Literal
from pydantic import BaseModel, Field, model_validator

class Roi(BaseModel):
    x: float = Field(0, ge=0, le=1)
    y: float = Field(0, ge=0, le=1)
    width: float = Field(1, gt=0, le=1)
    height: float = Field(1, gt=0, le=1)

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
    preprocessing: dict = Field(default_factory=dict)
    roi: Roi = Field(default_factory=Roi)
    engine_options: dict = Field(default_factory=dict)
    @model_validator(mode="after")
    def fps_order(self):
        if self.inference_fps > self.video_fps:
            raise ValueError("inference_fps must be <= video_fps")
        return self

class InferenceSettingsResponse(InferenceSettingsInput):
    model_config = {"from_attributes": True}
