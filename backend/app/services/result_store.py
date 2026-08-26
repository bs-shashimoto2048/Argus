from datetime import datetime, timedelta

from sqlalchemy import select

from ..core.database import SessionLocal
from ..models import InferenceResult, LatestResult
from reading.models import CandidateStatus, ConfirmedReading

# LatestResult.value/previous_value/statusを更新する(=運用値として採用する)status。
_ACCEPTED_STATUSES = (CandidateStatus.CONFIRMED, CandidateStatus.LOW_CONFIDENCE)


def save_result(monitor_id: int, confirmed: ConfirmedReading) -> None:
    """ReadingStabilizerが確定したConfirmed Readingを永続化する。

    ここではTemporal Stabilization/Validationのロジックを一切持たない
    (ReadingStabilizer/ReadingValidatorの責務であり、ResultStoreは保存のみ)。
    """
    db = SessionLocal()
    try:
        latest = db.scalar(select(LatestResult).where(LatestResult.monitor_id == monitor_id))
        if not latest:
            latest = LatestResult(monitor_id=monitor_id)
            db.add(latest)

        status = confirmed.validation_status

        # Issue #32: last_error(下のif/elifで従来通り更新する「粘着性」のある値)とは別に、
        # 「現在まさにエラー中かどうか」を表すcurrent_errorを判定する。ReadingStabilizer/
        # Validatorの判定ロジック(状態遷移の閾値等)には一切触れず、既にConfirmedReadingへ
        # 格納済みのraw_error(=直近1tickのRaw Reading自体の成否)を読むだけ。直近tickの
        # Raw Readingが成功していれば(raw_error is None)、Confirmed/Pending/Rejectedの
        # いずれであっても「読取自体は少なくとも今復旧している」ことを意味するため、
        # current_errorを即座にクリアする(last_errorのように後続のConfirmed成立まで
        # 待たない)。current_errorが実際に設定されるのは、下のNO_READING分岐
        # (＝連続失敗が閾値へ到達した瞬間)のみ。
        if confirmed.raw_error is None:
            latest.current_error = None

        if status in _ACCEPTED_STATUSES:
            if confirmed.value is not None and latest.value != confirmed.value:
                # Issue #28: 値が入れ替わる瞬間、旧value自体だけでなく、その値が
                # 確定した時点の信頼度・確定日時も「前回値側」として退避する
                # (previous_confidence/previous_confirmed_atは今回追加した専用カラム。
                # ReadingStabilizer/Validatorの判定ロジックには一切触れない)。
                latest.previous_value = latest.value
                latest.previous_confidence = latest.confidence
                latest.previous_confirmed_at = latest.confirmed_at
            if confirmed.value is not None:
                latest.value = confirmed.value
                latest.confirmed_at = confirmed.confirmed_at
            latest.confidence = confirmed.confidence
            latest.status = "ok" if status == CandidateStatus.CONFIRMED else "low_confidence"
            latest.last_error = None
            latest.current_error = None
            latest.engine = confirmed.engine or None
        elif status == CandidateStatus.NO_READING:
            # 連続読取失敗が閾値へ到達した場合のみread_error扱いにする。
            # (単発のNO_DETECTION等はここへ来ず、値も温存される)
            latest.status = "read_error"
            latest.last_error = confirmed.raw_error or "NO_DETECTION"
            latest.current_error = latest.last_error
            latest.engine = confirmed.engine or None
        elif status == CandidateStatus.PENDING and latest.value is None:
            # 初回起動などまだ一度もConfirmed実績が無い場合のみ「判定中」を表示する。
            # 既にConfirmed値が存在する場合は、そのまま(ok/low_confidence等)を維持する。
            latest.status = "pending"
        # rejected/invalid_format/decrease_detected/rate_exceededは一時的な異常値として
        # 静かに棄却する(LatestResult/Monitor.statusを一切変更しない)。Alertは常にこの
        # Confirmed Readingの正常経路だけを見る設計にするため、ここでRawの棄却理由を
        # 運用値へ混ぜない。

        latest.processing_time_ms = confirmed.processing_time_ms
        latest.timestamp = datetime.utcnow()

        # Issue #29: Monitor.statusは映像Runtime接続状態(connecting/running/
        # reconnecting/stopped/error、RuntimeManager経由でMonitorRuntimeのみが
        # 書き込む)専用のカラムとする。読取・推論状態は上のlatest.status(API上は
        # inference_status)だけで表現し、ここでMonitor.statusへは一切書き込まない。
        # 以前はここでCONFIRMED->"normal"/LOW_CONFIDENCE->"warning"/NO_READING->
        # "read_error"をMonitor.statusへも書き込んでいたが、この関数(save_result)は
        # 推論tickのたびに(RuntimeManagerの映像状態更新より遥かに高頻度で)呼ばれるため、
        # 実質的にMonitor.statusが常に読取状態で上書きされてしまい、かつRuntime再構築時に
        # 旧Runtimeのcallbackが書き込んだ"stopped"等と競合すると、映像が実際にはrunning中
        # でも状態バッジが停止中のまま残る不整合が生じていた。

        if status in _ACCEPTED_STATUSES or status == CandidateStatus.NO_READING:
            effective_value = confirmed.value if status in _ACCEPTED_STATUSES else None
            last_history = db.scalar(select(InferenceResult).where(InferenceResult.monitor_id == monitor_id).order_by(InferenceResult.created_at.desc()))
            should_record = last_history is None or last_history.value != effective_value or last_history.created_at < datetime.utcnow() - timedelta(seconds=60)
            if should_record:
                db.add(InferenceResult(monitor_id=monitor_id, value=effective_value, confidence=confirmed.confidence if status in _ACCEPTED_STATUSES else None, detections=[], processing_time_ms=confirmed.processing_time_ms, engine=confirmed.engine or None))
        db.commit()
    finally:
        db.close()
