from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field, field_validator

class VideoSourceInput(BaseModel):
    source_type: Literal["camera", "local_camera", "url"] = "camera"
    device_id: int | None = Field(default=0, ge=0)
    url: str | None = None
    username: str | None = None
    password: str | None = None
    history_id: int | None = Field(default=None, ge=1)

    @field_validator("url")
    @classmethod
    def normalize_url(cls, value: str | None) -> str | None:
        return value.strip() if value else value

class VideoSourceResponse(BaseModel):
    source_type: str
    device_id: int | None
    url: str | None
    username: str | None
    has_password: bool

class UrlHistoryResponse(BaseModel):
    id: int
    url: str
    username: str | None
    last_verified_at: datetime
    has_password: bool = False
    model_config = {"from_attributes": True}


class SourceTestResponse(BaseModel):
    connected: bool
    source_type: str
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    error_code: str | None = None
    message: str
    # viewer URLのquery(imagepath等)から実stream URLを解決した場合の診断情報(sanitize済み、
    # 元URLと同一の場合はNone)。credential/実IPは含まない。
    resolved_url_hint: str | None = None
