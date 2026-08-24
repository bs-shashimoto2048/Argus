from sqlalchemy import Float, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from ..core.database import Base

class InferenceSettings(Base):
    __tablename__ = "inference_settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    monitor_id: Mapped[int] = mapped_column(ForeignKey("monitors.id", ondelete="CASCADE"), unique=True)
    method: Mapped[str] = mapped_column(String(32), default="object_detection")
    engine: Mapped[str] = mapped_column(String(32), default="ultralytics")
    model_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    device: Mapped[str] = mapped_column(String(32), default="auto")
    video_fps: Mapped[int] = mapped_column(Integer, default=15)
    inference_fps: Mapped[int] = mapped_column(Integer, default=5)
    confidence: Mapped[float] = mapped_column(Float, default=0.25)
    iou: Mapped[float] = mapped_column(Float, default=0.70)
    image_size: Mapped[int] = mapped_column(Integer, default=640)
    preprocessing: Mapped[dict] = mapped_column(JSON, default=dict)
    roi: Mapped[dict] = mapped_column(JSON, default=lambda: {"x": 0, "y": 0, "width": 1, "height": 1})
    # Issue #16: ROIの意味づけ(object_detectionのみ有効)。既定はfilter_only(推奨)。
    roi_mode: Mapped[str] = mapped_column(String(32), default="filter_only")
    context_margin: Mapped[float] = mapped_column(Float, default=1.0)
    reading: Mapped[dict] = mapped_column(JSON, default=dict)
    engine_options: Mapped[dict] = mapped_column(JSON, default=dict)
    monitor = relationship("Monitor", back_populates="inference")
