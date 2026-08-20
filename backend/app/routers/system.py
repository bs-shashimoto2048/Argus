import os
import threading

from fastapi import APIRouter

from ..core.config import settings
from ..inference.diagnostics import system_diagnostics
from ..inference.model_catalog import load_registry

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/inference")
def inference_diagnostics():
    return system_diagnostics()


@router.get("/process")
def process_diagnostics():
    """Backendプロセス自体のリソース使用状況(Issue #14: 複数Monitor同時稼働時の
    Thread/Memory調査用)。credential/URLは含まない。psutilが無い環境ではmemory/
    handle等はNoneを返す(threading.active_count()は標準ライブラリのみで取得可能)。
    """
    from runtime.runtime_manager import runtime_manager

    active_runtimes = runtime_manager.count()
    result = {
        "pid": os.getpid(),
        "python_thread_count": threading.active_count(),
        "active_monitor_runtimes": active_runtimes,
        "memory_rss_mb": None,
        "os_thread_count": None,
        "handle_count": None,
    }
    try:
        import psutil

        proc = psutil.Process(os.getpid())
        result["memory_rss_mb"] = round(proc.memory_info().rss / 1024 / 1024, 1)
        result["os_thread_count"] = proc.num_threads()
        try:
            result["handle_count"] = proc.num_handles()
        except AttributeError:
            pass  # Windows以外ではnum_handles()が無い
    except ImportError:
        pass
    return result


@router.get("/models")
def list_models():
    """data/models/registry.jsonのModel Catalogを返す(role/精度要約/推奨設定等)。"""
    return {"models": load_registry(settings.data_dir / "models")}
