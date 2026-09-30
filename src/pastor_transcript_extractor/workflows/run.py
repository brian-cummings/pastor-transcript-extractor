from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Callable

from pastor_transcript_extractor.workflows.audio_stage import (
    AudioStageDependencies,
    AudioStageRequest,
    AudioStageScopeDependencies,
    AudioStageScopeRequest,
    resolve_audio_stage_scope,
    stage_audio_inputs,
)
from pastor_transcript_extractor.workflows.pipeline import (
    PipelineDependencies,
    PipelineRequest,
    run_pipeline,
)
from pastor_transcript_extractor.workflows.resume_pipeline import (
    ResumePipelineDependencies,
    ResumePipelineRequest,
    resume_staged_pipeline,
)


RunEventCallback = Callable[[object], None]
RunOperation = Callable[..., object]


class RunMode(str, Enum):
    ONLINE = "online"
    STAGE_AUDIO = "stage_audio"
    RESUME = "resume"


@dataclass(frozen=True, slots=True)
class RunWorkflowRequest:
    url: str | None = None
    pastor: str | None = None
    all_sources: bool = False
    failed_only: bool = False
    replace_existing: bool = False
    limit: int | None = 26
    all_videos: bool = False
    captions_only: bool = False
    transcribe_missing: bool = True
    jobs: int = 2
    classifier: str = "auto"
    llm_model: str | None = None
    recording_verifier_backend: str = "ollama"
    recording_verifier_model: str | None = None
    skip_review: bool = False
    run_identity: bool = False
    base_dir: Path | None = None
    source_ids: tuple[int, ...] = ()
    stage_audio_only: bool = False
    skip_discovery: bool = False
    resume_stage: Path | None = None
    acquire_captions: bool = False
    download_jobs: int = 2
    caption_request_interval_seconds: float = 5.0
    cookies_from_browser: str | None = None
    cookies: Path | None = None


@dataclass(frozen=True, slots=True)
class RunWorkflowResult:
    mode: RunMode
    result: object | None


@dataclass(frozen=True, slots=True)
class RunWorkflowDependencies:
    get_database: RunOperation
    build_paths: RunOperation
    build_tools: RunOperation
    verify_manifest: RunOperation
    audio_scope: AudioStageScopeDependencies
    audio_stage: AudioStageDependencies
    resume_pipeline: ResumePipelineDependencies
    online_pipeline: PipelineDependencies
    resolve_audio_scope: RunOperation = resolve_audio_stage_scope
    stage_audio: RunOperation = stage_audio_inputs
    resume: RunOperation = resume_staged_pipeline
    online: RunOperation = run_pipeline


def _validate_mode(request: RunWorkflowRequest) -> RunMode:
    if request.cookies_from_browser is not None and request.cookies is not None:
        raise ValueError(
            "Use either --cookies-from-browser or --cookies for YouTube, not both."
        )
    if request.stage_audio_only and request.resume_stage is not None:
        raise ValueError("Use either --stage-audio-only or --resume-stage, not both.")
    if request.skip_discovery and not request.stage_audio_only:
        raise ValueError(
            "--skip-discovery is only valid with --stage-offline-inputs."
        )
    if request.acquire_captions and request.resume_stage is None:
        raise ValueError("--acquire-captions is only valid with --resume-stage.")
    if request.resume_stage is not None:
        if (
            request.url is not None
            or request.pastor is not None
            or request.all_sources
            or request.source_ids
            or request.failed_only
        ):
            raise ValueError(
                "--resume-stage supplies the exact video scope; do not pass "
                "another scope."
            )
        if request.replace_existing:
            raise ValueError("--replace-existing is not valid with --resume-stage.")
        return RunMode.RESUME
    if request.stage_audio_only:
        if request.captions_only:
            raise ValueError(
                "--captions-only is not meaningful with --stage-audio-only."
            )
        if request.run_identity:
            raise ValueError(
                "--identity runs during --resume-stage, not audio staging."
            )
        return RunMode.STAGE_AUDIO
    return RunMode.ONLINE


