from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from pastor_transcript_extractor.config import (
    AppPaths,
    ToolConfig,
    build_paths,
    build_tool_config,
    ensure_directories,
)
from pastor_transcript_extractor.discovery import (
    extract_discovered_videos,
    sort_discovered_videos_by_recency,
)
from pastor_transcript_extractor.identity import (
    latest_metadata_live_status,
    persist_metadata_snapshot,
)
from pastor_transcript_extractor.models import VideoStatus
from pastor_transcript_extractor.sermon_policy import (
    duration_meets_sermon_minimum,
    duration_within_sermon_maximum,
    live_status_is_sermon_eligible,
    maximum_sermon_duration_seconds,
    minimum_sermon_duration_seconds,
    publication_is_not_future,
    video_is_sermon_eligible,
)
from pastor_transcript_extractor.storage import Database


DEFAULT_DISCOVER_LIMIT = 26
DiscoveryProgressCallback = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class DiscoveryRequest:
    limit: int | None = DEFAULT_DISCOVER_LIMIT
    all_videos: bool = False
    source_id: int | None = None


@dataclass(frozen=True, slots=True)
class DiscoveryServiceResult:
    selected_video_ids_by_source: dict[int, tuple[int, ...]]
    found_count: int = 0
    discovered_count: int = 0
    skipped_count: int = 0
    excluded_count: int = 0
    below_minimum_count: int = 0
    above_maximum_count: int = 0
    active_live_count: int = 0
    future_count: int = 0


def _discover_candidate_window(
    *,
    discovered_videos,
    existing_source_videos,
    effective_limit: int | None,
):
    if effective_limit is None:
        return discovered_videos

    candidates = list(discovered_videos[:effective_limit])
    candidate_ids = {video.youtube_video_id for video in candidates}
    retained_published_values = sorted(
        [video.published_at.isoformat() for video in existing_source_videos if video.published_at is not None]
    )
    if not retained_published_values:
        return candidates

    oldest_retained_published_at = retained_published_values[0]
    for video in discovered_videos[effective_limit:]:
        if video.published_at is None or video.published_at < oldest_retained_published_at:
            continue
        if video.youtube_video_id in candidate_ids:
            continue
        candidates.append(video)
        candidate_ids.add(video.youtube_video_id)
    return candidates
