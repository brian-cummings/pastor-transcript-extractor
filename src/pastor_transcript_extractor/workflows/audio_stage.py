from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
import shlex
from typing import Callable

from pastor_transcript_extractor.audio_staging import write_audio_stage_manifest
from pastor_transcript_extractor.config import AppPaths, ToolConfig
from pastor_transcript_extractor.media_artifacts import (
    MediaVerificationCache,
    StageSourceAudioResult,
    stage_source_audio_for_video,
)
from pastor_transcript_extractor.storage import Database
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
    workers = min(request.download_jobs, len(selected_video_ids))
    report(
        f"Staging source audio for {len(selected_video_ids)} video(s) with "
        f"{workers} worker(s)."
    )
    verification_cache = MediaVerificationCache(
        app_paths.logs / "source-audio-verification"
    )
    results, retry_video_ids = _stage_pass(
        database,
        app_paths,
        tool_config,
        selected_video_ids,
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
    if verified_video_ids:
        report(
            f"Fetching available captions for {len(verified_video_ids)} verified "
            "staged video(s)."
        )
        try:
            dependencies.fetch_captions(
                base_dir=request.base_dir,
                video_ids=verified_video_ids,
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
