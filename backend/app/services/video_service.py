from ..schemas.video_source import VideoSourceInput
from runtime.video_reader import ReaderConfig, VideoCheckResult, VideoReader


def reader_config(
    source: VideoSourceInput,
    password: str | None = None,
    video_fps: float = 15.0,
    inference_settings: dict | None = None,
) -> ReaderConfig:
    return ReaderConfig(
        source_type=source.source_type,
        device_id=source.device_id,
        url=source.url,
        username=source.username,
        password=password,
        video_fps=video_fps,
        inference_settings=inference_settings,
    )


def check_source(source: VideoSourceInput, password: str | None = None) -> tuple[bool, str]:
    if source.source_type == "url" and not (source.url or "").strip():
        return False, "URLを入力してください"
    result = check_source_detailed(source, password)
    return result.connected, result.message


def check_source_detailed(source: VideoSourceInput, password: str | None = None) -> VideoCheckResult:
    return VideoReader(reader_config(source, password)).check_detailed()
