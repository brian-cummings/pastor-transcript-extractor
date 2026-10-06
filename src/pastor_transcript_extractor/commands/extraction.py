from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from pastor_transcript_extractor import application, config
from pastor_transcript_extractor.commands import common as command_common
from pastor_transcript_extractor.commands.apps import root_app
from pastor_transcript_extractor.inference_defaults import (
    DEFAULT_CLASSIFIER,
    DEFAULT_RECORDING_VERIFIER_BACKEND,
    DEFAULT_TYPESAFE_MODEL,
)


console = Console()


@root_app.command(
    help="Chunk transcript artifacts into reviewable segments and proposed Markdown."
)
def extract(
    missing_only: bool = typer.Option(
        False,
        "--missing-only",
        help="Only extract videos without a proposed Markdown artifact.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help=(
            "Rebuild extraction artifacts even when a video is already marked "
            "extracted or exported."
        ),
    ),
    source_id: int | None = typer.Option(
        None,
        help="Only extract videos from a specific source id.",
    ),
    classifier: str = typer.Option(
        DEFAULT_CLASSIFIER,
        "--classifier",
        help="Content classifier: auto, rules, llm, or typesafe.",
    ),
    llm_model: str | None = typer.Option(
        None,
        "--llm-model",
        help="Override the configured local Ollama model.",
    ),
    recording_verifier_backend: str = typer.Option(
        DEFAULT_RECORDING_VERIFIER_BACKEND,
        "--recording-verifier-backend",
        help="Ambiguous-recording verifier: ollama, typesafe, or none.",
    ),
    recording_verifier_model: str | None = typer.Option(
        None,
        "--recording-verifier-model",
        help=f"Verifier model override; TypeSafe defaults to {DEFAULT_TYPESAFE_MODEL}.",
    ),
    jobs: int = typer.Option(
        2,
        "--jobs",
        min=1,
        help="Concurrent video extraction jobs.",
    ),
    base_dir: Path | None = typer.Option(
        None,
        help="Override app data directory.",
    ),
) -> None:
    database = command_common.get_database(base_dir)
    paths = config.build_paths(base_dir, remember=True)
    try:
        result = application.extract_batch(
            database,
            paths,
            missing_only=missing_only,
            force=force,
            source_id=source_id,
            classifier=classifier,
            llm_model=llm_model,
            recording_verifier_backend=recording_verifier_backend,
            recording_verifier_model=recording_verifier_model,
            workers=jobs,
            event_callback=lambda message: console.print(message, markup=False),
            progress_callback=lambda stage, current, total: console.print(
                f"  {stage} block {current}/{total}"
            ),
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print(
        f"Extracted {result.processed} video(s); skipped {result.skipped}; "
        f"failed {result.failed}."
    )
