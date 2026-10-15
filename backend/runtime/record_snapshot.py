"""1推論tick = 1つのimmutableなsnapshot(定時計測recordの証跡の整合性のため)。

1回の推論処理(Engine inference → overlay生成 → ReadingStabilizer.update() → ConfirmedReading → 運用値の保存)が
すべて完了したあとで、そのtickの情報だけを1つの不変オブジェクトにまとめ、InferenceSchedulerが丸ごと差し替える。
HourlyRecordWorkerは、記録を作るときにこのsnapshotを**1回だけ**取得し、同じsnapshotだけから
Raw・信頼度・validation_status・正式値・画像(元画像/overlay)・engine/model・推論時刻を使う。
そのため「記録のRaw=215850なのに、overlay画像は別のtickの215858」のような不整合が起きない。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

# 毎時記録のsnapshot選択(Issue #77)。計測枠の基準時刻の前後この秒数の範囲から、最も近い正常なsnapshotを選ぶ。
# 推論5fps・窓5tick・多数決3tick一致のため、1tickの揺れや数秒の棄却はこの範囲で十分に外れる想定。
RECORD_SELECT_BEFORE_SECONDS = 10.0
RECORD_SELECT_AFTER_SECONDS = 10.0
# 直近snapshotを保持する時間と最小間隔(画像を含むため、全tickは保持せず間引く)。
RECORD_RING_SECONDS = 30.0
RECORD_RING_MIN_SPACING_SECONDS = 0.5


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

    # このtickのRaw自体が、多数決で採用された候補と一致し、桁数(expected_digits)も満たすか。
    # overlay/Raw(そのtick単独)と、validation_status/正式値(窓内の多数決)が食い違わないtickだけTrueになる。
    raw_matches_candidate: bool = False

    @property
    def value_accepted(self) -> bool:
        """このtickのRawが正式値として採用された(confirmed / low_confidence)か。"""
        return self.validation_status in ("confirmed", "low_confidence")


def record_grade(snapshot: InferenceRecordSnapshot) -> int | None:
    """毎時記録に「正常採用」してよいtickの適性(小さいほど良い)。0: confirmed / 1: low_confidence。
    Raw・推論画像・candidate・validationの意味が一致する(raw_matches_candidate)tickだけが対象で、
    Stabilizer上confirmedでもRawが候補と食い違うtick、および棄却中(invalid_format/pending等)のtickはNone(正常採用しない)。"""
    if not snapshot.raw_matches_candidate:
        return None
    if snapshot.validation_status == "confirmed":
        return 0
    if snapshot.validation_status == "low_confidence":
        return 1
    return None


def evidence_consistent(snapshot: InferenceRecordSnapshot) -> bool:
    """このsnapshotを、Rawと一致する正常な証跡(value_source=confirmed)として記録してよいか。"""
    return record_grade(snapshot) is not None


def select_record_snapshot(snapshots: list[InferenceRecordSnapshot], target: datetime,
                           before: float = RECORD_SELECT_BEFORE_SECONDS, after: float = RECORD_SELECT_AFTER_SECONDS) -> InferenceRecordSnapshot | None:
    """基準時刻targetの前後(before/after秒)から、記録に使うsnapshotを1つ選ぶ(適性の高い順、同じ適性なら基準時刻に近い順)。
    範囲内に採用されたsnapshotが無ければNone(呼び出し側が従来の安全側へ進む)。"""
    low, high = target - timedelta(seconds=before), target + timedelta(seconds=after)
    pool = [s for s in snapshots if low <= s.inference_at <= high and record_grade(s) is not None]
    if not pool:
        return None
    return min(pool, key=lambda s: (record_grade(s), abs((s.inference_at - target).total_seconds()), s.inference_at))
