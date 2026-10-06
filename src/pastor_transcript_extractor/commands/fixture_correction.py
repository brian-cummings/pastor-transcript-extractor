from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path

import typer
from rich.console import Console

from pastor_transcript_extractor import application, config, local_llm
from pastor_transcript_extractor.commands.apps import root_app
from pastor_transcript_extractor.commands import common as command_common
from pastor_transcript_extractor.fixture_correction import (
    load_fixture_window_correction,
)
from pastor_transcript_extractor.fixture_validation import FixtureValidationError
from pastor_transcript_extractor.inference_defaults import (
    DEFAULT_RECORDING_VERIFIER_BACKEND,
    DEFAULT_TYPESAFE_MODEL,
)
from pastor_transcript_extractor.media_artifacts import (
    get_authoritative_normalized_media_artifact,
)
from pastor_transcript_extractor.workflows.fixture_correction import (
    propagate_fixture_correction,
)
from pastor_transcript_extractor.workflows.reclassification import (
    has_reusable_extraction_segments,
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


console = Console()


def _run_fixture_correction(request: FixtureCorrectionCommandRequest) -> None:
    try:
        correction = load_fixture_window_correction(
            request.fixture_dir,
            request.youtube_video_id,
        )
    except FixtureValidationError as error:
        raise typer.BadParameter(str(error)) from error
    database = command_common.get_database(request.base_dir)
    paths = config.build_paths(request.base_dir, remember=True)
    video = database.get_video_by_youtube_id(request.youtube_video_id)
    if video is None:
        raise typer.BadParameter(
            f"Unknown YouTube video ID: {request.youtube_video_id}"
        )
    extraction = database.get_latest_extraction_result_for_video(video.id)
    if extraction is None or not has_reusable_extraction_segments(extraction):
        raise typer.BadParameter(
            f"Video {request.youtube_video_id} has no reusable extraction segments"
        )
    previous_observation = database.get_latest_speaker_observation_for_video(
        video.id
    )
    try:
        normalized_audio, _availability = (
            get_authoritative_normalized_media_artifact(database, video.id)
        )
    except AttributeError:
        normalized_audio = None
    llm_config = config.build_llm_config()
    if request.llm_model is not None:
        llm_config = replace(llm_config, model=request.llm_model)
    client = local_llm.OllamaClient(llm_config)
    try:
        verifier = application.build_recording_verifier_runner(
            backend=request.recording_verifier_backend,
            model=request.recording_verifier_model,
            llm_config=llm_config,
        )
    except (RuntimeError, ValueError) as error:
        raise typer.BadParameter(str(error)) from error
    try:
        result = propagate_fixture_correction(
            database,
            paths,
            video=video,
            correction=correction,
            previous_observation=previous_observation,
            normalized_audio=normalized_audio,
            llm_client=client,
            prompt_version=llm_config.prompt_version,
            context_size=llm_config.context_size,
            inference_cache_root=(
                request.inference_cache_root.expanduser().resolve()
                if request.inference_cache_root is not None
                else None
            ),
            recording_verifier=verifier,
            recording_verifier_cache_root=(
                request.recording_verifier_cache_root.expanduser().resolve()
                if request.recording_verifier_cache_root is not None
                else None
            ),
            event_callback=lambda message: console.print(message, markup=False),
        )
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        raise typer.BadParameter(
            f"Fixture override was saved, but correction propagation failed: {error}"
        ) from error
    console.print(
        f"Corrected video #{result.video_id}: disposition={result.disposition_status}; "
        f"speaker_fingerprint_{result.fingerprint_state}="
        f"{result.observation_fingerprint}; "
        f"previous={result.previous_fingerprint or 'none'}; "
        f"automatic_pair_eligibility={result.automatic_pair_eligibility}."
    )


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
    _run_fixture_correction(
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
