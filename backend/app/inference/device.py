def resolve_device(requested: str) -> str:
    if not isinstance(requested, str):
        raise ValueError("device must be auto, cpu, or cuda:N")
    if requested == "cpu": return "cpu"
    if requested == "auto":
        try:
            import torch
            return "cuda:0" if torch.cuda.is_available() else "cpu"
        except ImportError:
            return "cpu"
    if requested.startswith("cuda:"):
        try:
            import torch
            index = int(requested.split(":", 1)[1])
            if index < 0:
                raise ValueError(f"CUDA device is unavailable: {requested}")
            if not torch.cuda.is_available() or index >= torch.cuda.device_count():
                raise ValueError(f"CUDA device is unavailable: {requested}")
        except ImportError as exc:
            raise ValueError("PyTorch is not installed") from exc
        return requested
    raise ValueError("device must be auto, cpu, or cuda:N")
