from pydantic import BaseModel
class ConnectionCheckResponse(BaseModel):
    success: bool
    message: str
    detail: str | None = None
