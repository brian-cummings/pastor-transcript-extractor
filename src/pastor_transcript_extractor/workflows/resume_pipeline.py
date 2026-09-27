from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from pastor_transcript_extractor.application import (
    ExtractionBatchResult,
    ReviewBatchResult,
    extract_batch,
    prepare_review_exports,
)
from pastor_transcript_extractor.config import AppPaths
from pastor_transcript_extractor.storage import Database
from pastor_transcript_extractor.workflows.caption_acquisition import (
    CaptionAcquisitionBlockedError,
    fetch_captions_service,
)
from pastor_transcript_extractor.workflows.transcription import (
    transcribe_videos_service,
)


ResumeEvent = str | ReviewBatchResult
ResumeEventCallback = Callable[[ResumeEvent], None]
ResumeOperation = Callable[..., object]


@dataclass(frozen=True, slots=True)
class ResumePipelineRequest:
    video_ids: frozenset[int]
    manifest_path: Path
    acquire_captions: bool = False
    captions_only: bool = False
    transcribe_missing: bool = True
    jobs: int = 2
    classifier: str = "auto"
    llm_model: str | None = None
    skip_review: bool = False
    run_identity: bool = False
    base_dir: Path | None = None
    caption_request_interval_seconds: float = 5.0
    cookies_from_browser: str | None = None
    cookies: Path | None = None


@dataclass(frozen=True, slots=True)
class ResumePipelineResult:
    video_count: int
    extraction: ExtractionBatchResult
    captions_blocked: bool = False
    review_batch_count: int = 0


@dataclass(frozen=True, slots=True)
class ResumePipelineDependencies:
    fetch_captions: ResumeOperation = fetch_captions_service
    transcribe: ResumeOperation = transcribe_videos_service
    extract: ResumeOperation = extract_batch
    ensure_media: ResumeOperation | None = None
    run_identity: ResumeOperation | None = None
    prepare_reviews: ResumeOperation = prepare_review_exports


def _pastor_slugs_for_videos(
    database: Database,
    video_ids: frozenset[int],
) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                pastor.slug
                for video_id in video_ids
                for video in [database.get_video_by_id(video_id)]
                if video is not None and video.pastor_id is not None
                for pastor in [database.get_pastor_by_id(video.pastor_id)]
                if pastor is not None
            }
        )
    )


def resume_staged_pipeline(
    database: Database,
    app_paths: AppPaths,
    request: ResumePipelineRequest,
    *,
    event_callback: ResumeEventCallback | None = None,
    dependencies: ResumePipelineDependencies = ResumePipelineDependencies(),
) -> ResumePipelineResult:
    def emit(event: ResumeEvent) -> None:
        if event_callback is not None:
            event_callback(event)

    emit(
        f"Resuming {len(request.video_ids)} video(s) from verified audio stage "
        f"{request.manifest_path}."
    )
    captions_blocked = False
    if request.acquire_captions:
        emit(
            "Resume checkpoint: reconciling requested online captions; persisted "
            "caption artifacts will be skipped."
        )
        caption_options = {}
        if request.cookies_from_browser is not None:
            caption_options["cookies_from_browser"] = request.cookies_from_browser
        if request.cookies is not None:
            caption_options["cookies"] = request.cookies
        try:
            dependencies.fetch_captions(
                base_dir=request.base_dir,
                video_ids=set(request.video_ids),
                request_interval_seconds=request.caption_request_interval_seconds,
                **caption_options,
            )
        except CaptionAcquisitionBlockedError as error:
            captions_blocked = True
            emit(f"[yellow]Caption acquisition stopped[/yellow]: {error}")
            emit(
                "Remaining caption misses will stay pending because local "
                "transcription is disabled by --captions-only."
                if request.captions_only
                else "Continuing with offline local transcription for remaining "
                "caption misses."
            )
    else:
        emit(
            "Resume checkpoint: skipping caption acquisition; persisted captions "
            "remain available and caption misses will use staged audio."
        )

    if not request.captions_only:
        emit(
            "Resume checkpoint: reconciling local transcripts; completed transcript "
            "artifacts will be skipped."
        )
        dependencies.transcribe(
            missing_only=False,
            captions_missing_only=request.transcribe_missing,
            jobs=request.jobs,
            base_dir=request.base_dir,
            video_ids=set(request.video_ids),
            allow_network=False,
        )
    else:
        emit("Resume checkpoint: local transcription disabled by --captions-only.")

    emit(
        "Resume checkpoint: reconciling sermon extraction; completed extraction "
        "artifacts will be skipped."
    )
    extraction = dependencies.extract(
        database,
        app_paths,
        video_ids=set(request.video_ids),
        classifier=request.classifier,
        llm_model=request.llm_model,
        workers=request.jobs,
        event_callback=lambda message: emit(str(message)),
        progress_callback=lambda stage, current, total: emit(
            f"  {stage} block {current}/{total}"
        ),
    )
    emit(
        f"Extracted {extraction.processed} video(s); skipped {extraction.skipped}; "
        f"failed {extraction.failed}."
    )
    emit(
        "Resume checkpoint: ensuring normalized audio and archiving eligible "
        "source artifacts."
    )
    if dependencies.ensure_media is not None:
        dependencies.ensure_media(
            database,
            app_paths,
            video_ids=set(request.video_ids),
            allow_download=False,
        )
    if request.run_identity and dependencies.run_identity is not None:
        emit("Resume checkpoint: starting the requested identity workflow.")
        dependencies.run_identity(request.base_dir, jobs=request.jobs)

    review_count = 0
    if not request.skip_review:
        emit("Resume checkpoint: refreshing review exports.")
        for pastor_slug in _pastor_slugs_for_videos(database, request.video_ids):
            batch = dependencies.prepare_reviews(
                database,
                app_paths,
                pastor_slug=pastor_slug,
                classifier=request.classifier,
                llm_model=request.llm_model,
                event_callback=lambda message: emit(str(message)),
            )
            emit(batch)
            review_count += 1
    else:
        emit("Resume checkpoint: review export skipped by --skip-review.")
    if not request.run_identity:
        emit("Resume complete; identity was not requested.")
    return ResumePipelineResult(
        video_count=len(request.video_ids),
        extraction=extraction,
        captions_blocked=captions_blocked,
        review_batch_count=review_count,
    )
