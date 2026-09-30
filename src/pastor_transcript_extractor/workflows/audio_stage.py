from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
import shlex
from typing import Callable, Mapping, Sequence

from pastor_transcript_extractor.audio_staging import write_audio_stage_manifest
from pastor_transcript_extractor.config import AppPaths, ToolConfig
from pastor_transcript_extractor.identity import latest_metadata_live_status
from pastor_transcript_extractor.media_artifacts import (
    MediaVerificationCache,
    StageSourceAudioResult,
    stage_source_audio_for_video,
)
from pastor_transcript_extractor.storage import Database
from pastor_transcript_extractor.sermon_policy import (
    live_status_is_sermon_eligible,
    maximum_sermon_duration_seconds,
    minimum_sermon_duration_seconds,
    video_is_sermon_eligible,
)
from pastor_transcript_extractor.workflows.caption_acquisition import (
    CaptionAcquisitionBlockedError,
    fetch_captions_service,
)


AudioStageProgressCallback = Callable[[str], None]
AudioStageOperation = Callable[..., object]


@dataclass(frozen=True, slots=True)
class AudioStageRequest:
    video_ids: frozenset[int]
    download_jobs: int
    resume_jobs: int
    base_dir: Path | None = None
    caption_request_interval_seconds: float = 5.0
    cookies_from_browser: str | None = None
    cookies: Path | None = None


@dataclass(frozen=True, slots=True)
class AudioStageResult:
    manifest_path: Path | None
    selected_count: int
    verified_video_ids: frozenset[int]
    failed_count: int
    captions_blocked: bool = False


@dataclass(frozen=True, slots=True)
class AudioStageDependencies:
    stage_video: AudioStageOperation = stage_source_audio_for_video
    write_manifest: AudioStageOperation = write_audio_stage_manifest
    fetch_captions: AudioStageOperation = fetch_captions_service


@dataclass(frozen=True, slots=True)
class AudioStageScopeRequest:
    url: str | None = None
    pastor: str | None = None
    all_sources: bool = False
    failed_only: bool = False
    replace_existing: bool = False
    limit: int | None = 26
    all_videos: bool = False
    source_ids: tuple[int, ...] = ()
    skip_discovery: bool = False
    base_dir: Path | None = None


@dataclass(frozen=True, slots=True)
class AudioStageScopeResult:
    database: Database
    video_ids: frozenset[int]
    skip_reason: str | None = None


@dataclass(frozen=True, slots=True)
class AudioStageScopeDependencies:
    get_database: AudioStageOperation
    add_source: AudioStageOperation
    delete_source: AudioStageOperation
    discover: AudioStageOperation
    select_existing: AudioStageOperation


def _has_registered_source_audio(database: Database, video_id: int) -> bool:
    return any(
        artifact.artifact_kind == "source_audio"
        and artifact.provenance_kind == "original_download"
        for artifact in database.list_media_artifacts_for_video(video_id)
    )


def _has_acquired_transcript(database: Database, video_id: int) -> bool:
    return database.get_latest_transcript_artifact_for_video(video_id) is not None


def select_existing_stage_video_ids(
    database: Database,
    source_ids: Sequence[int],
    *,
    limit: int | None,
    all_videos: bool,
    latest_live_status: AudioStageOperation = latest_metadata_live_status,
    has_registered_source_audio: AudioStageOperation = _has_registered_source_audio,
) -> set[int]:
    """Select newest eligible catalog videos without contacting source feeds."""

    excluded_ids = {
        video.youtube_video_id for video in database.list_excluded_videos()
    }
    minimum_duration = minimum_sermon_duration_seconds()
    maximum_duration = maximum_sermon_duration_seconds()
    selected: set[int] = set()
    for source_id in source_ids:
        candidates = [
            video
            for video in database.list_videos_by_source_id(source_id)
            if video.youtube_video_id not in excluded_ids
            and video_is_sermon_eligible(
                video.duration_seconds,
                video.published_at,
                minimum_seconds=minimum_duration,
                maximum_seconds=maximum_duration,
            )
            and (
                live_status_is_sermon_eligible(
                    latest_live_status(database, video.id)
                )
                or has_registered_source_audio(database, video.id)
            )
        ]
        candidates.sort(
            key=lambda video: (
                video.published_at is not None,
                video.published_at.isoformat()
                if hasattr(video.published_at, "isoformat")
                else str(video.published_at or ""),
                video.id,
            ),
            reverse=True,
        )
        chosen = candidates if all_videos or limit is None else candidates[:limit]
        selected.update(video.id for video in chosen)
    return selected


def _selected_discovery_video_ids(
    discovery: object,
    source_ids: Sequence[int],
) -> set[int]:
    selected_by_source = getattr(discovery, "selected_video_ids_by_source", {})
    if not isinstance(selected_by_source, Mapping):
        return set()
    return {
        video_id
        for source_id in source_ids
        for video_id in selected_by_source.get(source_id, ())
    }


