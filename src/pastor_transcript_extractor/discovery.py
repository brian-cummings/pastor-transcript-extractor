from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, urlparse


@dataclass(frozen=True, slots=True)
class DiscoveredVideo:
    youtube_video_id: str
    title: str
    url: str
    channel_name: str | None
    published_at: str | None
    duration_seconds: int | None
    metadata: dict[str, Any] = field(default_factory=dict, compare=False)


def sort_discovered_videos_by_recency(videos: list[DiscoveredVideo]) -> list[DiscoveredVideo]:
    def sort_key(video: DiscoveredVideo) -> tuple[int, str]:
        if video.published_at is None:
            return (0, "")
        return (1, video.published_at)

    return sorted(videos, key=sort_key, reverse=True)


def _published_at_from_info(info: dict[str, Any]) -> str | None:
    timestamp = info.get("timestamp") or info.get("release_timestamp")
    if timestamp is None:
        return None
    return datetime.fromtimestamp(float(timestamp), tz=timezone.utc).isoformat()


def _entry_timestamp(info: dict[str, Any]) -> float | None:
    timestamp = info.get("timestamp") or info.get("release_timestamp")
    if timestamp is None:
        return None
    return float(timestamp)


def _best_url(info: dict[str, Any]) -> str:
    video_id = info.get("id")
    if video_id:
        return f"https://www.youtube.com/watch?v={video_id}"
    webpage_url = info.get("webpage_url")
    if webpage_url:
        return str(webpage_url)
    return str(info.get("url", ""))


def _looks_like_video_payload(info: dict[str, Any]) -> bool:
    video_id = info.get("id") or info.get("video_id")
    if isinstance(video_id, str) and len(video_id) == 11:
        return True

    webpage_url = info.get("webpage_url")
    if isinstance(webpage_url, str):
        parsed = urlparse(webpage_url)
        query = parse_qs(parsed.query)
        if parsed.path == "/watch" and "v" in query:
            return True
        if parsed.netloc.lower().endswith("youtu.be"):
            return True

    original_url = info.get("original_url") or info.get("url")
    if isinstance(original_url, str):
        parsed = urlparse(original_url)
        query = parse_qs(parsed.query)
        if parsed.path == "/watch" and "v" in query:
            return True
        if parsed.netloc.lower().endswith("youtu.be"):
            return True

    ie_key = info.get("ie_key")
    if isinstance(ie_key, str) and ie_key.lower() == "youtube":
        return True

    return False


def _normalize_entry(entry: dict[str, Any]) -> DiscoveredVideo | None:
    youtube_video_id = entry.get("id") or entry.get("video_id")
    title = entry.get("title")
    if not youtube_video_id or not title:
        return None
    return DiscoveredVideo(
        youtube_video_id=str(youtube_video_id),
        title=str(title),
        url=_best_url(entry),
        channel_name=entry.get("channel") or entry.get("uploader"),
        published_at=_published_at_from_info(entry),
        duration_seconds=entry.get("duration"),
        metadata=dict(entry),
    )


def _tab_priority(entry: dict[str, Any]) -> int:
    webpage_url = entry.get("webpage_url")
    if not isinstance(webpage_url, str):
        return 0
    if "/streams" in webpage_url:
        return 3
    if "/videos" in webpage_url:
        return 2
    if "/shorts" in webpage_url:
        return 1
    return 0


def _iter_video_entries(payload: dict[str, Any]) -> list[dict[str, Any]]:
    discovered: list[tuple[float | None, int, int, dict[str, Any]]] = []
    sequence = 0

    def visit(entry: dict[str, Any], inherited_priority: int = 0) -> None:
        nonlocal sequence
        nested_entries = entry.get("entries")
        current_priority = max(inherited_priority, _tab_priority(entry))
        if isinstance(nested_entries, list):
            for nested in nested_entries:
                if isinstance(nested, dict):
                    visit(nested, current_priority)
            return

        if _looks_like_video_payload(entry):
            discovered.append((_entry_timestamp(entry), current_priority, sequence, entry))
            sequence += 1

    visit(payload)
    discovered.sort(
        key=lambda item: (
            item[0] is not None,
            item[0] if item[0] is not None else float("-inf"),
            item[1],
            -item[2],
        ),
        reverse=True,
    )
    return [entry for _, _, _, entry in discovered]


def extract_discovered_videos(url: str, yt_dlp_bin: str, yt_dlp_js_runtimes: str | None = None) -> list[DiscoveredVideo]:
    command = [
        yt_dlp_bin,
        "--dump-single-json",
        "--flat-playlist",
        "--skip-download",
        "--no-warnings",
        "--quiet",
    ]
    if yt_dlp_js_runtimes:
        command.extend(["--js-runtimes", yt_dlp_js_runtimes])
    command.append(url)
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    payload = json.loads(result.stdout)

    entries = _iter_video_entries(payload) if isinstance(payload, dict) else []

    discovered: list[DiscoveredVideo] = []
    for entry in entries:
        normalized = _normalize_entry(entry)
        if normalized is not None:
            discovered.append(normalized)
    return sort_discovered_videos_by_recency(discovered)
