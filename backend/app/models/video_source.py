from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from ..core.database import Base

class VideoSource(Base):
    __tablename__ = "video_sources"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    monitor_id: Mapped[int] = mapped_column(ForeignKey("monitors.id", ondelete="CASCADE"), unique=True)
    source_type: Mapped[str] = mapped_column(String(16), default="camera")
    device_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    username: Mapped[str | None] = mapped_column(String(256), nullable=True)
    encrypted_password: Mapped[str | None] = mapped_column(String(4096), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    monitor = relationship("Monitor", back_populates="source")

class UrlHistory(Base):
    __tablename__ = "url_histories"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    url: Mapped[str] = mapped_column(String(2048), unique=True)
    username: Mapped[str | None] = mapped_column(String(256), nullable=True)
    encrypted_password: Mapped[str | None] = mapped_column(String(4096), nullable=True)
    last_verified_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
