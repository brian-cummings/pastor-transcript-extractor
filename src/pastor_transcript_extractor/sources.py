from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from pastor_transcript_extractor.models import SourceType


class UnsupportedSourceError(ValueError):
    pass


def detect_source_type(url: str) -> SourceType:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    query = parse_qs(parsed.query)

    if "youtube.com" not in host and "youtu.be" not in host:
        raise UnsupportedSourceError("Only YouTube URLs are supported in V1.")

    if "list" in query:
        return SourceType.PLAYLIST
    if host.endswith("youtu.be"):
        return SourceType.VIDEO
    if path.startswith("/watch") and "v" in query:
        return SourceType.VIDEO
    if path.startswith("/@") or path.startswith("/channel/") or path.startswith("/c/") or path.startswith("/user/"):
        return SourceType.CHANNEL

    raise UnsupportedSourceError("Could not determine whether the YouTube URL is a video, playlist, or channel.")
