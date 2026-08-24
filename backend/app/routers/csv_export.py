from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from ..core.database import get_db
from ..models import Monitor
from ..schemas.system import CsvExportRunResponse, CsvExportSettingsInput, CsvExportSettingsResponse, CsvExportStatusResponse
from ..services import csv_export_service as svc
from runtime.csv_export_worker import csv_export_worker

router = APIRouter(prefix="/api/system/csv-export", tags=["csv-export"])


@router.get("", response_model=CsvExportStatusResponse)
def get_csv_export_status(db: Session = Depends(get_db)):
    settings = svc.get_settings(db)
    logs = svc.latest_export_log_by_monitor(db)
    monitors = db.query(Monitor).options(joinedload(Monitor.latest_result)).order_by(Monitor.id).all()
    last_errors = {outcome.monitor_id: outcome.detail for outcome in csv_export_worker.last_outcomes if outcome.status == "error"}
    monitor_rows = []
    for monitor in monitors:
        log = logs.get(monitor.id)
        monitor_rows.append({
            "monitor_id": monitor.id,
            "display_name": monitor.display_name,
            "last_exported_hour": log.hour_bucket if log else None,
            "last_exported_at": log.exported_at.isoformat() if log else None,
            "last_error": last_errors.get(monitor.id),
        })
    return CsvExportStatusResponse(
        enabled=settings.csv_export_enabled,
        output_folder=settings.csv_output_folder,
        worker_running=csv_export_worker.is_running(),
        last_tick_at=csv_export_worker.last_tick_at.isoformat() if csv_export_worker.last_tick_at else None,
        last_test_run_at=csv_export_worker.last_test_run_at.isoformat() if csv_export_worker.last_test_run_at else None,
        monitors=monitor_rows,
    )


@router.put("", response_model=CsvExportSettingsResponse)
def update_csv_export_settings(payload: CsvExportSettingsInput, db: Session = Depends(get_db)):
    settings = svc.update_settings(db, enabled=payload.enabled, output_folder=payload.output_folder)
    return CsvExportSettingsResponse(enabled=settings.csv_export_enabled, output_folder=settings.csv_output_folder)


@router.post("/run-now", response_model=CsvExportRunResponse)
def run_csv_export_now():
    """本番scheduler(1時間ごとのtick、argus_hourly_readings.csv)とは別の、テスト・確認用の
    即時実行API。argus_hourly_readings_test.csvへ追記するのみで、dedupを行わないため
    何度でも実行できる。本番のCsvExportLog(dedup)・最終出力日時には一切影響しない。"""
    try:
        outcomes = csv_export_worker.run_test_export()
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return CsvExportRunResponse(outcomes=[{"monitor_id": o.monitor_id, "display_name": o.display_name, "status": o.status, "detail": o.detail} for o in outcomes])
