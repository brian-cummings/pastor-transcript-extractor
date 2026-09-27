from __future__ import annotations

from pathlib import Path
import time

from rich.console import Console

from pastor_transcript_extractor import discovery, transcription
from pastor_transcript_extractor.workflows.caption_acquisition import (
    CaptionAcquisitionResult,
    fetch_captions_service as _fetch_captions_service,
)
from pastor_transcript_extractor.workflows.source_discovery import (
    DiscoveryServiceResult,
    discover_sources_service as _discover_sources_service,
)


DEFAULT_DISCOVER_LIMIT = 26
console = Console()


def discover_sources_service(
    limit: int | None = DEFAULT_DISCOVER_LIMIT,
    all_videos: bool = False,
    source_id: int | None = None,
    base_dir: Path | None = None,
) -> DiscoveryServiceResult:
    """Adapt source discovery progress and extraction to the command surface."""
    return _discover_sources_service(
        limit,
        all_videos,
        source_id,
        base_dir,
        progress_callback=lambda message: console.print(message, markup=False),
        extract_videos=discovery.extract_discovered_videos,
    )


def fetch_captions_service(
    source_id: int | None = None,
    base_dir: Path | None = None,
    video_ids: set[int] | None = None,
    request_interval_seconds: float = 0.0,
    cookies_from_browser: str | None = None,
    cookies: Path | None = None,
) -> CaptionAcquisitionResult:
    """Adapt caption acquisition progress and scheduling to the command surface."""
    return _fetch_captions_service(
        source_id=source_id,
        base_dir=base_dir,
        video_ids=video_ids,
        request_interval_seconds=request_interval_seconds,
        cookies_from_browser=cookies_from_browser,
        cookies=cookies,
        progress_callback=console.print,
        fetch_captions=transcription.fetch_captions_video,
        monotonic=time.monotonic,
        sleeper=time.sleep,
    )
