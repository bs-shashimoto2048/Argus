from sqlalchemy import select
from sqlalchemy.orm import Session
from ..models import UrlHistory
from ..schemas.video_source import UrlHistoryResponse
from .monitor_service import delete_url_history, list_url_history

def histories(db: Session):
    return [UrlHistoryResponse(id=x.id, url=x.url, username=x.username, last_verified_at=x.last_verified_at, has_password=bool(x.encrypted_password)) for x in list_url_history(db)]