def _resume_run(
    request: RunWorkflowRequest,
    dependencies: RunWorkflowDependencies,
    emit: RunEventCallback,
) -> object:
    assert request.resume_stage is not None
    database = dependencies.get_database(request.base_dir)
    app_paths = dependencies.build_paths(request.base_dir, remember=True)
    emit("Resume checkpoint: verifying every checksum-pinned staged source artifact.")
    video_ids = dependencies.verify_manifest(
        database,
        app_paths,
        request.resume_stage,
    )
    return dependencies.resume(
        database,
        app_paths,
        ResumePipelineRequest(
            video_ids=frozenset(video_ids),
            manifest_path=request.resume_stage,
            acquire_captions=request.acquire_captions,
            captions_only=request.captions_only,
            transcribe_missing=request.transcribe_missing,
            jobs=request.jobs,
            classifier=request.classifier,
            llm_model=request.llm_model,
            recording_verifier_backend=request.recording_verifier_backend,
            recording_verifier_model=request.recording_verifier_model,
            skip_review=request.skip_review,
            run_identity=request.run_identity,
            base_dir=request.base_dir,
            caption_request_interval_seconds=(
                request.caption_request_interval_seconds
            ),
            cookies_from_browser=request.cookies_from_browser,
            cookies=request.cookies,
        ),
        event_callback=emit,
        dependencies=dependencies.resume_pipeline,
    )


def _stage_audio_run(
    request: RunWorkflowRequest,
    dependencies: RunWorkflowDependencies,
    emit: RunEventCallback,
) -> object:
    selection = dependencies.resolve_audio_scope(
        AudioStageScopeRequest(
            url=request.url,
            pastor=request.pastor,
            all_sources=request.all_sources,
            failed_only=request.failed_only,
            replace_existing=request.replace_existing,
            limit=request.limit,
            all_videos=request.all_videos,
            source_ids=request.source_ids,
            skip_discovery=request.skip_discovery,
            base_dir=request.base_dir,
        ),
        progress_callback=lambda message: emit(str(message)),
        dependencies=dependencies.audio_scope,
    )
    if selection.skip_reason is not None:
        return selection
    app_paths = dependencies.build_paths(request.base_dir, remember=True)
    return dependencies.stage_audio(
        selection.database,
        app_paths,
        dependencies.build_tools(),
        AudioStageRequest(
            video_ids=selection.video_ids,
            download_jobs=request.download_jobs,
            resume_jobs=request.jobs,
            base_dir=request.base_dir,
            caption_request_interval_seconds=(
                request.caption_request_interval_seconds
            ),
            cookies_from_browser=request.cookies_from_browser,
            cookies=request.cookies,
        ),
        progress_callback=lambda message: emit(str(message)),
        dependencies=dependencies.audio_stage,
    )


def _online_run(
    request: RunWorkflowRequest,
    dependencies: RunWorkflowDependencies,
    emit: RunEventCallback,
) -> object:
    return dependencies.online(
        PipelineRequest(
            url=request.url,
            pastor=request.pastor,
            all_sources=request.all_sources,
            failed_only=request.failed_only,
            replace_existing=request.replace_existing,
            limit=request.limit,
            all_videos=request.all_videos,
            captions_only=request.captions_only,
            transcribe_missing=request.transcribe_missing,
            jobs=request.jobs,
            classifier=request.classifier,
            llm_model=request.llm_model,
            recording_verifier_backend=request.recording_verifier_backend,
            recording_verifier_model=request.recording_verifier_model,
            skip_review=request.skip_review,
            run_identity=request.run_identity,
            base_dir=request.base_dir,
            source_ids=request.source_ids,
            cookies_from_browser=request.cookies_from_browser,
            cookies=request.cookies,
            caption_request_interval_seconds=(
                request.caption_request_interval_seconds
            ),
        ),
        event_callback=emit,
        dependencies=dependencies.online_pipeline,
    )


def run_workflow(
    request: RunWorkflowRequest,
    *,
    event_callback: RunEventCallback | None = None,
    dependencies: RunWorkflowDependencies,
) -> RunWorkflowResult:
    """Validate one run request, dispatch one mode, and return its evidence."""
    def emit(event: object) -> None:
        if event_callback is not None:
            event_callback(event)

    canonical_request = replace(
        request,
        source_ids=tuple(dict.fromkeys(request.source_ids)),
    )
    mode = _validate_mode(canonical_request)
    if mode is RunMode.RESUME:
        result = _resume_run(canonical_request, dependencies, emit)
    elif mode is RunMode.STAGE_AUDIO:
        result = _stage_audio_run(canonical_request, dependencies, emit)
    else:
        result = _online_run(canonical_request, dependencies, emit)
    return RunWorkflowResult(mode, result)
