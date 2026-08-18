"""推論関連の依存ライブラリ・デバイス状況を確認するためのDiagnostics。

Backend起動やDiagnostics APIから呼び出す。秘密情報・内部パスは返さない。
"""
from __future__ import annotations

from .engines import _find_tesseract_executable


def torch_diagnostics() -> dict:
    try:
        import torch
    except ImportError:
        return {"available": False, "version": None, "cuda_available": False, "cuda_version": None, "device_count": 0, "devices": []}
    cuda_available = bool(torch.cuda.is_available())
    devices = []
    if cuda_available:
        for index in range(torch.cuda.device_count()):
            devices.append({"index": index, "name": torch.cuda.get_device_name(index)})
    return {
        "available": True,
        "version": torch.__version__,
        "cuda_available": cuda_available,
        "cuda_version": torch.version.cuda if cuda_available else None,
        "device_count": len(devices),
        "devices": devices,
    }


def ultralytics_diagnostics() -> dict:
    try:
        import ultralytics
    except ImportError:
        return {"available": False, "version": None}
    return {"available": True, "version": getattr(ultralytics, "__version__", None)}


def easyocr_diagnostics() -> dict:
    try:
        import easyocr
    except ImportError:
        return {"available": False}
    return {"available": True}


def tesseract_diagnostics() -> dict:
    try:
        import pytesseract
    except ImportError:
        return {"python_package": False, "executable": False, "version": None}
    executable_path = _find_tesseract_executable()
    version = None
    if executable_path:
        try:
            pytesseract.pytesseract.tesseract_cmd = executable_path
            version = str(pytesseract.get_tesseract_version())
        except Exception:
            executable_path = None
    return {"python_package": True, "executable": bool(executable_path), "version": version}


def device_options() -> list[dict]:
    """Frontendのdevice選択肢を実環境から生成する。存在しないGPUは含めない。"""
    options = [{"value": "auto", "label": "Auto"}, {"value": "cpu", "label": "CPU"}]
    for device in torch_diagnostics()["devices"]:
        options.append({"value": f"cuda:{device['index']}", "label": f"GPU {device['index']} - {device['name']}"})
    return options


def system_diagnostics() -> dict:
    return {
        "torch": torch_diagnostics(),
        "ultralytics": ultralytics_diagnostics(),
        "easyocr": easyocr_diagnostics(),
        "tesseract": tesseract_diagnostics(),
        "devices": device_options(),
    }
