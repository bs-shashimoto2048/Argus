from ..schemas.video_source import VideoSourceInput
from runtime.video_reader import ReaderConfig, VideoReader

def reader_config(source: VideoSourceInput, password: str | None = None) -> ReaderConfig:
    return ReaderConfig(source_type=source.source_type, device_id=source.device_id, url=source.url, username=source.username, password=password)

def check_source(source: VideoSourceInput, password: str | None = None) -> tuple[bool, str]:
    if source.source_type == "url" and not (source.url or "").strip(): return False, "URLを入力してください"
    return VideoReader.check(reader_config(source, password))
