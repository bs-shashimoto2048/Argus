from pydantic import BaseModel
from .inference import PreprocessSettings, Roi


class PreprocessPreviewRequest(BaseModel):
    settings: PreprocessSettings
    roi: Roi | None = None
