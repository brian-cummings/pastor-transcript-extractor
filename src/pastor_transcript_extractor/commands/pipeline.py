from __future__ import annotations

from pathlib import Path
from typing import Callable

import typer
from rich.console import Console

from pastor_transcript_extractor.commands.apps import root_app
from pastor_transcript_extractor.workflows.run import RunWorkflowRequest
from pastor_transcript_extractor.workflows.transcription import (
    DEFAULT_PREP_WORKERS,
    default_transcribe_jobs,
)


DEFAULT_DISCOVER_LIMIT = 26
RunInvoker = Callable[[RunWorkflowRequest], object]
console = Console()
_run_invoker: RunInvoker | None = None


def configure_run_command(invoker: RunInvoker) -> None:
    """Bind the application workflow at composition time."""
    global _run_invoker
    _run_invoker = invoker


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
        help="Content classifier: auto, rules, or llm.",
    ),
    llm_model: str | None = typer.Option(
        None,
        "--llm-model",
        help="Override the configured local Ollama model.",
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
