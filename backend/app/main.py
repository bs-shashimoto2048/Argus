import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .core.config import settings
from .core.database import Base, SessionLocal, engine
from sqlalchemy import text
from .models import Monitor
from .routers import cameras, csv_export, data_storage, health, monitors, preprocess, reading, records, roi, sources, streams, system
from runtime.runtime_manager import runtime_manager
from runtime.csv_export_worker import csv_export_worker
from runtime.hourly_record_worker import hourly_record_worker
from runtime.record_writer import record_writer
from runtime.video_reader import ReaderConfig
from .services.secret_store import decrypt
from .services.result_store import save_result
from .services.reading_record_service import backfill_value_source
from .services.reading_baseline_service import restore_baseline
from .services.monitor_service import _build_inference_settings, backfill_display_order

logger = logging.getLogger("argus.startup")

def _set_result(monitor_id: int, result):
    return save_result(monitor_id, result)  # そのtickの運用値の状態(snapshot用)を返す

def _set_status(monitor_id: int, status: str) -> None:
    db = SessionLocal()
    try:
        monitor = db.get(Monitor, monitor_id)
        if monitor:
            monitor.status = status
            db.commit()
    finally: db.close()

@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(engine)
    if engine.url.get_backend_name() == "sqlite":
        with engine.begin() as connection:
            columns = connection.execute(text("PRAGMA table_info(url_histories)")).all()
            if not any(row[1] == "encrypted_password" for row in columns):
                connection.execute(text("ALTER TABLE url_histories ADD COLUMN encrypted_password VARCHAR(4096)"))
            for table, column, definition in (
                ("latest_results", "status", "VARCHAR(32) DEFAULT 'disabled'"),
                ("latest_results", "engine", "VARCHAR(32)"),
                ("latest_results", "processing_time_ms", "FLOAT"),
                ("latest_results", "last_error", "VARCHAR(128)"),
                ("latest_results", "current_error", "VARCHAR(128)"),
                ("latest_results", "previous_confidence", "FLOAT"),
                ("latest_results", "previous_confirmed_at", "DATETIME"),
                ("latest_results", "confirmed_at", "DATETIME"),
                ("inference_results", "engine", "VARCHAR(32)"),
                ("system_settings", "hourly_record_enabled", "BOOLEAN DEFAULT 1"),
                ("system_settings", "image_root_folder", "VARCHAR(500)"),
                ("system_settings", "excel_output_folder", "VARCHAR(500)"),
                ("system_settings", "save_original_image", "BOOLEAN DEFAULT 1"),
                ("system_settings", "save_overlay_image", "BOOLEAN DEFAULT 1"),
                ("system_settings", "storage_warn_free_gb", "FLOAT DEFAULT 10"),
                ("system_settings", "storage_stop_free_gb", "FLOAT DEFAULT 5"),
                ("reading_records", "value_source", "VARCHAR(16) DEFAULT 'none'"),
                ("monitors", "display_order", "INTEGER"),
                ("reading_records", "raw_confidence", "FLOAT"),
                ("reading_records", "inference_at", "DATETIME"),
                ("reading_records", "original_value", "VARCHAR(128)"),
                ("reading_records", "correction_count", "INTEGER DEFAULT 0"),
                ("reading_records", "corrected_at", "DATETIME"),
                ("reading_records", "corrected_by", "VARCHAR(80)"),
                ("inference_settings", "reading", "JSON"),
                ("inference_settings", "roi_mode", "VARCHAR(32) DEFAULT 'filter_only'"),
                ("inference_settings", "context_margin", "FLOAT DEFAULT 1.0"),
            ):
                table_columns = connection.execute(text(f"PRAGMA table_info({table})")).all()
                if not any(row[1] == column for row in table_columns):
                    connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))
                    if (table, column) == ("reading_records", "value_source"):
                        backfill_value_source(connection)
            # 表示順が未設定(NULL)のMonitorは、現在の安定した順序(id昇順)の順位で補完する。設定済みの値は変更しない(冪等)。
            backfill_display_order(connection)
    runtime_manager.set_status_callback(_set_status)
    runtime_manager.set_result_callback(_set_result)
    runtime_manager.set_baseline_provider(restore_baseline)
    db = SessionLocal()
    try:
        for monitor in db.query(Monitor).all():
            if monitor.enabled and monitor.source:
                try:
                    inference_settings = _build_inference_settings(monitor.inference)
                    runtime_manager.start_monitor(monitor.id, ReaderConfig(source_type=monitor.source.source_type, device_id=monitor.source.device_id, url=monitor.source.url, username=monitor.source.username, password=decrypt(monitor.source.encrypted_password), video_fps=monitor.inference.video_fps if monitor.inference else 15.0, inference_settings=inference_settings))
                except Exception:
                    # 1台のRuntime起動失敗が他Monitor・アプリ全体の起動を止めないようにする。
                    logger.exception("monitor %s のRuntime起動に失敗しました。このMonitorは停止状態のまま起動を継続します。", monitor.id)
    finally:
        db.close()
    csv_export_worker.start()
    record_writer.start()
    hourly_record_worker.start()
    yield
    hourly_record_worker.stop()
    record_writer.stop()
    csv_export_worker.stop()
    runtime_manager.stop_all()

app = FastAPI(title=settings.app_name, version=settings.version, lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_origin_regex=settings.cors_origin_regex, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(health.router)
app.include_router(cameras.router)
app.include_router(monitors.router)
app.include_router(sources.router)
app.include_router(streams.router)
app.include_router(preprocess.router)
app.include_router(roi.router)
app.include_router(reading.router)
app.include_router(system.router)
app.include_router(csv_export.router)
app.include_router(records.router)
app.include_router(data_storage.router)
