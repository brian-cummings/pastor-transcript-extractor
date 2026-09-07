from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from pastor_transcript_extractor.config import AppPaths
from pastor_transcript_extractor.identity import persist_metadata_snapshot
from pastor_transcript_extractor.media import VideoUnavailableError, fetch_video_metadata
from pastor_transcript_extractor.models import Video
from pastor_transcript_extractor.storage import Database


METADATA_ENRICHMENT_SOURCE_KIND = "yt_dlp_full_video"


@dataclass(frozen=True, slots=True)
class MetadataEnrichmentResult:
    eligible: int
    enriched: int
    already_complete: int
    unavailable: int
    failed: int


MetadataFetcher = Callable[[str, str, str | None], dict[str, Any]]
ProgressCallback = Callable[[int, int, Video, str, str | None], None]


def latest_metadata_description(database: Database, video: Video) -> str | None:
    artifact = database.get_latest_metadata_artifact_for_video(video.id)
    if artifact is None:
        return None
    try:
        payload = json.loads(Path(artifact.artifact_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, Mapping):
        return None
    raw_metadata = payload.get("raw_metadata")
    if not isinstance(raw_metadata, Mapping):
        return None
    description = raw_metadata.get("description")
    if not isinstance(description, str) or not description.strip():
        return None
    return description


def videos_for_profile(database: Database, profile_id: int) -> tuple[Video, ...]:
    if database.get_speaker_profile(profile_id) is None:
        raise ValueError(f"Speaker profile does not exist: {profile_id}")
    videos: dict[int, Video] = {}
    for observation_id in database.list_effective_observation_ids_for_profile(profile_id):
        observation = database.get_speaker_observation(observation_id)
        if observation is None:
            continue
        video = database.get_video_by_id(observation.video_id)
        if video is not None:
            videos[video.id] = video
    return tuple(videos[video_id] for video_id in sorted(videos))


def videos_for_profiles(
    database: Database, profile_ids: Sequence[int]
) -> tuple[Video, ...]:
    videos: dict[int, Video] = {}
    for profile_id in profile_ids:
        for video in videos_for_profile(database, profile_id):
            videos[video.id] = video
    return tuple(videos[video_id] for video_id in sorted(videos))


def enrich_metadata(
    database: Database,
    app_paths: AppPaths,
    videos: Sequence[Video],
    *,
    yt_dlp_bin: str,
    yt_dlp_js_runtimes: str | None = None,
    fetcher: MetadataFetcher | None = None,
    progress_callback: ProgressCallback | None = None,
) -> MetadataEnrichmentResult:
    selected = tuple({video.id: video for video in videos}.values())
    fetch_metadata = fetcher or fetch_video_metadata
    eligible = 0
    enriched = 0
    already_complete = 0
    unavailable = 0
    failed = 0
    total = len(selected)

    for index, video in enumerate(selected, start=1):
        if latest_metadata_description(database, video) is not None:
            already_complete += 1
            if progress_callback is not None:
                progress_callback(index, total, video, "already_complete", None)
            continue
        eligible += 1
        try:
            metadata = fetch_metadata(video.url, yt_dlp_bin, yt_dlp_js_runtimes)
            description = metadata.get("description")
            if not isinstance(description, str) or not description.strip():
                raise ValueError("full metadata has no nonblank description")
            pastor = (
                database.get_pastor_by_id(video.pastor_id)
                if video.pastor_id is not None
                else None
            )
            persist_metadata_snapshot(
                database,
                app_paths,
                video=video,
                pastor=pastor,
                source_kind=METADATA_ENRICHMENT_SOURCE_KIND,
                raw_metadata=metadata,
            )
        except VideoUnavailableError as error:
            unavailable += 1
            if progress_callback is not None:
                progress_callback(index, total, video, "unavailable", str(error))
            continue
        except Exception as error:
            failed += 1
            if progress_callback is not None:
                progress_callback(index, total, video, "failed", str(error))
            continue
        enriched += 1
        if progress_callback is not None:
            progress_callback(index, total, video, "enriched", None)

    return MetadataEnrichmentResult(
        eligible=eligible,
        enriched=enriched,
        already_complete=already_complete,
        unavailable=unavailable,
        failed=failed,
    )
