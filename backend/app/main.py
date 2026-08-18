from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .core.config import settings
from .core.database import Base, SessionLocal, engine
from .models import Monitor
from .routers import cameras, health, monitors, sources, streams
from runtime.runtime_manager import runtime_manager
from runtime.video_reader import ReaderConfig
from .services.secret_store import decrypt

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
    runtime_manager.set_status_callback(_set_status)
    db = SessionLocal()
    try:
        for monitor in db.query(Monitor).all():
            if monitor.enabled and monitor.source:
                runtime_manager.start_monitor(monitor.id, ReaderConfig(source_type=monitor.source.source_type, device_id=monitor.source.device_id, url=monitor.source.url, username=monitor.source.username, password=decrypt(monitor.source.encrypted_password)))
    finally:
        db.close()
    yield
    runtime_manager.stop_all()

app = FastAPI(title=settings.app_name, version=settings.version, lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_origin_regex=settings.cors_origin_regex, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(health.router)
app.include_router(cameras.router)
app.include_router(monitors.router)
app.include_router(sources.router)
app.include_router(streams.router)
