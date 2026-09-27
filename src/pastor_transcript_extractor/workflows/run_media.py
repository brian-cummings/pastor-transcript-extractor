from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from pastor_transcript_extractor.config import AppPaths, ToolConfig, build_tool_config
from pastor_transcript_extractor.media_archive import archive_source_media
from pastor_transcript_extractor.media_artifacts import (
    ensure_audio_for_video,
    get_verified_normalized_media_artifact,
    video_has_isolated_sermon,
)
from pastor_transcript_extractor.storage import Database


RunMediaProgressCallback = Callable[[str, str | None], None]
RunMediaOperation = Callable[..., object]


@dataclass(frozen=True, slots=True)
class RunMediaRequest:
    video_ids: frozenset[int] | None = None
    allow_download: bool = True


@dataclass(frozen=True, slots=True)
class RunMediaResult:
    eligible_count: int = 0
    verified_count: int = 0
    downloaded_count: int = 0
    unavailable_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    archive_configured: bool = False
    archive_eligible_count: int = 0
    archived_count: int = 0
    already_archived_count: int = 0
    archive_unavailable_count: int = 0
    archive_failed_count: int = 0


@dataclass(frozen=True, slots=True)
class RunMediaDependencies:
    has_isolated_sermon: RunMediaOperation = video_has_isolated_sermon
    get_verified_media: RunMediaOperation = get_verified_normalized_media_artifact
    build_tools: Callable[[], ToolConfig] = build_tool_config
    ensure_audio: RunMediaOperation = ensure_audio_for_video
    archive_source: RunMediaOperation = archive_source_media


def _eligible_videos(
    database: Database,
    request: RunMediaRequest,
    dependencies: RunMediaDependencies,
):
    videos = [
        video
        for video in database.list_videos()
        if request.video_ids is None or video.id in request.video_ids
    ]
    return [
        video
        for video in videos
        if dependencies.has_isolated_sermon(database, video.id)[0]
        and dependencies.get_verified_media(database, video.id) is None
    ]


def _ensure_audio_pass(
    database: Database,
    app_paths: AppPaths,
    tools: ToolConfig,
    videos: list,
    request: RunMediaRequest,
    *,
    retry: bool,
    report: RunMediaProgressCallback,
    ensure_audio: RunMediaOperation,
) -> tuple[list[tuple[object, object | None]], list]:
    results: list[tuple[object, object | None]] = []
    retry_videos = []
    pass_label = "retry " if retry else ""
    for index, video in enumerate(videos, start=1):
        try:
            result = ensure_audio(
                database,
                app_paths,
                tools,
                video_id=video.id,
                allow_download=request.allow_download,
            )
        except Exception as error:
            result = None
            detail = f"unexpected_media_error: {type(error).__name__}: {error}"
        else:
            detail = result.reason_code
        should_retry = result is None or result.outcome == "failed"
        if should_retry and not retry:
            retry_videos.append(video)
            suffix = "; deferred for retry after the first pass"
        else:
            suffix = ""
        outcome = result.outcome if result is not None else "failed"
        report(
            f"Run audio {pass_label}[{index}/{len(videos)}] "
            f"{video.youtube_video_id}: {outcome} ({detail}){suffix}",
            "red" if outcome == "failed" else None,
        )
        results.append((video, result))
    return results, retry_videos


def _ensure_audio(
    database: Database,
    app_paths: AppPaths,
    request: RunMediaRequest,
    eligible: list,
    *,
    report: RunMediaProgressCallback,
    dependencies: RunMediaDependencies,
) -> tuple[dict[str, int], int]:
    counts = {"verified": 0, "unavailable": 0, "failed": 0, "skipped": 0}
    if not eligible:
        return counts, 0
    tools = dependencies.build_tools()
    initial, retry_videos = _ensure_audio_pass(
        database,
        app_paths,
        tools,
        eligible,
        request,
        retry=False,
        report=report,
        ensure_audio=dependencies.ensure_audio,
    )
    final_results = {video.id: result for video, result in initial}
    if retry_videos:
        report(
            f"Retrying {len(retry_videos)} normalized-audio failure(s) after "
            "the first pass.",
            None,
        )
        retried, _ = _ensure_audio_pass(
            database,
            app_paths,
            tools,
            retry_videos,
            request,
            retry=True,
            report=report,
            ensure_audio=dependencies.ensure_audio,
        )
        final_results.update((video.id, result) for video, result in retried)

    downloaded = 0
    for video in eligible:
        result = final_results[video.id]
        if result is None:
            counts["failed"] += 1
            continue
        counts[result.outcome] += 1
        downloaded += int(result.downloaded)
    return counts, downloaded


