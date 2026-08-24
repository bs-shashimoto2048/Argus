from datetime import datetime
from pydantic import BaseModel, Field
from .video_source import VideoSourceInput, VideoSourceResponse
from .inference import InferenceSettingsInput, InferenceSettingsResponse, Roi

class MonitorCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    display_name: str = Field(min_length=1, max_length=160)
    location: str = Field(default="", max_length=160)

class MonitorUpdate(BaseModel):
    # Issue #25: nameを編集可能にする。実行時の識別には常にMonitor ID(id)が使われ、
    # nameは表示/CSV出力/UNIQUE制約のみに関わることを確認済み(RuntimeManager/
    # ルーティング/ファイルパス生成のいずれもnameへ依存していない)。フォーマットは
    # MonitorCreate.nameと同一の制約を維持する。
    name: str | None = Field(default=None, min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    display_name: str | None = Field(default=None, min_length=1, max_length=160)
    location: str | None = Field(default=None, max_length=160)
    enabled: bool | None = None
    source: VideoSourceInput | None = None
    inference: InferenceSettingsInput | None = None

class MonitorResponse(BaseModel):
    id: int
    name: str
    display_name: str
    location: str
    enabled: bool
    status: str
    created_at: datetime
    updated_at: datetime
    source: VideoSourceResponse | None
    inference: InferenceSettingsResponse
    current_value: str | None = None
    previous_value: str | None = None
    confidence: float | None = None
    last_updated: datetime | None = None
    inference_status: str = "disabled"
    last_inference_error: str | None = None
    model_config = {"from_attributes": True}
