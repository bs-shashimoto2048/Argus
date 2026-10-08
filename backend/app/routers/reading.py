import json
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.database import get_db
from ..services import monitor_service, reading_baseline_service as baseline_service
from reading.baseline import conflict_alert, conflict_active, conflict_duration_seconds
from reading.models import RawReading

from runtime.runtime_manager import runtime_manager

router = APIRouter(prefix="/api/monitors", tags=["reading"])


def _serialize_raw(reading: RawReading) -> dict:
    return {
        "value": reading.value,
        "confidence": reading.confidence,
        "timestamp": reading.timestamp.isoformat() if reading.timestamp else None,
        "engine": reading.engine,
        "error": reading.error,
        "detection_count": reading.detection_count,
    }


@router.get("/{monitor_id}/reading/diagnostics")
def reading_diagnostics(monitor_id: int):
    """Raw Reading -> Confirmed Readingの安定化状態を確認するためのDebug API。

    password/認証URL/filesystemの内部pathは含めない。通常UIで常用する想定はない。
    """
    runtime = runtime_manager.get_runtime(monitor_id)
    scheduler = runtime.inference_scheduler if runtime else None
    if scheduler is None:
        raise HTTPException(409, "モニターの推論Schedulerは稼働していません")

    confirmed = scheduler.latest_confirmed
    stabilizer = scheduler.stabilizer
    now = datetime.now(timezone.utc)
    conflict = stabilizer.conflict
    baseline = stabilizer.baseline_snapshot()
    return {
        # Issue #40: Raw(元の桁列)とは別に、baseline/合意候補/conflictを返す(値は最終運用値の形式=先頭0除去後)。
        "baseline": None if baseline is None else {
            "value": baseline["value"], "numeric_value": baseline["numeric_value"], "epoch": baseline["epoch"],
            "confirmed_at": baseline["confirmed_at"].isoformat() if baseline["confirmed_at"] else None,
        },
        "candidate": stabilizer.last_candidate,
        "conflict": None if conflict is None else {
            "status": conflict.status.value, "candidate": conflict.candidate, "count": conflict.count,
            "started_at": conflict.started_at.isoformat(), "last_at": conflict.last_at.isoformat(),
            "duration_seconds": int(conflict_duration_seconds(conflict)),
            "active": conflict_active(conflict, now), "alert": conflict_alert(conflict, now),
        },
        "enabled": stabilizer.settings.enabled,
        "mode": stabilizer.settings.mode.value,
        "consecutive_failures": stabilizer.consecutive_failures,
        "recent_raw": [_serialize_raw(reading) for reading in stabilizer.recent_raw],
        "confirmed": {
            "value": confirmed.value if confirmed else None,
            "confidence": confirmed.confidence if confirmed else None,
            "confirmed_at": confirmed.confirmed_at.isoformat() if confirmed and confirmed.confirmed_at else None,
            "raw_count": confirmed.raw_count if confirmed else 0,
            "agreement_count": confirmed.agreement_count if confirmed else 0,
            "engine": confirmed.engine if confirmed else None,
            "validation_status": confirmed.validation_status.value if confirmed else None,
            "raw_value": confirmed.raw_value if confirmed else None,
            "raw_confidence": confirmed.raw_confidence if confirmed else None,
        },
    }


class ResetRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    operator: str = Field(min_length=1, max_length=160)

    def cleaned(self) -> tuple[str, str]:
        reason, operator = self.reason.strip(), self.operator.strip()
        if not reason or not operator:
            raise HTTPException(422, "reasonとoperatorは必須です")
        return reason, operator


class RebaseRequest(ResetRequest):
    value: str = Field(min_length=1, max_length=64)
    force: bool = False


