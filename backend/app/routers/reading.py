import json
import os
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from ..core.config import settings
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
    return {
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
