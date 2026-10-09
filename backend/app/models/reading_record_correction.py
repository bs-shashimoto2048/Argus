from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..core.database import Base


class ReadingRecordCorrection(Base):
    """読取値(正式値)の手動修正の監査履歴。reading_recordsの修正の正本。

    修正のたびに1行を追加し、UPDATE/DELETEしない(複数回修正しても全履歴が残る)。
    old_*/new_*は修正の前後の正式値と、それに連動するusage。raw_*/validation_status等は、修正の時点で
    記録に残っていた元証跡(記録時にAIが何を見てどう判断したか。修正では変更しない)のコピー。
    """

    __tablename__ = "reading_record_corrections"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    record_id: Mapped[int] = mapped_column(Integer, ForeignKey("reading_records.id", ondelete="CASCADE"), index=True)
    monitor_id: Mapped[int] = mapped_column(Integer, index=True)
    corrected_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)  # naive UTC
    operator: Mapped[str] = mapped_column(String(80))
    reason: Mapped[str] = mapped_column(Text)
    old_value: Mapped[str | None] = mapped_column(String(128), nullable=True)
    new_value: Mapped[str] = mapped_column(String(128))
    old_numeric_value: Mapped[str | None] = mapped_column(String(64), nullable=True)
    new_numeric_value: Mapped[str | None] = mapped_column(String(64), nullable=True)
    old_usage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    new_usage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    raw_value: Mapped[str | None] = mapped_column(String(128), nullable=True)
    raw_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    validation_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    value_source: Mapped[str | None] = mapped_column(String(16), nullable=True)
    baseline_value: Mapped[str | None] = mapped_column(String(128), nullable=True)
    baseline_conflict: Mapped[bool] = mapped_column(Boolean, default=False)
    original_image_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    overlay_image_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    client_host: Mapped[str] = mapped_column(String(64), default="")
    context: Mapped[dict | None] = mapped_column(JSON, nullable=True)