def _monitor_or_404(db: Session, monitor_id: int):
    try:
        return monitor_service.get_monitor(db, monitor_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


def _client_host(request: Request) -> str:
    return request.client.host if request.client else ""


def _run_baseline_action(action):
    try:
        return action()
    except baseline_service.ReadingDisabledError as exc:
        raise HTTPException(409, {"code": "READING_DISABLED", "message": str(exc)}) from exc
    except baseline_service.InvalidBaselineValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except baseline_service.ForceRequiredError as exc:
        raise HTTPException(409, {"code": "FORCE_REQUIRED", "message": str(exc), "candidate": exc.candidate,
                                  "requested": exc.requested, "tolerance": str(exc.tolerance)}) from exc


@router.get("/{monitor_id}/reading/baseline")
def get_baseline(monitor_id: int, db: Session = Depends(get_db)):
    """monotonic baseline(基準値)・conflict(固着)状態・最新のRaw合意候補を返す。"""
    return baseline_service.get_status(db, _monitor_or_404(db, monitor_id))


@router.post("/{monitor_id}/reading/baseline/reset")
def reset_baseline(monitor_id: int, body: ResetRequest, request: Request, db: Session = Depends(get_db)):
    """baselineをクリアする。次に正常にCONFIRMEDされた値が新しいbaselineになる(表示値は直接変更しない)。"""
    reason, operator = body.cleaned()
    monitor = _monitor_or_404(db, monitor_id)
    return _run_baseline_action(lambda: baseline_service.reset_baseline(db, monitor, reason, operator, _client_host(request)))


@router.post("/{monitor_id}/reading/baseline/rebase")
def rebase_baseline(monitor_id: int, body: RebaseRequest, request: Request, db: Session = Depends(get_db)):
    """baselineを、運用者が実メーターで確認した値へ置き換える(表示値は直接変更しない)。"""
    reason, operator = body.cleaned()
    monitor = _monitor_or_404(db, monitor_id)
    return _run_baseline_action(lambda: baseline_service.rebase_baseline(db, monitor, body.value, reason, operator, _client_host(request), body.force))


@router.get("/{monitor_id}/reading/baseline/events")
def baseline_events(monitor_id: int, limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)):
    """baseline操作の監査履歴(新しい順)。Monitor削除後も取得できる。"""
    return {"events": baseline_service.list_events(db, monitor_id, limit)}


@router.post("/{monitor_id}/reading/capture")
def capture_dataset_candidate(monitor_id: int):
    """現在フレームをDataset候補として保存する開発者向け機能(Issue #56-58)。

    本番ユーザーの誤操作を避けるため既定で無効。`ARGUS_ENABLE_DATASET_CAPTURE=1`
    設定時のみ有効。password/認証URL等のcredentialはmetadataへ含めない。
    NO_DETECTION/LOW_CONFIDENCE/reading rejected等のhard exampleを狙って
    保存したい場合も、このAPIを呼ぶタイミングは呼び出し側(将来のUI/運用)が決める。
    """
    if os.getenv("ARGUS_ENABLE_DATASET_CAPTURE") != "1":
        raise HTTPException(403, "データ収集モードは無効です(ARGUS_ENABLE_DATASET_CAPTURE=1で有効化してください)")

    runtime = runtime_manager.get_runtime(monitor_id)
    if runtime is None:
        raise HTTPException(409, "モニターのRuntimeは稼働していません")
    data, _ = runtime.buffer.get()
    if not data:
        raise HTTPException(503, "映像フレームをまだ取得できていません")

    scheduler = runtime.inference_scheduler
    confirmed = scheduler.latest_confirmed if scheduler else None
    raw = scheduler.latest_result if scheduler else None

    out_dir = settings.data_dir / "dataset_candidates" / str(monitor_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    image_path = out_dir / f"{stamp}.jpg"
    meta_path = out_dir / f"{stamp}.json"
    image_path.write_bytes(data)
    meta_path.write_text(json.dumps({
        "monitor_id": monitor_id,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "raw_value": raw.value if raw else None,
        "raw_confidence": raw.confidence if raw else None,
        "raw_error": raw.error if raw else None,
        "confirmed_value": confirmed.value if confirmed else None,
        "confirmed_status": confirmed.validation_status.value if confirmed else None,
        "engine": raw.engine if raw else None,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    return {"saved": True, "image": image_path.name, "monitor_id": monitor_id}