def resolve_audio_stage_scope(
    request: AudioStageScopeRequest,
    *,
    progress_callback: AudioStageProgressCallback | None = None,
    dependencies: AudioStageScopeDependencies,
) -> AudioStageScopeResult:
    """Validate and resolve an audio-stage source scope to exact video ids."""
    def report(message: str) -> None:
        if progress_callback is not None:
            progress_callback(message)

    if request.failed_only:
        raise ValueError(
            "--stage-audio-only requires a source scope, not --failed-only."
        )
    database = dependencies.get_database(request.base_dir)
    if request.source_ids:
        if request.url is not None or request.pastor is not None or request.all_sources:
            raise ValueError("Use only one source scope with --stage-audio-only.")
        unknown = [
            source_id
            for source_id in request.source_ids
            if database.get_source_by_id(source_id) is None
        ]
        if unknown:
            raise ValueError("Unknown source id(s): " + ", ".join(map(str, unknown)))
        if request.skip_discovery:
            selected = dependencies.select_existing(
                database,
                request.source_ids,
                limit=request.limit,
                all_videos=request.all_videos,
            )
        else:
            selected = set()
            for source_id in request.source_ids:
                discovery = dependencies.discover(
                    request.limit,
                    request.all_videos,
                    source_id,
                    request.base_dir,
                )
                selected.update(
                    _selected_discovery_video_ids(discovery, (source_id,))
                )
    elif request.all_sources:
        if request.url is not None or request.pastor is not None:
            raise ValueError("Do not pass a URL or pastor when using --all.")
        enabled_source_ids = tuple(
            source.id for source in database.list_processing_enabled_sources()
        )
        if not enabled_source_ids:
            reason = "No processing-enabled sources configured."
            report(reason)
            return AudioStageScopeResult(database, frozenset(), reason)
        if request.skip_discovery:
            selected = dependencies.select_existing(
                database,
                enabled_source_ids,
                limit=request.limit,
                all_videos=request.all_videos,
            )
        else:
            discovery = dependencies.discover(
                request.limit,
                request.all_videos,
                None,
                request.base_dir,
            )
            selected = _selected_discovery_video_ids(
                discovery,
                enabled_source_ids,
            )
    else:
        if request.skip_discovery:
            raise ValueError(
                "--skip-discovery requires --all or at least one --source-id."
            )
        if request.url is None or request.pastor is None:
            raise ValueError(
                "Audio staging requires URL plus --pastor, --source-id, or --all."
            )
        if request.replace_existing:
            existing_source = database.get_source_by_url(request.url)
            if existing_source is not None:
                dependencies.delete_source(
                    existing_source.id,
                    True,
                    request.base_dir,
                )
                database = dependencies.get_database(request.base_dir)
        dependencies.add_source(
            request.url,
            request.pastor,
            None,
            request.base_dir,
        )
        source = database.get_source_by_url(request.url)
        if source is None:
            raise RuntimeError("Added source could not be reloaded.")
        discovery = dependencies.discover(
            request.limit,
            request.all_videos,
            source.id,
            request.base_dir,
        )
        selected = _selected_discovery_video_ids(discovery, (source.id,))

    video_ids = frozenset(selected)
    if request.skip_discovery:
        report(
            f"Selected {len(video_ids)} eligible existing catalog video(s) "
            "without source discovery."
        )
    if not video_ids:
        reason = "No videos selected for audio staging."
        report(reason)
        return AudioStageScopeResult(database, video_ids, reason)
    return AudioStageScopeResult(database, video_ids)


def _failed_stage_result(
    database: Database,
    video_id: int,
    error: Exception,
) -> StageSourceAudioResult:
    video = database.get_video_by_id(video_id)
    return StageSourceAudioResult(
        video_id=video_id,
        youtube_video_id=(
            video.youtube_video_id if video is not None else f"video-{video_id}"
        ),
        outcome="failed",
        reason_code=(
            "unexpected_source_audio_stage_error: "
            f"{type(error).__name__}: {error}"
        ),
        artifact=None,
        attempt=None,
        downloaded=False,
    )


