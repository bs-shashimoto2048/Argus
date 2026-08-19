from fastapi import APIRouter, HTTPException

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
