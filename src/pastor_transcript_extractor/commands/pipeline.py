from __future__ import annotations

from pathlib import Path
from typing import Callable

import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, TaskProgressColumn, TextColumn, TimeElapsedColumn

from pastor_transcript_extractor import (
    audio_staging,
    config,
    media_archive,
    media_artifacts,
)
from pastor_transcript_extractor.application import ReviewBatchResult
from pastor_transcript_extractor.commands.apps import root_app
from pastor_transcript_extractor.config import AppPaths
from pastor_transcript_extractor.storage import Database
from pastor_transcript_extractor.workflows.run import RunWorkflowRequest
from pastor_transcript_extractor.workflows.pipeline import (
    PostContentIdentityRequest,
    run_post_content_identity as run_post_content_identity_workflow,
)
from pastor_transcript_extractor.workflows.run_media import (
    RunMediaDependencies,
    RunMediaRequest,
    ensure_and_archive_run_media as ensure_and_archive_run_media_workflow,
)
from pastor_transcript_extractor.workflows.transcription import (
    DEFAULT_PREP_WORKERS,
    default_transcribe_jobs,
)


DEFAULT_DISCOVER_LIMIT = 26
RunInvoker = Callable[[RunWorkflowRequest], object]
IdentityRunner = Callable[..., object]
console = Console()
_run_invoker: RunInvoker | None = None
_identity_runner: IdentityRunner | None = None


def configure_run_command(invoker: RunInvoker) -> None:
    """Bind the application workflow at composition time."""
    global _run_invoker
    _run_invoker = invoker


def configure_identity_runner(identity_runner: IdentityRunner) -> None:
    """Bind the identity workflow at composition time."""
    global _identity_runner
    _identity_runner = identity_runner


def run_post_content_identity(
    base_dir: Path | None,
    *,
    jobs: int = 2,
) -> None:
    if _identity_runner is None:
        raise RuntimeError("Identity workflow is not configured.")
    run_post_content_identity_workflow(
        PostContentIdentityRequest(base_dir=base_dir, jobs=jobs),
        event_callback=lambda message: console.print(message, markup=False),
        identity_runner=_identity_runner,
    )


def print_review_batch(batch: ReviewBatchResult) -> None:
    for pastor_result in batch.pastors:
        result = pastor_result.export
        console.print(f"Wrote pastor review markdown to {result.export_path}")
        console.print(f"Wrote review manifest to {result.manifest_path}")
        console.print(
            f"Included {result.video_count} video(s); skipped {result.skipped_count}."
        )
    if batch.prepared or batch.failed:
        console.print(
            f"Prepared {batch.prepared} video(s) for review; failed {batch.failed}."
        )


def ensure_and_archive_run_media(
    database: Database,
    paths: AppPaths,
    *,
    video_ids: set[int] | None = None,
    allow_download: bool = True,
) -> None:
    """Render media-assurance progress for the top-level run workflow."""
    ensure_and_archive_run_media_workflow(
        database,
        paths,
        RunMediaRequest(
            video_ids=None if video_ids is None else frozenset(video_ids),
            allow_download=allow_download,
        ),
        progress_callback=lambda message, style: console.print(
            message,
            style=style,
            markup=False,
        ),
        dependencies=RunMediaDependencies(
            has_isolated_sermon=media_artifacts.video_has_isolated_sermon,
            get_verified_media=media_artifacts.get_verified_normalized_media_artifact,
            build_tools=config.build_tool_config,
            ensure_audio=media_artifacts.ensure_audio_for_video,
            archive_source=media_archive.archive_source_media,
        ),
    )


