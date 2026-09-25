from __future__ import annotations

import json
from pathlib import Path
import shlex
import subprocess

import typer
from rich.console import Console

from pastor_transcript_extractor.commands.apps import media_app
from pastor_transcript_extractor.commands.common import get_database
from pastor_transcript_extractor.config import build_paths, build_tool_config
from pastor_transcript_extractor.identity import record_neutral_speaker_evidence
from pastor_transcript_extractor.media_artifacts import (
    ArchivedMediaUnavailableError,
    audit_normalized_audio_provenance,
    get_authoritative_normalized_media_artifact,
    repair_normalized_audio_provenance,
)
from pastor_transcript_extractor.speaker_review_invalidation import (
    invalidate_reviews_for_videos,
)
from pastor_transcript_extractor.storage import Database


console = Console()


@media_app.command(
    "audit-normalized-provenance",
    help="Read-only audit of derived and reconstructed normalized-audio conflicts.",
)
def media_audit_normalized_provenance(
    json_output: bool = typer.Option(
        False, "--json", help="Emit the complete machine-readable report."
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    paths = build_paths(base_dir)
    if not paths.database.exists():
        raise typer.BadParameter(f"Application database does not exist: {paths.database}")
    report = audit_normalized_audio_provenance(
        Database(paths.database, readonly=True)
    )

    def artifact_payload(artifact) -> dict[str, object]:
        return {
            "artifact_id": artifact.id,
            "path": artifact.artifact_path,
            "created_at": artifact.created_at.isoformat(),
            "sha256": artifact.content_sha256,
            "duration_seconds": artifact.duration_seconds,
            "byte_size": artifact.byte_size,
            "manifest_path": artifact.manifest_path,
        }

    payload = {
        "schema_version": 1,
        "generated_at": report.generated_at.isoformat(),
        "video_count": len(report.records),
        "affected_count": len(report.affected),
        "historically_affected_count": sum(
            record.historical_reconstructed_override for record in report.records
        ),
        "videos": [
            {
                "video_id": record.video_id,
                "youtube_video_id": record.youtube_video_id,
                "derived_normalized_artifact": artifact_payload(record.derived_artifact),
                "reconstructed_existing_normalized_artifact": artifact_payload(
                    record.reconstructed_artifact
                ),
                "reconstructed_currently_selected": (
                    record.reconstructed_currently_selected
                ),
                "legacy_reconstructed_override": record.legacy_reconstructed_override,
                "historical_reconstructed_override": (
                    record.historical_reconstructed_override
                ),
                "reconstructed_age_seconds": record.reconstructed_age_seconds,
            }
            for record in report.records
        ],
    }
    if json_output:
        console.print_json(json.dumps(payload, sort_keys=True))
        return
    console.print(
        f"Normalized provenance pairs={len(report.records)}; "
        f"affected={len(report.affected)}. This audit is read-only."
    )
    for record in report.records:
        derived = record.derived_artifact
        reconstructed = record.reconstructed_artifact
        console.print(
            f"{record.youtube_video_id}: affected={record.legacy_reconstructed_override} "
            f"reconstructed_selected={record.reconstructed_currently_selected} "
            f"age_days={record.reconstructed_age_seconds / 86400:.2f}\n"
            f"  derived: {derived.artifact_path} created={derived.created_at.isoformat()} "
            f"sha256={derived.content_sha256} duration={derived.duration_seconds} "
            f"bytes={derived.byte_size}\n"
            f"  reconstructed: {reconstructed.artifact_path} "
            f"created={reconstructed.created_at.isoformat()} "
            f"sha256={reconstructed.content_sha256} duration={reconstructed.duration_seconds} "
            f"bytes={reconstructed.byte_size}"
        )


@media_app.command(
    "repair-normalized-provenance",
    help="Re-normalize affected audio from verified immutable source artifacts.",
)
def media_repair_normalized_provenance(
    all_affected: bool = typer.Option(
        False, "--all-affected", help="Repair every video identified by the audit."
    ),
    youtube_video_id: str | None = typer.Option(
        None, "--youtube-video-id", help="Repair one affected YouTube video."
    ),
    evaluation_root: Path = typer.Option(
        Path("evaluation/speaker-pairs"),
        help="Speaker-review artifacts to revoke when they used affected audio.",
    ),
    reviewer: str = typer.Option(
        "normalized-provenance-repair",
        help="Reviewer or system actor recorded on append-only cleanup events.",
    ),
    regenerate_fingerprints: bool = typer.Option(
        False,
        "--regenerate-fingerprints",
        help=(
            "Append audio-bound speaker observations using the repaired "
            "normalized-audio SHA-256."
        ),
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    if (youtube_video_id is None) == (not all_affected):
        raise typer.BadParameter(
            "Pass exactly one of --youtube-video-id or --all-affected."
        )
    database = get_database(base_dir)
    video_ids = None
    if youtube_video_id is not None:
        video = database.get_video_by_youtube_id(youtube_video_id)
        if video is None:
            raise typer.BadParameter(f"Unknown YouTube video ID: {youtube_video_id}")
        video_ids = {video.id}
    try:
        audit_report = audit_normalized_audio_provenance(database)
        affected_records = [
            record
            for record in audit_report.affected
            if video_ids is None or record.video_id in video_ids
        ]
        cleanup_records = [
            record
            for record in audit_report.records
            if record.historical_reconstructed_override
            and (video_ids is None or record.video_id in video_ids)
        ]
        repaired = repair_normalized_audio_provenance(
            database,
            build_paths(base_dir),
            build_tool_config(),
            video_ids=video_ids,
        )
        # Repair performs an all-video availability preflight. Only after it
        # succeeds may identity/review state be invalidated.
        cleanup = invalidate_reviews_for_videos(
            database,
            evaluation_root=evaluation_root,
            youtube_video_ids={record.youtube_video_id for record in cleanup_records},
            suspect_audio_sha256_by_video={
                record.youtube_video_id: {record.reconstructed_artifact.content_sha256}
                for record in cleanup_records
            },
            reviewer=reviewer,
            reason=(
                "Invalidated because review clips were generated from a reconstructed "
                "normalized-audio artifact that incorrectly overrode verified media-service audio."
            ),
        )
        regenerated: list[tuple[str, str | None, str]] = []
        if regenerate_fingerprints:
            regeneration_video_ids = {
                record.video_id for record in cleanup_records
            } | {result.video_id for result in repaired}
            for regeneration_video_id in sorted(regeneration_video_ids):
                video = database.get_video_by_id(regeneration_video_id)
                extraction = database.get_latest_extraction_result_for_video(
                    regeneration_video_id
                )
                normalized_audio, _availability = (
                    get_authoritative_normalized_media_artifact(
                        database, regeneration_video_id
                    )
                )
                if video is None or extraction is None or normalized_audio is None:
                    raise ValueError(
                        f"video {regeneration_video_id}: cannot regenerate an "
                        "audio-bound speaker fingerprint"
                    )
                previous = database.get_latest_speaker_observation_for_video(
                    regeneration_video_id
                )
                pastor = (
                    database.get_pastor_by_id(video.pastor_id)
                    if video.pastor_id is not None
                    else None
                )
                speaker_record = record_neutral_speaker_evidence(
                    database,
                    build_paths(base_dir),
                    video=video,
                    extraction_result=extraction,
                    pastor=pastor,
                    normalized_audio_artifact=normalized_audio,
                )
                observation = speaker_record.neutral_evidence.observation
                if observation is None:
                    raise ValueError(
                        f"{video.youtube_video_id}: extraction has no valid sermon window"
                    )
                regenerated.append(
                    (
                        video.youtube_video_id,
                        previous.input_fingerprint if previous is not None else None,
                        observation.input_fingerprint,
                    )
                )
    except ArchivedMediaUnavailableError as error:
        target = (
            f" --youtube-video-id {youtube_video_id}"
            if youtube_video_id
            else " --all-affected"
        )
        retry = (
            "pte media repair-normalized-provenance"
            f"{target} --regenerate-fingerprints --reviewer {shlex.quote(reviewer)}"
            + (
                f" --base-dir {shlex.quote(str(base_dir))}"
                if base_dir is not None
                else ""
            )
        )
        raise typer.BadParameter(f"{error}. Retry: {retry}") from error
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        raise typer.BadParameter(str(error)) from error
    console.print(
        "Speaker evidence cleanup: "
        f"drafts_revoked={len(cleanup.revoked_draft_ids)} "
        f"reviews_revoked={len(cleanup.revoked_review_event_ids)} "
        f"observations_reset={cleanup.dispositions_reset} "
        f"memberships_detached={cleanup.memberships_detached} "
        f"differences_cleared={cleanup.differences_cleared}."
    )
    for result in repaired:
        console.print(
            f"{result.youtube_video_id}: repaired artifact={result.artifact.artifact_path} "
            f"source_artifact_id={result.source_artifact.id} "
            f"manifest={result.artifact.manifest_path}"
        )
    for youtube_id, previous_fingerprint, fingerprint in regenerated:
        console.print(
            f"{youtube_id}: regenerated speaker fingerprint={fingerprint} "
            f"previous={previous_fingerprint or 'none'}"
        )
    console.print(
        f"Normalized provenance repair complete: repaired={len(repaired)}; "
        f"fingerprints_regenerated={len(regenerated)}; "
        "old artifacts and observations were preserved."
    )
