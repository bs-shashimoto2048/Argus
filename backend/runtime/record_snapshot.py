"""1推論tick = 1つのimmutableなsnapshot(定時計測recordの証跡の整合性のため)。

1回の推論処理(Engine inference → overlay生成 → ReadingStabilizer.update() → ConfirmedReading → 運用値の保存)が
すべて完了したあとで、そのtickの情報だけを1つの不変オブジェクトにまとめ、InferenceSchedulerが丸ごと差し替える。
HourlyRecordWorkerは、記録を作るときにこのsnapshotを**1回だけ**取得し、同じsnapshotだけから
Raw・信頼度・validation_status・正式値・画像(元画像/overlay)・engine/model・推論時刻を使う。
そのため「記録のRaw=215850なのに、overlay画像は別のtickの215858」のような不整合が起きない。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class InferenceRecordSnapshot:
    monitor_id: int
    tick: int  # InferenceSchedulerごとの通し番号(同じsnapshotかどうかの確認用)
    inference_at: datetime  # この推論tickの時刻(tz-aware UTC)
    captured_at: datetime | None  # 推論に使ったフレームを取得した時刻(tz-aware UTC)

    # 証跡画像: この推論tickが実際に使ったフレームと、そこから生成したoverlay(同一フレーム)
    original_jpeg: bytes | None
    overlay_jpeg: bytes | None

    # このtickのRaw Reading(AIが何を見たか)
    raw_value: str | None  # 先頭0を含む元の桁列
    raw_confidence: float | None
    raw_error: str | None
    detection_count: int

    # このtickの読取判定(ReadingStabilizer.update()の結果)
    validation_status: str  # confirmed / low_confidence / pending / decrease_detected / ...
    candidate_value: str | None  # 合意した候補(先頭0除去後)。合意が無ければNone
    agreement_count: int
    raw_count: int

    # 正式値(運用値): このtickの処理が終わった時点のLatestResult相当(ResultStoreが保存した値)。
    # Raw/validationが棄却中のtickでは、直前の正常Confirmed値を保持した値になる(carried_forwardの判定材料)。
    confirmed_value: str | None
    confirmed_confidence: float | None
    confirmed_at: datetime | None
    inference_status: str | None  # LatestResult.status相当(ok / low_confidence / read_error / pending)

    engine: str | None
    model_id: str | None
    processing_time_ms: float | None

    # このtick時点のbaseline(monotonic基準値)とconflict
    baseline_value: str | None
    baseline_epoch: int
    baseline_conflict: bool  # 警告に達したconflict(Dashboardのバッジと同じ基準)
    conflict_status: str | None
    conflict_candidate: str | None
    conflict_count: int

    @property
    def value_accepted(self) -> bool:
        """このtickのRawが正式値として採用された(confirmed / low_confidence)か。"""
        return self.validation_status in ("confirmed", "low_confidence")