def verify_audio_stage_manifest(
    database: Database,
    paths: AppPaths,
    manifest_path: Path,
) -> set[int]:
    """Verify a resume manifest while rendering bounded command progress."""
    with Progress(
        TextColumn("{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        verification_task = progress.add_task(
            "Reading audio-stage manifest",
            total=None,
        )

        def report_stage_verification(
            index: int,
            total: int,
            youtube_video_id: str,
        ) -> None:
            progress.update(
                verification_task,
                total=total,
                completed=index - 1,
                description=(
                    f"Verifying staged source [{index}/{total}] "
                    f"{youtube_video_id}"
                ),
            )

        video_ids = audio_staging.load_and_verify_audio_stage_manifest(
            database,
            manifest_path,
            progress_callback=report_stage_verification,
            verification_cache=media_artifacts.MediaVerificationCache(
                paths.logs / "source-audio-verification"
            ),
        )
        progress.update(
            verification_task,
            total=len(video_ids),
            completed=len(video_ids),
            description=f"Verified {len(video_ids)} staged source artifact(s)",
        )
    return video_ids


def _render_run_plan(request: RunWorkflowRequest) -> None:
    if request.stage_audio_only:
        selection = (
            "select the existing catalog"
            if request.skip_discovery
            else "discover the selected scope"
        )
        console.print(
            f"Run will {selection}, stage immutable source audio and available "
            "captions, write a checksum-pinned resume manifest, and stop."
        )
    elif request.resume_stage is not None:
        if request.acquire_captions:
            console.print(
                "Run will verify the staged source manifest, acquire available "
                "captions, then finish local transcription, extraction, media "
                "assurance, archival, and review without further network downloads."
            )
        else:
            console.print(
                "Run will verify the staged source manifest and finish transcription, "
                "extraction, media assurance, archival, and review without network "
                "downloads."
            )
    else:
        console.print(
            "Run adds the source, discovers videos, fetches captions, optionally "
            "transcribes, extracts, ensures isolated-sermon audio, archives eligible "
            "sources when configured, and writes disposition-aware pastor review "
            "artifacts."
        )


@root_app.command(
    help=(
        "Run intake, extraction, audio assurance, source archival, and "
        "disposition-aware pastor review export."
    ),
    rich_help_panel="Workflows",
)
def run(
    url: str | None = typer.Argument(None, help="YouTube video, playlist, or channel URL."),
    pastor: str | None = typer.Option(None, help="Pastor slug to associate with this source."),
    all_sources: bool = typer.Option(
        False,
        "--all",
        help=(
            "Run the full workflow for every processing-enabled source. This does not "
            "remove the per-source discovery limit; use --all-videos for that."
        ),
    ),
    source_ids: list[int] | None = typer.Option(
        None,
        "--source-id",
        help="Run one or more existing source ids; repeat this option for each source.",
    ),
    failed_only: bool = typer.Option(
        False,
        "--failed-only",
        help="Reprocess only failed videos systemwide without rebuilding successful artifacts.",
    ),
    replace_existing: bool = typer.Option(
        False,
        "--replace-existing",
        help="Replace a matching source first.",
    ),
    limit: int | None = typer.Option(
        DEFAULT_DISCOVER_LIMIT,
        "--limit",
        min=1,
        help="Videos per source; defaults to 26.",
    ),
    all_videos: bool = typer.Option(
        False,
        "--all-videos",
        help="Process all discovered videos.",
    ),
    captions_only: bool = typer.Option(
        False,
        "--captions-only",
        help="Do not run local transcription.",
    ),
    transcribe_missing: bool = typer.Option(
        True,
        "--transcribe-missing/--no-transcribe-missing",
        help="Only transcribe caption misses by default.",
    ),
    jobs: int = typer.Option(
        default_transcribe_jobs(),
        "--jobs",
        min=1,
        help="Concurrent transcription jobs.",
    ),
    classifier: str = typer.Option(
        "auto",
        "--classifier",
        help="Content classifier: auto, rules, llm, or typesafe.",
    ),
    llm_model: str | None = typer.Option(
        None,
        "--llm-model",
        help="Override the configured local Ollama model.",
    ),
    recording_verifier_backend: str = typer.Option(
        "ollama",
        "--recording-verifier-backend",
        help="Ambiguous-recording verifier: ollama, typesafe, or none.",
    ),
    recording_verifier_model: str | None = typer.Option(
        None,
        "--recording-verifier-model",
        help="Verifier model override; defaults by backend.",
    ),
    skip_review: bool = typer.Option(
        False,
        "--skip-review",
        help="Skip writing review exports after extraction and media maintenance.",
    ),
    run_identity: bool = typer.Option(
        False,
        "--identity",
        "--run-identity",
        help=(
            "After content processing, run the guarded automatic identity workflow "
            "and synchronize boundary feedback before review export."
        ),
    ),
    stage_audio_only: bool = typer.Option(
        False,
        "--stage-audio-only",
        "--stage-offline-inputs",
        help=(
            "Discover or select the requested scope, download immutable source audio "
            "and available captions, write a resume manifest, and stop."
        ),
    ),
    skip_discovery: bool = typer.Option(
        False,
        "--skip-discovery",
        help=(
            "With --stage-offline-inputs, select eligible videos already in the "
            "catalog without contacting source feeds."
        ),
    ),
    resume_stage: Path | None = typer.Option(
        None,
        "--resume-stage",
        exists=True,
        dir_okay=False,
        help=(
            "Process exactly the videos in a verified audio-stage manifest "
            "without network downloads."
        ),
    ),
    acquire_captions: bool = typer.Option(
        False,
        "--acquire-captions",
        help=(
            "With --resume-stage, fetch available captions for the verified manifest "
            "scope before offline-only local transcription."
        ),
    ),
    cookies_from_browser: str | None = typer.Option(
        None,
        "--cookies-from-browser",
        help=(
            "Use an explicit browser profile for authenticated YouTube caption "
            "requests, for example chrome or 'chrome:Profile 1'."
        ),
    ),
    cookies: Path | None = typer.Option(
        None,
        "--cookies",
        exists=True,
        dir_okay=False,
        help="Use an explicit Netscape-format cookie file for YouTube captions.",
    ),
    download_jobs: int = typer.Option(
        DEFAULT_PREP_WORKERS,
        "--download-jobs",
        min=1,
        help="Concurrent source-audio downloads during --stage-audio-only.",
    ),
    base_dir: Path | None = typer.Option(
        None,
        help="Override app data directory.",
    ),
) -> None:
    request = RunWorkflowRequest(
        url=url,
        pastor=pastor,
        all_sources=all_sources,
        source_ids=tuple(source_ids or ()),
        failed_only=failed_only,
        replace_existing=replace_existing,
        limit=limit,
        all_videos=all_videos,
        captions_only=captions_only,
        transcribe_missing=transcribe_missing,
        jobs=jobs,
        classifier=classifier,
        llm_model=llm_model,
        recording_verifier_backend=recording_verifier_backend,
        recording_verifier_model=recording_verifier_model,
        skip_review=skip_review,
        run_identity=run_identity,
        base_dir=base_dir,
        stage_audio_only=stage_audio_only,
        skip_discovery=skip_discovery,
        resume_stage=resume_stage,
        acquire_captions=acquire_captions,
        download_jobs=download_jobs,
        cookies_from_browser=cookies_from_browser,
        cookies=cookies,
    )
    _render_run_plan(request)
    if _run_invoker is None:
        raise RuntimeError("Run workflow was not configured.")
    try:
        _run_invoker(request)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
