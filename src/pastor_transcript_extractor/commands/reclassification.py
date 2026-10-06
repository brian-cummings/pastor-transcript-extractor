from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import typer

from pastor_transcript_extractor.commands.apps import root_app
from pastor_transcript_extractor.inference_defaults import (
    DEFAULT_RECORDING_VERIFIER_BACKEND,
    DEFAULT_TYPESAFE_MODEL,
)


@dataclass(frozen=True, slots=True)
class ReclassificationCommandRequest:
    video_id: int | None
    source_id: int | None
    review_required: bool
    all_videos: bool
    fixture_dir: Path | None
    llm_model: str | None
    recording_verifier_backend: str
    recording_verifier_model: str | None
    jobs: int
    inference_cache_root: Path | None
    recording_verifier_cache_root: Path | None
    force: bool
    base_dir: Path | None


ReclassificationInvoker = Callable[[ReclassificationCommandRequest], object]
_reclassification_invoker: ReclassificationInvoker | None = None


def configure_reclassification_command(invoker: ReclassificationInvoker) -> None:
    """Bind reclassification composition after CLI modules are imported."""
    global _reclassification_invoker
    _reclassification_invoker = invoker


@root_app.command(help="Rerun classification using existing extraction segments.")
def reclassify(
    video_id: int | None = typer.Option(
        None, "--video-id", help="Reclassify one database video id."
    ),
    source_id: int | None = typer.Option(
        None, "--source-id", help="Reclassify extracted videos from one source id."
    ),
    review_required: bool = typer.Option(
        False,
        "--review-required",
        help=(
            "Reclassify videos whose latest extraction has a persisted "
            "review_required final disposition."
        ),
    ),
    all_videos: bool = typer.Option(
        False,
        "--all",
        help="Reclassify every database video with reusable extraction segments.",
    ),
    fixture_dir: Path | None = typer.Option(
        None,
        "--fixture-dir",
        help="Reclassify every approved fixture in this directory.",
    ),
    llm_model: str | None = typer.Option(
        None, "--llm-model", help="Override the configured local Ollama model."
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
        2, "--jobs", min=1, help="Concurrent video classification jobs."
    ),
    inference_cache_root: Path | None = typer.Option(
        None,
        "--inference-cache-root",
        help=(
            "Use a separate per-video inference cache root, primarily for "
            "controlled comparisons."
        ),
    ),
    recording_verifier_cache_root: Path | None = typer.Option(
        None,
        "--recording-verifier-cache-root",
        help="Use a shared recording-verifier cache root.",
    ),
    force: bool = typer.Option(
        False, "--force", help="Rerun even when model and prompt versions match."
    ),
    base_dir: Path | None = typer.Option(
        None,
        "--base-dir",
        help=(
            "Application-data directory containing app.db; pass the directory, "
            "not the database file."
        ),
    ),
) -> None:
    if _reclassification_invoker is None:
        raise RuntimeError("Reclassification command was not configured.")
    _reclassification_invoker(
        ReclassificationCommandRequest(
            video_id=video_id,
            source_id=source_id,
            review_required=review_required,
            all_videos=all_videos,
            fixture_dir=fixture_dir,
            llm_model=llm_model,
            recording_verifier_backend=recording_verifier_backend,
            recording_verifier_model=recording_verifier_model,
            jobs=jobs,
            inference_cache_root=inference_cache_root,
            recording_verifier_cache_root=recording_verifier_cache_root,
            force=force,
            base_dir=base_dir,
        )
    )