def _stage_pass(
    database: Database,
    app_paths: AppPaths,
    tool_config: ToolConfig,
    video_ids: set[int],
    *,
    workers: int,
    retry: bool,
    verification_cache: MediaVerificationCache,
    report: AudioStageProgressCallback,
    stage_video: AudioStageOperation,
) -> tuple[list[StageSourceAudioResult], set[int]]:
    results: list[StageSourceAudioResult] = []
    retry_video_ids: set[int] = set()
    pass_label = "retry " if retry else ""
    with ThreadPoolExecutor(max_workers=min(workers, len(video_ids))) as executor:
        futures = {
            executor.submit(
                stage_video,
                database,
                app_paths,
                tool_config,
                video_id=video_id,
                verification_cache=verification_cache,
            ): video_id
            for video_id in video_ids
        }
        for index, future in enumerate(as_completed(futures), start=1):
            video_id = futures[future]
            try:
                result = future.result()
            except Exception as error:
                result = _failed_stage_result(database, video_id, error)
            if result.outcome == "failed" and not retry:
                retry_video_ids.add(video_id)
                suffix = "; deferred for retry after the first pass"
            else:
                suffix = ""
            results.append(result)
            report(
                f"Audio stage {pass_label}[{index}/{len(futures)}] "
                f"{result.youtube_video_id}: {result.outcome} "
                f"({result.reason_code}){suffix}"
            )
    return results, retry_video_ids


def stage_audio_inputs(
    database: Database,
    app_paths: AppPaths,
    tool_config: ToolConfig,
    request: AudioStageRequest,
    *,
    progress_callback: AudioStageProgressCallback | None = None,
    dependencies: AudioStageDependencies = AudioStageDependencies(),
) -> AudioStageResult:
    def report(message: str) -> None:
        if progress_callback is not None:
            progress_callback(message)

    if not request.video_ids:
        report("No videos selected for audio staging.")
        return AudioStageResult(None, 0, frozenset(), 0)

    selected_video_ids = set(request.video_ids)
    transcript_video_ids = {
        video_id
        for video_id in selected_video_ids
        if _has_acquired_transcript(database, video_id)
    }
    stage_video_ids = selected_video_ids - transcript_video_ids
    if transcript_video_ids:
        report(
            f"Bypassing {len(transcript_video_ids)} selected video(s) with "
            "acquired transcripts; source audio and captions will not be requested."
        )
    if not stage_video_ids:
        report("No videos require audio staging.")
        return AudioStageResult(None, len(selected_video_ids), frozenset(), 0)

    workers = min(request.download_jobs, len(stage_video_ids))
    report(
        f"Staging source audio for {len(stage_video_ids)} video(s) with "
        f"{workers} worker(s)."
    )
    verification_cache = MediaVerificationCache(
        app_paths.logs / "source-audio-verification"
    )
    results, retry_video_ids = _stage_pass(
        database,
        app_paths,
        tool_config,
        stage_video_ids,
        workers=workers,
        retry=False,
        verification_cache=verification_cache,
        report=report,
        stage_video=dependencies.stage_video,
    )
    results_by_video_id = {result.video_id: result for result in results}
    if retry_video_ids:
        report(
            f"Retrying {len(retry_video_ids)} source-audio staging failure(s) "
            "after the first pass."
        )
        retry_results, _ = _stage_pass(
            database,
            app_paths,
            tool_config,
            retry_video_ids,
            workers=workers,
            retry=True,
            verification_cache=verification_cache,
            report=report,
            stage_video=dependencies.stage_video,
        )
        results_by_video_id.update(
            (result.video_id, result) for result in retry_results
        )

    final_results = list(results_by_video_id.values())
    manifest = dependencies.write_manifest(app_paths.logs, final_results)
    verified_video_ids = {
        result.video_id for result in final_results if result.outcome == "verified"
    }
    downloaded_video_ids = {
        result.video_id
        for result in final_results
        if result.outcome == "verified" and result.downloaded
    }
    report(
        f"Audio stage complete: verified={len(verified_video_ids)}, "
        f"failed={len(final_results) - len(verified_video_ids)}."
    )
    report(f"Manifest: {manifest}")
    report(
        "Offline resume: pte run "
        f"--resume-stage {shlex.quote(str(manifest))} --jobs {request.resume_jobs} "
        f"--base-dir {shlex.quote(str(app_paths.root))}"
    )

    captions_blocked = False
    if downloaded_video_ids:
        report(
            f"Fetching available captions for {len(downloaded_video_ids)} newly "
            "downloaded video(s)."
        )
        try:
            dependencies.fetch_captions(
                base_dir=request.base_dir,
                video_ids=downloaded_video_ids,
                request_interval_seconds=request.caption_request_interval_seconds,
                **(
                    {"cookies_from_browser": request.cookies_from_browser}
                    if request.cookies_from_browser is not None
                    else {}
                ),
                **({"cookies": request.cookies} if request.cookies is not None else {}),
            )
        except CaptionAcquisitionBlockedError as error:
            captions_blocked = True
            report(f"[yellow]Caption acquisition stopped[/yellow]: {error}")
            report(
                "The audio stage is complete. Use the offline resume command above; "
                "caption misses will use local transcription."
            )
    return AudioStageResult(
        manifest_path=manifest,
        selected_count=len(selected_video_ids),
        verified_video_ids=frozenset(verified_video_ids),
        failed_count=len(final_results) - len(verified_video_ids),
        captions_blocked=captions_blocked,
    )
