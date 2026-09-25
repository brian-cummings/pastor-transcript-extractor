from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from pastor_transcript_extractor.artifact_namespace import resolve_video_artifact_paths
from pastor_transcript_extractor.commands.apps import root_app
from pastor_transcript_extractor.commands.common import get_database
from pastor_transcript_extractor.config import build_paths
from pastor_transcript_extractor.fixture_validation import (
    FixtureValidationError,
    ValidatedFixture,
    validate_fixture_payload,
)
from pastor_transcript_extractor.pipeline_diagnostics import (
    build_diagnostic_markdown,
    build_diagnostic_trace,
    build_identity_operational_outcome,
    load_identity_association_attempts,
    load_identity_boundary_feedback,
)


console = Console()


def _load_pipeline_diagnostic_fixture(
    fixture_path: Path | None,
    *,
    youtube_video_id: str,
) -> ValidatedFixture | None:
    if fixture_path is None:
        return None
    resolved = fixture_path.expanduser().resolve()
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
        fixture = validate_fixture_payload(payload, path=resolved)
    except (OSError, json.JSONDecodeError, FixtureValidationError) as error:
        raise typer.BadParameter(f"Invalid diagnostic fixture: {error}") from error
    if fixture.video_id != youtube_video_id:
        raise typer.BadParameter(
            f"Fixture video id {fixture.video_id!r} does not match {youtube_video_id!r}."
        )
    return fixture


def _persisted_identity_outcome(
    database: Any,
    *,
    video_id: int,
    extraction_result_id: int,
    content_disposition: str | None,
    association_attempts: list[dict[str, Any]],
    boundary_feedback: list[dict[str, Any]],
) -> dict[str, Any]:
    observation = database.get_latest_speaker_observation_for_video(video_id)
    profile_ids = (
        sorted(
            {
                database.resolve_speaker_profile_id(profile_id)
                for profile_id in database.list_effective_profile_ids_for_observation(
                    observation.id
                )
            }
        )
        if observation is not None
        else []
    )
    profile_redirects = {
        profile.id: database.resolve_speaker_profile_id(profile.id)
        for profile in database.list_speaker_profiles()
    }
    return build_identity_operational_outcome(
        content_disposition=content_disposition,
        extraction_result_id=extraction_result_id,
        observation=(
            {
                "id": observation.id,
                "extraction_result_id": observation.extraction_result_id,
                "input_fingerprint": observation.input_fingerprint,
            }
            if observation is not None
            else None
        ),
        effective_profile_ids=profile_ids,
        association_attempts=association_attempts,
        boundary_feedback=boundary_feedback,
        profile_redirects=profile_redirects,
    )

@root_app.command(
    "diagnose",
    help="Build a read-only sermon-isolation trace and human diagnostic views.",
)
def diagnose_pipeline(
    video_id: int = typer.Option(..., "--video-id", help="Database video id to diagnose."),
    fixture: Path | None = typer.Option(
        None,
        "--fixture",
        help="Optional reviewed fixture JSON for actual recall and contamination measurements.",
    ),
    output_dir: Path | None = typer.Option(
        None,
        "--output-dir",
        help="Output directory; defaults to the video's immutable artifact namespace.",
    ),
    identity_feedback_root: Path = typer.Option(
        Path("evaluation/speaker-associations/shadow-runs"),
        "--identity-feedback-root",
        help=(
            "Existing identity shadow artifacts containing association outcomes and "
            "sermon-edge advisories."
        ),
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    paths = build_paths(base_dir, remember=True)
    video = database.get_video_by_id(video_id)
    if video is None:
        raise typer.BadParameter(f"Unknown video id: {video_id}")
    extraction = database.get_latest_extraction_result_for_video(video.id)
    if extraction is None or not extraction.proposed_json_path:
        raise typer.BadParameter(f"Video #{video.id} has no proposed extraction artifact.")
    proposed_path = Path(extraction.proposed_json_path)
    try:
        proposed = json.loads(proposed_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise typer.BadParameter(f"Invalid proposed extraction artifact: {error}") from error
    if not isinstance(proposed, dict):
        raise typer.BadParameter("Proposed extraction artifact must be a JSON object.")
    reviewed_fixture = _load_pipeline_diagnostic_fixture(
        fixture,
        youtube_video_id=video.youtube_video_id,
    )
    identity_feedback = load_identity_boundary_feedback(
        identity_feedback_root,
        database_video_ids={video.id},
    )
    identity_attempts = load_identity_association_attempts(
        identity_feedback_root,
        database_video_ids={video.id},
    )
    disposition = proposed.get("final_disposition")
    disposition = disposition if isinstance(disposition, dict) else {}
    identity_observation = database.get_latest_speaker_observation_for_video(video.id)
    boundary_feedback = [
        event
        for event in identity_feedback.get(video.id, [])
        if event.get("observation_id") in {
            None,
            identity_observation.id if identity_observation is not None else None,
        }
    ]
    trace = build_diagnostic_trace(
        proposed,
        proposed_path=proposed_path,
        youtube_video_id=video.youtube_video_id,
        database_video_id=video.id,
        fixture=reviewed_fixture,
        media_duration_seconds=float(video.duration_seconds) if video.duration_seconds else None,
        video_title=video.title,
        identity_boundary_feedback=boundary_feedback,
        identity_outcome=_persisted_identity_outcome(
            database,
            video_id=video.id,
            extraction_result_id=extraction.id,
            content_disposition=(
                str(disposition["status"]) if disposition.get("status") else None
            ),
            association_attempts=identity_attempts.get(video.id, []),
            boundary_feedback=boundary_feedback,
        ),
    )
    root = (
        output_dir.expanduser().resolve()
        if output_dir is not None
        else resolve_video_artifact_paths(database, paths, video).root / "diagnostics"
    )
    root.mkdir(parents=True, exist_ok=True)
    trace_path = root / "diagnostic-trace-v7.json"
    report_path = root / "diagnostic-report.md"
    trace_path.write_text(json.dumps(trace, indent=2, sort_keys=True), encoding="utf-8")
    report_path.write_text(build_diagnostic_markdown(trace), encoding="utf-8")
    console.print(f"Wrote canonical diagnostic trace to {trace_path}")
    console.print(f"Wrote pipeline and timeline views to {report_path}")
    operational = trace.get("operational_status", {})
    operational = operational if isinstance(operational, dict) else {}
    blocker = operational.get("blocker")
    blocker_label = (
        f"{blocker.get('stage')} / {blocker.get('code')}"
        if isinstance(blocker, dict)
        else "none"
    )
    window = operational.get("effective_window")
    window_label = (
        f"{float(window['start_seconds']):.0f}s–{float(window['end_seconds']):.0f}s"
        if isinstance(window, dict)
        and isinstance(window.get("start_seconds"), (int, float))
        and isinstance(window.get("end_seconds"), (int, float))
        else "none"
    )
    console.print(
        f"Current disposition: {operational.get('disposition', 'unknown')}; "
        f"effective window: {window_label}; operational blocker: {blocker_label}."
    )
    if trace.get("ground_truth", {}).get("status") != "available":
        console.print("Measured correctness: unavailable without reviewed ground truth.")
    observed = trace.get("earliest_observed_failure")
    cause = trace.get("root_cause_hypothesis", {})
    console.print(
        "Earliest observed failure: "
        f"{observed.get('stage') if isinstance(observed, dict) else 'none'}; "
        f"likely cause: {cause.get('stage') or 'none'} "
        f"({cause.get('confidence') or 'n/a'} confidence)."
    )
