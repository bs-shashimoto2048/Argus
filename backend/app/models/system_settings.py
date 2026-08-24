from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from ..core.database import Base


class SystemSettings(Base):
    """Monitor個別ではないApp全体の設定(Issue #17現時点ではCSV出力設定のみ)。

    常に単一行(id=1)のみを保持するsingletonテーブル。行が無ければ
    services.csv_export_service.get_settings()が既定値で作成する。
    """
    __tablename__ = "system_settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    csv_export_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    csv_output_folder: Mapped[str | None] = mapped_column(String(500), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CsvExportLog(Base):
    """1時間ごとのCSV出力の重複防止用ログ(Issue #17)。

    (monitor_id, hour_bucket)の組にUNIQUE制約を持たせ、「この時間帯は既に出力済み」を
    DBレベルで保証する(Backend再起動・複数リクエストが同時に来ても二重出力しない)。
    この行は「出力成功済み」の記録としてのみ使う。ファイル書込に失敗した場合は
    (services.csv_export_service側で)この行を作らない/削除し、次回tickで再試行できる
    ようにする。
    """
    __tablename__ = "csv_export_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    monitor_id: Mapped[int] = mapped_column(ForeignKey("monitors.id", ondelete="CASCADE"))
    # 出力対象のhour境界(Asia/Tokyo基準)をISO8601文字列で保持する(例: "2026-08-24T09:00:00+09:00")。
    hour_bucket: Mapped[str] = mapped_column(String(40))
    exported_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("monitor_id", "hour_bucket", name="uq_csv_export_monitor_hour"),)