def _archive_media(
    database: Database,
    app_paths: AppPaths,
    request: RunMediaRequest,
    *,
    report: RunMediaProgressCallback,
    archive_source: RunMediaOperation,
):
    def report_preflight(event) -> None:
        report(
            f"Run archive preflight {event.check}: {event.status} — {event.detail}",
            None,
        )

    def report_progress(event) -> None:
        if event.stage == "complete":
            detail = f" ({event.detail})" if event.detail else ""
            report(
                f"Run archive [{event.index}/{event.total}] artifact "
                f"#{event.media_artifact_id}: {event.outcome}{detail}",
                None,
            )
            return
        report(
            f"Run archive [{event.index}/{event.total}] "
            f"{event.source_path.name}: {event.stage}",
            None,
        )

    archive = archive_source(
        database,
        app_paths,
        video_ids=None if request.video_ids is None else set(request.video_ids),
        wait_for_lock=True,
        progress_callback=report_progress,
        preflight_callback=report_preflight,
    )
    if archive.counts["failed"]:
        report(
            f"Retrying source archival after {archive.counts['failed']} "
            "artifact failure(s) in the first pass.",
            None,
        )
        archive = archive_source(
            database,
            app_paths,
            video_ids=None if request.video_ids is None else set(request.video_ids),
            wait_for_lock=True,
            progress_callback=report_progress,
            preflight_callback=report_preflight,
        )
    return archive


def ensure_and_archive_run_media(
    database: Database,
    app_paths: AppPaths,
    request: RunMediaRequest,
    *,
    progress_callback: RunMediaProgressCallback | None = None,
    dependencies: RunMediaDependencies = RunMediaDependencies(),
) -> RunMediaResult:
    def report(message: str, style: str | None = None) -> None:
        if progress_callback is not None:
            progress_callback(message, style)

    eligible = _eligible_videos(database, request, dependencies)
    counts, downloaded = _ensure_audio(
        database,
        app_paths,
        request,
        eligible,
        report=report,
        dependencies=dependencies,
    )
    report(
        "Run audio ensure complete: "
        f"eligible={len(eligible)}, verified={counts['verified']} "
        f"(downloaded={downloaded}), unavailable={counts['unavailable']}, "
        f"failed={counts['failed']}, skipped={counts['skipped']}.",
        None,
    )

    if database.get_active_media_archive_destination() is None:
        report(
            "Run media archive skipped: no archive destination is configured.",
            None,
        )
        return RunMediaResult(
            eligible_count=len(eligible),
            verified_count=counts["verified"],
            downloaded_count=downloaded,
            unavailable_count=counts["unavailable"],
            failed_count=counts["failed"],
            skipped_count=counts["skipped"],
        )

    archive = _archive_media(
        database,
        app_paths,
        request,
        report=report,
        archive_source=dependencies.archive_source,
    )
    archive_counts = archive.counts
    report(
        f"Run media archive complete: eligible={archive.eligible}, "
        f"archived={archive_counts['archived']}, "
        f"already_archived={archive_counts['already_archived']}, "
        f"unavailable={archive_counts['destination_unavailable']}, "
        f"failed={archive_counts['failed']}.",
        None,
    )
    return RunMediaResult(
        eligible_count=len(eligible),
        verified_count=counts["verified"],
        downloaded_count=downloaded,
        unavailable_count=counts["unavailable"],
        failed_count=counts["failed"],
        skipped_count=counts["skipped"],
        archive_configured=True,
        archive_eligible_count=archive.eligible,
        archived_count=archive_counts["archived"],
        already_archived_count=archive_counts["already_archived"],
        archive_unavailable_count=archive_counts["destination_unavailable"],
        archive_failed_count=archive_counts["failed"],
    )
