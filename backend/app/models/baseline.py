from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base


class ReadingBaseline(Base):
    """monotonic/rate検証の基準値(Issue #40)。Monitorごとに1行。

    LatestResult.value(表示用、LOW_CONFIDENCEも含む)とは独立に、CONFIRMEDだけを永続化する。
    運用者のreset/rebaseはこの行だけを書き換え、表示値(LatestResult)は直接変更しない。
    """

    __tablename__ = "reading_baselines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    monitor_id: Mapped[int] = mapped_column(ForeignKey("monitors.id", ondelete="CASCADE"), unique=True)
    # 最終運用値の形式(先頭0除去後)と、比較用のDecimal文字列。pending_reset中はNoneもあり得る。
    value: Mapped[str | None] = mapped_column(String(128), nullable=True)
    numeric_value: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # naive UTC
    # confirmed / operator_reset / operator_rebase / auto_semantic_reset
    source: Mapped[str] = mapped_column(String(32), default="confirmed")
    # active: baselineとして使う / pending_reset: 次の正常CONFIRMEDを新baselineにする
    state: Mapped[str] = mapped_column(String(32), default="active")
    # reset/rebase/自動resetのたびに増える世代番号。古い世代のConfirmedがbaselineを上書きしないための排他に使う。
    epoch: Mapped[int] = mapped_column(Integer, default=0)
    # semantic fingerprint: これらが変わるとbaselineの数値尺度が変わるため、復元せず自動クリアする。
    decimal_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expected_digits: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # baselineと矛盾する合意候補(decrease_detected/rate_exceeded)の継続状態。
    conflict_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    conflict_candidate: Mapped[str | None] = mapped_column(String(128), nullable=True)
    conflict_count: Mapped[int] = mapped_column(Integer, default=0)
    conflict_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    conflict_last_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    monitor = relationship("Monitor", back_populates="reading_baseline")


class ReadingBaselineEvent(Base):
    """baseline操作の監査履歴。Monitor削除後も残すため、monitor_idへのForeignKeyは張らない。"""

    __tablename__ = "reading_baseline_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    monitor_id: Mapped[int] = mapped_column(Integer, index=True)
    monitor_name: Mapped[str] = mapped_column(String(80), default="")
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)  # naive UTC
    action: Mapped[str] = mapped_column(String(32))  # reset / rebase / auto_semantic_reset
    old_value: Mapped[str | None] = mapped_column(String(128), nullable=True)
    old_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    new_value: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    operator: Mapped[str] = mapped_column(String(160), default="")
    client_host: Mapped[str] = mapped_column(String(64), default="")
    context: Mapped[dict] = mapped_column(JSON, default=dict)
