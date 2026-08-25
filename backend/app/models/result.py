from datetime import datetime
from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from ..core.database import Base

class LatestResult(Base):
    __tablename__ = "latest_results"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    monitor_id: Mapped[int] = mapped_column(ForeignKey("monitors.id", ondelete="CASCADE"), unique=True)
    value: Mapped[str | None] = mapped_column(String(128), nullable=True)
    previous_value: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Issue #28: 前回確定値(previous_value)の信頼度・確定日時。previous_valueが
    # 「一つ前の確定値の文字列」を既に保持しているのに対し、confidence/timestampは
    # 常に「現在の(最新の)値」用に上書きされるため、前回値側の信頼度・確定日時を
    # 個別に保持する専用カラムを追加する(ReadingStabilizerの判定ロジックには
    # 触れず、result_store.pyの保存処理のみ拡張)。
    previous_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    previous_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 現在値(value)が実際に確定した瞬間。既存のtimestampは「最後にsave_resultが
    # 呼ばれた時刻」(accepted以外のstatusでも毎サイクル更新される汎用フィールド)で
    # あり「確定した瞬間」とは意味が異なるため、別カラムとして保持する。
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    timestamp: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="disabled")
    engine: Mapped[str | None] = mapped_column(String(32), nullable=True)
    processing_time_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(128), nullable=True)
    monitor = relationship("Monitor", back_populates="latest_result")

class InferenceResult(Base):
    __tablename__ = "inference_results"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    monitor_id: Mapped[int] = mapped_column(ForeignKey("monitors.id", ondelete="CASCADE"))
    value: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    detections: Mapped[list] = mapped_column(JSON, default=list)
    processing_time_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    engine: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
