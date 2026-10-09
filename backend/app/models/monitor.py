from datetime import datetime
from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from ..core.database import Base

class Monitor(Base):
    __tablename__ = "monitors"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(160))
    location: Mapped[str] = mapped_column(String(160), default="")
    # Dashboard/Monitor管理の表示順(小さいほど先頭)。一覧は display_order ASC -> id ASC。欠番があってもよい。
    # 既存DBへのcolumn追加時はNULLになるため、起動時に現在のid昇順で補完する(main.py)。
    display_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(32), default="stopped")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    source = relationship("VideoSource", back_populates="monitor", uselist=False, cascade="all, delete-orphan")
    inference = relationship("InferenceSettings", back_populates="monitor", uselist=False, cascade="all, delete-orphan")
    latest_result = relationship("LatestResult", back_populates="monitor", uselist=False, cascade="all, delete-orphan")
    reading_baseline = relationship("ReadingBaseline", back_populates="monitor", uselist=False, cascade="all, delete-orphan")
