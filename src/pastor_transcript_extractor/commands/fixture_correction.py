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
class FixtureCorrectionCommandRequest:
    youtube_video_id: str
    fixture_dir: Path
    llm_model: str | None
    recording_verifier_backend: str
    recording_verifier_model: str | None
    inference_cache_root: Path | None
    recording_verifier_cache_root: Path | None
    base_dir: Path | None


FixtureCorrectionInvoker = Callable[[FixtureCorrectionCommandRequest], object]
_fixture_correction_invoker: FixtureCorrectionInvoker | None = None


def configure_fixture_correction_command(
    invoker: FixtureCorrectionInvoker,
) -> None:
    """Bind fixture-correction composition after CLI modules are imported."""
    global _fixture_correction_invoker
    _fixture_correction_invoker = invoker


@root_app.command(
    "apply-fixture-correction",
    help=(
        "Apply one approved continuous sermon fixture to its production window "
        "and speaker observation."
    ),
)
def apply_fixture_correction(
    youtube_video_id: str = typer.Argument(
        ...,
        help="YouTube video ID whose approved fixture supplies the correction.",
    ),
    fixture_dir: Path = typer.Option(
        Path("evaluation/fixtures"),
        "--fixture-dir",
        help="Directory containing <youtube-video-id>.json fixtures.",
    ),
    llm_model: str | None = typer.Option(
        None,
        "--llm-model",
        help="Override the configured local Ollama classification model.",
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
    inference_cache_root: Path | None = typer.Option(
        None,
        "--inference-cache-root",
        help="Use a separate per-video inference cache root.",
    ),
    recording_verifier_cache_root: Path | None = typer.Option(
        None,
        "--recording-verifier-cache-root",
        help="Use a shared recording-verifier cache root.",
    ),
    base_dir: Path | None = typer.Option(
        None,
        help="Override app data directory.",
    ),
) -> None:
    if _fixture_correction_invoker is None:
        raise RuntimeError("Fixture correction command was not configured.")
    _fixture_correction_invoker(
        FixtureCorrectionCommandRequest(
            youtube_video_id=youtube_video_id,
            fixture_dir=fixture_dir,
            llm_model=llm_model,
            recording_verifier_backend=recording_verifier_backend,
            recording_verifier_model=recording_verifier_model,
            inference_cache_root=inference_cache_root,
            recording_verifier_cache_root=recording_verifier_cache_root,
            base_dir=base_dir,
        )
    )