def discover_sources(
    database: Database,
    app_paths: AppPaths,
    tool_config: ToolConfig,
    request: DiscoveryRequest,
    *,
    progress_callback: DiscoveryProgressCallback | None = None,
    extract_videos: Callable[..., list] = extract_discovered_videos,
) -> DiscoveryServiceResult:
    limit = request.limit
    all_videos = request.all_videos
    source_id = request.source_id

    def report(message: object, **_kwargs: object) -> None:
        if progress_callback is not None:
            progress_callback(str(message))

    sources = database.list_sources()
    if source_id is not None:
        sources = [source for source in sources if source.id == source_id]
    else:
        sources = [source for source in sources if source.processing_enabled]
    if not sources:
        report("No sources queued.")
        return DiscoveryServiceResult({})

    discovered_count = 0
    skipped_count = 0
    excluded_count = 0
    below_minimum_count = 0
    above_maximum_count = 0
    active_live_count = 0
    future_count = 0
    found_count = 0
    effective_limit = None if all_videos else limit
    minimum_duration = minimum_sermon_duration_seconds()
    maximum_duration = maximum_sermon_duration_seconds()
    existing_ids = {
        video.youtube_video_id for video in database.list_videos()
    }
    excluded_ids = {
        video.youtube_video_id for video in database.list_excluded_videos()
    }
    total_sources = len(sources)
    source_attempts: dict[int, int] = {}
    selected_video_ids_by_source: dict[int, tuple[int, ...]] = {}
    for index, source in enumerate(sources, start=1):
        source_attempts[source.id] = source_attempts.get(source.id, 0) + 1
        retrying = source_attempts[source.id] > 1
        pastor_record = (
            database.get_pastor_by_id(source.pastor_id)
            if source.pastor_id is not None
            else None
        )
        organization_record = (
            database.get_organization_by_id(source.organization_id)
            if source.organization_id is not None
            else None
        )
        publisher_label = (
            organization_record.slug
            if organization_record is not None
            else "organization-unknown"
        )
        if pastor_record is not None:
            context_label = (
                f"for pastor {pastor_record.slug} target; "
                f"publisher {publisher_label}"
            )
        else:
            context_label = f"for publisher {publisher_label}"
        progress_label = (
            f"Discovery retry [{source_attempts[source.id] - 1}/1]"
            if retrying
            else f"[{index}/{total_sources}] Discovering"
        )
        report(
            f"{progress_label} source #{source.id} {context_label}: {source.url}",
            markup=False,
        )
        try:
            discovered_videos = extract_videos(
                source.url,
                tool_config.yt_dlp_bin,
                tool_config.yt_dlp_js_runtimes,
            )
        except Exception as error:
            if not retrying:
                report(
                    f"[red]Failed to discover[/red] {source.url}: {error}; "
                    "deferred for retry after the first pass"
                )
                sources.append(source)
            else:
                report(
                    f"[red]Failed discovery retry[/red] {source.url}: {error}"
                )
            selected_video_ids_by_source[source.id] = ()
            continue

        discovered_videos = sort_discovered_videos_by_recency(discovered_videos)
        source_found_count = len(discovered_videos)
        short_videos = [
            video
            for video in discovered_videos
            if not duration_meets_sermon_minimum(
                video.duration_seconds,
                minimum_seconds=minimum_duration,
            )
            and publication_is_not_future(video.published_at)
            and live_status_is_sermon_eligible(video.metadata.get("live_status"))
        ]
        future_videos = [
            video
            for video in discovered_videos
            if not publication_is_not_future(video.published_at)
        ]
        long_videos = [
            video
            for video in discovered_videos
            if not duration_within_sermon_maximum(
                video.duration_seconds,
                maximum_seconds=maximum_duration,
            )
            and publication_is_not_future(video.published_at)
            and live_status_is_sermon_eligible(video.metadata.get("live_status"))
        ]
        active_live_videos = [
            video
            for video in discovered_videos
            if not live_status_is_sermon_eligible(video.metadata.get("live_status"))
            and publication_is_not_future(video.published_at)
        ]
        discovered_videos = [
            video
            for video in discovered_videos
            if video_is_sermon_eligible(
                video.duration_seconds,
                video.published_at,
                minimum_seconds=minimum_duration,
                maximum_seconds=maximum_duration,
                live_status=video.metadata.get("live_status"),
            )
        ]
        selected_discovered = (
            discovered_videos
            if effective_limit is None
            else discovered_videos[:effective_limit]
        )
        selected_youtube_ids = {
            video.youtube_video_id
            for video in selected_discovered
            if video.youtube_video_id not in excluded_ids
        }
        found_count += source_found_count
        below_minimum_count += len(short_videos)
        above_maximum_count += len(long_videos)
        active_live_count += len(active_live_videos)
        future_count += len(future_videos)
        existing_source_videos = database.list_videos_by_source_id(source.id)
        discovered_videos = _discover_candidate_window(
            discovered_videos=discovered_videos,
            existing_source_videos=existing_source_videos,
            effective_limit=effective_limit,
        )

        source_discovered_count = 0
        source_skipped_count = 0
        source_excluded_count = 0
        for discovered in discovered_videos:
            if discovered.youtube_video_id in excluded_ids:
                excluded_count += 1
                source_excluded_count += 1
                continue
            if discovered.youtube_video_id in existing_ids:
                skipped_count += 1
                source_skipped_count += 1
                existing_video = database.get_video_by_youtube_id(
                    discovered.youtube_video_id
                )
                discovered_live_status = discovered.metadata.get("live_status")
                if (
                    existing_video is not None
                    and isinstance(discovered_live_status, str)
                    and discovered_live_status
                    != latest_metadata_live_status(database, existing_video.id)
                ):
                    # Preserve live-state transitions so a completed broadcast
                    # can become eligible without rewriting older snapshots.
                    persist_metadata_snapshot(
                        database,
                        app_paths,
                        video=existing_video,
                        pastor=pastor_record,
                        source_kind="yt_dlp_flat_playlist",
                        raw_metadata=discovered.metadata,
                    )
                continue
            video = database.add_video(
                source_id=source.id,
                pastor_id=source.pastor_id,
                youtube_video_id=discovered.youtube_video_id,
                title=discovered.title,
                url=discovered.url,
                channel_name=discovered.channel_name,
                published_at=discovered.published_at,
                duration_seconds=discovered.duration_seconds,
                status=VideoStatus.DISCOVERED,
            )
            persist_metadata_snapshot(
                database,
                app_paths,
                video=video,
                pastor=pastor_record,
                source_kind="yt_dlp_flat_playlist",
                raw_metadata=discovered.metadata,
            )
            discovered_count += 1
            source_discovered_count += 1
            existing_ids.add(discovered.youtube_video_id)
        source_summary = (
            f"{'Discovery retry complete' if retrying else f'[{index}/{total_sources}] Finished'} "
            f"source #{source.id}: found {source_found_count}, "
            f"queued {source_discovered_count}, skipped {source_skipped_count}"
        )
        if short_videos:
            source_summary += f", below minimum {len(short_videos)}"
        if long_videos:
            source_summary += f", above maximum {len(long_videos)}"
        if active_live_videos:
            source_summary += f", active/upcoming live {len(active_live_videos)}"
        if future_videos:
            source_summary += f", future {len(future_videos)}"
        if source_excluded_count:
            source_summary += f", excluded {source_excluded_count}"
        report(f"{source_summary}.", markup=False)
        selected_video_ids_by_source[source.id] = tuple(
            video.id
            for video in database.list_videos_by_source_id(source.id)
            if video.youtube_video_id in selected_youtube_ids
        )

    if effective_limit is not None:
        summary = (
            f"Found {found_count} video(s); queued {discovered_count} new video(s) after limit {effective_limit}; "
            f"skipped {skipped_count} duplicate(s)."
        )
    else:
        summary = f"Found {found_count} video(s); queued {discovered_count} new video(s); skipped {skipped_count} duplicate(s)."
    if excluded_count:
        summary = f"{summary[:-1]}; excluded {excluded_count} video(s)."
    if below_minimum_count:
        summary = (
            f"{summary[:-1]}; bypassed {below_minimum_count} video(s) below the "
            f"configured {minimum_duration:g}-second sermon minimum."
        )
    if above_maximum_count:
        summary = (
            f"{summary[:-1]}; bypassed {above_maximum_count} video(s) above the "
            f"configured {maximum_duration:g}-second sermon-video maximum."
        )
    if active_live_count:
        summary = (
            f"{summary[:-1]}; bypassed {active_live_count} active or upcoming "
            "live broadcast(s)."
        )
    if future_count:
        summary = f"{summary[:-1]}; bypassed {future_count} future event(s)."
    report(summary)
    return DiscoveryServiceResult(
        selected_video_ids_by_source=selected_video_ids_by_source,
        found_count=found_count,
        discovered_count=discovered_count,
        skipped_count=skipped_count,
        excluded_count=excluded_count,
        below_minimum_count=below_minimum_count,
        above_maximum_count=above_maximum_count,
        active_live_count=active_live_count,
        future_count=future_count,
    )
def discover_sources_service(
    limit: int | None = DEFAULT_DISCOVER_LIMIT,
    all_videos: bool = False,
    source_id: int | None = None,
    base_dir: Path | None = None,
    *,
    progress_callback: DiscoveryProgressCallback | None = None,
    extract_videos: Callable[..., list] = extract_discovered_videos,
) -> DiscoveryServiceResult:
    app_paths = build_paths(base_dir, remember=True)
    ensure_directories(app_paths)
    database = Database(app_paths.database)
    database.initialize()
    return discover_sources(
        database,
        app_paths,
        build_tool_config(),
        DiscoveryRequest(
            limit=limit,
            all_videos=all_videos,
            source_id=source_id,
        ),
        progress_callback=progress_callback,
        extract_videos=extract_videos,
    )
