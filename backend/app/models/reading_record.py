from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..core.database import Base


class ReadingRecord(Base):
    """正式な計測履歴: 1時間ごとに1 Monitor 1件(Issue: UI再設計 Phase 1)。

    値が変わるたびの記録ではない(それは`inference_results`のheartbeat履歴)。状態変化
    (通信異常/読取不能/baseline conflict/reset/rebase)は別概念で、既存の`reading_baseline_events`
    やruntime情報で扱い、ここへは混在させない(将来、専用のevent履歴へ分離できる)。

    Monitorを削除しても記録は残す(証跡のため)ので、monitor_idへのForeignKeyは張らない。
    SQLiteはMonitor IDを再利用し得るため、参照時はMonitorが存在する間、その作成時刻以降の
    記録だけを返す(services.reading_record_service)。
    """

    __tablename__ = "reading_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    monitor_id: Mapped[int] = mapped_column(Integer, index=True)
    monitor_name: Mapped[str] = mapped_column(String(160), default="")  # 記録時点のMonitor表示名のスナップショット
    # 計測枠(Asia/Tokyoの時の境界)。(monitor_id, hour_bucket)で一意 = 1時間に1件。例: "2026-10-08T14:00:00+09:00"
    hour_bucket: Mapped[str] = mapped_column(String(40))
    # 実際に記録した時刻(naive UTC)。通常は毎時00分、Backend再起動等で遅れた場合は遅れた時刻になる。
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # 最終運用値(先頭0除去後)と比較用のDecimal文字列。映像/読取が正常でない時間帯はNone。
    value: Mapped[str | None] = mapped_column(String(128), nullable=True)
    numeric_value: Mapped[str | None] = mapped_column(String(64), nullable=True)
    raw_value: Mapped[str | None] = mapped_column(String(128), nullable=True)  # 元の桁列(先頭0を含む)
    previous_value: Mapped[str | None] = mapped_column(String(128), nullable=True)  # 前回(1時間前)の定時計測値
    usage: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 今回 - 前回(連続した正常データでなければNone)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    validation_status: Mapped[str | None] = mapped_column(String(32), nullable=True)  # confirmed / low_confidence / ...
    display_status: Mapped[str] = mapped_column(String(32), default="normal")  # normal / warning / read_error / error / stopped / ...
    baseline_conflict: Mapped[bool] = mapped_column(Boolean, default=False)
    engine: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    # 記録画像(Phase 2): DBには画像ルートからの相対パスを保存する。
    original_image_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    overlay_image_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    image_status: Mapped[str] = mapped_column(String(16), default="not_saved")  # not_saved / ok / failed / dropped / disabled
    image_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    __table_args__ = (UniqueConstraint("monitor_id", "hour_bucket", name="uq_reading_records_monitor_hour"),)
