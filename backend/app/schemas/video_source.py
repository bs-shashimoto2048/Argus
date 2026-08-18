from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field, field_validator

class VideoSourceInput(BaseModel):
    source_type: Literal["camera", "url"] = "camera"
    device_id: int | None = Field(default=0, ge=0)
    url: str | None = None
    username: str | None = None
    password: str | None = None
    history_id: int | None = Field(default=None, ge=1)

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
