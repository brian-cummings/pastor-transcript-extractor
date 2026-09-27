from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, as_completed, wait
from dataclasses import dataclass, replace
from datetime import date
import json
from importlib import metadata as importlib_metadata
import os
from pathlib import Path
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys
import time
from threading import Lock, local
from typing import Any, Callable, Mapping, Sequence
import webbrowser

import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, TaskID, TaskProgressColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from pastor_transcript_extractor.application import ReviewBatchResult, extract_batch, prepare_review_exports
from pastor_transcript_extractor.audio_staging import (
    load_and_verify_audio_stage_manifest,
    write_audio_stage_manifest,
)
from pastor_transcript_extractor.artifact_namespace import resolve_video_artifact_paths
from pastor_transcript_extractor.church_database_import import (
    IMPORT_PROVIDER,
    ChurchDatabaseImportError,
    import_church_sources,
    imported_source_ids,
)
from pastor_transcript_extractor.commands.apps import (
    attach_command_groups,
    identity_app,
    organization_app,
    pastor_app,
    source_ownership_app,
    root_app,
)
from pastor_transcript_extractor.commands.analysis import content as _analysis_content_commands
from pastor_transcript_extractor.commands.analysis import scripture as _analysis_scripture_commands
from pastor_transcript_extractor.commands.analysis import structure as _analysis_structure_commands
from pastor_transcript_extractor.commands.analysis import style as _analysis_style_commands
from pastor_transcript_extractor.commands import benchmark as _benchmark_commands
from pastor_transcript_extractor.commands import catalog as _catalog_commands
from pastor_transcript_extractor.commands.catalog import (
    add_source_service,
    delete_source_service,
)
from pastor_transcript_extractor.commands import diagnostics as _diagnostic_commands
from pastor_transcript_extractor.commands import media as _media_commands
from pastor_transcript_extractor.commands import media_archive as _media_archive_commands
from pastor_transcript_extractor.commands import media_provenance as _media_provenance_commands
from pastor_transcript_extractor.commands import evaluation as _evaluation_commands
from pastor_transcript_extractor.commands import pipeline as _pipeline_commands
from pastor_transcript_extractor.commands.identity import evaluation as _identity_evaluation_commands
from pastor_transcript_extractor.commands.identity import review as _identity_review_commands
from pastor_transcript_extractor.commands.identity import profiles as _identity_profile_commands
from pastor_transcript_extractor.commands.identity import metadata as _identity_metadata_commands
from pastor_transcript_extractor.commands.identity import coordination as _identity_coordination_commands
from pastor_transcript_extractor.commands.identity.coordination import (
    coordinate_identity_command,
)
from pastor_transcript_extractor.commands.identity import assignments as _identity_assignment_commands
from pastor_transcript_extractor.commands.identity import workflow as _identity_workflow_commands
from pastor_transcript_extractor.commands.identity.workflow import identity_run_command
from pastor_transcript_extractor.commands.identity.common import (
    _held_out_speaker_fixture_fingerprints,
)
from pastor_transcript_extractor.commands.identity.review import (
    _normalize_review_terminal_input,
    _reviewed_evidence_sync_command,
    review_speaker_pair,
)
from pastor_transcript_extractor.commands.common import unknown_pastor_error as _unknown_pastor_error
from pastor_transcript_extractor.config import (
    AppPaths,
    build_llm_config,
    build_paths,
    build_pastor_paths,
    build_tool_config,
    ensure_directories,
)
from pastor_transcript_extractor.discovery import extract_discovered_videos
from pastor_transcript_extractor.disposition import REVIEW_REQUIRED
from pastor_transcript_extractor.extraction import reclassify_video
from pastor_transcript_extractor.sermon_policy import (
    duration_meets_sermon_minimum,
    duration_within_sermon_maximum,
    maximum_sermon_duration_seconds,
    minimum_sermon_duration_seconds,
    publication_is_not_future,
    video_is_sermon_eligible,
)
from pastor_transcript_extractor.exporting import export_profile_transcript_collection
from pastor_transcript_extractor.evaluation_partitioning import (
    assign_recording_partition,
    extend_source_family_registry,
    load_source_family_registry,
)
from pastor_transcript_extractor.fixture_correction import (
    load_fixture_window_correction,
    persist_fixture_window_override,
)
from pastor_transcript_extractor.fixture_validation import (
    FixtureValidationError,
    ValidatedFixture,
    validate_fixture_directory,
    validate_fixture_payload,
)
from pastor_transcript_extractor.ground_truth_review import (
    NEGATIVE_FAILURE_MODES,
    POSITIVE_FAILURE_MODES,
    approved_negative_fixture_payload,
    approved_fixture_payload,
    draft_payload,
    format_timestamp,
    open_video_url,
    parse_interruptions,
    parse_timestamp,
    suggested_envelope,
    transcript_context,
    write_json,
    youtube_timestamp_url,
)
from pastor_transcript_extractor.profile_analysis import (
    resolve_profile_sermon_scope,
)
from pastor_transcript_extractor.reviewed_speaker_evidence import (
    ReviewedSpeakerEvidence,
    ReviewedEvidenceSyncResult,
    load_reviewed_speaker_evidence,
    sync_reviewed_speaker_evidence,
)
from pastor_transcript_extractor.identity import (
    backfill_shadow_identity_assessments,
    latest_metadata_live_status,
    persist_metadata_snapshot,
    record_neutral_speaker_evidence,
)
from pastor_transcript_extractor.identity_attribution import (
    configured_target_title_selection_hint,
    title_byline_selection_hint,
)
from pastor_transcript_extractor.identity_coordination import (
    build_identity_coordination_report,
    count_missing_discovery_reviewed_constraints,
    load_discovery_acoustic_ranking_pairs,
    load_discovery_observation_states,
    load_discovery_resolution_pairs,
    load_prepared_shadow_association_context,
    load_shadow_association_confirmation_pairs,
    load_unmatched_association_fingerprints,
    write_identity_coordination_report,
)
from pastor_transcript_extractor.models import (
    MediaArtifact,
    SpeakerObservation,
    TranscriptSourceKind,
    Video,
    VideoStatus,
)
from pastor_transcript_extractor.media_archive import (
    ArchivePreflightEvent,
    ArchiveProgressEvent,
    ArchiveRunResult,
    CanonicalAudioPreparationProgressEvent,
    archive_normalized_media,
    archive_source_media,
    media_archive_lock_held,
    prepare_canonical_audio,
    load_verified_canonical_clips,
    write_canonical_clip_preparation_manifest,
)
from pastor_transcript_extractor.media_artifacts import (
    ArchivedMediaUnavailableError,
    MediaVerificationCache,
    backfill_existing_media_artifacts,
    ensure_audio_for_video,
    get_verified_normalized_media_artifact,
    get_authoritative_normalized_media_artifact,
    stage_source_audio_for_video,
    resolve_normalized_audio_path,
    video_has_isolated_sermon,
)
from pastor_transcript_extractor.pipeline_diagnostics import (
    load_identity_association_attempts,
)
from pastor_transcript_extractor.local_llm import LocalLlmError, OllamaClient
from pastor_transcript_extractor.identity_boundary_review import (
    persist_association_boundary_evidence,
)
from pastor_transcript_extractor.identity_leverage import (
    build_profile_leverage_snapshot,
    compare_profile_leverage_snapshots,
    profile_neighborhood_video_ids,
)
from pastor_transcript_extractor.identity_exemplar_preparation import (
    ExemplarPreparationStateCache,
)
from pastor_transcript_extractor.identity_stage_cache import (
    build_association_input_state,
    build_identity_stage_fingerprint,
    load_identity_stage_checkpoint,
    load_identity_stage_input_state,
    write_identity_stage_checkpoint,
)
from pastor_transcript_extractor.identity_automation import (
    build_identity_association_work_plan,
    latest_association_reports,
    observation_profile_lineage_exclusion,
    select_superseded_profile_member_review,
    write_identity_work_event,
)
from pastor_transcript_extractor.speaker_pair_diagnostics import (
    AudioSpanCache,
    EmbeddingCache,
    PairDiagnosticCache,
    SherpaOnnxEmbeddingBackend,
    SpanSpec,
    analyze_observation_pair,
    build_embedding_centroid,
)
from pastor_transcript_extractor.speaker_association_audit import (
    audit_speaker_association_coverage,
)
from pastor_transcript_extractor.speaker_pair_eligibility import (
    assess_automatic_speaker_observation,
    select_verified_automatic_speaker_pair,
)
from pastor_transcript_extractor.speaker_pair_review import (
    CLIP_ACTIVITY_POLICY_VERSION,
    InsufficientSpeechActivityError,
    ObservationQualification,
    PairJudgment,
    prepare_review_observation,
)
from pastor_transcript_extractor.speaker_observation_consistency import (
    load_consistency_score_index,
    load_discovery_consistency_policy,
)
from pastor_transcript_extractor.speaker_pair_selector import (
    PairCandidateObservation,
    PairSelection,
    SelectionGoal,
    select_next_speaker_pair,
    selection_history_from_artifacts,
)
from pastor_transcript_extractor.speaker_review_invalidation import (
    evaluation_root_for_pair_artifact,
    filter_active_pair_artifacts,
    load_review_revocations,
    pair_artifact_is_revoked,
)
from pastor_transcript_extractor.speaker_profile_status import (
    applicable_status_commands,
    build_profile_pipeline_status,
)
from pastor_transcript_extractor.speaker_machine_assignment import (
    active_machine_assignment_evidence,
    apply_machine_assignment_plan,
    load_machine_assignment_policy,
    machine_assignment_report,
    machine_assignment_status,
    plan_machine_assignments,
    reconcile_machine_assignments,
    rollback_machine_assignments,
)
from pastor_transcript_extractor.speaker_negative_window_audit import (
    audit_speaker_negative_windows,
)
from pastor_transcript_extractor.speaker_profile_metadata_attribution import (
    profile_metadata_candidate_profile_ids,
    run_profile_metadata_attribution,
)
from pastor_transcript_extractor.speaker_profile_discovery import (
    ActivityQualifiedSelectionCache,
    DiscoveryCandidate,
    SHADOW_PROFILE_DISCOVERY_VERSION,
    TRANSCRIPT_GROUNDED_SPAN_SELECTION_VERSION,
    build_discovery_signature,
    build_discovery_signature_from_canonical_clips,
    evaluate_shadow_profile_discovery,
    load_verified_shadow_profile_discovery,
    nominate_discovery_pairs,
    prepare_activity_qualified_spans,
    refine_activity_qualified_spans,
    select_transcript_grounded_span_candidates,
    write_shadow_profile_discovery,
)
from pastor_transcript_extractor.speaker_profile_promotion import (
    apply_candidate_confirmations,
    apply_discovery_promotions,
    plan_candidate_confirmations,
    plan_discovery_promotions,
)
from pastor_transcript_extractor.source_profile_consolidation import (
    apply_source_profile_consolidation,
    build_source_profile_consolidation_plan,
    list_source_profile_cohorts,
    source_profile_candidates,
    source_profile_consolidation_payload,
    write_source_profile_consolidation_artifact,
    write_source_profile_consolidation_packet,
)
from pastor_transcript_extractor.speaker_shadow_association import (
    DISCOVERY_PROFILE_REASON,
    SHADOW_ASSOCIATION_VERSION,
    ShadowExemplar,
    assess_profile_association_readiness,
    build_shadow_association_input_fingerprint,
    evaluate_shadow_association,
    leave_one_out_profile_readiness,
    load_reusable_shadow_association,
    load_shadow_policy,
    plan_pending_discovery_confirmation_routes,
    select_profile_exemplars,
    select_routed_association_profiles,
    select_staged_association_profiles,
    should_activate_cross_source_fallback,
    summarize_shadow_associations,
    write_shadow_association,
    write_shadow_association_admission,
)
from pastor_transcript_extractor.speaker_registry import (
    record_observation_difference,
    record_observation_review,
)
from pastor_transcript_extractor.sermon_fixture_selector import (
    SermonSelectionHistory,
    select_next_sermon_fixture,
    sermon_candidate_from_proposal,
    sermon_duration_bucket,
)
from pastor_transcript_extractor.storage import Database
from pastor_transcript_extractor.transcription import (
    PreparedTranscriptInput,
    complete_transcription_video,
    fetch_captions_video,
    prepare_transcription_input,
)
from pastor_transcript_extractor.workflows.source_discovery import (
    DiscoveryServiceResult,
    discover_sources_service as _discover_sources_service,
)
from pastor_transcript_extractor.workflows.source_sync import (
    SourceSyncConfigurationError,
    SourceSyncDependencies,
    SourceSyncDiskReserveError,
    SourceSyncRequest,
    sync_imported_sources_workflow,
)
from pastor_transcript_extractor.workflows.run_media import (
    RunMediaDependencies,
    RunMediaRequest,
    ensure_and_archive_run_media as _ensure_and_archive_run_media_workflow,
)
from pastor_transcript_extractor.workflows.audio_stage import (
    AudioStageDependencies,
    AudioStageScopeDependencies,
    select_existing_stage_video_ids as _select_existing_stage_video_ids_workflow,
)
from pastor_transcript_extractor.workflows.resume_pipeline import (
    ResumePipelineDependencies,
)
from pastor_transcript_extractor.workflows.pipeline import (
    PipelineDependencies,
    PostContentIdentityRequest,
    run_post_content_identity,
)
from pastor_transcript_extractor.workflows.run import (
    RunWorkflowDependencies,
    RunWorkflowRequest,
    run_workflow,
)
from pastor_transcript_extractor.workflows.identity.run import (
    AssociationExecutionRequest,
    DiscoveryExecutionRequest,
    IdentityWorkflowRequest,
    decide_association_cache,
    decide_discovery_execution,
    execute_association_stage,
    execute_discovery_stage,
    finalize_discovery_stage,
    index_current_association_results,
    persist_association_checkpoint_stage,
    reconcile_current_assignment_results_stage,
    reconcile_machine_assignments_stage,
    repair_association_stage,
    run_machine_assignment_stage,
    run_metadata_attribution_stage,
    select_discovery_reports,
    select_pending_exemplar_repairs,
    synchronize_reviewed_evidence_stage,
    validate_identity_workflow_request,
)
from pastor_transcript_extractor.workflows.identity.finalization import (
    ActionableReviewAudioPreparation,
    CoordinationStageRequest,
    run_coordination_stage,
    run_review_prewarm_stage,
)
from pastor_transcript_extractor.workflows.caption_acquisition import (
    CaptionAcquisitionBlockedError,
    CaptionAcquisitionResult,
    fetch_captions_service as _fetch_captions_service,
)
from pastor_transcript_extractor.workflows.transcription import (
    DEFAULT_PREP_WORKERS,
    DEFAULT_TRANSCRIBE_JOBS,
    default_transcribe_jobs as _workflow_default_transcribe_jobs,
    recover_stale_transcribing_videos as _recover_stale_transcribing_videos,
    should_transcribe_video as _should_transcribe_video,
    transcribe_videos_service as _transcribe_videos_service,
)
from pastor_transcript_extractor.workflows.transcription_events import (
    STAGE_DONE,
    STAGE_DOWNLOADING,
    STAGE_FAILED,
    STAGE_NORMALIZING,
    STAGE_QUEUED_PREP,
    STAGE_QUEUED_TRANSCRIBE,
    STAGE_TRANSCRIBING,
    TranscriptionBatchFinished,
    TranscriptionBatchStarted,
    TranscriptionEvent,
    TranscriptionMessage,
    TranscriptionProgressed,
    TranscriptionResult,
    TranscriptionRetrying,
    TranscriptionStageChanged,
    TranscriptionTaskSubmitted,
    TranscriptionVideoFinished,
    TranscriptionVideoQueued,
)

app = root_app
attach_command_groups(app)
console = Console()
DEFAULT_DISCOVER_LIMIT = 26
CAPTION_BATCH_REQUEST_INTERVAL_SECONDS = 5.0
MIN_SYNC_FREE_DISK_FRACTION = 0.20
SYNC_ARCHIVE_WAIT_INITIAL_SECONDS = 1.0
SYNC_ARCHIVE_WAIT_MAX_SECONDS = 30.0
DEFAULT_SPEAKER_MODEL_SHA256 = "357a834f702b80161e5b981182c038e18553c1f2ca752ed6cec2052365d4129b"


def _catalog_video_is_sermon_eligible(
    database: Database,
    video: object,
    *,
    minimum_seconds: float | None = None,
    maximum_seconds: float | None = None,
) -> bool:
    return video_is_sermon_eligible(
        getattr(video, "duration_seconds", None),
        getattr(video, "published_at", None),
        minimum_seconds=minimum_seconds,
        maximum_seconds=maximum_seconds,
    )


def _select_existing_stage_video_ids(
    database: Database,
    source_ids: Sequence[int],
    *,
    limit: int | None,
    all_videos: bool,
) -> set[int]:
    return _select_existing_stage_video_ids_workflow(
        database,
        source_ids,
        limit=limit,
        all_videos=all_videos,
        latest_live_status=latest_metadata_live_status,
    )

def _prompt_failure_mode(*, contains_sermon: bool) -> str:
    options = POSITIVE_FAILURE_MODES if contains_sermon else NEGATIVE_FAILURE_MODES
    default = "unknown" if contains_sermon else "non_sermon_event"
    console.print("Failure mode options:")
    for code, description in options.items():
        console.print(f"  {code:<42} {description}")
    console.print("  other                                      Enter a custom failure mode.")
    while True:
        selected = typer.prompt("Failure mode", default=default).strip()
        if selected in options:
            return selected
        if selected == "other":
            custom = typer.prompt("Custom failure mode").strip()
            if custom:
                return custom
            console.print("[red]Custom failure mode cannot be blank.[/red]")
            continue
        console.print(f"[red]Choose one of: {', '.join((*options, 'other'))}[/red]")


@app.command(help="Review and approve sermon ground truth without treating detector output as truth.")
def review_ground_truth(
    youtube_video_id: str = typer.Argument(..., help="YouTube video ID already present in the database."),
    reviewer: str | None = typer.Option(None, help="Human reviewer name or stable reviewer identifier."),
    evaluation_dir: Path = typer.Option(Path("evaluation"), help="Root containing drafts/ and fixtures/."),
    open_video: bool = typer.Option(False, "--open-video", help="Open the YouTube start link in a browser."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
    selection_manifest_json: str | None = typer.Option(None, hidden=True),
) -> None:
    database = get_database(base_dir)
    video = database.get_video_by_youtube_id(youtube_video_id)
    if video is None:
        raise typer.BadParameter(f"Unknown YouTube video ID: {youtube_video_id}")
    extraction = database.get_latest_extraction_result_for_video(video.id)
    if extraction is None or not extraction.proposed_json_path:
        raise typer.BadParameter(f"Video {youtube_video_id} has no proposed extraction JSON")
    proposed_path = Path(extraction.proposed_json_path)
    try:
        payload = json.loads(proposed_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise typer.BadParameter(f"Could not load proposed extraction: {error}") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("segments"), list):
        raise typer.BadParameter("Proposed extraction is missing timestamped segments")
    segments = [segment for segment in payload["segments"] if isinstance(segment, dict)]
    segment_ends = [
        segment.get("end_seconds")
        for segment in segments
        if isinstance(segment.get("end_seconds"), (int, float))
    ]
    fallback_end = float(video.duration_seconds or (max(segment_ends) if segment_ends else 0.0))
    suggested_start, suggested_end, proposal_source = suggested_envelope(
        payload,
        fallback_end_seconds=fallback_end,
    )
    root = evaluation_dir.expanduser().resolve()
    draft_path = root / "drafts" / f"{youtube_video_id}.json"
    fixture_path = root / "fixtures" / f"{youtube_video_id}.json"
    try:
        selection_manifest = (
            json.loads(selection_manifest_json)
            if isinstance(selection_manifest_json, str)
            else None
        )
        if selection_manifest is not None and not isinstance(selection_manifest, dict):
            raise ValueError("selection manifest must be a JSON object")
        if selection_manifest is None and draft_path.exists():
            existing_draft = json.loads(draft_path.read_text(encoding="utf-8"))
            existing_manifest = (
                existing_draft.get("selection_manifest")
                if isinstance(existing_draft, dict)
                else None
            )
            if isinstance(existing_manifest, dict):
                selection_manifest = existing_manifest
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise typer.BadParameter(str(error)) from error
    write_json(
        draft_path,
        draft_payload(
            video_id=youtube_video_id,
            source_url=video.url,
            start_seconds=suggested_start,
            end_seconds=suggested_end,
            proposal_source=proposal_source,
            selection_manifest=selection_manifest,
        ),
    )
    console.print(f"Wrote unreviewed detector-assisted draft to {draft_path}")
    console.print(f"Video: {video.title}")
    if open_video:
        open_video_url(youtube_timestamp_url(video.url, suggested_start))

    def review_boundary(label: str, initial: float) -> float:
        current = initial
        while True:
            console.print(f"\n[bold]{label} candidate: {format_timestamp(current)}[/bold]")
            console.print(f"YouTube: {youtube_timestamp_url(video.url, current)}")
            console.print(transcript_context(segments, current))
            entered = typer.prompt(
                f"{label} timestamp (HH:MM:SS, or relative +5/-30)",
                default=format_timestamp(current),
            )
            try:
                candidate = parse_timestamp(entered, current=current)
            except ValueError as error:
                console.print(f"[red]{error}[/red]")
                continue
            if typer.confirm(f"Use {format_timestamp(candidate)} as the {label.lower()}?", default=True):
                return candidate
            current = candidate

    contains_sermon = typer.confirm(
        "Does this video contain a worship-service sermon?",
        default=True,
    )
    if not contains_sermon:
        reviewer_value = reviewer or typer.prompt("Reviewed by")
        failure_mode = _prompt_failure_mode(contains_sermon=False)
        notes = typer.prompt("Review notes", default="No worship-service sermon found.")
        fixture = approved_negative_fixture_payload(
            video_id=youtube_video_id,
            reviewer=reviewer_value,
            failure_mode=failure_mode,
            notes=notes,
            selection_manifest=selection_manifest,
        )
        validate_fixture_payload(fixture, path=fixture_path)
        if fixture_path.exists() and not typer.confirm(
            f"Overwrite existing fixture {fixture_path}?", default=False
        ):
            console.print("Existing fixture preserved.")
            return
        if not typer.confirm("Write this manually approved negative fixture?", default=True):
            console.print("Approval cancelled; the unreviewed draft was preserved.")
            return
        write_json(fixture_path, fixture)
        console.print(f"Wrote manually approved negative fixture to {fixture_path}")
        return
    start = review_boundary("Sermon start", suggested_start)
    end = review_boundary("Sermon end", suggested_end)
    if end <= start:
        raise typer.BadParameter("Approved sermon end must be after its start")
    while True:
        entered = typer.prompt(
            "Allowed interruptions as start-end pairs separated by commas (blank for none)",
            default="",
            show_default=False,
        )
        try:
            interruptions = parse_interruptions(entered)
            break
        except ValueError as error:
            console.print(f"[red]{error}[/red]")
    reviewer_value = reviewer or typer.prompt("Reviewed by")
    failure_mode = _prompt_failure_mode(contains_sermon=True)
    notes = typer.prompt("Review notes", default="")
    fixture = approved_fixture_payload(
        video_id=youtube_video_id,
        start_seconds=start,
        end_seconds=end,
        interruptions=interruptions,
        reviewer=reviewer_value,
        failure_mode=failure_mode,
        notes=notes,
        selection_manifest=selection_manifest,
    )
    validate_fixture_payload(fixture, path=fixture_path)
    if fixture_path.exists() and not typer.confirm(f"Overwrite existing fixture {fixture_path}?", default=False):
        console.print("Existing fixture preserved.")
        return
    if not typer.confirm("Write this manually approved ground-truth fixture?", default=True):
        console.print("Approval cancelled; the unreviewed draft was preserved.")
        return
    write_json(fixture_path, fixture)
    console.print(f"Wrote manually approved fixture to {fixture_path}")


@app.command(
    "review-next-ground-truth",
    help="Deterministically nominate and review the next sermon-segment fixture.",
)
def review_next_ground_truth(
    reviewer: str | None = typer.Option(None, help="Human reviewer name or stable identifier."),
    evaluation_dir: Path = typer.Option(Path("evaluation"), help="Root containing drafts/ and fixtures/."),
    source_family_registry: Path = typer.Option(
        Path("evaluation/source-families.json"),
        help="Frozen source-family registry used for partition-safe nomination.",
    ),
    open_video: bool = typer.Option(True, "--open-video/--no-open-video", help="Open the selected video."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    root = evaluation_dir.expanduser().resolve()
    try:
        registry = load_source_family_registry(source_family_registry.expanduser().resolve())
        drafts = _load_json_artifacts(sorted((root / "drafts").glob("*.json")))
        fixtures = _load_json_artifacts(sorted((root / "fixtures").glob("*.json")))
        excluded_ids = {
            str(payload["video_id"])
            for payload in (*drafts, *fixtures)
            if payload.get("video_id")
        }
        automatic_ids = {
            str(payload["video_id"])
            for payload in (*drafts, *fixtures)
            if payload.get("video_id")
            and isinstance(payload.get("selection_manifest"), dict)
            and payload["selection_manifest"].get("selection_origin") == "automatic"
        }

        candidates = []
        candidates_by_id = {}
        unregistered_source_urls: set[str] = set()
        for video in database.list_videos():
            extraction = database.get_latest_extraction_result_for_video(video.id)
            if extraction is None or not extraction.proposed_json_path:
                continue
            proposed_path = Path(extraction.proposed_json_path)
            try:
                proposal = json.loads(proposed_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(proposal, dict) or not isinstance(proposal.get("segments"), list):
                continue
            source = database.get_source_by_id(video.source_id)
            transcript = database.get_latest_transcript_artifact_for_video(video.id)
            if source is None:
                continue
            family = registry.resolve_source_url(source.url)
            if family is None:
                unregistered_source_urls.add(source.url)
                continue
            partition_assignment = assign_recording_partition(
                registry=registry,
                video_id=video.youtube_video_id,
                source_url=source.url,
                caption_source=transcript.source_kind.value if transcript else "unknown",
                recording_date=video.published_at,
            )
            candidate = sermon_candidate_from_proposal(
                video_id=video.youtube_video_id,
                corpus_group=partition_assignment.source_family_id,
                recording_date=video.published_at,
                duration_seconds=float(video.duration_seconds) if video.duration_seconds else None,
                proposal=proposal,
                source_family_id=partition_assignment.source_family_id,
                recording_condition_group_id=(
                    partition_assignment.recording_condition_group_id
                ),
                partition=partition_assignment.partition.value,
            )
            candidates.append(candidate)
            candidates_by_id[candidate.video_id] = candidate

        group_use: dict[str, int] = {}
        condition_use: dict[str, int] = {}
        signal_use: dict[str, int] = {}
        source_use: dict[str, int] = {}
        bucket_use: dict[str, int] = {}
        prior_dates = []
        history_by_video_id = {
            str(payload["video_id"]): payload
            for payload in (*drafts, *fixtures)
            if payload.get("video_id")
        }
        for history_item in history_by_video_id.values():
            candidate = candidates_by_id.get(str(history_item.get("video_id", "")))
            if candidate is None:
                continue
            manifest = history_item.get("selection_manifest")
            manifest = manifest if isinstance(manifest, dict) else {}
            family_id = str(
                manifest.get("source_family_id") or candidate.effective_source_family_id
            )
            condition_id = str(
                manifest.get("recording_condition_group_id")
                or candidate.effective_condition_group_id
            )
            group_use[family_id] = group_use.get(family_id, 0) + 1
            condition_use[condition_id] = condition_use.get(condition_id, 0) + 1
            frozen_signals = manifest.get("nomination_signals")
            frozen_signals = frozen_signals if isinstance(frozen_signals, list) else []
            for signal in frozen_signals:
                if not isinstance(signal, str):
                    continue
                signal_use[signal] = signal_use.get(signal, 0) + 1
            source_use[candidate.proposal_source] = source_use.get(candidate.proposal_source, 0) + 1
            bucket = sermon_duration_bucket(candidate.duration_seconds)
            bucket_use[bucket] = bucket_use.get(bucket, 0) + 1
            if candidate.recording_date is not None:
                prior_dates.append(candidate.recording_date)
        selection = select_next_sermon_fixture(
            candidates,
            SermonSelectionHistory(
                excluded_video_ids=frozenset(excluded_ids),
                automatic_selection_count=len(automatic_ids),
                corpus_group_use=group_use,
                source_family_use=group_use,
                recording_condition_group_use=condition_use,
                nomination_signal_use=signal_use,
                proposal_source_use=source_use,
                duration_bucket_use=bucket_use,
                prior_recording_dates=tuple(prior_dates),
            ),
        )
        if unregistered_source_urls:
            selection.manifest["unregistered_source_count"] = len(unregistered_source_urls)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise typer.BadParameter(str(error)) from error

    if selection.manifest.get("unregistered_source_count"):
        console.print(
            f"Skipped {selection.manifest['unregistered_source_count']} unregistered source(s); "
            "add them to the source-family registry before nomination."
        )
    console.print(
        f"Selected {selection.candidate.video_id} from "
        f"{selection.manifest['selection_stratum']}; "
        f"reasons={','.join(selection.manifest['reason_codes'])}"
    )
    review_ground_truth(
        youtube_video_id=selection.candidate.video_id,
        reviewer=reviewer,
        evaluation_dir=evaluation_dir,
        open_video=open_video,
        base_dir=base_dir,
        selection_manifest_json=json.dumps(selection.manifest, sort_keys=True),
    )


def get_database(base_dir: Path | None = None) -> Database:
    paths = build_paths(base_dir, remember=True)
    ensure_directories(paths)
    database = Database(paths.database)
    database.initialize()
    return database


def _association_admission_is_actionable(stage: str, reason_code: str) -> bool:
    if stage != "metadata_eligibility":
        return True
    return reason_code in {
        "diagnostic_spans_unavailable",
        "registered_normalized_media_unavailable",
    }


def _load_json_artifacts(paths: Sequence[Path]) -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"{path}: expected a JSON object")
        payloads.append(payload)
    roots = {
        root
        for path in paths
        if (root := evaluation_root_for_pair_artifact(path)) is not None
    }
    for root in roots:
        payloads = filter_active_pair_artifacts(
            payloads,
            load_review_revocations(root),
        )
    return payloads


def _reviewed_observation_pairs(
    database: Database,
    evidence: ReviewedSpeakerEvidence,
    *,
    outcome: str,
) -> set[tuple[int, int]]:
    observation_ids_by_fingerprint = {
        observation.input_fingerprint: observation.id
        for observation in database.list_speaker_observations()
    }
    pairs: set[tuple[int, int]] = set()
    for relation in evidence.pair_relations.values():
        if relation.outcome != outcome or len(relation.fingerprints) != 2:
            continue
        fingerprints = sorted(relation.fingerprints)
        if not all(
            fingerprint in observation_ids_by_fingerprint
            for fingerprint in fingerprints
        ):
            continue
        pairs.add(
            tuple(
                sorted(
                    observation_ids_by_fingerprint[fingerprint]
                    for fingerprint in fingerprints
                )
            )
        )
    return pairs


def _print_reviewed_evidence_summary(
    evidence: ReviewedSpeakerEvidence,
    result: ReviewedEvidenceSyncResult | None,
) -> None:
    console.print(
        "Reviewed evidence: "
        f"events={evidence.review_event_count} "
        f"qualifications={len(evidence.qualifications)} "
        f"same_components={len(evidence.same_components())} "
        f"pair_relations={len(evidence.pair_relations)} "
        f"conflicts={len(evidence.qualification_conflicts) + len(evidence.pair_conflicts)}"
    )
    if result is None:
        return
    console.print(
        "Registry sync: "
        f"qualification_events={result.qualification_events_added} "
        f"profiles={result.profiles_added} "
        f"memberships={result.membership_events_added} "
        f"different_constraints={result.difference_events_added} "
        f"name_claims={result.name_claim_events_added} "
        f"profile_redirects={result.profile_redirect_events_added} "
        f"missing={len(result.missing_observations)} "
        f"merge_candidates={len(result.merge_candidates)} "
        f"conflicts={len(result.conflicts)}"
    )
    for candidate in result.merge_candidates:
        console.print(f"[cyan]Merge candidate:[/cyan] {candidate}")
    for conflict in result.conflicts:
        console.print(f"[yellow]Review conflict:[/yellow] {conflict}")


@identity_app.command(
    "association-audit",
    help="Verify that every latest extraction has a terminal association-coverage state.",
)
def association_audit_command(
    association_root: Path = typer.Option(
        Path("evaluation/speaker-associations/shadow-runs"),
        help="Versioned speaker-association attempt artifacts.",
    ),
    cache_dir: Path = typer.Option(
        Path("evaluation/speaker-pairs/cache"),
        help="Media-verification cache used for current eligibility checks.",
    ),
    policy_path: Path = typer.Option(
        Path(
            "evaluation/speaker-pairs/policies/"
            "campplus-development-candidate-v1.json"
        ),
        help="Require association attempts produced with this exact policy artifact.",
    ),
    required_model_fingerprint: str | None = typer.Option(
        None,
        help="Optionally require one exact acoustic model fingerprint.",
    ),
    output_root: Path | None = typer.Option(
        None,
        help="Audit artifact directory; defaults under the application logs directory.",
    ),
    strict: bool = typer.Option(
        True,
        "--strict/--allow-gaps",
        help="Exit nonzero when any latest extraction is unaccounted.",
    ),
    base_dir: Path | None = typer.Option(
        None,
        help="Override app data directory.",
    ),
) -> None:
    paths = build_paths(base_dir)
    if not paths.database.exists():
        raise typer.BadParameter(
            f"Application database does not exist: {paths.database}"
        )
    destination_root = (
        output_root.expanduser().resolve()
        if output_root is not None
        else paths.logs / "association-audits"
    )
    try:
        policy_spec = load_shadow_policy(policy_path)
        result = audit_speaker_association_coverage(
            Database(paths.database, readonly=True),
            association_root=association_root,
            output_root=destination_root,
            verification_cache=MediaVerificationCache(
                cache_dir.expanduser().resolve() / "media-verification"
            ),
            required_policy_sha256=policy_spec.artifact_sha256,
            required_model_fingerprint=required_model_fingerprint,
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise typer.BadParameter(str(error)) from error
    counts = result.payload["counts"]
    console.print(
        "Association coverage: "
        f"extractions={counts['extractions']} "
        f"accounted={counts['accounted']} "
        f"unaccounted={counts['unaccounted']} "
        f"invalid_artifacts={counts['invalid_association_artifacts']}."
    )
    console.print(
        "Coverage states: "
        + ", ".join(
            f"{state}={count}"
            for state, count in result.payload["coverage_state_counts"].items()
        )
    )
    unaccounted_reasons: dict[str, int] = {}
    for case in result.payload["cases"]:
        if case["accounted"] is False:
            reason = str(case["reason_code"])
            unaccounted_reasons[reason] = unaccounted_reasons.get(reason, 0) + 1
    if unaccounted_reasons:
        console.print(
            "Unaccounted reasons: "
            + ", ".join(
                f"{reason}={count}"
                for reason, count in sorted(unaccounted_reasons.items())
            )
        )
    console.print(f"Wrote association coverage audit to {result.report_path}")
    if strict and not result.ok:
        raise typer.Exit(code=1)


@identity_app.command(
    "consolidate-source-profiles",
    help=(
        "Plan or human-approve complete-link consolidation of anonymous "
        "profiles sharing a source."
    ),
)
def consolidate_source_profiles_command(
    source_id: int | None = typer.Option(
        None,
        "--source-id",
        min=1,
        help="Source whose anonymous profiles should be compared.",
    ),
    list_sources: bool = typer.Option(
        False,
        "--list-sources",
        help="List sources with eligible anonymous profile cohorts.",
    ),
    minimum_profiles: int = typer.Option(
        2,
        "--minimum-profiles",
        min=1,
        help="Minimum eligible profile count shown by --list-sources.",
    ),
    plan_only: bool = typer.Option(
        False,
        "--plan-only",
        help="Inventory the source cohort without acoustic execution or writes.",
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Prompt for one human approval per complete-link cohort and merge it.",
    ),
    reviewer: str | None = typer.Option(
        None,
        help="Stable reviewer identifier; required with --apply.",
    ),
    exemplars_per_profile: int = typer.Option(
        3,
        min=2,
        max=5,
        help="Independent recording exemplars compared for each profile.",
    ),
    jobs: int = typer.Option(2, "--jobs", min=1),
    open_packet: bool = typer.Option(
        True,
        "--open-packet/--no-open-packet",
        help="Open the weakest-edge review packet before an apply prompt.",
    ),
    model_path: Path = typer.Option(
        Path(
            "evaluation/speaker-pairs/models/"
            "3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx"
        )
    ),
    model_sha256: str = typer.Option(DEFAULT_SPEAKER_MODEL_SHA256),
    policy_path: Path = typer.Option(
        Path(
            "evaluation/speaker-pairs/policies/"
            "campplus-development-candidate-v1.json"
        )
    ),
    evaluation_root: Path = typer.Option(Path("evaluation/speaker-pairs")),
    cache_dir: Path = typer.Option(Path("evaluation/speaker-pairs/cache")),
    output_root: Path = typer.Option(
        Path("evaluation/source-profile-consolidation/runs")
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> Path | None:
    if (source_id is None) == (not list_sources):
        raise typer.BadParameter(
            "Pass exactly one of --source-id or --list-sources"
        )
    if list_sources and apply:
        raise typer.BadParameter("--list-sources cannot be combined with --apply")
    if plan_only and apply:
        raise typer.BadParameter("--plan-only cannot be combined with --apply")
    if apply and not (reviewer or "").strip():
        raise typer.BadParameter("--apply requires --reviewer")
    paths = build_paths(base_dir)
    if not paths.database.exists():
        raise typer.BadParameter(f"Application database does not exist: {paths.database}")
    database = Database(paths.database, readonly=not apply)
    if source_id is not None and database.get_source_by_id(source_id) is None:
        raise typer.BadParameter(f"Unknown source: {source_id}")
    try:
        reviewed_evidence = load_reviewed_speaker_evidence(
            evaluation_root.expanduser().resolve()
        )
        if list_sources:
            summaries = list_source_profile_cohorts(
                database,
                reviewed_evidence,
                exemplars_per_profile=exemplars_per_profile,
                minimum_profiles=minimum_profiles,
            )
            table = Table(title="Eligible anonymous profile cohorts by source")
            table.add_column("Source", justify="right", no_wrap=True)
            table.add_column("Profiles", justify="right", no_wrap=True)
            table.add_column("Members", justify="right", no_wrap=True)
            table.add_column("Exemplars", justify="right", no_wrap=True)
            table.add_column("Max pairs", justify="right", no_wrap=True)
            table.add_column("Excluded", justify="right", no_wrap=True)
            table.add_column("Source reference", no_wrap=True)
            for summary in summaries:
                table.add_row(
                    str(summary.source_id),
                    str(summary.profile_count),
                    str(summary.member_count),
                    str(summary.exemplar_count),
                    str(summary.comparison_upper_bound),
                    str(summary.excluded_profile_count),
                    summary.source_reference,
                )
            console.print(table)
            console.print(
                f"Sources shown={len(summaries)}; minimum_profiles="
                f"{minimum_profiles}. Read-only inventory; source is retrieval "
                "context only."
            )
            return None
        policy_spec = load_shadow_policy(policy_path)
        assert source_id is not None
        candidates, excluded = source_profile_candidates(
            database,
            reviewed_evidence,
            source_id=source_id,
            exemplars_per_profile=exemplars_per_profile,
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise typer.BadParameter(str(error)) from error

    pair_upper_bound = sum(
        len(left.exemplar_observation_ids) * len(right.exemplar_observation_ids)
        for index, left in enumerate(candidates)
        for right in candidates[index + 1 :]
    )
    console.print(
        "Source-profile consolidation plan: "
        f"source={source_id} profiles={len(candidates)} "
        f"exemplars={sum(len(item.exemplar_observation_ids) for item in candidates)} "
        f"pair_comparison_upper_bound={pair_upper_bound} excluded={len(excluded)}."
    )
    for candidate in candidates:
        names = ",".join(candidate.normalized_names) or "anonymous"
        console.print(
            f"- profile {candidate.profile_id}: members="
            f"{len(candidate.member_observation_ids)} recordings="
            f"{candidate.recording_count} exemplars="
            f"{len(candidate.exemplar_observation_ids)} names={names}"
        )
    for profile_id, reason in excluded:
        console.print(f"- excluded profile {profile_id}: {reason}")
    if plan_only:
        console.print(
            "Plan only; source was used only to retrieve the cohort. No audio, "
            "acoustic comparisons, artifacts, or registry records were created."
        )
        return None
    if len(candidates) < 2:
        raise typer.BadParameter(
            "Fewer than two safe profiles with independent exemplars share this source."
        )

    cache_root = cache_dir.expanduser().resolve()
    verification_cache = MediaVerificationCache(
        cache_root,
        fallback_roots=(cache_root / "media-verification",),
    )
    try:
        backend = SherpaOnnxEmbeddingBackend(
            model_path.expanduser().resolve(),
            expected_sha256=model_sha256,
        )
    except (OSError, RuntimeError, ValueError) as error:
        raise typer.BadParameter(str(error)) from error
    span_cache = AudioSpanCache(cache_root)
    embedding_cache = EmbeddingCache(cache_root)
    pair_diagnostic_cache = PairDiagnosticCache(cache_root)
    activity_selection_cache = ActivityQualifiedSelectionCache(cache_root)

    signatures_by_observation_id = {}
    preparation_failures: list[tuple[int, str]] = []
    prepared_ids_by_profile: dict[int, tuple[int, ...]] = {}

    def prepare_observation(
        candidate,
        observation_id: int,
    ) -> bool:
        observation = database.get_speaker_observation(observation_id)
        if observation is None:
            preparation_failures.append((observation_id, "observation_missing"))
            return False
        eligibility = assess_automatic_speaker_observation(
            database,
            observation.video_id,
            observation_id=observation.id,
            verification_cache=verification_cache,
            verify_media=True,
        )
        media_was_verified = eligibility.eligible
        canonical_clips = ()
        if eligibility.reason_code == "archived_media_unavailable":
            # Archival finalization deliberately preserves immutable,
            # checksum-bound canonical clips. Prefer those cached acoustic
            # inputs over reopening a complete archived recording.
            cached_eligibility = assess_automatic_speaker_observation(
                database,
                observation.video_id,
                observation_id=observation.id,
                verify_media=False,
            )
            canonical_clips = (
                load_verified_canonical_clips(
                    cached_eligibility.media_artifact,
                    observation,
                )
                if cached_eligibility.eligible
                and cached_eligibility.media_artifact is not None
                else ()
            )
            if canonical_clips:
                eligibility = cached_eligibility
        if (
            not eligibility.eligible
            or eligibility.observation is None
            or eligibility.observation.id != observation.id
            or eligibility.media_artifact is None
        ):
            preparation_failures.append(
                (observation_id, eligibility.reason_code)
            )
            return False
        span_specs = eligibility.diagnostic_spans
        if not span_specs:
            preparation_failures.append(
                (observation_id, "diagnostic_spans_unavailable")
            )
            return False
        acoustic_candidate = DiscoveryCandidate(
            observation=observation,
            audio_path=Path(eligibility.media_artifact.artifact_path),
            source_id=source_id,
            normalized_names=candidate.normalized_names,
            span_specs=span_specs,
            activity_qualify_spans=True,
            normalized_audio_sha256=eligibility.media_artifact.content_sha256,
        )
        try:
            if media_was_verified:
                span_cache.remember_verified_source(
                    acoustic_candidate.audio_path,
                    eligibility.media_artifact.content_sha256,
                )
            if canonical_clips:
                signature = build_discovery_signature_from_canonical_clips(
                    acoustic_candidate,
                    canonical_clips,
                    embedding_cache=embedding_cache,
                    backend=backend,
                    policy=policy_spec.policy,
                )
            else:
                signature = build_discovery_signature(
                    acoustic_candidate,
                    span_cache=span_cache,
                    embedding_cache=embedding_cache,
                    backend=backend,
                    policy=policy_spec.policy,
                    activity_selection_cache=activity_selection_cache,
                )
        except (OSError, RuntimeError, ValueError) as error:
            preparation_failures.append(
                (observation_id, str(error) or type(error).__name__)
            )
            return False
        signatures_by_observation_id[observation_id] = signature
        return True

    for candidate in candidates:
        prepared_ids: list[int] = []
        prepared_video_ids: set[int] = set()
        observation_pool = tuple(
            dict.fromkeys(
                (*candidate.exemplar_observation_ids, *candidate.member_observation_ids)
            )
        )
        for observation_id in observation_pool:
            if len(prepared_ids) >= exemplars_per_profile:
                break
            observation = database.get_speaker_observation(observation_id)
            if observation is None or observation.video_id in prepared_video_ids:
                continue
            if prepare_observation(candidate, observation_id):
                prepared_ids.append(observation_id)
                prepared_video_ids.add(observation.video_id)
        prepared_ids_by_profile[candidate.profile_id] = tuple(prepared_ids)

    prepared_candidates = []
    failure_reason_by_observation_id = dict(preparation_failures)
    for candidate in candidates:
        prepared_ids = prepared_ids_by_profile[candidate.profile_id]
        if len(prepared_ids) < 2:
            failed_reasons: dict[str, list[int]] = {}
            attempted_ids = {
                observation_id
                for observation_id, _reason in preparation_failures
                if observation_id in candidate.member_observation_ids
            }
            for observation_id in sorted(attempted_ids):
                reason = failure_reason_by_observation_id.get(observation_id)
                if reason is not None:
                    failed_reasons.setdefault(reason, []).append(observation_id)
            reason_summary = "; ".join(
                f"{reason}={len(observation_ids)} "
                f"(observations {','.join(map(str, observation_ids))})"
                for reason, observation_ids in sorted(failed_reasons.items())
            )
            console.print(
                f"Excluded profile {candidate.profile_id}: fewer than two "
                "usable acoustic exemplars"
                f"{f'; {reason_summary}' if reason_summary else ''}."
            )
            continue
        prepared_candidates.append(
            replace(candidate, exemplar_observation_ids=prepared_ids)
        )
    if len(prepared_candidates) < 2:
        selected_observation_ids = {
            observation_id
            for candidate in candidates
            for observation_id in candidate.exemplar_observation_ids
        }
        archived_observation_ids = {
            observation_id
            for observation_id, reason in preparation_failures
            if reason == "archived_media_unavailable"
        }
        if archived_observation_ids == selected_observation_ids:
            destination = database.get_active_media_archive_destination()
            archive_root = (
                f" at {destination.archive_root}"
                if destination is not None
                else ""
            )
            status_command = (
                "pte media archive-status --base-dir "
                f"{shlex.quote(str(paths.root))}"
            )
            raise typer.BadParameter(
                "All selected observations remain valid, but their archived "
                f"normalized audio is unavailable{archive_root}. Reconnect the "
                "configured media archive, verify it with "
                f"`{status_command}`, then rerun this command."
            )
        raise typer.BadParameter(
            "Fewer than two profiles retained two usable acoustic exemplars; "
            "see the per-profile reason codes above."
        )

    comparison_pairs = [
        tuple(sorted((left_id, right_id)))
        for index, left in enumerate(prepared_candidates)
        for right in prepared_candidates[index + 1 :]
        for left_id in left.exemplar_observation_ids
        for right_id in right.exemplar_observation_ids
    ]

    def compare_pair(
        pair: tuple[int, int],
    ) -> tuple[tuple[int, int], Mapping[str, Any]]:
        left = signatures_by_observation_id[pair[0]]
        right = signatures_by_observation_id[pair[1]]
        result = analyze_observation_pair(
            observation_a=left.candidate.observation,
            observation_b=right.candidate.observation,
            audio_path_a=left.candidate.audio_path,
            audio_path_b=right.candidate.audio_path,
            span_cache=span_cache,
            embedding_cache=embedding_cache,
            backend=backend,
            policy=policy_spec.policy,
            span_specs_a=left.span_specs,
            span_specs_b=right.span_specs,
            span_specs_are_activity_qualified=True,
            prepared_spans_a=left.prepared_spans,
            prepared_spans_b=right.prepared_spans,
            pair_diagnostic_cache=pair_diagnostic_cache,
        )
        return pair, result

    comparisons: dict[tuple[int, int], Mapping[str, Any]] = {}
    if jobs == 1:
        for pair in comparison_pairs:
            key, result = compare_pair(pair)
            comparisons[key] = result
    else:
        with ThreadPoolExecutor(
            max_workers=min(jobs, len(comparison_pairs))
        ) as executor:
            for key, result in executor.map(compare_pair, comparison_pairs):
                comparisons[key] = result

    plan = build_source_profile_consolidation_plan(
        database,
        source_id=source_id,
        candidates=prepared_candidates,
        comparisons=comparisons,
    )
    plan = replace(
        plan,
        excluded_profiles=excluded,
    )
    payload = source_profile_consolidation_payload(
        plan,
        comparisons=comparisons,
        model_fingerprint=backend.spec.fingerprint,
        policy_fingerprint=policy_spec.artifact_sha256,
        preparation_failures=preparation_failures,
    )
    result_sha256 = str(payload["result_sha256"])
    artifact_path = write_source_profile_consolidation_artifact(
        output_root.expanduser().resolve()
        / result_sha256[:16]
        / f"{result_sha256}.json",
        payload,
    )
    console.print(
        f"Source-profile acoustic plan complete: comparisons={len(comparisons)} "
        f"proposals={len(plan.proposals)} cache_hits={pair_diagnostic_cache.hits} "
        f"cache_misses={pair_diagnostic_cache.misses}."
    )
    for index, proposal in enumerate(plan.proposals, start=1):
        packet_path = write_source_profile_consolidation_packet(
            database,
            proposal,
            artifact_path.with_name(f"proposal-{index}.html"),
        )
        console.print(
            f"MERGE PROPOSAL {index}: profiles "
            f"{','.join(str(value) for value in proposal.profile_ids)} would "
            "become one canonical profile after approval. "
            f"All {proposal.comparison_count} required comparisons passed; "
            "review the weakest observation pair "
            f"{proposal.weakest_observation_pair[0]}-"
            f"{proposal.weakest_observation_pair[1]}."
        )
        console.print(f"Review packet: {packet_path}")
        if not apply:
            continue
        if open_packet:
            webbrowser.open(packet_path.as_uri())
        if not typer.confirm(
            "Approve this complete-link cohort as one speaker?",
            default=False,
        ):
            console.print("Cohort deferred; no registry mutation was written.")
            continue
        conflicts: list[str] = []
        canonical_id = apply_source_profile_consolidation(
            database,
            plan=plan,
            proposal=proposal,
            reviewer=(reviewer or "").strip(),
            artifact_sha256=result_sha256,
            conflicts=conflicts,
        )
        if canonical_id is None:
            console.print(
                "Cohort was not merged: " + "; ".join(conflicts or ["unknown conflict"])
            )
        else:
            console.print(f"Merged cohort into canonical profile {canonical_id}.")
            refreshed_candidates, refreshed_excluded = source_profile_candidates(
                database,
                reviewed_evidence,
                source_id=source_id,
                exemplars_per_profile=exemplars_per_profile,
            )
            refreshed_ids = ",".join(
                str(item.profile_id) for item in refreshed_candidates
            ) or "none"
            console.print(
                f"POST-MERGE SOURCE STATE: source {source_id} now has "
                f"{len(refreshed_candidates)} eligible canonical profile(s): "
                f"{refreshed_ids}; excluded={len(refreshed_excluded)}."
            )
            if len(refreshed_candidates) >= 2:
                console.print(
                    "This source will remain in the default --list-sources "
                    "inventory because at least two eligible profiles remain."
                )
            else:
                console.print(
                    "This source will leave the default --list-sources "
                    "inventory; use --minimum-profiles 1 to display it."
                )
    console.print(f"Wrote source-profile consolidation artifact to {artifact_path}")
    if not apply:
        if plan.proposals:
            apply_command = shlex.join(
                [
                    "pte",
                    "identity",
                    "consolidate-source-profiles",
                    "--source-id",
                    str(source_id),
                    "--apply",
                    "--reviewer",
                    "REVIEWER_ID",
                    "--base-dir",
                    str(paths.root),
                ]
            )
            console.print(
                "NEXT ACTION: No merge has occurred. Run the following command "
                "to revalidate the proposal, open one weakest-edge review "
                "packet per cohort, and receive an approval prompt:"
            )
            console.print(apply_command)
            console.print(
                "Approve a prompt only when the two weakest-edge recordings "
                "contain the same principal speaker. Approval merges every "
                "profile listed in that proposal; deferral writes no registry "
                "mutation."
            )
        else:
            console.print(
                "NO MERGE ACTION: No proposal passed the complete-link policy. "
                "No registry mutations were made, and --apply has nothing to "
                "review."
            )
    elif not plan.proposals:
        console.print(
            "NO MERGE ACTION: Revalidation produced no proposals, so no "
            "approval prompts or registry mutations were created."
        )
    return artifact_path


@identity_app.command(
    "shadow-discover-profiles",
    help="Discover provisional anonymous profiles among unassigned observations.",
)
def shadow_discover_profiles_command(
    plan_only: bool = typer.Option(
        False,
        "--plan-only",
        help="Report candidate coverage without acoustic execution.",
    ),
    limit: int | None = typer.Option(
        None,
        min=1,
        help="Maximum eligible observations to include.",
    ),
    nearest_neighbors: int = typer.Option(
        8,
        min=2,
        help="Centroid-nearest observations nominated per candidate.",
    ),
    maximum_pairs: int | None = typer.Option(
        None,
        min=1,
        help="Optional global cap on nominated acoustic comparisons.",
    ),
    closure_candidates_per_same_pair: int = typer.Option(
        8,
        min=0,
        help=(
            "Likely third observations tested against both endpoints of each "
            "same-speaker seed pair."
        ),
    ),
    source_complete_link_limit: int = typer.Option(
        12,
        min=2,
        help=(
            "Source groups at or below this size receive complete pair "
            "retrieval coverage; source is never identity evidence."
        ),
    ),
    source_nearest_neighbors: int = typer.Option(
        4,
        min=1,
        help="Per-observation source-local quota for larger source groups.",
    ),
    borderline_deferred_minimum: float = typer.Option(
        0.50,
        min=0.0,
        max=1.0,
        help="Inclusive lower score for guarded deferred closure.",
    ),
    borderline_deferred_maximum: float = typer.Option(
        0.60,
        min=0.0,
        max=1.0,
        help="Exclusive upper score for guarded deferred closure.",
    ),
    borderline_deferred_candidates_per_same_pair: int = typer.Option(
        4,
        min=0,
        help=(
            "Borderline-deferred third candidates compared acoustically with "
            "both endpoints of a strong same-speaker seed."
        ),
    ),
    staged_review_candidates_per_component: int = typer.Option(
        2,
        min=0,
        help=(
            "Strong third candidates with two ambiguous seed edges retained "
            "per blocked component for staged blinded review."
        ),
    ),
    staged_review_maximum_same_boundary_distance: float = typer.Option(
        0.15,
        min=0.0,
        max=1.0,
        help=(
            "Maximum acoustic distance from the same-speaker boundary for "
            "a staged human-review candidate; this does not change pair "
            "decision thresholds."
        ),
    ),
    jobs: int = typer.Option(
        2,
        "--jobs",
        min=1,
        help="Concurrent acoustic pair-comparison jobs.",
    ),
    minimum_component_members: int = typer.Option(
        3,
        min=3,
        help="Distinct recordings required for a provisional profile proposal.",
    ),
    consistency_report: Path | None = typer.Option(
        None,
        help="Optional threshold-free observation-consistency report.",
    ),
    minimum_consistency_score: float | None = typer.Option(
        None,
        min=-1.0,
        max=1.0,
        help="Require a scored observation at or above this calibrated value.",
    ),
    consistency_policy: Path = typer.Option(
        Path(
            "evaluation/speaker-pairs/policies/"
            "observation-consistency-discovery-v1.json"
        ),
        help=(
            "Versioned policy that tiers freshly computed discovery "
            "consistency scores."
        ),
    ),
    include_deferred: bool = typer.Option(
        False,
        "--include-deferred",
        help=(
            "Deprecated unsafe diagnostic override; deferred observations now "
            "remain outside global discovery."
        ),
    ),
    model_path: Path = typer.Option(
        Path(
            "evaluation/speaker-pairs/models/"
            "3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx"
        ),
        help="Local ONNX speaker-embedding model.",
    ),
    model_sha256: str = typer.Option(
        DEFAULT_SPEAKER_MODEL_SHA256,
        help="Required checksum for the local model.",
    ),
    policy_path: Path = typer.Option(
        Path(
            "evaluation/speaker-pairs/policies/"
            "campplus-development-candidate-v1.json"
        ),
        help="Pinned approved or experimental shadow decision policy.",
    ),
    evaluation_root: Path = typer.Option(
        Path("evaluation/speaker-pairs"),
        help="Reviewed pair evidence used as explicit discovery constraints.",
    ),
    cache_dir: Path = typer.Option(
        Path("evaluation/speaker-pairs/cache"),
        help="Ignored exact-span, embedding, and media-verification cache.",
    ),
    output_root: Path = typer.Option(
        Path("evaluation/speaker-profile-discovery/shadow-runs"),
        help="Ignored versioned shadow profile-discovery artifacts.",
    ),
    base_dir: Path | None = typer.Option(
        None,
        help="Override app data directory.",
    ),
) -> Path | None:
    if include_deferred:
        raise typer.BadParameter(
            "--include-deferred is no longer supported; use the guarded "
            "borderline-deferred closure band instead"
        )
    if minimum_consistency_score is not None and consistency_report is None:
        raise typer.BadParameter(
            "--minimum-consistency-score requires --consistency-report"
        )
    paths = build_paths(base_dir)
    if not paths.database.exists():
        raise typer.BadParameter(
            f"Application database does not exist: {paths.database}"
        )
    database = Database(paths.database, readonly=True)
    cache_root = cache_dir.expanduser().resolve()
    verification_cache = MediaVerificationCache(
        cache_root,
        fallback_roots=(cache_root / "media-verification",),
    )
    try:
        policy_spec = load_shadow_policy(policy_path)
        consistency_policy_spec = load_discovery_consistency_policy(
            consistency_policy
        )
        if not (
            0.0
            <= borderline_deferred_minimum
            < borderline_deferred_maximum
            <= consistency_policy_spec.strong_minimum
        ):
            raise ValueError(
                "borderline deferred band must be ordered and cannot overlap "
                "the strong tier"
            )
        reviewed_evidence = load_reviewed_speaker_evidence(
            evaluation_root.expanduser().resolve()
        )
        consistency_index = (
            load_consistency_score_index(
                consistency_report.expanduser().resolve()
            )
            if consistency_report is not None
            else None
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise typer.BadParameter(str(error)) from error

    names_by_observation: dict[int, set[str]] = {}
    for claim in database.list_speaker_name_claims():
        if (
            claim.observation_id is not None
            and claim.explicit_speaker_attribution
            and claim.normalized_name.strip()
        ):
            names_by_observation.setdefault(claim.observation_id, set()).add(
                claim.normalized_name.strip()
            )

    candidates: list[DiscoveryCandidate] = []
    excluded_reasons: dict[str, int] = {}
    for video in database.list_videos():
        eligibility = assess_automatic_speaker_observation(
            database,
            video.id,
            verification_cache=verification_cache,
            verify_media=False,
        )
        if (
            not eligibility.eligible
            or eligibility.observation is None
            or eligibility.media_artifact is None
        ):
            reason = eligibility.reason_code
            excluded_reasons[reason] = excluded_reasons.get(reason, 0) + 1
            continue
        observation = eligibility.observation
        profile_exclusion = observation_profile_lineage_exclusion(
            database,
            video_id=video.id,
            observation_id=observation.id,
        )
        if profile_exclusion is not None:
            excluded_reasons[profile_exclusion] = (
                excluded_reasons.get(profile_exclusion, 0) + 1
            )
            continue
        review_action = database.get_effective_observation_review_action(
            observation.id
        )
        if review_action not in {None, "qualified_single_speaker"}:
            reason = f"reviewed_{review_action}"
            excluded_reasons[reason] = excluded_reasons.get(reason, 0) + 1
            continue
        extraction = database.get_latest_extraction_result_for_video(video.id)
        try:
            proposed_payload = (
                json.loads(
                    Path(extraction.proposed_json_path).read_text(
                        encoding="utf-8"
                    )
                )
                if extraction is not None and extraction.proposed_json_path
                else None
            )
        except (OSError, UnicodeError, json.JSONDecodeError):
            proposed_payload = None
        if not isinstance(proposed_payload, dict):
            excluded_reasons["speech_grounding_artifact_unavailable"] = (
                excluded_reasons.get(
                    "speech_grounding_artifact_unavailable", 0
                )
                + 1
            )
            continue
        span_specs = select_transcript_grounded_span_candidates(
            proposed_payload,
            observation,
        )
        if not span_specs:
            excluded_reasons["speech_grounded_spans_unavailable"] = (
                excluded_reasons.get(
                    "speech_grounded_spans_unavailable", 0
                )
                + 1
            )
            continue
        consistency_score = (
            consistency_index.scores.get(observation.input_fingerprint)
            if consistency_index is not None
            else None
        )
        if minimum_consistency_score is not None:
            if consistency_score is None:
                excluded_reasons["consistency_score_missing"] = (
                    excluded_reasons.get("consistency_score_missing", 0) + 1
                )
                continue
            if consistency_score < minimum_consistency_score:
                excluded_reasons["consistency_score_below_threshold"] = (
                    excluded_reasons.get(
                        "consistency_score_below_threshold", 0
                    )
                    + 1
                )
                continue
        verified_eligibility = assess_automatic_speaker_observation(
            database,
            video.id,
            verification_cache=verification_cache,
            verify_media=True,
        )
        if (
            not verified_eligibility.eligible
            or verified_eligibility.observation is None
            or verified_eligibility.media_artifact is None
            or verified_eligibility.observation.id != observation.id
        ):
            reason = verified_eligibility.reason_code
            excluded_reasons[reason] = excluded_reasons.get(reason, 0) + 1
            continue
        candidates.append(
            DiscoveryCandidate(
                observation=observation,
                audio_path=Path(
                    verified_eligibility.media_artifact.artifact_path
                ),
                source_id=video.source_id,
                normalized_names=tuple(
                    sorted(names_by_observation.get(observation.id, ()))
                ),
                consistency_score=consistency_score,
                span_specs=span_specs,
                activity_qualify_spans=True,
                normalized_audio_sha256=(
                    verified_eligibility.media_artifact.content_sha256
                ),
            )
        )
    candidates.sort(
        key=lambda item: item.observation.input_fingerprint
    )
    if limit is not None:
        candidates = candidates[:limit]

    estimated_global_pairs = min(
        len(candidates) * nearest_neighbors,
        len(candidates) * max(0, len(candidates) - 1) // 2,
    )
    if maximum_pairs is not None:
        estimated_global_pairs = min(estimated_global_pairs, maximum_pairs)
    candidate_counts_by_source: dict[int, int] = {}
    for candidate in candidates:
        candidate_counts_by_source[candidate.source_id] = (
            candidate_counts_by_source.get(candidate.source_id, 0) + 1
        )
    estimated_source_local_pairs = sum(
        (
            source_count * (source_count - 1) // 2
            if source_count <= source_complete_link_limit
            else min(
                source_count * (source_count - 1) // 2,
                source_count * source_nearest_neighbors,
            )
        )
        for source_count in candidate_counts_by_source.values()
        if source_count >= 2
    )
    console.print(
        "Profile discovery plan: "
        f"eligible_unassigned={len(candidates)} "
        f"excluded={sum(excluded_reasons.values())} "
        f"nearest_neighbors={nearest_neighbors} "
        f"estimated_global_pair_upper_bound={estimated_global_pairs} "
        f"estimated_source_local_pair_upper_bound="
        f"{estimated_source_local_pairs} "
        f"closure_candidates_per_same_pair="
        f"{closure_candidates_per_same_pair} "
        f"source_complete_link_limit={source_complete_link_limit} "
        f"source_nearest_neighbors={source_nearest_neighbors} "
        f"borderline_deferred_band=[{borderline_deferred_minimum:.2f},"
        f"{borderline_deferred_maximum:.2f}) "
        f"borderline_deferred_candidates_per_same_pair="
        f"{borderline_deferred_candidates_per_same_pair} "
        f"staged_review_candidates_per_component="
        f"{staged_review_candidates_per_component} "
        f"staged_review_maximum_same_boundary_distance="
        f"{staged_review_maximum_same_boundary_distance:.3f}"
    )
    console.print(
        "Consistency nomination: "
        f"policy={consistency_policy_spec.policy_version} "
        f"feature={consistency_policy_spec.feature} "
        f"strong_minimum={consistency_policy_spec.strong_minimum:.3f} "
        f"include_deferred={include_deferred} "
        f"status={consistency_policy_spec.review_status}"
    )
    if excluded_reasons:
        console.print(
            "Excluded reasons: "
            + ", ".join(
                f"{reason}={count}"
                for reason, count in sorted(excluded_reasons.items())
            )
        )
    if plan_only:
        console.print(
            "Plan only; no embeddings, comparisons, discovery artifacts, "
            "or registry mutations were created."
        )
        return
    if len(candidates) < minimum_component_members:
        raise typer.BadParameter(
            "Too few eligible observations for provisional profile discovery."
        )

    try:
        backend = SherpaOnnxEmbeddingBackend(
            model_path.expanduser().resolve(),
            expected_sha256=model_sha256,
        )
    except (OSError, RuntimeError, ValueError) as error:
        raise typer.BadParameter(str(error)) from error
    span_cache = AudioSpanCache(cache_root)
    embedding_cache = EmbeddingCache(cache_root)
    pair_diagnostic_cache = PairDiagnosticCache(cache_root)
    activity_selection_cache = ActivityQualifiedSelectionCache(cache_root)
    signatures = []
    signature_failures: list[dict[str, object]] = []
    for index, candidate in enumerate(candidates, start=1):
        try:
            if candidate.normalized_audio_sha256:
                span_cache.remember_verified_source(
                    candidate.audio_path,
                    candidate.normalized_audio_sha256,
                )
            signatures.append(
                build_discovery_signature(
                    candidate,
                    span_cache=span_cache,
                    embedding_cache=embedding_cache,
                    backend=backend,
                    policy=policy_spec.policy,
                    activity_selection_cache=activity_selection_cache,
                )
            )
        except (OSError, RuntimeError, ValueError) as error:
            reason = str(error) or type(error).__name__
            signature_failures.append(
                {
                    "observation_id": candidate.observation.id,
                    "video_id": candidate.observation.video_id,
                    "observation_fingerprint": (
                        candidate.observation.input_fingerprint
                    ),
                    "reason": reason,
                    "error_type": type(error).__name__,
                }
            )
        console.print(
            f"Signature {index}/{len(candidates)}: "
            f"{candidate.observation.input_fingerprint[:16]}"
        )
    console.print(
        "Discovery signature preparation: "
        f"selection_cache_hits={activity_selection_cache.hits} "
        f"selection_cache_misses={activity_selection_cache.misses} "
        f"selection_failure_hits={activity_selection_cache.failure_hits}."
    )
    if len(signatures) < minimum_component_members:
        raise typer.BadParameter(
            "Too few observations produced usable discovery signatures."
        )
    nominations = nominate_discovery_pairs(
        signatures,
        nearest_neighbors=nearest_neighbors,
        maximum_pairs=maximum_pairs,
        consistency_policy=consistency_policy_spec,
        include_deferred=include_deferred,
        source_complete_link_limit=source_complete_link_limit,
        source_nearest_neighbors=source_nearest_neighbors,
    )
    if not nominations:
        raise typer.BadParameter("No discovery pairs were nominated.")

    signatures_by_observation_id = {
        signature.candidate.observation.id: signature
        for signature in signatures
    }
    pair_index = 0
    pair_progress_lock = Lock()

    def compare(
        observation_a: SpeakerObservation,
        observation_b: SpeakerObservation,
        audio_path_a: Path,
        audio_path_b: Path,
    ) -> dict[str, object]:
        nonlocal pair_index
        with pair_progress_lock:
            pair_index += 1
            phase = (
                f"{pair_index}/{len(nominations)}"
                if pair_index <= len(nominations)
                else f"closure+{pair_index - len(nominations)}"
            )
            console.print(
                f"Pair {phase}: {observation_a.input_fingerprint[:8]}:"
                f"{observation_b.input_fingerprint[:8]}"
            )
        signature_a = signatures_by_observation_id[observation_a.id]
        signature_b = signatures_by_observation_id[observation_b.id]
        return analyze_observation_pair(
            observation_a=observation_a,
            observation_b=observation_b,
            audio_path_a=audio_path_a,
            audio_path_b=audio_path_b,
            span_cache=span_cache,
            embedding_cache=embedding_cache,
            backend=backend,
            policy=policy_spec.policy,
            span_specs_a=signature_a.span_specs,
            span_specs_b=signature_b.span_specs,
            span_specs_are_activity_qualified=True,
            pair_diagnostic_cache=pair_diagnostic_cache,
        )

    report = evaluate_shadow_profile_discovery(
        signatures=signatures,
        nominations=nominations,
        compare=compare,
        policy_spec=policy_spec,
        model_fingerprint=backend.spec.fingerprint,
        minimum_component_members=minimum_component_members,
        reviewed_same_pairs=tuple(
            sorted(
                _reviewed_observation_pairs(
                    database,
                    reviewed_evidence,
                    outcome="same_speaker",
                )
            )
        ),
        reviewed_difference_pairs=tuple(
            sorted(
                set(
                    database.list_effective_observation_difference_pairs()
                )
                | _reviewed_observation_pairs(
                    database,
                    reviewed_evidence,
                    outcome="different_speaker",
                )
            )
        ),
        consistency_report_sha256=(
            consistency_index.report_sha256
            if consistency_index is not None
            else None
        ),
        minimum_consistency_score=minimum_consistency_score,
        signature_failures=signature_failures,
        nearest_neighbors=nearest_neighbors,
        maximum_pairs=maximum_pairs,
        consistency_policy=consistency_policy_spec,
        include_deferred=include_deferred,
        closure_candidates_per_same_pair=closure_candidates_per_same_pair,
        source_complete_link_limit=source_complete_link_limit,
        source_nearest_neighbors=source_nearest_neighbors,
        borderline_deferred_minimum=borderline_deferred_minimum,
        borderline_deferred_maximum=borderline_deferred_maximum,
        borderline_deferred_candidates_per_same_pair=(
            borderline_deferred_candidates_per_same_pair
        ),
        staged_review_candidates_per_component=(
            staged_review_candidates_per_component
        ),
        staged_review_maximum_same_boundary_distance=(
            staged_review_maximum_same_boundary_distance
        ),
        jobs=jobs,
    )
    console.print(
        "Discovery pair diagnostics: "
        f"cache_hits={pair_diagnostic_cache.hits} "
        f"cache_misses={pair_diagnostic_cache.misses}."
    )
    destination = write_shadow_profile_discovery(output_root, report)
    counts = report["counts"]
    console.print(
        "Shadow profile discovery complete: "
        f"signatures={counts['eligible_signatures']} "
        f"strong={counts['strong_signatures']} "
        f"deferred={counts['deferred_signatures']} "
        f"signature_failures={counts['signature_failures']} "
        f"pairs={counts['nominated_pairs']} "
        f"global_pairs={counts['global_pairs']} "
        f"source_local_pairs={counts['source_local_pairs']} "
        f"closure_pairs={counts['closure_pairs']} "
        f"borderline_deferred_pairs={counts['borderline_deferred_pairs']} "
        f"strong_pairs={counts['strong_strong_pairs']} "
        f"deferred_pairs={counts['deferred_pairs']} "
        f"provisional_profiles="
        f"{counts['provisional_profile_candidates']} "
        f"blocked_components={counts['blocked_components']} "
        f"actionable_review_frontiers="
        f"{counts['blocked_components_with_actionable_review_frontier']} "
        f"immediate_review_pairs="
        f"{counts['immediate_actionable_review_frontier_pairs']} "
        f"staged_review_pairs="
        f"{counts['staged_actionable_review_frontier_pairs']} "
        f"staged_pairs_excluded_by_distance="
        f"{counts['staged_review_candidates_excluded_by_distance']} "
        f"distant_staged_components="
        f"{counts['blocked_components_with_only_distant_staged_candidates']}"
    )
    console.print(
        "Pair outcomes: "
        + ", ".join(
            f"{outcome}={count}"
            for outcome, count in report["pair_outcome_counts"].items()
        )
    )
    insufficient_reason_counts: dict[str, int] = {}
    for result in report["pair_results"]:
        if result.get("outcome") != "insufficient_evidence":
            continue
        reason = str(result.get("reason", "unknown"))
        insufficient_reason_counts[reason] = (
            insufficient_reason_counts.get(reason, 0) + 1
        )
    if insufficient_reason_counts:
        console.print(
            "Insufficient-evidence reasons: "
            + ", ".join(
                f"{reason}={count}"
                for reason, count in sorted(
                    insufficient_reason_counts.items()
                )
            )
        )
    exploratory_rankings = tuple(
        ranking
        for ranking in load_discovery_acoustic_ranking_pairs(destination)
        if ranking.outcome == "insufficient_evidence"
    )
    if exploratory_rankings:
        exploratory_observation_count = len(
            {
                fingerprint
                for ranking in exploratory_rankings
                for fingerprint in (
                    ranking.fingerprint_a,
                    ranking.fingerprint_b,
                )
            }
        )
        console.print(
            "Exploratory human-review nominations: "
            f"pairs={len(exploratory_rankings)} "
            f"observations={exploratory_observation_count}; "
            "acoustic outcomes remain insufficient_evidence."
        )
    if signature_failures:
        failure_counts: dict[str, int] = {}
        for failure in signature_failures:
            reason = str(failure["reason"])
            failure_counts[reason] = failure_counts.get(reason, 0) + 1
        console.print(
            "Signature failures: "
            + ", ".join(
                f"{reason}={count}"
                for reason, count in sorted(failure_counts.items())
            )
        )
    for component in report["components"]:
        if component["outcome"] != "provisional_profile_candidate":
            continue
        names = ",".join(component["normalized_names"]) or "anonymous"
        console.print(
            f"Provisional component {component['component_id'][:12]}: "
            f"members={component['member_count']} "
            f"recordings={component['recording_count']} "
            f"sources={component['source_count']} "
            f"names={names}"
        )
    console.print(f"Wrote shadow profile discovery to {destination}")
    console.print(
        f"Policy status={policy_spec.review_status}; registry mutations=0."
    )
    return destination


@identity_app.command(
    "promote-discovered-profiles",
    help="Promote verified discovery components into reversible provisional profiles.",
)
def promote_discovered_profiles_command(
    discovery_report: Path = typer.Option(
        ...,
        "--discovery-report",
        exists=True,
        dir_okay=False,
        readable=True,
        help="Completed shadow profile-discovery JSON artifact.",
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Create provisional profiles and attach their seed observations.",
    ),
    base_dir: Path | None = typer.Option(
        None,
        help="Override app data directory.",
    ),
) -> None:
    paths = build_paths(base_dir)
    if not paths.database.exists():
        raise typer.BadParameter(
            f"Application database does not exist: {paths.database}"
        )
    try:
        plan = plan_discovery_promotions(
            Database(paths.database, readonly=True),
            discovery_report,
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise typer.BadParameter(str(error)) from error
    console.print(
        "Discovery promotion plan: "
        f"eligible_components={len(plan.candidates)} "
        f"skipped={len(plan.skipped)}"
    )
    for candidate in plan.candidates:
        names = ",".join(candidate.normalized_names) or "anonymous"
        state = (
            f"existing_profile={candidate.existing_profile_id}"
            if candidate.existing_profile_id is not None
            else "new_provisional_profile"
        )
        console.print(
            f"Component {candidate.component_id[:12]}: "
            f"members={len(candidate.observation_ids)} "
            f"recordings={len(candidate.recording_ids)} "
            f"names={names} {state}"
        )
    for skipped in plan.skipped:
        console.print(
            f"Skipped {str(skipped['component_id'])[:12]}: "
            f"{skipped['reason']}"
        )
    if not apply:
        console.print(
            "Plan only; pass --apply to create reversible provisional profiles."
        )
        return
    database = Database(paths.database)
    database.initialize()
    try:
        profile_ids = apply_discovery_promotions(database, plan)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print(
        "Discovery promotion complete: "
        f"profiles={len(profile_ids)} ids="
        + (",".join(str(value) for value in profile_ids) or "none")
    )
    console.print(
        "Profiles are shadow-usable but remain automatic-blocked until an "
        "independent association is confirmed."
    )


@identity_app.command(
    "confirm-discovered-profiles",
    help="Attach independent proposed matches to provisional discovery profiles.",
)
def confirm_discovered_profiles_command(
    input_root: Path = typer.Option(
        Path("evaluation/speaker-associations/shadow-runs"),
        help="Versioned shadow-association artifact root.",
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Attach validated confirmations to their provisional profiles.",
    ),
    base_dir: Path | None = typer.Option(
        None,
        help="Override app data directory.",
    ),
) -> None:
    paths = build_paths(base_dir)
    if not paths.database.exists():
        raise typer.BadParameter(
            f"Application database does not exist: {paths.database}"
        )
    report_paths = sorted(
        input_root.expanduser().resolve().glob("*/*.json")
    )
    plan = plan_candidate_confirmations(
        Database(paths.database, readonly=True),
        report_paths,
    )
    console.print(
        "Candidate confirmation plan: "
        f"eligible_associations={len(plan.candidates)} "
        f"invalid_artifacts={len(plan.skipped)} "
        f"ignored={sum(plan.ignored_counts.values())}"
    )
    if plan.ignored_counts:
        console.print(
            "Ignored reasons: "
            + ", ".join(
                f"{reason}={count}"
                for reason, count in plan.ignored_counts.items()
            )
        )
    for candidate in plan.candidates:
        console.print(
            f"Profile {candidate.profile_id}: "
            f"observation={candidate.observation_id} "
            f"video={candidate.video_id} "
            f"artifact={candidate.report_path}"
        )
    if not apply:
        console.print(
            "Plan only; pass --apply to attach these independent recordings."
        )
        return
    database = Database(paths.database)
    database.initialize()
    try:
        event_ids = apply_candidate_confirmations(database, plan)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print(
        "Candidate confirmation complete: "
        f"confirmed={len(event_ids)}"
    )
    if event_ids:
        console.print(
            "Confirmed discovery profiles now satisfy the profile-level "
            "automatic readiness gate; model/policy approval remains separate."
        )
    else:
        console.print(
            "No discovery profile received an independent confirmation; "
            "profile readiness is unchanged."
        )




ACTIONABLE_REVIEW_PREWARM_VERSION = "actionable_review_prewarm_v2"


def _actionable_review_prewarm_path(cache_dir: Path) -> Path:
    return (
        cache_dir.expanduser().resolve()
        / "selector-context"
        / "actionable-review-prewarm-v2.json"
    )


def _load_actionable_review_prewarm(cache_dir: Path) -> tuple[str, ...]:
    path = _actionable_review_prewarm_path(cache_dir)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        fingerprints = payload["ready_fingerprints"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        return ()
    if (
        not isinstance(payload, dict)
        or payload.get("version") != ACTIONABLE_REVIEW_PREWARM_VERSION
        or not isinstance(fingerprints, list)
        or not all(
            isinstance(fingerprint, str) and fingerprint
            for fingerprint in fingerprints
        )
    ):
        return ()
    return tuple(dict.fromkeys(fingerprints))


def _write_actionable_review_prewarm(
    cache_dir: Path,
    fingerprints: Sequence[str],
) -> None:
    path = _actionable_review_prewarm_path(cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": ACTIONABLE_REVIEW_PREWARM_VERSION,
        "ready_fingerprints": list(dict.fromkeys(fingerprints)),
    }
    temporary = path.with_suffix(".json.partial")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _actionable_review_fingerprints(
    *,
    discovery_report: Path | None,
    association_reports: Sequence[Path],
    automatic_profile_ready_ids: frozenset[int] = frozenset(),
    association_progress_callback: Callable[[int, int, Path], None]
    | None = None,
    association_cache_path: Path | None = None,
) -> tuple[str, ...]:
    """Order observations by current human-review nomination value."""
    ordered: list[str] = []
    if association_reports:
        nominations = load_shadow_association_confirmation_pairs(
            association_reports,
            progress_callback=association_progress_callback,
            cache_path=association_cache_path,
        )
        for nomination in nominations:
            if nomination.profile_id in automatic_profile_ready_ids:
                continue
            ordered.extend(
                (
                    nomination.candidate_fingerprint,
                    nomination.exemplar_fingerprint,
                )
            )
    if discovery_report is not None:
        for nomination in load_discovery_resolution_pairs(discovery_report):
            ordered.extend(
                (nomination.fingerprint_a, nomination.fingerprint_b)
            )
        for nomination in load_discovery_acoustic_ranking_pairs(
            discovery_report
        ):
            ordered.extend(
                (nomination.fingerprint_a, nomination.fingerprint_b)
            )
    return tuple(dict.fromkeys(ordered))


def _prepare_actionable_review_audio(
    database: Database,
    paths: AppPaths,
    *,
    discovery_report: Path | None,
    association_reports: Sequence[Path],
    cache_dir: Path = Path("evaluation/speaker-pairs/cache"),
    limit: int = 24,
    automatic_profile_ready_ids: frozenset[int] = frozenset(),
    association_progress_callback: Callable[[int, int, Path], None]
    | None = None,
) -> ActionableReviewAudioPreparation:
    """Prewarm exact review clips for the current actionable frontier."""
    if limit < 1:
        raise ValueError("review audio prewarm limit must be positive")
    nominated_fingerprints = _actionable_review_fingerprints(
        discovery_report=discovery_report,
        association_reports=association_reports,
        automatic_profile_ready_ids=automatic_profile_ready_ids,
        association_progress_callback=association_progress_callback,
        association_cache_path=(
            cache_dir.expanduser().resolve()
            / "selector-context"
            / "association-nominations-v1.json"
        ),
    )
    fingerprints: list[str] = []
    preflight_rejection_counts: dict[str, int] = {}
    for fingerprint in nominated_fingerprints:
        observation = database.get_speaker_observation_by_fingerprint(
            fingerprint
        )
        video = (
            database.get_video_by_id(observation.video_id)
            if observation is not None
            else None
        )
        if observation is None or video is None:
            reason = "observation_or_video_unavailable"
            preflight_rejection_counts[reason] = (
                preflight_rejection_counts.get(reason, 0) + 1
            )
            continue
        eligibility = assess_automatic_speaker_observation(
            database,
            video.id,
            verify_media=False,
        )
        if (
            not eligibility.eligible
            or eligibility.observation is None
            or eligibility.observation.input_fingerprint != fingerprint
        ):
            reason = (
                getattr(eligibility, "reason_code", "ineligible")
                if not eligibility.eligible
                else "selected_observation_changed"
            )
            preflight_rejection_counts[reason] = (
                preflight_rejection_counts.get(reason, 0) + 1
            )
            continue
        if automatic_profile_ready_ids:
            direct_profile_ids = {
                database.resolve_speaker_profile_id(profile_id)
                for profile_id in (
                    database.list_effective_profile_ids_for_observation(
                        observation.id
                    )
                )
            }
            superseded_profile_ids = {
                database.resolve_speaker_profile_id(profile_id)
                for profile_id in (
                    database.list_effective_profile_ids_for_superseded_observations(
                        video_id=observation.video_id,
                        current_observation_id=observation.id,
                    )
                )
            }
            if (
                direct_profile_ids | superseded_profile_ids
            ) & automatic_profile_ready_ids:
                reason = "automatic_profile_ready_lineage"
                preflight_rejection_counts[reason] = (
                    preflight_rejection_counts.get(reason, 0) + 1
                )
                continue
        fingerprints.append(fingerprint)
        if len(fingerprints) == limit:
            break
    preflight_excluded = sum(preflight_rejection_counts.values())
    if preflight_rejection_counts:
        console.print(
            "Review prewarm preflight: "
            f"excluded={preflight_excluded} "
            + " ".join(
                f"{reason}={count}"
                for reason, count in sorted(
                    preflight_rejection_counts.items()
                )
            )
        )
    span_cache = AudioSpanCache(cache_dir.expanduser().resolve())
    verification_cache = MediaVerificationCache(
        cache_dir.expanduser().resolve()
    )
    prepared = 0
    already_cached = 0
    excluded = preflight_excluded
    failed = 0
    ready_fingerprints: list[str] = []
    for index, fingerprint in enumerate(fingerprints, start=1):
        observation = database.get_speaker_observation_by_fingerprint(
            fingerprint
        )
        video = (
            database.get_video_by_id(observation.video_id)
            if observation is not None
            else None
        )
        if observation is None or video is None:
            excluded += 1
            console.print(
                f"Review prewarm [{index}/{len(fingerprints)}] "
                f"{fingerprint[:12]}: excluded "
                "(observation_or_video_unavailable)"
            )
            continue
        console.print(
            f"Review prewarm [{index}/{len(fingerprints)}] "
            f"{video.youtube_video_id}: verifying current media"
        )
        eligibility = assess_automatic_speaker_observation(
            database,
            video.id,
            verification_cache=verification_cache,
            verify_media=True,
        )
        if (
            not eligibility.eligible
            or eligibility.observation is None
            or eligibility.media_artifact is None
            or eligibility.observation.input_fingerprint != fingerprint
        ):
            excluded += 1
            reason = (
                getattr(eligibility, "reason_code", "ineligible")
                if not eligibility.eligible
                else "selected_observation_changed"
            )
            console.print(
                f"Review prewarm [{index}/{len(fingerprints)}] "
                f"{video.youtube_video_id}: excluded ({reason})"
            )
            continue
        try:
            console.print(
                f"Review prewarm [{index}/{len(fingerprints)}] "
                f"{video.youtube_video_id}: preparing review clips"
            )
            result = prepare_review_observation(
                observation=observation,
                audio_path=Path(eligibility.media_artifact.artifact_path),
                span_cache=span_cache,
            )
            cache_hits = sum(span.cache_hit for span in result.spans)
            write_canonical_clip_preparation_manifest(
                paths,
                eligibility.media_artifact,
                observation,
                clip_paths=tuple(
                    Path(span.wav_path) for span in result.spans
                ),
            )
        except (
            ArchivedMediaUnavailableError,
            OSError,
            RuntimeError,
            ValueError,
            subprocess.SubprocessError,
        ) as error:
            failed += 1
            console.print(
                f"Review prewarm [{index}/{len(fingerprints)}] "
                f"{video.youtube_video_id}: failed "
                f"({type(error).__name__}: {error})"
            )
            continue
        if cache_hits == len(result.spans):
            already_cached += 1
            outcome = "cached"
        else:
            prepared += 1
            outcome = "prepared"
        ready_fingerprints.append(fingerprint)
        console.print(
            f"Review prewarm [{index}/{len(fingerprints)}] "
            f"{video.youtube_video_id}: {outcome} "
            f"({len(result.spans)} clips; cache_hits={cache_hits})"
        )
    _write_actionable_review_prewarm(cache_dir, ready_fingerprints)
    return ActionableReviewAudioPreparation(
        requested=len(fingerprints) + preflight_excluded,
        prepared=prepared,
        already_cached=already_cached,
        excluded=excluded,
        failed=failed,
        ready_fingerprints=tuple(ready_fingerprints),
    )


def _repair_exemplars_and_retry_association(
    *,
    pending_exemplar_repairs: Sequence[Any],
    current_association_reports: tuple[Path, ...],
    youtube_video_id: str | None,
    all_extractions: bool,
    paths: AppPaths,
    base_dir: Path | None,
    state_cache: ExemplarPreparationStateCache,
    jobs: int,
) -> tuple[Path, ...]:
    profile_ids = tuple(
        sorted({state.profile_id for state in pending_exemplar_repairs})
    )
    baseline: Path | None = None
    try:
        baseline = profile_leverage_snapshot_command(
            profile_id=list(profile_ids),
            decision_kind="exemplar_media_fix",
            baseline=None,
            profile_level_decisions=0,
            sermon_level_reviews=0,
            prospective_correct=0,
            prospective_incorrect=0,
            association_root=Path(
                "evaluation/speaker-associations/shadow-runs"
            ),
            output_root=Path("evaluation/identity-leverage"),
            base_dir=base_dir,
        )
    except (OSError, ValueError, typer.BadParameter) as error:
        console.print(
            "Exemplar repair leverage baseline was unavailable; repair "
            f"will continue without impact measurement: {error}"
        )
    repair_video_ids = {state.video_id for state in pending_exemplar_repairs}
    console.print(
        "Exemplar repair: running existing canonical preparation for "
        f"{len(repair_video_ids)} pending media blocker(s) across profile(s) "
        + ", ".join(str(value) for value in profile_ids)
        + "."
    )
    retry_association = False
    try:
        repair_result = prepare_canonical_audio(
            Database(paths.database),
            paths,
            cache_root=Path("evaluation/speaker-pairs/cache"),
            video_ids=repair_video_ids,
            all_eligible=False,
            dry_run=False,
        )
    except (OSError, RuntimeError, ValueError) as error:
        console.print(
            "Exemplar repair deferred after a transient preparation "
            f"failure: {type(error).__name__}: {error}"
        )
    else:
        repair_items_by_video_id = {
            item.video_id: item for item in repair_result.items
        }
        for state in pending_exemplar_repairs:
            item = repair_items_by_video_id.get(state.video_id)
            state_cache.record_repair_attempt(
                state,
                outcome=item.outcome if item is not None else "not_selected",
                detail=(
                    item.reason
                    if item is not None
                    else "no eligible repair input"
                ),
            )
        retry_association = bool(repair_result.counts.get("prepared"))
        console.print(
            "Exemplar repair outcomes: "
            + ", ".join(
                f"{outcome}={count}"
                for outcome, count in repair_result.counts.items()
                if count
            )
        )
    if retry_association:
        console.print(
            "Exemplar repair changed canonical inputs; retrying the existing "
            "association pass once in this identity run."
        )
        retried_reports = shadow_associate_speakers_command(
            youtube_video_id=youtube_video_id,
            all_eligible=all_extractions,
            unattempted_only=False,
            neighborhood_profile_id=[],
            include_profiled=False,
            limit=None,
            plan_only=False,
            minimum_profile_members=3,
            maximum_exemplars=3,
            minimum_same_exemplars=2,
            maximum_global_profiles=1,
            jobs=jobs,
            model_path=Path(
                "evaluation/speaker-pairs/models/"
                "3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx"
            ),
            model_sha256=DEFAULT_SPEAKER_MODEL_SHA256,
            policy_path=Path(
                "evaluation/speaker-pairs/policies/"
                "campplus-development-candidate-v1.json"
            ),
            evaluation_root=Path("evaluation/speaker-pairs"),
            cache_dir=Path("evaluation/speaker-pairs/cache"),
            output_root=Path(
                "evaluation/speaker-associations/shadow-runs"
            ),
            base_dir=base_dir,
        )
        if retried_reports:
            current_association_reports = retried_reports
    if baseline is not None:
        try:
            profile_leverage_snapshot_command(
                profile_id=list(profile_ids),
                decision_kind="exemplar_media_fix",
                baseline=baseline,
                profile_level_decisions=0,
                sermon_level_reviews=0,
                prospective_correct=0,
                prospective_incorrect=0,
                association_root=Path(
                    "evaluation/speaker-associations/shadow-runs"
                ),
                output_root=Path("evaluation/identity-leverage"),
                base_dir=base_dir,
            )
        except (OSError, ValueError, typer.BadParameter) as error:
            console.print(
                "Exemplar repair completed, but observed leverage could not "
                f"be recorded: {error}"
            )
    return current_association_reports


def _identity_stage_input_paths(
    database: Database,
    *,
    additional_paths: Sequence[Path],
) -> tuple[Path, ...]:
    paths = list(additional_paths)
    for video in database.list_videos():
        extraction = database.get_latest_extraction_result_for_video(video.id)
        if extraction is not None and extraction.proposed_json_path:
            paths.append(Path(extraction.proposed_json_path))
    return tuple(paths)


def _identity_stage_fingerprint_or_none(
    paths: AppPaths,
    database: Database,
    *,
    stage: str,
    parameters: Mapping[str, Any],
    additional_paths: Sequence[Path],
) -> str | None:
    try:
        return build_identity_stage_fingerprint(
            paths.database,
            stage=stage,
            parameters=parameters,
            input_paths=_identity_stage_input_paths(
                database,
                additional_paths=additional_paths,
            ),
        )
    except (OSError, UnicodeError, sqlite3.DatabaseError, ValueError) as error:
        console.print(
            f"Identity {stage} cache unavailable; running stage: "
            f"{type(error).__name__}: {error}"
        )
        return None


def _write_identity_stage_checkpoint_best_effort(
    root: Path,
    *,
    stage: str,
    input_fingerprint: str,
    outputs: Sequence[Path],
    input_state: Mapping[str, Any] | None = None,
) -> None:
    try:
        write_identity_stage_checkpoint(
            root,
            stage=stage,
            input_fingerprint=input_fingerprint,
            outputs=outputs,
            input_state=input_state,
        )
    except (OSError, UnicodeError, ValueError) as error:
        console.print(
            f"Identity {stage} cache could not be saved; future runs will "
            f"recompute the stage: {type(error).__name__}: {error}"
        )


def _association_input_state_or_none(
    paths: AppPaths,
    *,
    parameters: Mapping[str, Any],
    global_input_paths: Sequence[Path],
) -> Mapping[str, Any] | None:
    try:
        return build_association_input_state(
            paths.database,
            parameters=parameters,
            global_input_paths=global_input_paths,
        )
    except (OSError, UnicodeError, sqlite3.DatabaseError, ValueError) as error:
        console.print(
            "Association incremental cache unavailable; using full refresh: "
            f"{type(error).__name__}: {error}"
        )
        return None


def run_identity_workflow_service(
    *,
    youtube_video_id: str | None,
    all_extractions: bool,
    plan_only: bool,
    skip_discovery: bool,
    apply_automatic: bool,
    apply_confirmations: bool,
    apply_promotions: bool,
    apply_machine_canary: bool = False,
    machine_assignment_policy_path: Path | None = None,
    review_prewarm_limit: int = 24,
    base_dir: Path | None,
    jobs: int = 2,
) -> None:
    request = IdentityWorkflowRequest(
        youtube_video_id=youtube_video_id,
        all_extractions=all_extractions,
        plan_only=plan_only,
        skip_discovery=skip_discovery,
        apply_automatic=apply_automatic,
        apply_confirmations=apply_confirmations,
        apply_promotions=apply_promotions,
        apply_machine_canary=apply_machine_canary,
        machine_assignment_policy_path=machine_assignment_policy_path,
        review_prewarm_limit=review_prewarm_limit,
        base_dir=base_dir,
        jobs=jobs,
    )
    policy = validate_identity_workflow_request(request)
    effective_apply_confirmations = policy.apply_confirmations
    effective_apply_promotions = policy.apply_promotions
    effective_apply_machine = policy.apply_machine_assignments
    paths = build_paths(base_dir, remember=not plan_only)
    if not paths.database.exists():
        raise ValueError(f"Application database does not exist: {paths.database}")
    database = Database(paths.database, readonly=True)
    database_video_id = None
    if youtube_video_id is not None:
        video = database.get_video_by_youtube_id(youtube_video_id)
        if video is None:
            raise ValueError(f"Unknown YouTube video ID: {youtube_video_id}")
        database_video_id = video.id

    console.print(
        "[bold]Identity run[/bold] "
        f"scope={'all' if all_extractions else youtube_video_id} "
        f"mode={'plan' if plan_only else 'execute'} jobs={jobs}"
    )
    reviewed_stage = synchronize_reviewed_evidence_stage(
        paths.database,
        plan_only=plan_only,
    )
    reviewed_evidence = reviewed_stage.evidence
    _print_reviewed_evidence_summary(reviewed_evidence, reviewed_stage.sync)
    if plan_only:
        console.print(
            "Reviewed-evidence sync: plan-only; registry was not mutated."
        )
    if plan_only:
        console.print("Backfill: plan-only; no identity artifacts were written.")
    else:
        identity_backfill(video_id=database_video_id, base_dir=base_dir)

    machine_cache = MediaVerificationCache(
        Path("evaluation/speaker-pairs/cache/media-verification").resolve()
    )
    reconciliation = reconcile_machine_assignments_stage(
        paths.database,
        verification_cache=machine_cache,
        plan_only=plan_only,
    )
    if reconciliation is None:
        console.print(
            "Machine assignment reconciliation: plan-only; no events were written."
        )
    else:
        console.print(
            "Machine assignment reconciliation: "
            f"confirmed={reconciliation.confirmed} "
            f"revoked={reconciliation.revoked} "
            f"circuit_revoked={reconciliation.circuit_breaker_revoked} "
            f"unchanged={reconciliation.unchanged}."
        )

    identity_stage_cache_root = paths.logs / "identity-stage-cache"
    speaker_evaluation_root = Path("evaluation/speaker-pairs").resolve()
    association_policy_path = Path(
        "evaluation/speaker-pairs/policies/"
        "campplus-development-candidate-v1.json"
    ).resolve()
    reviewed_evidence_inputs = (
        speaker_evaluation_root / "drafts",
        speaker_evaluation_root / "reviews",
        speaker_evaluation_root / "fixtures",
        speaker_evaluation_root / "revocations",
    )
    association_parameters = {
        "association_version": SHADOW_ASSOCIATION_VERSION,
        "span_selection_version": TRANSCRIPT_GROUNDED_SPAN_SELECTION_VERSION,
        "scope": "all" if all_extractions else youtube_video_id,
        "minimum_profile_members": 3,
        "maximum_exemplars": 3,
        "minimum_same_exemplars": 2,
        "maximum_global_profiles": 1,
        "model_sha256": DEFAULT_SPEAKER_MODEL_SHA256,
    }
    association_global_inputs = (
        *reviewed_evidence_inputs,
        association_policy_path,
    )
    previous_association_input_state = (
        load_identity_stage_input_state(
            identity_stage_cache_root,
            stage="association",
        )
        if all_extractions and not plan_only
        else None
    )
    association_input_state = (
        _association_input_state_or_none(
            paths,
            parameters=association_parameters,
            global_input_paths=association_global_inputs,
        )
        if all_extractions and not plan_only
        else None
    )
    association_fingerprint = (
        _identity_stage_fingerprint_or_none(
            paths,
            Database(paths.database, readonly=True),
            stage="association",
            parameters=association_parameters,
            additional_paths=association_global_inputs,
        )
        if not plan_only
        else None
    )
    cached_association_reports = (
        load_identity_stage_checkpoint(
            identity_stage_cache_root,
            stage="association",
            input_fingerprint=association_fingerprint,
        )
        if association_fingerprint is not None
        else None
    )
    association_cache = decide_association_cache(
        cached_reports=cached_association_reports,
        previous_input_state=previous_association_input_state,
        current_input_state=association_input_state,
        all_extractions=all_extractions,
    )
    association_checkpoint_needs_refresh = (
        association_cache.checkpoint_needs_refresh
    )
    if association_cache.cached_reports is not None:
        console.print(
            "Association stage: unchanged inputs; reused completed stage "
            f"with {len(association_cache.cached_reports)} report(s)."
        )
    else:
        if association_cache.incremental:
            console.print(
                "Association stage: only new observation-local inputs changed; "
                "evaluating unattempted observations."
            )
        else:
            console.print(
                "Association stage: global or ambiguous inputs changed; "
                "running conservative full refresh."
            )
    current_association_reports = execute_association_stage(
        AssociationExecutionRequest(
            youtube_video_id=youtube_video_id,
            all_extractions=all_extractions,
            plan_only=plan_only,
            jobs=jobs,
            model_sha256=DEFAULT_SPEAKER_MODEL_SHA256,
            policy_path=association_policy_path,
            evaluation_root=speaker_evaluation_root,
            cache_dir=Path("evaluation/speaker-pairs/cache"),
            output_root=Path("evaluation/speaker-associations/shadow-runs"),
            base_dir=base_dir,
        ),
        association_cache,
        associator=shadow_associate_speakers_command,
    )
    exemplar_state_cache = ExemplarPreparationStateCache(
        Path("evaluation/speaker-pairs/cache").resolve()
    )
    pending_exemplar_repairs = select_pending_exemplar_repairs(
        exemplar_state_cache,
        database_video_id=database_video_id,
        plan_only=plan_only,
    )
    repair_stage = repair_association_stage(
        pending_repairs=pending_exemplar_repairs,
        current_reports=current_association_reports,
        youtube_video_id=youtube_video_id,
        all_extractions=all_extractions,
        paths=paths,
        base_dir=base_dir,
        state_cache=exemplar_state_cache,
        jobs=jobs,
        repairer=_repair_exemplars_and_retry_association,
    )
    current_association_reports = repair_stage.reports
    if repair_stage.checkpoint_needs_refresh:
        association_checkpoint_needs_refresh = True

    # Assignment planning is a projection of every current association result,
    # not merely the artifacts produced by this invocation. Superseded evidence
    # is explicitly revoked before the current proposal is planned.
    association_root = Path("evaluation/speaker-associations/shadow-runs")
    persisted_current_reports = latest_association_reports(association_root)
    if persisted_current_reports:
        current_association_reports = persisted_current_reports
    persist_association_checkpoint_stage(
        plan_only=plan_only,
        checkpoint_needs_refresh=association_checkpoint_needs_refresh,
        all_extractions=all_extractions,
        reports=current_association_reports,
        fingerprint_factory=lambda: _identity_stage_fingerprint_or_none(
            paths,
            Database(paths.database, readonly=True),
            stage="association",
            parameters=association_parameters,
            additional_paths=association_global_inputs,
        ),
        input_state_factory=lambda: (
            _association_input_state_or_none(
                paths,
                parameters=association_parameters,
                global_input_paths=association_global_inputs,
            )
        ),
        checkpoint_writer=lambda fingerprint, reports, input_state: (
            _write_identity_stage_checkpoint_best_effort(
                identity_stage_cache_root,
                stage="association",
                input_fingerprint=fingerprint,
                outputs=reports,
                input_state=input_state,
            )
        ),
    )
    current_result_sha256_by_observation = index_current_association_results(
        current_association_reports
    )
    current_reconciliation = reconcile_current_assignment_results_stage(
        paths.database,
        verification_cache=machine_cache,
        result_sha256_by_observation=current_result_sha256_by_observation,
        plan_only=plan_only,
    )
    if current_reconciliation is not None:
        console.print(
            "Current-result assignment reconciliation: "
            f"confirmed={current_reconciliation.confirmed} "
            f"revoked={current_reconciliation.revoked} "
            f"unchanged={current_reconciliation.unchanged}."
        )

    machine_stage = run_machine_assignment_stage(
        paths.database,
        reports=current_association_reports,
        reviewed_evidence=reviewed_evidence,
        policy_path=machine_assignment_policy_path
        or Path(
            "evaluation/speaker-associations/policies/"
            "machine-assignment-human-on-loop-v1.json"
        ),
        verification_cache=machine_cache,
        excluded_observation_fingerprints=(
            _held_out_speaker_fixture_fingerprints(
                Path("evaluation/speaker-pairs/fixtures").resolve()
            )
        ),
        database_video_id=database_video_id,
        plan_only=plan_only,
        activate_canary=effective_apply_machine,
    )
    machine_policy = machine_stage.policy
    machine_readiness = machine_stage.readiness
    machine_plan = machine_stage.plan
    console.print(
        "Machine assignment plan: "
        f"mode={machine_policy.mode} "
        f"eligible={len(machine_plan.candidates)} "
        f"skipped={sum(machine_plan.skipped_counts.values())} "
        f"tripped_policies={len(machine_plan.tripped_policy_fingerprints)}."
    )
    if machine_plan.skipped_counts:
        console.print(
            "Machine assignment skips: "
            + ", ".join(
                f"{reason}={count}"
                for reason, count in machine_plan.skipped_counts.items()
            )
        )
    if machine_stage.applied is None:
        console.print(
            "Machine assignment evidence: plan-only; no ledger rows or "
            "provisional assignments were written."
        )
    else:
        machine_apply = machine_stage.applied
        console.print(
            "Machine assignment evidence: "
            f"recorded={machine_apply.evidence_recorded} "
            f"reused={machine_apply.evidence_reused} "
            f"activated={machine_apply.assignments_activated} "
            f"blocked={machine_apply.activation_blocked}."
        )

    confirm_discovered_profiles_command(
        input_root=Path("evaluation/speaker-associations/shadow-runs"),
        apply=effective_apply_confirmations and not plan_only,
        base_dir=base_dir,
    )

    discovery_root = Path(
        "evaluation/speaker-profile-discovery/shadow-runs"
    )
    discovery_parameters = {
        "discovery_version": SHADOW_PROFILE_DISCOVERY_VERSION,
        "span_selection_version": TRANSCRIPT_GROUNDED_SPAN_SELECTION_VERSION,
        "scope": "all",
        "nearest_neighbors": 8,
        "maximum_pairs": None,
        "closure_candidates_per_same_pair": 8,
        "source_complete_link_limit": 12,
        "source_nearest_neighbors": 4,
        "borderline_deferred_minimum": 0.50,
        "borderline_deferred_maximum": 0.60,
        "borderline_deferred_candidates_per_same_pair": 4,
        "staged_review_candidates_per_component": 2,
        "staged_review_maximum_same_boundary_distance": 0.15,
        "minimum_component_members": 3,
        "model_sha256": DEFAULT_SPEAKER_MODEL_SHA256,
    }
    consistency_policy_path = Path(
        "evaluation/speaker-pairs/policies/"
        "observation-consistency-discovery-v1.json"
    ).resolve()
    discovery_fingerprint = None
    cached_discovery_reports = None
    generated_discovery_report = None
    if all_extractions and not skip_discovery and not plan_only:
        discovery_fingerprint = _identity_stage_fingerprint_or_none(
            paths,
            Database(paths.database, readonly=True),
            stage="discovery",
            parameters=discovery_parameters,
            additional_paths=(
                *reviewed_evidence_inputs,
                association_policy_path,
                consistency_policy_path,
            ),
        )
        if discovery_fingerprint is not None:
            cached_discovery_reports = load_identity_stage_checkpoint(
                identity_stage_cache_root,
                stage="discovery",
                input_fingerprint=discovery_fingerprint,
            )
    discovery_decision = decide_discovery_execution(
        all_extractions=all_extractions,
        skip_discovery=skip_discovery,
        cached_reports=cached_discovery_reports,
    )
    if discovery_decision.mode in {"cached", "execute"}:
        if discovery_decision.mode == "cached":
            console.print(
                "Discovery stage: unchanged inputs; reused completed stage "
                f"with {len(discovery_decision.cached_reports or ())} report(s)."
            )
    elif discovery_decision.mode == "skipped":
        console.print("Discovery: skipped by --skip-discovery.")
    else:
        console.print("Discovery: deferred to a corpus-wide identity run.")

    generated_discovery_report = execute_discovery_stage(
        DiscoveryExecutionRequest(
            plan_only=plan_only,
            jobs=jobs,
            model_sha256=DEFAULT_SPEAKER_MODEL_SHA256,
            consistency_policy_path=consistency_policy_path,
            association_policy_path=association_policy_path,
            evaluation_root=speaker_evaluation_root,
            cache_dir=Path("evaluation/speaker-pairs/cache"),
            output_root=discovery_root,
            base_dir=base_dir,
        ),
        discovery_decision,
        discoverer=shadow_discover_profiles_command,
    )

    discovery_selection = select_discovery_reports(
        cached_reports=cached_discovery_reports,
        generated_report=(
            generated_discovery_report
            if isinstance(generated_discovery_report, Path)
            else None
        ),
        discovery_root=discovery_root,
    )
    latest_discovery = discovery_selection.latest
    discovery_finalization = finalize_discovery_stage(
        decision=discovery_decision,
        plan_only=plan_only,
        fingerprint=discovery_fingerprint,
        latest_report=latest_discovery,
        apply_promotions=effective_apply_promotions,
        checkpoint_writer=lambda fingerprint, outputs: (
            _write_identity_stage_checkpoint_best_effort(
                identity_stage_cache_root,
                stage="discovery",
                input_fingerprint=fingerprint,
                outputs=outputs,
            )
        ),
        promoter=lambda report, apply: promote_discovered_profiles_command(
            discovery_report=report,
            apply=apply,
            base_dir=base_dir,
        ),
    )
    if discovery_decision.mode != "deferred" and not discovery_finalization.promotion_attempted:
        console.print("Discovery promotion: no completed report available.")

    metadata_stage = run_metadata_attribution_stage(
        paths.database,
        output_root=paths.logs / "profile-metadata-attribution",
        plan_only=plan_only,
        database_video_id=database_video_id,
        progress_callback=(
            lambda index, total, profile_id, outcome: console.print(
                "Profile metadata attribution "
                f"[{index}/{total}] profile={profile_id}: {outcome}"
            )
        ),
    )
    if metadata_stage.status == "plan_only":
        console.print(
            "Profile metadata attribution: plan-only; "
            f"eligible={len(metadata_stage.candidate_profile_ids)}; "
            "no Ollama calls or artifacts were created."
        )
    elif metadata_stage.status == "disabled":
        console.print(
            "Profile metadata attribution: skipped — local LLM is disabled."
        )
    elif metadata_stage.status == "empty":
        console.print("Profile metadata attribution: eligible=0; no Ollama calls.")
    elif metadata_stage.status == "failed":
        console.print(
            "Profile metadata attribution: skipped — "
            f"{metadata_stage.error}"
        )
    else:
        metadata_run = metadata_stage.run
        if metadata_run is None:
            raise RuntimeError("Executed metadata stage returned no result.")
        console.print(
            "Profile metadata attribution: "
            f"eligible={metadata_run.eligible} "
            f"proposed={metadata_run.proposed} "
            f"insufficient_evidence={metadata_run.insufficient_evidence} "
            f"conflicting_evidence={metadata_run.conflicting_evidence} "
            f"invalid_metadata={metadata_run.invalid_metadata} "
            f"cache_hits={metadata_run.cache_hits} "
            f"model_calls={metadata_run.model_calls} "
            f"failed={metadata_run.failed}."
        )
        _print_profile_metadata_proposals(metadata_run)
        if metadata_run.failed:
            console.print(
                "Profile metadata diagnostics were persisted. "
                "Inspect them with `pte identity "
                "analyze-profile-metadata --all --details "
                f"--base-dir {paths.root}`."
            )
    run_coordination_stage(
        CoordinationStageRequest(
            youtube_video_id=youtube_video_id,
            all_extractions=all_extractions,
            discovery_report=latest_discovery,
            discovery_root=discovery_root,
            model_sha256=DEFAULT_SPEAKER_MODEL_SHA256,
            base_dir=base_dir,
        ),
        coordinator=coordinate_identity_command,
    )
    prewarm_stage = run_review_prewarm_stage(
        paths.database,
        paths,
        plan_only=plan_only,
        all_extractions=all_extractions,
        limit=review_prewarm_limit,
        discovery_report=latest_discovery,
        association_reports=current_association_reports,
        automatic_profile_ready_ids=frozenset(
            item.profile_id
            for item in machine_readiness
            if item.automatic_profile_ready
        ),
        prewarmer=_prepare_actionable_review_audio,
    )
    if prewarm_stage.status == "plan_only":
        console.print(
            "Review audio prewarm: plan-only; actionable review clips were "
            "not prepared."
        )
    elif prewarm_stage.status == "deferred":
        console.print(
            "Review audio prewarm: deferred to a corpus-wide identity run."
        )
    elif prewarm_stage.status == "disabled":
        console.print("Review audio prewarm: disabled by limit=0.")
    elif prewarm_stage.status == "failed":
        console.print(f"Review audio prewarm: skipped — {prewarm_stage.error}")
    else:
        review_preparation = prewarm_stage.preparation
        if review_preparation is None:
            raise RuntimeError("Executed prewarm stage returned no result.")
        console.print(
            "Review audio prewarm: "
            f"requested={review_preparation.requested} "
            f"prepared={review_preparation.prepared} "
            f"cached={review_preparation.already_cached} "
            f"excluded={review_preparation.excluded} "
            f"failed={review_preparation.failed}."
        )
    if plan_only:
        console.print(
            "Normalized archive: plan-only; canonical manifests and media were not changed."
        )
    elif isinstance(paths, AppPaths):
        _archive_normalized_after_identity(
            Database(paths.database),
            paths,
            video_ids=(
                {database_video_id} if database_video_id is not None else None
            ),
            all_eligible=all_extractions,
        )
    console.print(
        "Identity run complete. Human pair review, attribution, conflict "
        "adjudication, and policy changes remain explicit."
    )


def _invoke_identity_workflow_request(request: IdentityWorkflowRequest) -> None:
    run_identity_workflow_service(
        youtube_video_id=request.youtube_video_id,
        all_extractions=request.all_extractions,
        plan_only=request.plan_only,
        skip_discovery=request.skip_discovery,
        apply_automatic=request.apply_automatic,
        apply_confirmations=request.apply_confirmations,
        apply_promotions=request.apply_promotions,
        apply_machine_canary=request.apply_machine_canary,
        machine_assignment_policy_path=request.machine_assignment_policy_path,
        review_prewarm_limit=request.review_prewarm_limit,
        base_dir=request.base_dir,
        jobs=request.jobs,
    )


def _archive_normalized_after_identity(
    database: Database,
    paths: AppPaths,
    *,
    video_ids: set[int] | None,
    all_eligible: bool,
) -> None:
    def report_preparation(event: CanonicalAudioPreparationProgressEvent) -> None:
        if event.stage == "complete":
            console.print(
                f"Identity canonical audio [{event.index}/{event.total}] "
                f"{event.youtube_video_id}: {event.outcome} — {event.detail}",
                markup=False,
            )
        elif event.stage == "preparing_clips":
            console.print(
                f"Identity canonical audio [{event.index}/{event.total}] "
                f"{event.youtube_video_id}: preparing clips",
                markup=False,
            )

    preparation = prepare_canonical_audio(
        database,
        paths,
        cache_root=Path("evaluation/speaker-pairs/cache"),
        video_ids=video_ids,
        all_eligible=all_eligible,
        wait_for_lock=True,
        progress_callback=report_preparation,
    )
    preparation_counts = preparation.counts
    if not all_eligible and len(video_ids or ()) == 1:
        deferred = next(
            (item for item in preparation.items if item.outcome == "deferred"),
            None,
        )
        if deferred is not None:
            retry = (
                "pte media prepare-canonical-audio "
                f"--youtube-video-id {deferred.youtube_video_id} "
                f"--base-dir {shlex.quote(str(paths.root))}"
            )
            raise ValueError(
                f"archived_media_unavailable for {deferred.youtube_video_id}. "
                f"Retry: {retry}"
            )
    destination = database.get_active_media_archive_destination()
    if destination is None:
        console.print(
            "Normalized archive skipped: no archive destination is configured; "
            "canonical audio preparation completed."
        )
        return

    with Progress(
        TextColumn("{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task_id = progress.add_task(
            "Evaluating normalized-audio eligibility", total=None
        )

        def report_preflight(event: ArchivePreflightEvent) -> None:
            progress.console.print(
                f"Identity archive preflight {event.check}: "
                f"{event.status} — {event.detail}",
                markup=False,
            )

        def report_progress(event: ArchiveProgressEvent) -> None:
            if event.stage == "complete":
                detail = f" ({event.detail})" if event.detail else ""
                progress.console.print(
                    f"Identity archive [{event.index}/{event.total}] normalized "
                    f"artifact #{event.media_artifact_id}: {event.outcome} -> "
                    f"{event.archive_path}{detail}",
                    markup=False,
                )
                progress.update(
                    task_id,
                    total=event.total,
                    completed=event.index,
                    description=(
                        f"Identity normalized archive "
                        f"({event.index}/{event.total})"
                    ),
                )
                return
            progress.update(
                task_id,
                total=event.total,
                completed=event.index - 1,
                description=(
                    f"Identity archive [{event.index}/{event.total}] "
                    f"{event.source_path.name}: {event.stage}"
                ),
            )

        archive = archive_normalized_media(
            database,
            paths,
            video_ids=video_ids,
            all_eligible=all_eligible,
            wait_for_lock=True,
            progress_callback=report_progress,
            preflight_callback=report_preflight,
        )
    counts = archive.counts
    blocked = sum(not item.eligible for item in archive.eligibility)
    deferred = counts["destination_unavailable"]
    console.print(
        "Identity normalized archive: "
        f"canonical_prepared={preparation_counts['prepared']}; "
        f"canonical_current={preparation_counts['already_prepared']}; "
        f"canonical_deferred={preparation_counts['deferred']}; "
        f"canonical_blocked={preparation_counts['blocked']}; "
        f"canonical_failed={preparation_counts['failed']}; "
        f"eligible={archive.eligible}; "
        f"archived={counts['archived']}; "
        f"already_archived={counts['already_archived']}; deferred={deferred}; "
        f"failed={counts['failed']}; blocked={blocked}."
    )


@identity_app.command(
    "profile-leverage-snapshot",
    help=(
        "Persist an observed before/after profile-state experiment without "
        "changing membership."
    ),
)
def profile_leverage_snapshot_command(
    profile_id: list[int] = typer.Option(
        ...,
        "--profile-id",
        min=1,
        help="Affected profile id; repeat for a duplicate-profile group.",
    ),
    decision_kind: str = typer.Option(
        ...,
        "--decision-kind",
        help=(
            "duplicate_profile_cleanup, readiness_promotion, "
            "exemplar_media_fix, prospective_confirmation, or sermon_review."
        ),
    ),
    baseline: Path | None = typer.Option(
        None,
        "--baseline",
        help="Prior snapshot to compare after the decision and neighborhood replay.",
    ),
    profile_level_decisions: int = typer.Option(0, min=0),
    sermon_level_reviews: int = typer.Option(0, min=0),
    prospective_correct: int = typer.Option(0, min=0),
    prospective_incorrect: int = typer.Option(0, min=0),
    association_root: Path = typer.Option(
        Path("evaluation/speaker-associations/shadow-runs"),
        help="Existing shadow-association artifacts.",
    ),
    output_root: Path = typer.Option(
        Path("evaluation/identity-leverage"),
        help="Ignored profile-leverage experiment artifacts.",
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> Path:
    paths = build_paths(base_dir)
    if not paths.database.exists():
        raise typer.BadParameter(
            f"Application database does not exist: {paths.database}"
        )
    database = Database(paths.database, readonly=True)
    try:
        snapshot = build_profile_leverage_snapshot(
            database,
            association_root=association_root,
            profile_ids=profile_id,
            decision_kind=decision_kind,
            profile_level_decisions=profile_level_decisions,
            sermon_level_reviews=sermon_level_reviews,
            prospective_correct=prospective_correct,
            prospective_incorrect=prospective_incorrect,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    run_id = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    experiment_slug = (
        decision_kind.replace("_", "-")
        + "-profiles-"
        + "-".join(str(value) for value in sorted(set(profile_id)))
    )
    destination_root = output_root.expanduser().resolve() / run_id / experiment_slug
    suffix = 1
    while destination_root.exists():
        destination_root = (
            output_root.expanduser().resolve()
            / f"{run_id}-{suffix:02d}"
            / experiment_slug
        )
        suffix += 1
    destination_root.mkdir(parents=True, exist_ok=True)
    snapshot_path = destination_root / "profile-leverage-snapshot.json"
    snapshot_path.write_text(
        json.dumps(snapshot, indent=2, sort_keys=True), encoding="utf-8"
    )
    console.print(f"Wrote profile leverage snapshot to {snapshot_path}")
    console.print(
        "Affected neighborhood: "
        f"{snapshot['state']['neighborhood_observation_count']} observation(s)."
    )
    if baseline is not None:
        try:
            before = json.loads(
                baseline.expanduser().resolve().read_text(encoding="utf-8")
            )
            result = compare_profile_leverage_snapshots(before, snapshot)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
            raise typer.BadParameter(str(error)) from error
        result_path = destination_root / "profile-leverage-result.json"
        result_path.write_text(
            json.dumps(result, indent=2, sort_keys=True), encoding="utf-8"
        )
        observed = result["observed"]
        console.print(
            "Observed leverage: "
            f"resolved={observed['newly_resolved_sermon_count']} "
            f"proposals_enabled={observed['downstream_proposals_enabled']} "
            "("
            f"new={len(observed.get('new_proposal_observation_ids', []))} "
            "made_actionable="
            f"{observed.get('proposals_made_actionable', 0)}"
            ") "
            f"abstentions_eliminated={observed['abstentions_eliminated']} "
            "exemplar_repairs="
            f"{observed['unresolved_cases_repaired_through_exemplar_media_fixes']}"
        )
        console.print(f"Wrote observed leverage result to {result_path}")
    return snapshot_path


def _review_leverage_context(
    manifest: Mapping[str, Any],
) -> tuple[tuple[int, ...], str] | None:
    objective = manifest.get("selection_objective")
    if objective in {
        "shadow_association_confirmation",
        "shadow_association_prospective_confirmation",
        "machine_assignment_validation",
    }:
        association = manifest.get("shadow_association_confirmation")
        if not isinstance(association, Mapping):
            return None
        profile_id = association.get("profile_id")
        if not isinstance(profile_id, int):
            return None
        decision_kind = (
            "prospective_confirmation"
            if objective
            in {
                "shadow_association_prospective_confirmation",
                "machine_assignment_validation",
            }
            else "readiness_promotion"
        )
        return (profile_id,), decision_kind
    if objective == "attribution_reconciliation_bridge":
        consolidation = manifest.get("profile_consolidation")
        profile_ids = (
            consolidation.get("profile_ids")
            if isinstance(consolidation, Mapping)
            else None
        )
        if (
            not isinstance(profile_ids, list)
            or len(profile_ids) < 2
            or not all(isinstance(value, int) and value > 0 for value in profile_ids)
        ):
            return None
        return tuple(sorted(set(profile_ids))), "duplicate_profile_cleanup"
    if objective == "profile_reinforcement":
        reinforcement = manifest.get("profile_reinforcement")
        profile_ids = (
            reinforcement.get("profile_ids")
            if isinstance(reinforcement, Mapping)
            else None
        )
        if (
            not isinstance(profile_ids, list)
            or len(profile_ids) != 1
            or not isinstance(profile_ids[0], int)
        ):
            return None
        return (profile_ids[0],), "readiness_promotion"
    return None


def _machine_safety_for_profiles(
    report: Mapping[str, Any],
    profile_ids: Sequence[int],
) -> dict[str, Any]:
    requested = set(profile_ids)
    assignments = [
        assignment
        for assignment in report.get("assignments", ())
        if isinstance(assignment, Mapping)
        and (
            assignment.get("profile_id") in requested
            or assignment.get("original_profile_id") in requested
        )
    ]
    state_counts: dict[str, int] = {}
    for assignment in assignments:
        state = str(assignment.get("state") or "unknown")
        state_counts[state] = state_counts.get(state, 0) + 1
    policy_fingerprints = sorted(
        {
            str(assignment["policy_fingerprint"])
            for assignment in assignments
            if assignment.get("policy_fingerprint")
        }
    )
    tripped = sorted(
        set(policy_fingerprints)
        & {
            str(value)
            for value in report.get("tripped_policy_fingerprints", ())
        }
    )
    policy_trips = [
        {
            "profile_id": trip.get("profile_id"),
            "youtube_video_id": trip.get("youtube_video_id"),
            "reason": trip.get("reason"),
            "policy_fingerprint": trip.get("policy_fingerprint"),
        }
        for trip in report.get("policy_trips", ())
        if isinstance(trip, Mapping)
        and (
            trip.get("profile_id") in requested
            or trip.get("policy_fingerprint") in tripped
        )
    ]
    return {
        "assignment_state_counts": dict(sorted(state_counts.items())),
        "policy_fingerprints": policy_fingerprints,
        "tripped_policy_fingerprints": tripped,
        "policy_trips": policy_trips,
        "machine_policy_mutation_allowed": False,
        "circuit_breaker_preserved": True,
    }


def _review_leverage_human_counts(
    decision_kind: str,
    pair_judgment: object,
) -> tuple[int, int, int, int]:
    profile_level_decisions = int(
        decision_kind
        in {"readiness_promotion", "duplicate_profile_cleanup"}
    )
    sermon_level_reviews = int(decision_kind == "prospective_confirmation")
    prospective_correct = int(
        decision_kind == "prospective_confirmation"
        and pair_judgment == PairJudgment.SAME_SPEAKER
    )
    prospective_incorrect = int(
        decision_kind == "prospective_confirmation"
        and pair_judgment == PairJudgment.DIFFERENT_SPEAKER
    )
    return (
        profile_level_decisions,
        sermon_level_reviews,
        prospective_correct,
        prospective_incorrect,
    )


def _replay_profile_association_neighborhood(
    profile_ids: Sequence[int],
    *,
    evaluation_root: Path,
    cache_dir: Path,
    association_root: Path,
    base_dir: Path | None,
) -> tuple[Path, ...]:
    """Run the existing bounded association workflow after identity review."""
    requested_profile_ids = sorted(set(profile_ids))
    if not requested_profile_ids:
        raise ValueError("profile neighborhood replay requires a profile id")
    return shadow_associate_speakers_command(
        youtube_video_id=None,
        all_eligible=False,
        unattempted_only=False,
        neighborhood_profile_id=requested_profile_ids,
        include_profiled=False,
        limit=None,
        plan_only=False,
        minimum_profile_members=3,
        maximum_exemplars=3,
        minimum_same_exemplars=2,
        maximum_global_profiles=1,
        jobs=2,
        model_path=Path(
            "evaluation/speaker-pairs/models/"
            "3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx"
        ),
        model_sha256=DEFAULT_SPEAKER_MODEL_SHA256,
        policy_path=Path(
            "evaluation/speaker-pairs/policies/"
            "campplus-development-candidate-v1.json"
        ),
        evaluation_root=evaluation_root,
        cache_dir=cache_dir,
        output_root=association_root,
        base_dir=base_dir,
    )


def _path_state(path_value: str | None) -> dict[str, Any]:
    if not path_value:
        return {"path": path_value, "exists": False}
    path = Path(path_value).expanduser().resolve()
    try:
        stat = path.stat()
    except OSError:
        return {"path": str(path), "exists": False}
    return {
        "path": str(path),
        "exists": True,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def _exemplar_preparation_evidence(
    database: Database,
    *,
    profile_id: int,
    observation: SpeakerObservation,
    assessed_observation: SpeakerObservation | None,
    media_artifact: Any | None,
    model_fingerprint: str | None,
    policy_artifact_sha256: str,
) -> dict[str, Any]:
    extraction = database.get_latest_extraction_result_for_video(
        observation.video_id
    )
    return {
        "profile_id": profile_id,
        "observation_id": observation.id,
        "observation_fingerprint": observation.input_fingerprint,
        "observation_extraction_result_id": observation.extraction_result_id,
        "assessed_observation": (
            {
                "id": assessed_observation.id,
                "input_fingerprint": assessed_observation.input_fingerprint,
                "extraction_result_id": assessed_observation.extraction_result_id,
            }
            if assessed_observation is not None
            else None
        ),
        "profile_member_is_current_automatic_observation": (
            assessed_observation is not None
            and assessed_observation.id == observation.id
        ),
        "effective_review_action": (
            database.get_effective_observation_review_action(observation.id)
        ),
        "latest_extraction": (
            {
                "id": extraction.id,
                "version": extraction.version,
                "json": _path_state(extraction.proposed_json_path),
            }
            if extraction is not None
            else None
        ),
        "media": (
            {
                "id": media_artifact.id,
                "input_fingerprint": media_artifact.input_fingerprint,
                "content_sha256": media_artifact.content_sha256,
                "artifact": _path_state(media_artifact.artifact_path),
            }
            if media_artifact is not None
            else None
        ),
        "span_selection_version": TRANSCRIPT_GROUNDED_SPAN_SELECTION_VERSION,
        "model_fingerprint": model_fingerprint,
        "policy_artifact_sha256": policy_artifact_sha256,
    }


def _exemplar_preparation_initial_blocker(
    *,
    profile_observation_id: int,
    assessment_eligible: bool,
    assessed_observation_id: int | None,
    assessment_reason_code: str,
) -> tuple[str, str]:
    if (
        assessment_eligible
        and assessed_observation_id is not None
        and assessed_observation_id != profile_observation_id
    ):
        return (
            "observation_consistency",
            "assessed_observation_mismatch",
        )
    stage = (
        "extraction_lookup"
        if assessment_reason_code.startswith("extraction_")
        else "media_registration"
        if "media" in assessment_reason_code
        or "audio" in assessment_reason_code
        else "observation_consistency"
    )
    return stage, assessment_reason_code


@identity_app.command(
    "shadow-associate-speakers",
    help="Propose multi-exemplar profile matches without changing registry membership.",
)
def shadow_associate_speakers_command(
    youtube_video_id: str | None = typer.Option(
        None,
        "--youtube-video-id",
        help="Evaluate one YouTube video.",
    ),
    all_eligible: bool = typer.Option(
        False,
        "--all-eligible",
        help="Evaluate every currently eligible unassigned sermon observation.",
    ),
    unattempted_only: bool = typer.Option(
        False,
        "--unattempted-only",
        help=(
            "With --all-eligible, evaluate only current observations with no "
            "persisted shadow-association attempt."
        ),
    ),
    neighborhood_profile_id: list[int] = typer.Option(
        [],
        "--neighborhood-profile-id",
        min=1,
        help=(
            "Replay only observations with persisted direct routing, comparison, "
            "proposal, or exemplar-exclusion evidence for this profile; repeatable."
        ),
    ),
    include_profiled: bool = typer.Option(
        False,
        "--include-profiled",
        help=(
            "Include already-profiled observations for boundary-evidence "
            "regeneration; profile membership remains unchanged."
        ),
    ),
    limit: int | None = typer.Option(
        None,
        min=1,
        help="Maximum candidates to evaluate when using --all-eligible.",
    ),
    plan_only: bool = typer.Option(
        False,
        "--plan-only",
        help="Report readiness and candidate coverage without acoustic execution.",
    ),
    minimum_profile_members: int = typer.Option(
        3,
        min=3,
        help="Distinct reviewed members required for shadow profile matching.",
    ),
    maximum_exemplars: int = typer.Option(
        3,
        min=2,
        help="Maximum independently recorded exemplars compared per profile.",
    ),
    minimum_same_exemplars: int = typer.Option(
        2,
        min=2,
        help="Same-speaker comparisons required to propose one profile.",
    ),
    maximum_global_profiles: int = typer.Option(
        1,
        min=1,
        help=(
            "Maximum cross-source acoustic fallback profiles when no "
            "same-source, explicit-name, or confirmation route exists."
        ),
    ),
    jobs: int = typer.Option(
        2,
        "--jobs",
        min=1,
        help="Concurrent acoustic preprocessing and comparison jobs.",
    ),
    model_path: Path = typer.Option(
        Path(
            "evaluation/speaker-pairs/models/"
            "3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx"
        ),
        help="Local ONNX speaker-embedding model.",
    ),
    model_sha256: str = typer.Option(
        DEFAULT_SPEAKER_MODEL_SHA256,
        help="Required checksum for the local model.",
    ),
    policy_path: Path = typer.Option(
        Path(
            "evaluation/speaker-pairs/policies/"
            "campplus-development-candidate-v1.json"
        ),
        help="Pinned approved or experimental shadow decision policy.",
    ),
    evaluation_root: Path = typer.Option(
        Path("evaluation/speaker-pairs"),
        help="Speaker-pair drafts, reviews, and fixtures root.",
    ),
    cache_dir: Path = typer.Option(
        Path("evaluation/speaker-pairs/cache"),
        help="Ignored exact-span, embedding, and media-verification cache.",
    ),
    output_root: Path = typer.Option(
        Path("evaluation/speaker-associations/shadow-runs"),
        help="Ignored versioned shadow-association artifacts.",
    ),
    base_dir: Path | None = typer.Option(
        None,
        help="Override app data directory.",
    ),
) -> tuple[Path, ...]:
    selection_modes = sum(
        (youtube_video_id is not None, all_eligible, bool(neighborhood_profile_id))
    )
    if selection_modes != 1:
        raise typer.BadParameter(
            "Pass exactly one of --youtube-video-id, --all-eligible, or "
            "--neighborhood-profile-id."
        )
    if unattempted_only and not all_eligible:
        raise typer.BadParameter(
            "--unattempted-only requires --all-eligible."
        )
    if minimum_same_exemplars > maximum_exemplars:
        raise typer.BadParameter(
            "--minimum-same-exemplars cannot exceed --maximum-exemplars."
        )
    paths = build_paths(base_dir)
    if not paths.database.exists():
        raise typer.BadParameter(
            f"Application database does not exist: {paths.database}"
        )
    database = Database(paths.database, readonly=True)
    cache_root = cache_dir.expanduser().resolve()
    verification_cache = MediaVerificationCache(
        cache_root / "media-verification"
    )
    span_cache = AudioSpanCache(cache_root)
    try:
        evidence = load_reviewed_speaker_evidence(
            evaluation_root.expanduser().resolve()
        )
        policy_spec = load_shadow_policy(policy_path)
        readiness = assess_profile_association_readiness(
            database,
            evidence,
            minimum_members=minimum_profile_members,
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise typer.BadParameter(str(error)) from error

    backend = None
    embedding_cache = None
    pair_diagnostic_cache = None
    if not plan_only:
        try:
            backend = SherpaOnnxEmbeddingBackend(
                model_path.expanduser().resolve(),
                expected_sha256=model_sha256,
            )
        except (OSError, RuntimeError, ValueError) as error:
            raise typer.BadParameter(str(error)) from error
        embedding_cache = EmbeddingCache(cache_root)
        pair_diagnostic_cache = PairDiagnosticCache(cache_root)
        pair_cache_root = cache_root / "pair-diagnostics"
        if not pair_cache_root.is_dir() or not next(
            pair_cache_root.glob("*.json"), None
        ):
            association_reports = tuple(
                output_root.expanduser().resolve().glob("*/*.json")
            )
            console.print(
                "Association preprocessing: priming pair diagnostics from "
                f"{len(association_reports)} existing association artifact(s)."
            )
            pair_diagnostic_cache.prime_from_shadow_associations(
                association_reports
            )
            console.print(
                "Association preprocessing: pair diagnostic cache primed "
                f"from {pair_diagnostic_cache.primed} comparison result(s)."
            )

    span_selection_by_observation_id: dict[int, Mapping[str, Any]] = {}
    activity_selection_cache = ActivityQualifiedSelectionCache(cache_root)

    def transcript_grounded_spans(
        video_id: int,
        observation: SpeakerObservation,
        audio_path: Path,
        source_audio_sha256: str,
        *,
        acoustic_backend=None,
    ) -> tuple[tuple[SpanSpec, ...], Mapping[str, Any] | None]:
        extraction = database.get_extraction_result(
            observation.extraction_result_id
        )
        if extraction is None or not extraction.proposed_json_path:
            return (), None
        try:
            payload = json.loads(
                Path(extraction.proposed_json_path).read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, json.JSONDecodeError):
            return (), None
        if not isinstance(payload, dict):
            return (), None
        candidates = select_transcript_grounded_span_candidates(
            payload,
            observation,
        )
        if not candidates or plan_only:
            return candidates, None
        assert backend is not None
        assert embedding_cache is not None
        selected_backend = acoustic_backend or backend
        qualified = activity_selection_cache.get_or_prepare(
            observation=observation,
            source_audio_sha256=source_audio_sha256,
            audio_path=audio_path,
            span_cache=span_cache,
            candidate_specs=candidates,
            embedding_cache=embedding_cache,
            backend=selected_backend,
            policy=policy_spec.policy,
        )
        selection = {
            **qualified.selection,
            "coherent_sermon_speaker_spans": [
                {
                    "start_seconds": spec.start_seconds,
                    "end_seconds": spec.end_seconds,
                    "speaker_key": (
                        "sermon_speaker_candidate:"
                        f"{observation.input_fingerprint}"
                    ),
                    "relationship": "coherent_sermon_speaker",
                }
                for spec in qualified.span_specs
            ],
        }
        return qualified.span_specs, selection

    videos_by_id = {video.id: video for video in database.list_videos()}
    observations_by_id = {
        observation.id: observation
        for observation in database.list_speaker_observations()
    }
    current_observation_by_video_id: dict[int, SpeakerObservation] = {}
    for observation in observations_by_id.values():
        current = current_observation_by_video_id.get(observation.video_id)
        if current is None or observation.id > current.id:
            current_observation_by_video_id[observation.video_id] = observation
    source_id_by_video_id = {
        video_id: video.source_id for video_id, video in videos_by_id.items()
    }
    candidate_names_by_observation: dict[int, set[str]] = {}
    for claim in database.list_speaker_name_claims():
        if (
            claim.observation_id is not None
            and claim.explicit_speaker_attribution
            and claim.normalized_name.strip()
        ):
            candidate_names_by_observation.setdefault(
                claim.observation_id,
                set(),
            ).add(claim.normalized_name.strip())
    eligible_exemplars: list[ShadowExemplar] = []
    span_specs_by_observation_id: dict[int, tuple[SpanSpec, ...]] = {}
    exemplar_state_cache = ExemplarPreparationStateCache(cache_root)
    exemplar_preparation_counts: dict[str, int] = {}
    exemplar_preparation_by_profile: dict[int, dict[str, int]] = {}

    def count_exemplar_preparation(profile_id: int, key: str) -> None:
        exemplar_preparation_counts[key] = (
            exemplar_preparation_counts.get(key, 0) + 1
        )
        profile_counts = exemplar_preparation_by_profile.setdefault(
            profile_id, {}
        )
        profile_counts[key] = profile_counts.get(key, 0) + 1

    def record_exemplar_preparation(
        *,
        profile_id: int,
        observation: SpeakerObservation,
        evidence_payload: Mapping[str, Any],
        stage: str,
        outcome: str,
        reason_code: str,
    ) -> None:
        count_exemplar_preparation(
            profile_id,
            "eligible" if outcome == "eligible" else f"{stage}:{reason_code}"
        )
        if plan_only:
            return
        video = videos_by_id.get(observation.video_id)
        if video is None:
            return
        exemplar_state_cache.record(
            profile_id=profile_id,
            observation_id=observation.id,
            observation_fingerprint=observation.input_fingerprint,
            video_id=observation.video_id,
            youtube_video_id=video.youtube_video_id,
            evidence=evidence_payload,
            stage=stage,
            outcome=outcome,
            reason_code=reason_code,
        )
    review_ready_profiles = [
        profile for profile in readiness if profile.review_ready
    ]
    console.print(
        "Association preprocessing: "
        f"preparing exemplars for {len(review_ready_profiles)} review-ready "
        "profile(s)."
    )
    for profile_index, profile in enumerate(review_ready_profiles, start=1):
        console.print(
            "Association preprocessing: "
            f"profile {profile_index}/{len(review_ready_profiles)} "
            f"id={profile.profile_id} "
            f"members={len(profile.member_observation_ids)} "
            f"certified_exemplars="
            f"{len(profile.certified_exemplar_observation_ids)}"
        )
        preparation_observation_ids = (
            profile.certified_exemplar_observation_ids
            if (
                profile.automatic_profile_ready
                and profile.certified_exemplar_observation_ids
            )
            else profile.member_observation_ids
        )
        for observation_id in preparation_observation_ids:
            observation = database.get_speaker_observation(observation_id)
            if observation is None:
                continue
            eligibility = assess_automatic_speaker_observation(
                database,
                observation.video_id,
                observation_id=observation.id,
                verification_cache=verification_cache,
                verify_media=False,
            )
            evidence_payload = _exemplar_preparation_evidence(
                database,
                profile_id=profile.profile_id,
                observation=observation,
                assessed_observation=eligibility.observation,
                media_artifact=eligibility.media_artifact,
                model_fingerprint=(
                    backend.spec.fingerprint if backend is not None else None
                ),
                policy_artifact_sha256=policy_spec.artifact_sha256,
            )
            evidence_fingerprint = exemplar_state_cache.evidence_fingerprint(
                evidence_payload
            )
            unchanged = (
                exemplar_state_cache.unchanged_deterministic_failure(
                    profile_id=profile.profile_id,
                    observation_fingerprint=observation.input_fingerprint,
                    evidence_fingerprint=evidence_fingerprint,
                )
                if not plan_only
                else None
            )
            if unchanged is not None:
                count_exemplar_preparation(
                    profile.profile_id,
                    f"cached:{unchanged.stage}:{unchanged.reason_code}"
                )
                continue
            if (
                not eligibility.eligible
                or eligibility.observation is None
                or eligibility.media_artifact is None
                or eligibility.observation.id != observation.id
            ):
                stage, reason_code = _exemplar_preparation_initial_blocker(
                    profile_observation_id=observation.id,
                    assessment_eligible=eligibility.eligible,
                    assessed_observation_id=(
                        eligibility.observation.id
                        if eligibility.observation is not None
                        else None
                    ),
                    assessment_reason_code=eligibility.reason_code,
                )
                record_exemplar_preparation(
                    profile_id=profile.profile_id,
                    observation=observation,
                    evidence_payload=evidence_payload,
                    stage=stage,
                    outcome="blocked",
                    reason_code=reason_code,
                )
                continue
            eligibility = assess_automatic_speaker_observation(
                database,
                observation.video_id,
                observation_id=observation.id,
                verification_cache=verification_cache,
                verify_media=True,
            )
            if (
                not eligibility.eligible
                or eligibility.observation is None
                or eligibility.media_artifact is None
                or eligibility.observation.id != observation.id
            ):
                record_exemplar_preparation(
                    profile_id=profile.profile_id,
                    observation=observation,
                    evidence_payload=evidence_payload,
                    stage="media_verification",
                    outcome="blocked",
                    reason_code=eligibility.reason_code,
                )
                continue
            audio_path = Path(eligibility.media_artifact.artifact_path)
            span_cache.remember_verified_source(
                audio_path,
                eligibility.media_artifact.content_sha256,
            )
            try:
                span_specs, span_selection = transcript_grounded_spans(
                    observation.video_id,
                    observation,
                    audio_path,
                    eligibility.media_artifact.content_sha256,
                )
            except (OSError, RuntimeError, ValueError) as error:
                reason_code = (
                    str(error) or "activity_qualified_spans_unavailable"
                )
                record_exemplar_preparation(
                    profile_id=profile.profile_id,
                    observation=observation,
                    evidence_payload=evidence_payload,
                    stage="activity_span_selection",
                    outcome="blocked",
                    reason_code=reason_code,
                )
                continue
            if not span_specs:
                record_exemplar_preparation(
                    profile_id=profile.profile_id,
                    observation=observation,
                    evidence_payload=evidence_payload,
                    stage="transcript_span_selection",
                    outcome="blocked",
                    reason_code="speech_grounded_spans_unavailable",
                )
                continue
            if span_selection is not None:
                span_selection_by_observation_id[
                    observation.id
                ] = span_selection
            span_specs_by_observation_id[observation.id] = span_specs
            eligible_exemplars.append(
                ShadowExemplar(
                    profile_id=profile.profile_id,
                    observation=observation,
                    audio_path=audio_path,
                    audio_sha256=eligibility.media_artifact.content_sha256,
                    span_specs=span_specs,
                )
            )
            record_exemplar_preparation(
                profile_id=profile.profile_id,
                observation=observation,
                evidence_payload=evidence_payload,
                stage="complete",
                outcome="eligible",
                reason_code="eligible_exemplar",
            )

    if exemplar_preparation_counts:
        console.print(
            "Exemplar preparation: "
            + ", ".join(
                f"{reason}={count}"
                for reason, count in sorted(
                    exemplar_preparation_counts.items()
                )
            )
        )
        for profile_id, counts in sorted(
            exemplar_preparation_by_profile.items()
        ):
            console.print(
                f"Profile {profile_id} exemplar funnel: "
                + ", ".join(
                    f"{reason}={count}"
                    for reason, count in sorted(counts.items())
                )
            )

    usable_profiles = []
    for profile in readiness:
        if not profile.review_ready:
            continue
        exemplars = select_profile_exemplars(
            profile,
            eligible_exemplars,
            videos_by_id=videos_by_id,
            maximum_exemplars=maximum_exemplars,
        )
        if len(exemplars) >= minimum_same_exemplars:
            usable_profiles.append((profile, exemplars))
    def profile_readiness_funnel_payload(
        profile_readiness,
        comparison_profiles,
        *,
        leave_one_out_observation_id: int | None = None,
    ):
        comparison_profile_ids = {
            profile.profile_id for profile, _exemplars in comparison_profiles
        }
        return {
            "canonical_profile_ids": sorted(
                profile.profile_id for profile in profile_readiness
            ),
            "review_ready_profile_ids": sorted(
                profile.profile_id
                for profile in profile_readiness
                if profile.review_ready
            ),
            "comparison_eligible_profile_ids": sorted(
                comparison_profile_ids
            ),
            "leave_one_out_observation_id": leave_one_out_observation_id,
            "excluded_profiles": [
                {
                    "profile_id": profile.profile_id,
                    "stage": (
                        "profile_readiness"
                        if not profile.review_ready
                        else "acoustic_exemplar_availability"
                    ),
                    "reason_codes": (
                        list(profile.shadow_blockers)
                        if not profile.review_ready
                        else [
                            "fewer_than_required_eligible_acoustic_exemplars"
                        ]
                    ),
                    "eligible_exemplar_count": sum(
                        exemplar.profile_id == profile.profile_id
                        and exemplar.observation.id
                        != leave_one_out_observation_id
                        for exemplar in eligible_exemplars
                    ),
                    "required_exemplar_count": minimum_same_exemplars,
                }
                for profile in profile_readiness
                if profile.profile_id not in comparison_profile_ids
            ],
        }

    profile_readiness_funnel = profile_readiness_funnel_payload(
        readiness, usable_profiles
    )

    requested_videos = []
    if youtube_video_id is not None:
        video = database.get_video_by_youtube_id(youtube_video_id)
        if video is None:
            raise typer.BadParameter(
                f"Unknown YouTube video ID: {youtube_video_id}"
            )
        requested_videos = [video]
    elif neighborhood_profile_id:
        try:
            neighborhood_video_ids = profile_neighborhood_video_ids(
                database,
                association_root=output_root,
                profile_ids=neighborhood_profile_id,
            )
        except ValueError as error:
            raise typer.BadParameter(str(error)) from error
        requested_videos = [
            videos_by_id[video_id]
            for video_id in neighborhood_video_ids
            if video_id in videos_by_id
        ]
        if not requested_videos:
            raise typer.BadParameter(
                "No persisted affected neighborhood was found for the requested "
                "profile id(s)."
            )
    else:
        requested_videos = [
            video
            for video in videos_by_id.values()
            if video.id in current_observation_by_video_id
        ]
        console.print(
            "Association candidate inventory: "
            f"database_videos={len(videos_by_id)} "
            f"videos_with_observations={len(requested_videos)} "
            f"skipped_without_observations="
            f"{len(videos_by_id) - len(requested_videos)}."
        )

    attempted_observation_fingerprints: set[str] = set()
    if unattempted_only:
        persisted_attempts = load_identity_association_attempts(
            output_root,
            database_video_ids={video.id for video in requested_videos},
        )
        attempted_observation_fingerprints = {
            fingerprint
            for attempts in persisted_attempts.values()
            for attempt in attempts
            if isinstance(
                fingerprint := attempt.get("observation_fingerprint"), str
            )
        }

    admission_paths: set[Path] = set()
    def persist_admission(
        video,
        observation: SpeakerObservation | None,
        *,
        stage: str,
        reason_code: str,
        media_sha256: str | None = None,
    ) -> None:
        if (
            plan_only
            or observation is None
        ):
            return
        admission_paths.add(
            write_shadow_association_admission(
                output_root,
                observation=observation,
                youtube_video_id=video.youtube_video_id,
                stage=stage,
                reason_code=reason_code,
                evidence={
                    "normalized_audio_sha256": media_sha256,
                    "span_selection_version": (
                        TRANSCRIPT_GROUNDED_SPAN_SELECTION_VERSION
                    ),
                    "model_fingerprint": (
                        backend.spec.fingerprint if backend is not None else None
                    ),
                    "policy_artifact_sha256": policy_spec.artifact_sha256,
                },
            )
        )

    candidates = []
    span_preparation_inputs = []
    ineligible_reasons: dict[str, int] = {}
    console.print(
        "Association preprocessing: "
        f"scanning {len(requested_videos)} video(s) for eligible candidates."
    )
    for video_index, video in enumerate(requested_videos, start=1):
        if (
            video_index == 1
            or video_index == len(requested_videos)
            or video_index % 25 == 0
        ):
            console.print(
                "Association preprocessing: "
                f"video={video_index}/{len(requested_videos)} "
                f"admitted_for_span_prep={len(span_preparation_inputs)} "
                f"excluded_so_far={sum(ineligible_reasons.values())}"
            )
        latest_observation = (
            database.get_latest_speaker_observation_for_video(video.id)
            if unattempted_only
            else None
        )
        if unattempted_only:
            if (
                latest_observation is not None
                and latest_observation.input_fingerprint
                in attempted_observation_fingerprints
            ):
                ineligible_reasons["association_already_attempted"] = (
                    ineligible_reasons.get(
                        "association_already_attempted", 0
                    )
                    + 1
                )
                continue
        eligibility = assess_automatic_speaker_observation(
            database,
            video.id,
            verification_cache=verification_cache,
            verify_media=False,
        )
        if not eligibility.eligible or eligibility.observation is None:
            ineligible_reasons[eligibility.reason_code] = (
                ineligible_reasons.get(eligibility.reason_code, 0) + 1
            )
            persist_admission(
                video,
                latest_observation,
                stage="metadata_eligibility",
                reason_code=eligibility.reason_code,
            )
            continue
        if (
            not include_profiled
            and database.list_effective_profile_ids_for_observation(
                eligibility.observation.id
            )
        ):
            ineligible_reasons["already_profiled"] = (
                ineligible_reasons.get("already_profiled", 0) + 1
            )
            persist_admission(
                video,
                eligibility.observation,
                stage="membership_filter",
                reason_code="already_profiled",
                media_sha256=(
                    eligibility.media_artifact.content_sha256
                    if eligibility.media_artifact is not None
                    else None
                ),
            )
            continue
        review_action = database.get_effective_observation_review_action(
            eligibility.observation.id
        )
        if review_action not in {None, "qualified_single_speaker"}:
            reason = f"reviewed_{review_action}"
            ineligible_reasons[reason] = ineligible_reasons.get(reason, 0) + 1
            persist_admission(
                video,
                eligibility.observation,
                stage="observation_review_filter",
                reason_code=reason,
                media_sha256=(
                    eligibility.media_artifact.content_sha256
                    if eligibility.media_artifact is not None
                    else None
                ),
            )
            continue
        eligibility = assess_automatic_speaker_observation(
            database,
            video.id,
            verification_cache=verification_cache,
            verify_media=True,
        )
        if not eligibility.eligible or eligibility.observation is None:
            ineligible_reasons[eligibility.reason_code] = (
                ineligible_reasons.get(eligibility.reason_code, 0) + 1
            )
            persist_admission(
                video,
                latest_observation,
                stage="verified_media_eligibility",
                reason_code=eligibility.reason_code,
            )
            continue
        if eligibility.media_artifact is None:
            ineligible_reasons["verified_normalized_media_unavailable"] = (
                ineligible_reasons.get(
                    "verified_normalized_media_unavailable",
                    0,
                )
                + 1
            )
            persist_admission(
                video,
                eligibility.observation,
                stage="verified_media_eligibility",
                reason_code="verified_normalized_media_unavailable",
            )
            continue
        audio_path = Path(eligibility.media_artifact.artifact_path)
        span_cache.remember_verified_source(
            audio_path,
            eligibility.media_artifact.content_sha256,
        )
        span_preparation_inputs.append((video, eligibility, audio_path))

    console.print(
        "Association span preparation: "
        f"candidates={len(span_preparation_inputs)} jobs={jobs}; "
        "cached selections are reused and misses are prepared concurrently."
    )
    worker_state = local()

    def span_preparation_backend():
        if jobs == 1:
            return backend
        worker_backend = getattr(worker_state, "backend", None)
        if worker_backend is None:
            worker_backend = SherpaOnnxEmbeddingBackend(
                model_path.expanduser().resolve(),
                expected_sha256=model_sha256,
                num_threads=1,
            )
            worker_state.backend = worker_backend
        return worker_backend

    def prepare_candidate_spans(item):
        video, eligibility, audio_path = item
        assert eligibility.observation is not None
        assert eligibility.media_artifact is not None
        try:
            span_specs, span_selection = transcript_grounded_spans(
                video.id,
                eligibility.observation,
                audio_path,
                eligibility.media_artifact.content_sha256,
                acoustic_backend=(
                    None if plan_only else span_preparation_backend()
                ),
            )
        except Exception as error:
            return item, (), None, (
                str(error) or "activity_qualified_spans_unavailable"
            )
        if not span_specs:
            return item, (), None, "speech_grounded_spans_unavailable"
        return item, span_specs, span_selection, None

    target_count = limit if all_eligible and limit is not None else None
    batch_size = max(1, jobs)
    next_progress = 25
    with ThreadPoolExecutor(max_workers=jobs) as span_executor:
        for batch_start in range(0, len(span_preparation_inputs), batch_size):
            if target_count is not None and len(candidates) >= target_count:
                break
            batch = span_preparation_inputs[
                batch_start : batch_start + batch_size
            ]
            results = span_executor.map(prepare_candidate_spans, batch)
            for item, span_specs, span_selection, reason in results:
                video, eligibility, _audio_path = item
                assert eligibility.observation is not None
                assert eligibility.media_artifact is not None
                if target_count is not None and len(candidates) >= target_count:
                    break
                if reason is not None:
                    ineligible_reasons[reason] = (
                        ineligible_reasons.get(reason, 0) + 1
                    )
                    persist_admission(
                        video,
                        eligibility.observation,
                        stage=(
                            "transcript_span_selection"
                            if reason == "speech_grounded_spans_unavailable"
                            else "activity_span_selection"
                        ),
                        reason_code=reason,
                        media_sha256=(
                            eligibility.media_artifact.content_sha256
                        ),
                    )
                    continue
                span_specs_by_observation_id[
                    eligibility.observation.id
                ] = span_specs
                if span_selection is not None:
                    span_selection_by_observation_id[
                        eligibility.observation.id
                    ] = span_selection
                candidates.append((video, eligibility, span_specs))
            completed = min(
                batch_start + len(batch), len(span_preparation_inputs)
            )
            if completed >= next_progress or completed == len(
                span_preparation_inputs
            ):
                console.print(
                    "Association span preparation: "
                    f"processed={completed}/{len(span_preparation_inputs)} "
                    f"eligible={len(candidates)} "
                    f"cache_hits={activity_selection_cache.hits} "
                    f"cache_misses={activity_selection_cache.misses}"
                )
                while next_progress <= completed:
                    next_progress += 25

    shadow_ready_count = sum(profile.shadow_ready for profile in readiness)
    review_ready_count = sum(profile.review_ready for profile in readiness)
    automatic_profile_ready_count = sum(
        profile.automatic_profile_ready for profile in readiness
    )
    console.print(
        "Profile readiness: "
        f"canonical={len(readiness)} "
        f"review_ready={review_ready_count} "
        f"shadow_ready={shadow_ready_count} "
        f"automatic_profile_ready={automatic_profile_ready_count} "
        f"acoustically_usable={len(usable_profiles)}"
    )
    for profile in readiness:
        blockers = (
            ",".join(profile.automatic_blockers)
            if profile.automatic_blockers
            else "none"
        )
        console.print(
            f"Profile {profile.profile_id}: members="
            f"{len(profile.member_observation_ids)} "
            f"recordings={profile.recording_count} "
            f"review_ready={profile.review_ready} "
            f"shadow_ready={profile.shadow_ready} "
            f"automatic_profile_ready={profile.automatic_profile_ready} "
            f"automatic_blockers={blockers}"
        )
    console.print(
        f"Candidate observations: eligible_unassigned={len(candidates)} "
        f"ineligible={sum(ineligible_reasons.values())}"
    )
    if ineligible_reasons:
        console.print(
            "Ineligible reasons: "
            + ", ".join(
                f"{reason}={count}"
                for reason, count in sorted(ineligible_reasons.items())
            )
        )
    if admission_paths:
        console.print(
            "Persisted strict association admissions: "
            f"excluded={len(admission_paths)}."
        )
    if plan_only:
        console.print(
            "Plan only; no acoustic comparisons or association artifacts were created."
        )
        return ()
    if not usable_profiles:
        if all_eligible:
            console.print(
                "No review-ready profile currently has enough eligible "
                "acoustic exemplars; blocker states were preserved and no "
                "comparison artifacts were created."
            )
            return ()
        raise typer.BadParameter(
            "No review-ready profile has enough eligible acoustic exemplars."
        )
    if not candidates:
        if all_eligible:
            console.print(
                "No candidate observation passed strict association admission; "
                "no comparison artifacts were created."
            )
            return ()
        raise typer.BadParameter(
            "No eligible unassigned candidate observation was selected."
        )

    assert backend is not None
    assert embedding_cache is not None
    assert pair_diagnostic_cache is not None

    def ordered_acoustic_map(function, items, *, thread_name_prefix):
        if jobs == 1 or len(items) < 2:
            return tuple(map(function, items))
        with ThreadPoolExecutor(
            max_workers=min(jobs, len(items)),
            thread_name_prefix=thread_name_prefix,
        ) as executor:
            return tuple(executor.map(function, items))

    exemplar_centroids: dict[int, tuple[float, ...]] = {}
    unique_exemplars = tuple(
        {
            exemplar.observation.id: exemplar
            for exemplar in eligible_exemplars
        }.values()
    )
    console.print(
        "Association preprocessing: building retrieval centroids for "
        f"{len(unique_exemplars)} eligible exemplar(s) with {jobs} job(s)."
    )

    def build_exemplar_centroid(exemplar):
        return exemplar.observation.id, build_embedding_centroid(
            observation=exemplar.observation,
            audio_path=exemplar.audio_path,
            span_specs=span_specs_by_observation_id[
                exemplar.observation.id
            ],
            span_cache=span_cache,
            embedding_cache=embedding_cache,
            backend=backend,
        )

    exemplar_centroids.update(
        ordered_acoustic_map(
            build_exemplar_centroid,
            unique_exemplars,
            thread_name_prefix="identity-exemplar-centroid",
        )
    )
    candidate_centroids: dict[int, tuple[float, ...]] = {}
    candidate_video_ids: dict[int, int] = {}
    console.print(
        "Association preprocessing: building retrieval centroids for "
        f"{len(candidates)} candidate observation(s) with {jobs} job(s)."
    )

    def build_candidate_centroid(indexed_candidate):
        candidate_index, (_video, eligibility, _span_specs) = indexed_candidate
        observation = eligibility.observation
        media_artifact = eligibility.media_artifact
        if observation is None or media_artifact is None:
            return candidate_index, None, None, None
        try:
            centroid = build_embedding_centroid(
                observation=observation,
                audio_path=Path(media_artifact.artifact_path),
                span_specs=span_specs_by_observation_id[observation.id],
                span_cache=span_cache,
                embedding_cache=embedding_cache,
                backend=backend,
            )
        except Exception as error:
            return (
                candidate_index,
                observation.id,
                observation.video_id,
                None,
                f"{type(error).__name__}:{error}",
            )
        return candidate_index, observation.id, observation.video_id, centroid, None

    indexed_candidates = tuple(enumerate(candidates, start=1))
    candidate_centroid_results = ordered_acoustic_map(
        build_candidate_centroid,
        indexed_candidates,
        thread_name_prefix="identity-candidate-centroid",
    )
    failed_candidate_observation_ids: set[int] = set()
    for candidate_index, observation_id, video_id, centroid, failure in (
        candidate_centroid_results
    ):
        if (
            candidate_index == 1
            or candidate_index == len(candidates)
            or candidate_index % 25 == 0
        ):
            console.print(
                "Association preprocessing: candidate centroid "
                f"{candidate_index}/{len(candidates)}"
            )
        if failure is not None and observation_id is not None:
            failed_candidate_observation_ids.add(observation_id)
            video = videos_by_id.get(video_id) if video_id is not None else None
            observation = observations_by_id.get(observation_id)
            if video is not None and observation is not None:
                persist_admission(
                    video,
                    observation,
                    stage="technical_failure",
                    reason_code="candidate_centroid_failed",
                )
            console.print(
                f"Association candidate failed in isolation: observation="
                f"{observation_id} stage=candidate_centroid detail={failure}"
            )
        elif (
            observation_id is not None
            and video_id is not None
            and centroid is not None
        ):
            candidate_centroids[observation_id] = centroid
            candidate_video_ids[observation_id] = video_id
    pending_confirmation_profiles = tuple(
        (profile, exemplars)
        for profile, exemplars in usable_profiles
        if (
            "discovery_candidate_unconfirmed"
            in profile.automatic_blockers
            and (
                registry_profile := database.get_speaker_profile(
                    profile.profile_id
                )
            )
            is not None
            and registry_profile.created_reason
            == DISCOVERY_PROFILE_REASON
            and database.get_speaker_profile_discovery_promotion(
                profile.profile_id
            )
            is not None
        )
    )
    confirmation_routes = plan_pending_discovery_confirmation_routes(
        pending_confirmation_profiles,
        candidate_centroids=candidate_centroids,
        candidate_video_ids=candidate_video_ids,
        exemplar_centroids=exemplar_centroids,
        candidates_per_profile=2,
    )
    pending_confirmation_profile_ids = {
        profile.profile_id
        for profile, _exemplars in pending_confirmation_profiles
    }
    routed_pending_profile_ids = {
        profile_id
        for profile_ids in confirmation_routes.values()
        for profile_id in profile_ids
    }
    console.print(
        "Pending discovery confirmation routing: "
        f"profiles={len(pending_confirmation_profile_ids)} "
        f"profiles_routed={len(routed_pending_profile_ids)} "
        f"candidate_observations={len(confirmation_routes)} "
        f"profile_candidate_routes="
        f"{sum(len(profile_ids) for profile_ids in confirmation_routes.values())}"
    )
    def compare(
        candidate: SpeakerObservation,
        exemplar: SpeakerObservation,
        candidate_audio_path: Path,
        exemplar_audio_path: Path,
    ) -> dict[str, object]:
        return analyze_observation_pair(
            observation_a=candidate,
            observation_b=exemplar,
            audio_path_a=candidate_audio_path,
            audio_path_b=exemplar_audio_path,
            span_cache=span_cache,
            embedding_cache=embedding_cache,
            backend=backend,
            policy=policy_spec.policy,
            span_specs_a=span_specs_by_observation_id[candidate.id],
            span_specs_b=span_specs_by_observation_id[exemplar.id],
            span_specs_are_activity_qualified=True,
            pair_diagnostic_cache=pair_diagnostic_cache,
        )

    outcome_counts: dict[str, int] = {}
    routing_counts: dict[str, int] = {}
    detailed_profile_comparisons = 0
    exhaustive_profile_comparisons = 0
    reused_associations = 0
    sermon_window_quality_flag_count = 0
    proposal_targets: dict[int, int] = {}
    written_reports: list[Path] = []
    comparison_executor: ThreadPoolExecutor | None = None
    for index, (video, eligibility, _span_specs) in enumerate(
        candidates,
        start=1,
    ):
        observation = eligibility.observation
        media_artifact = eligibility.media_artifact
        if observation is None or media_artifact is None:
            continue
        if observation.id in failed_candidate_observation_ids:
            continue
        explicit_candidate_names = set(
            candidate_names_by_observation.get(observation.id, ())
        )
        title_hint = title_byline_selection_hint(video.title)
        routing_names = explicit_candidate_names | (
            {title_hint} if title_hint else set()
        )
        effective_candidate_profile_ids = {
            database.resolve_speaker_profile_id(profile_id)
            for profile_id in database.list_effective_profile_ids_for_observation(
                observation.id
            )
        }
        leave_one_out_applied = bool(effective_candidate_profile_ids)
        if leave_one_out_applied:
            candidate_readiness = tuple(
                leave_one_out_profile_readiness(
                    profile,
                    candidate=observation,
                    observations_by_id=observations_by_id,
                    source_id_by_video_id=source_id_by_video_id,
                    normalized_names_by_observation_id=(
                        candidate_names_by_observation
                    ),
                    minimum_members=minimum_profile_members,
                )
                for profile in readiness
            )
            candidate_usable_profiles = []
            for profile in candidate_readiness:
                if not profile.review_ready:
                    continue
                exemplars = select_profile_exemplars(
                    profile,
                    eligible_exemplars,
                    videos_by_id=videos_by_id,
                    maximum_exemplars=maximum_exemplars,
                )
                if len(exemplars) >= minimum_same_exemplars:
                    candidate_usable_profiles.append((profile, exemplars))
            candidate_profile_readiness_funnel = (
                profile_readiness_funnel_payload(
                    candidate_readiness,
                    candidate_usable_profiles,
                    leave_one_out_observation_id=observation.id,
                )
            )
        else:
            candidate_usable_profiles = usable_profiles
            candidate_profile_readiness_funnel = profile_readiness_funnel
        legacy_routed_profiles = select_routed_association_profiles(
            candidate_usable_profiles,
            candidate_source_id=video.source_id,
            candidate_normalized_names=sorted(routing_names),
            source_id_by_video_id=source_id_by_video_id,
        )
        candidate_centroid = candidate_centroids[observation.id]
        confirmation_priority_profile_ids = frozenset(
            confirmation_routes.get(observation.id, ())
        )
        routing = select_staged_association_profiles(
            candidate_usable_profiles,
            candidate_source_id=video.source_id,
            candidate_normalized_names=sorted(routing_names),
            source_id_by_video_id=source_id_by_video_id,
            candidate_centroid=candidate_centroid,
            exemplar_centroids=exemplar_centroids,
            maximum_global_profiles=maximum_global_profiles,
            confirmation_priority_profile_ids=(
                confirmation_priority_profile_ids
            ),
        )
        candidate_profiles = routing.profiles
        exhaustive_profile_comparisons += len(legacy_routed_profiles)
        initial_routing_payload = {
            "route": routing.route,
            "exhaustive": routing.exhaustive,
            "priority_profile_ids": list(routing.priority_profile_ids),
            "shortlisted_profile_ids": list(routing.shortlisted_profile_ids),
            "total_routable_profiles": routing.total_routable_profiles,
            "maximum_global_profiles": maximum_global_profiles,
            "retrieval_evidence_only": True,
            "candidate_funnel": {
                **dict(routing.candidate_funnel or {}),
                **candidate_profile_readiness_funnel,
                "retrospective_evaluation": {
                    "leave_one_out_applied": leave_one_out_applied,
                    "hidden_effective_profile_ids": sorted(
                        effective_candidate_profile_ids
                    ),
                    "membership_used_as_routing_evidence": False,
                },
                "candidate_routing_inputs": {
                    "source_id": video.source_id,
                    "explicit_normalized_names": sorted(
                        explicit_candidate_names
                    ),
                    "title_byline_normalized_name": title_hint,
                    "routing_normalized_names": sorted(routing_names),
                },
                "profiles_actually_compared": sorted(
                    profile.profile_id
                    for profile, _exemplars in candidate_profiles
                ),
            },
        }
        if routing.confirmation_priority_profile_ids:
            initial_routing_payload[
                "confirmation_priority_profile_ids"
            ] = list(routing.confirmation_priority_profile_ids)

        def evaluate_profiles(
            selected_profiles,
            routing_payload,
        ):
            nonlocal comparison_executor
            span_selection_payload = {
                "version": TRANSCRIPT_GROUNDED_SPAN_SELECTION_VERSION,
                "required_label": "sermon",
                "span_count": 5,
                "duration_seconds": 12.0,
                "minimum_words": 8,
                "minimum_unique_words": 4,
                "candidate_multiplier": 3,
                "activity_qualified": True,
                "distributed_first": True,
                "within_observation_consistency_fallback": True,
                "candidate_selection": (
                    span_selection_by_observation_id.get(observation.id)
                ),
                "exemplar_selections": {
                    str(exemplar.observation.id): (
                        span_selection_by_observation_id.get(
                            exemplar.observation.id
                        )
                    )
                    for _profile, exemplars in selected_profiles
                    for exemplar in exemplars
                },
            }
            input_fingerprint = build_shadow_association_input_fingerprint(
                candidate=observation,
                candidate_audio_sha256=media_artifact.content_sha256,
                candidate_normalized_names=sorted(explicit_candidate_names),
                profiles=selected_profiles,
                policy_spec=policy_spec,
                model_fingerprint=backend.spec.fingerprint,
                minimum_same_exemplars=minimum_same_exemplars,
                reviewed_difference_pairs=(
                    database.list_effective_observation_difference_pairs()
                ),
                routing=routing_payload,
                span_selection=span_selection_payload,
            )
            reusable = load_reusable_shadow_association(
                output_root,
                candidate_fingerprint=observation.input_fingerprint,
                input_fingerprint=input_fingerprint,
            )
            if reusable is not None:
                return reusable[1], reusable[0]
            if jobs > 1 and comparison_executor is None:
                comparison_executor = ThreadPoolExecutor(
                    max_workers=jobs,
                    thread_name_prefix="identity-association",
                )
            try:
                report = evaluate_shadow_association(
                    candidate=observation,
                    candidate_audio_path=Path(media_artifact.artifact_path),
                    candidate_audio_sha256=media_artifact.content_sha256,
                    candidate_normalized_names=sorted(explicit_candidate_names),
                    profiles=selected_profiles,
                    compare=compare,
                    policy_spec=policy_spec,
                    model_fingerprint=backend.spec.fingerprint,
                    minimum_same_exemplars=minimum_same_exemplars,
                    reviewed_difference_pairs=(
                        database.list_effective_observation_difference_pairs()
                    ),
                    routing=routing_payload,
                    span_selection=span_selection_payload,
                    jobs=jobs,
                    executor=comparison_executor,
                )
            except BaseException:
                if comparison_executor is not None:
                    comparison_executor.shutdown(
                        wait=True,
                        cancel_futures=True,
                    )
                    comparison_executor = None
                raise
            return report, None

        try:
            report, reusable_path = evaluate_profiles(
                candidate_profiles, initial_routing_payload
            )
        except (OSError, RuntimeError, ValueError) as error:
            persist_admission(
                video,
                observation,
                stage="technical_failure",
                reason_code=f"association_evaluation_failed:{type(error).__name__}",
                media_sha256=media_artifact.content_sha256,
            )
            console.print(
                f"Association {index}/{len(candidates)} failed in isolation: "
                f"{video.youtube_video_id} {type(error).__name__}: {error}"
            )
            continue
        if reusable_path is None:
            detailed_profile_comparisons += len(candidate_profiles)
        if should_activate_cross_source_fallback(
            str(report["outcome"]), routing
        ):
            fallback_profiles = tuple(
                (*candidate_profiles, *routing.fallback_profiles)
            )
            fallback_profile_ids = [
                profile.profile_id
                for profile, _exemplars in routing.fallback_profiles
            ]
            initial_candidate_funnel = dict(
                initial_routing_payload.get("candidate_funnel") or {}
            )
            activated_retrieval_candidates = [
                {
                    **entry,
                    "routing_policy_eligible": True,
                    "selected_for_comparison": True,
                    "passed_shortlist_cutoff": True,
                    "weak_local_fallback_activated": True,
                }
                if isinstance(entry, Mapping)
                and entry.get("profile_id") in fallback_profile_ids
                else entry
                for entry in initial_candidate_funnel.get(
                    "retrieval_candidates", []
                )
            ]
            fallback_routing_payload = {
                **initial_routing_payload,
                "route": "source_local_then_bounded_cross_source_fallback",
                "initial_local_outcome": report["outcome"],
                "weak_local_fallback_activated": True,
                "fallback_profile_ids": fallback_profile_ids,
                "profiles_actually_compared": sorted(
                    profile.profile_id
                    for profile, _exemplars in fallback_profiles
                ),
                "candidate_funnel": {
                    **initial_candidate_funnel,
                    "retrieval_candidates": (
                        activated_retrieval_candidates
                    ),
                    "weak_local_fallback_activated": True,
                    "initial_local_outcome": report["outcome"],
                    "profiles_actually_compared": sorted(
                        profile.profile_id
                        for profile, _exemplars in fallback_profiles
                    ),
                },
            }
            try:
                report, reusable_path = evaluate_profiles(
                    fallback_profiles, fallback_routing_payload
                )
            except (OSError, RuntimeError, ValueError) as error:
                persist_admission(
                    video,
                    observation,
                    stage="technical_failure",
                    reason_code=(
                        "association_cross_source_fallback_failed:"
                        f"{type(error).__name__}"
                    ),
                    media_sha256=media_artifact.content_sha256,
                )
                console.print(
                    f"Association {index}/{len(candidates)} cross-source "
                    f"fallback failed in isolation: {video.youtube_video_id} "
                    f"{type(error).__name__}: {error}"
                )
                continue
            if reusable_path is None:
                detailed_profile_comparisons += len(
                    routing.fallback_profiles
                )
        if report["outcome"] == "proposed_match" and not routing.exhaustive:
            proposed_profile_id = report.get("proposed_profile_id")
            exhaustive_profiles = (
                candidate_usable_profiles
                if proposed_profile_id in pending_confirmation_profile_ids
                else legacy_routed_profiles
            )
            exhaustive_routing_payload = {
                "route": (
                    "exhaustive_pending_discovery_confirmation_validation"
                    if proposed_profile_id
                    in pending_confirmation_profile_ids
                    else "exhaustive_validation_after_shortlist_proposal"
                ),
                "exhaustive": True,
                "priority_profile_ids": list(
                    routing.priority_profile_ids
                ),
                "shortlisted_profile_ids": list(
                    routing.shortlisted_profile_ids
                ),
                "total_routable_profiles": len(exhaustive_profiles),
                "maximum_global_profiles": maximum_global_profiles,
                "retrieval_evidence_only": False,
                "initial_shortlist_result": "proposed_match",
                "candidate_funnel": {
                    **dict(routing.candidate_funnel or {}),
                    **candidate_profile_readiness_funnel,
                    "retrospective_evaluation": {
                        "leave_one_out_applied": leave_one_out_applied,
                        "hidden_effective_profile_ids": sorted(
                            effective_candidate_profile_ids
                        ),
                        "membership_used_as_routing_evidence": False,
                    },
                    "candidate_routing_inputs": {
                        "source_id": video.source_id,
                        "explicit_normalized_names": sorted(
                            explicit_candidate_names
                        ),
                        "title_byline_normalized_name": title_hint,
                        "routing_normalized_names": sorted(routing_names),
                    },
                    "profiles_actually_compared": sorted(
                        profile.profile_id
                        for profile, _exemplars in exhaustive_profiles
                    ),
                    "exhaustive_validation_after_shortlist": True,
                },
            }
            if routing.confirmation_priority_profile_ids:
                exhaustive_routing_payload[
                    "confirmation_priority_profile_ids"
                ] = list(routing.confirmation_priority_profile_ids)
            report, reusable_path = evaluate_profiles(
                exhaustive_profiles,
                exhaustive_routing_payload,
            )
            if reusable_path is None:
                detailed_profile_comparisons += len(exhaustive_profiles)
        final_routing = report["routing"]
        routing_route = str(final_routing["route"])
        routing_counts[routing_route] = routing_counts.get(routing_route, 0) + 1
        destination = reusable_path or write_shadow_association(
            output_root, report
        )
        reused_associations += int(reusable_path is not None)
        written_reports.append(destination)
        extraction = database.get_latest_extraction_result_for_video(
            observation.video_id
        )
        if extraction is not None and extraction.proposed_json_path:
            persist_association_boundary_evidence(
                extraction.proposed_json_path,
                report,
            )
        outcome = str(report["outcome"])
        outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1
        proposed_profile_id = report.get("proposed_profile_id")
        if outcome == "proposed_match" and isinstance(
            proposed_profile_id, int
        ):
            proposal_targets[proposed_profile_id] = (
                proposal_targets.get(proposed_profile_id, 0) + 1
            )
        window_flags = report["sermon_window_quality_flags"]
        sermon_window_quality_flag_count += len(window_flags)
        window_flag_text = (
            " window_flags="
            + ",".join(
                f"{flag['flag']}:{flag['edge']}"
                for flag in window_flags
            )
            if window_flags
            else ""
        )
        console.print(
            f"Association {index}/{len(candidates)}: "
            f"{video.youtube_video_id} "
            f"{outcome} profile={report['proposed_profile_id']} "
            f"reason={report['reason']} "
            f"artifact={destination}"
            f" reused={reusable_path is not None}"
            f"{window_flag_text}"
        )
    if comparison_executor is not None:
        comparison_executor.shutdown(wait=True)
    console.print(
        "Shadow association complete: "
        + " ".join(
            f"{outcome}={count}"
            for outcome, count in sorted(outcome_counts.items())
        )
    )
    console.print(
        "Association routing: "
        + " ".join(
            f"{route}={count}"
            for route, count in sorted(routing_counts.items())
        )
        + f" detailed_profiles={detailed_profile_comparisons} "
        f"exhaustive_profiles={exhaustive_profile_comparisons} "
        f"reused_associations={reused_associations} "
        f"pair_cache_hits={pair_diagnostic_cache.hits} "
        f"pair_cache_misses={pair_diagnostic_cache.misses} "
        f"selection_cache_hits={activity_selection_cache.hits} "
        f"selection_cache_misses={activity_selection_cache.misses} "
        f"selection_failure_hits={activity_selection_cache.failure_hits}"
    )
    console.print(
        "Association proposal targets: "
        + (
            ", ".join(
                f"profile_{profile_id}={count}"
                + (
                    "(pending_confirmation)"
                    if profile_id in pending_confirmation_profile_ids
                    else ""
                )
                for profile_id, count in sorted(proposal_targets.items())
            )
            if proposal_targets
            else "none"
        )
    )
    console.print(
        f"Policy status={policy_spec.review_status}; registry mutations=0."
    )
    console.print(
        "Sermon-window quality flags: "
        f"speaker_inconsistent_edge={sermon_window_quality_flag_count}; "
        "automatic boundary changes=0."
    )
    return tuple(written_reports)


@identity_app.command(
    "shadow-association-status",
    help="Measure saved shadow proposals against later reviewed registry state.",
)
def shadow_association_status_command(
    input_root: Path = typer.Option(
        Path("evaluation/speaker-associations/shadow-runs"),
        help="Versioned shadow-association artifact root.",
    ),
    base_dir: Path | None = typer.Option(
        None,
        help="Override app data directory.",
    ),
) -> None:
    paths = build_paths(base_dir)
    if not paths.database.exists():
        raise typer.BadParameter(
            f"Application database does not exist: {paths.database}"
        )
    try:
        reports = _load_json_artifacts(
            sorted(input_root.expanduser().resolve().glob("*/*.json"))
        )
        summary = summarize_shadow_associations(
            Database(paths.database, readonly=True),
            reports,
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise typer.BadParameter(str(error)) from error
    outcomes = summary["outcome_counts"]
    validation = summary["validation_counts"]
    console.print(
        f"Shadow associations: reports={summary['report_count']} "
        + " ".join(
            f"{outcome}={count}"
            for outcome, count in sorted(outcomes.items())
        )
    )
    console.print(
        "Reviewed replay: "
        f"confirmed={validation['confirmed_proposal']} "
        f"contradicted={validation['contradicted_proposal']} "
        f"pending_proposals={validation['pending_proposal']} "
        f"resolved_abstentions={validation['resolved_abstention']} "
        f"pending_abstentions={validation['pending_abstention']} "
        f"invalid={validation['invalid_artifact']}"
    )
    precision = summary["decided_proposal_precision"]
    console.print(
        "Decided proposal precision: "
        + (f"{precision:.4f}" if precision is not None else "not yet measurable")
    )
    console.print("This command is read-only; registry mutations=0.")


@identity_app.command(
    "detach-speaker-observation",
    help="Append a reviewed detachment without deleting membership history.",
)
def detach_speaker_observation(
    youtube_video_id: str = typer.Argument(..., help="Observation's YouTube video ID."),
    profile_id: int = typer.Option(..., help="Anonymous profile to detach."),
    reviewer: str = typer.Option(..., help="Stable human reviewer identifier."),
    reason: str = typer.Option(..., help="Review reason for the detachment."),
    review_event_key: str | None = typer.Option(
        None, help="Optional stable key for explicit idempotent replay."
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    video = database.get_video_by_youtube_id(youtube_video_id)
    observation = (
        database.get_latest_speaker_observation_for_video(video.id)
        if video is not None
        else None
    )
    if observation is None:
        raise typer.BadParameter(
            f"{youtube_video_id} has no immutable speaker observation"
        )
    event_key = review_event_key or (
        f"anonymous-speaker-detach-v1:{observation.input_fingerprint}:"
        f"{profile_id}:{reviewer}:{reason}"
    )
    try:
        record_observation_review(
            database,
            profile_id=profile_id,
            observation_id=observation.id,
            attach=False,
            reviewer=reviewer,
            reason=reason,
            review_event_key=event_key,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print(
        f"Detached observation #{observation.id} from profile #{profile_id}; "
        "prior events remain replayable."
    )


@identity_app.command(
    "record-speaker-difference",
    help="Record or clear an explicitly reviewed different-speaker constraint.",
)
def record_speaker_difference(
    video_a: str = typer.Argument(..., help="First reviewed YouTube video ID."),
    video_b: str = typer.Argument(..., help="Second reviewed YouTube video ID."),
    reviewer: str = typer.Option(..., help="Stable human reviewer identifier."),
    reason: str = typer.Option(..., help="Evidence-backed review reason."),
    different: bool = typer.Option(
        True,
        "--different/--clear",
        help="Assert or clear the effective constraint without deleting history.",
    ),
    review_event_key: str | None = typer.Option(
        None, help="Optional stable key for explicit idempotent replay."
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    videos = [
        database.get_video_by_youtube_id(value) for value in (video_a, video_b)
    ]
    observations = [
        database.get_latest_speaker_observation_for_video(video.id)
        if video is not None
        else None
        for video in videos
    ]
    if observations[0] is None or observations[1] is None:
        raise typer.BadParameter(
            "Both videos require immutable speaker observations"
        )
    action = "assert" if different else "clear"
    event_key = review_event_key or (
        f"speaker-difference-v1:{observations[0].input_fingerprint}:"
        f"{observations[1].input_fingerprint}:{action}:{reviewer}:{reason}"
    )
    try:
        record_observation_difference(
            database,
            observation_a_id=observations[0].id,
            observation_b_id=observations[1].id,
            different=different,
            reviewer=reviewer,
            reason=reason,
            review_event_key=event_key,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print(
        f"{'Recorded' if different else 'Cleared'} explicit different-speaker "
        "constraint; append-only history was preserved."
    )


@identity_app.command(
    "prepare-speaker-review-audio",
    help="Prewarm deterministic speech-qualified clips without creating review drafts.",
)
def prepare_speaker_review_audio(
    evaluation_scope: str = typer.Option(
        "validation",
        "--evaluation-scope",
        help="Prepare observations from validation, development, held_out, or all families.",
    ),
    limit: int | None = typer.Option(
        None,
        "--limit",
        min=1,
        help="Prepare at most this many observations; default prepares the full scope.",
    ),
    cache_dir: Path = typer.Option(
        Path("evaluation/speaker-pairs/cache"),
        help="Ignored exact-span audio cache shared with pair review.",
    ),
    source_family_registry: Path = typer.Option(
        Path("evaluation/source-families.json"),
        help="Frozen source-family registry used for partition scoping.",
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    allowed_scopes = {"all", "development", "validation", "held_out"}
    if evaluation_scope not in allowed_scopes:
        raise typer.BadParameter(
            "evaluation scope must be one of: all, development, validation, held_out"
        )
    paths = build_paths(base_dir)
    if not paths.database.exists():
        raise typer.BadParameter(f"Application database does not exist: {paths.database}")
    database = Database(paths.database, readonly=True)
    verification_cache = MediaVerificationCache(cache_dir.expanduser().resolve())
    try:
        registry = load_source_family_registry(
            source_family_registry.expanduser().resolve()
        )
        inputs: list[tuple[str, SpeakerObservation, MediaArtifact, Path]] = []
        unregistered_source_urls: set[str] = set()
        for video in database.list_videos():
            source = database.get_source_by_id(video.source_id)
            if source is None:
                continue
            family = registry.resolve_source_url(source.url)
            if family is None:
                unregistered_source_urls.add(source.url)
                continue
            if (
                evaluation_scope != "all"
                and family.partition.value != evaluation_scope
            ):
                continue
            eligibility = assess_automatic_speaker_observation(
                database,
                video.id,
                verification_cache=verification_cache,
            )
            if not eligibility.eligible:
                continue
            observation = eligibility.observation
            media = eligibility.media_artifact
            assert observation is not None
            assert media is not None
            inputs.append(
                (video.youtube_video_id, observation, media, Path(media.artifact_path))
            )
        inputs.sort(key=lambda item: item[1].input_fingerprint)
        if limit is not None:
            inputs = inputs[:limit]
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise typer.BadParameter(str(error)) from error
    if not inputs:
        raise typer.BadParameter(
            f"no eligible observations found in evaluation scope {evaluation_scope}"
        )

    span_cache = AudioSpanCache(cache_dir.expanduser().resolve())
    prepared_count = 0
    insufficient_count = 0
    failed_count = 0
    for index, (youtube_video_id, observation, media, audio_path) in enumerate(
        inputs,
        start=1,
    ):
        try:
            prepared = prepare_review_observation(
                observation=observation,
                audio_path=audio_path,
                span_cache=span_cache,
            )
            write_canonical_clip_preparation_manifest(
                paths,
                media,
                observation,
                clip_paths=tuple(Path(span.wav_path) for span in prepared.spans),
            )
        except InsufficientSpeechActivityError as error:
            insufficient_count += 1
            console.print(
                f"[{index}/{len(inputs)}] {youtube_video_id}: insufficient "
                f"({error.summary['qualified_clip_count']}/"
                f"{error.summary['minimum_clip_count']} clips)"
            )
            continue
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
            failed_count += 1
            console.print(
                f"[{index}/{len(inputs)}] {youtube_video_id}: failed "
                f"({type(error).__name__}: {error})"
            )
            continue
        prepared_count += 1
        cache_hits = sum(span.cache_hit for span in prepared.spans)
        console.print(
            f"[{index}/{len(inputs)}] {youtube_video_id}: prepared "
            f"({len(prepared.spans)} clips; qualified cache hits={cache_hits})"
        )
    if unregistered_source_urls:
        console.print(
            f"Skipped {len(unregistered_source_urls)} unregistered source(s)."
        )
    console.print(
        f"Review audio preparation complete: prepared={prepared_count} "
        f"insufficient={insufficient_count} failed={failed_count}; "
        "no drafts or review events were created."
    )


@identity_app.command(
    "prepare-actionable-review-audio",
    help=(
        "Precompute exact clips for current automation-readiness and "
        "profile-growth nominations without creating drafts."
    ),
)
def prepare_actionable_review_audio_command(
    limit: int = typer.Option(
        24,
        "--limit",
        min=1,
        help="Maximum unique nominated observations to prepare.",
    ),
    cache_dir: Path = typer.Option(
        Path("evaluation/speaker-pairs/cache"),
        help="Ignored exact-span audio cache shared with pair review.",
    ),
    discovery_root: Path = typer.Option(
        Path("evaluation/speaker-profile-discovery/shadow-runs"),
        help="Discovery artifacts used to prioritize review observations.",
    ),
    association_root: Path = typer.Option(
        Path("evaluation/speaker-associations/shadow-runs"),
        help="Association artifacts used to prioritize review observations.",
    ),
    base_dir: Path | None = typer.Option(
        None,
        help="Override app data directory.",
    ),
) -> None:
    paths = build_paths(base_dir)
    if not paths.database.exists():
        raise typer.BadParameter(
            f"Application database does not exist: {paths.database}"
        )
    discovery_reports = list(
        discovery_root.expanduser().resolve().glob("*/*.json")
    )
    latest_discovery = (
        max(
            discovery_reports,
            key=lambda path: (path.stat().st_mtime_ns, str(path)),
        )
        if discovery_reports
        else None
    )
    association_reports = tuple(
        association_root.expanduser().resolve().glob("*/*.json")
    )
    console.print(
        "Actionable review preprocessing: "
        f"association_artifacts={len(association_reports)} "
        f"discovery_report={latest_discovery or 'none'}."
    )
    try:
        database = Database(paths.database, readonly=True)
        console.print(
            "Actionable review preprocessing: assessing profile readiness."
        )
        reviewed_evidence = load_reviewed_speaker_evidence(
            Path("evaluation/speaker-pairs").resolve()
        )
        automatic_profile_ready_ids = frozenset(
            item.profile_id
            for item in assess_profile_association_readiness(
                database,
                reviewed_evidence,
            )
            if item.automatic_profile_ready
        )
        result = _prepare_actionable_review_audio(
            database,
            paths,
            discovery_report=latest_discovery,
            association_reports=association_reports,
            cache_dir=cache_dir,
            limit=limit,
            automatic_profile_ready_ids=automatic_profile_ready_ids,
            association_progress_callback=(
                lambda index, total, _path: console.print(
                    "Actionable review preprocessing: association artifact "
                    f"{index}/{total}."
                )
                if index == 1 or index == total or index % 50 == 0
                else None
            ),
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise typer.BadParameter(str(error)) from error
    console.print(
        "Actionable review audio preparation complete: "
        f"requested={result.requested} prepared={result.prepared} "
        f"cached={result.already_cached} excluded={result.excluded} "
        f"failed={result.failed}; no drafts or review events were created."
    )


@identity_app.command(
    "review-next-speaker-pair",
    help="Deterministically nominate and adjudicate the next unseen speaker pair.",
)
def review_next_speaker_pair(
    reviewer: str | None = typer.Option(None, help="Stable human reviewer identifier."),
    evaluation_root: Path = typer.Option(
        Path("evaluation/speaker-pairs"), help="Speaker-pair drafts, reviews, and fixtures root."
    ),
    cache_dir: Path = typer.Option(
        Path("evaluation/speaker-pairs/cache"), help="Ignored exact-span audio cache."
    ),
    source_family_registry: Path = typer.Option(
        Path("evaluation/source-families.json"),
        help="Frozen source-family registry used for partition-safe pair nomination.",
    ),
    open_packet: bool = typer.Option(
        True, "--open-packet/--no-open-packet", help="Open the local HTML review packet."
    ),
    prepare_only: bool = typer.Option(
        False, "--prepare-only", help="Create the selected packet without prompting for adjudication."
    ),
    evaluation_scope: str = typer.Option(
        "all",
        "--evaluation-scope",
        help="Nominate only from all, development, validation, or held_out source families.",
    ),
    selection_objective: SelectionGoal = typer.Option(
        SelectionGoal.EVALUATION,
        "--selection-objective",
        help=(
            "Use evaluation for the tuned fixture selector or profile-growth "
            "for reviewed component expansion; automation-readiness first "
            "reviews immediate and staged discovery frontiers, then resolves "
            "overlaps and reinforces profiles."
        ),
    ),
    profile_id: int | None = typer.Option(
        None,
        "--profile-id",
        min=1,
        help=(
            "Constrain profile-growth nomination to a specific canonical "
            "speaker profile."
        ),
    ),
    discovery_report: Path | None = typer.Option(
        None,
        "--discovery-report",
        exists=True,
        dir_okay=False,
        readable=True,
        help=(
            "Optional exact discovery artifact for automation-readiness or "
            "profile-growth acoustic ranking."
        ),
    ),
    discovery_root: Path = typer.Option(
        Path("evaluation/speaker-profile-discovery/shadow-runs"),
        help="Discovery artifacts used by automation-readiness nomination.",
    ),
    association_root: Path = typer.Option(
        Path("evaluation/speaker-associations/shadow-runs"),
        help=(
            "Shadow-association artifacts used for contextual profile-match "
            "confirmation nominations."
        ),
    ),
    observation_consistency_report: Path = typer.Option(
        Path(
            "evaluation/speaker-pairs/runs/"
            "observation-consistency-v1.json"
        ),
        help=(
            "Optional threshold-free consistency scores used only for "
            "balanced nomination ranking."
        ),
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    paths = build_paths(base_dir)
    if not paths.database.exists():
        raise typer.BadParameter(f"Application database does not exist: {paths.database}")
    database = Database(paths.database, readonly=True)
    if profile_id is not None and selection_objective != SelectionGoal.PROFILE_GROWTH:
        raise typer.BadParameter(
            "--profile-id requires --selection-objective profile-growth"
        )
    target_profile_id = None
    if profile_id is not None:
        try:
            target_profile_id = database.resolve_speaker_profile_id(profile_id)
        except ValueError as error:
            raise typer.BadParameter(str(error)) from error
        if target_profile_id != profile_id:
            console.print(
                f"Resolved speaker profile #{profile_id} to canonical "
                f"profile #{target_profile_id}."
            )
    root = evaluation_root.expanduser().resolve()
    verification_cache = MediaVerificationCache(cache_dir.expanduser().resolve())
    prewarmed_fingerprints = _load_actionable_review_prewarm(cache_dir)
    use_prewarmed_pool = bool(prewarmed_fingerprints) and target_profile_id is None
    if use_prewarmed_pool:
        console.print(
            "Speaker pair selection: using prewarmed pool with "
            f"{len(prewarmed_fingerprints)} observation(s)."
        )
    elif target_profile_id is not None:
        console.print(
            f"Speaker pair selection: targeting profile {target_profile_id}; "
            "the selected pair will be prepared on demand."
        )
    elif selection_objective in {
        SelectionGoal.AUTOMATION_READINESS,
        SelectionGoal.PROFILE_GROWTH,
    }:
        raise typer.BadParameter(
            "No prepared actionable review pool is available. Refresh it "
            "before reviewing:\n"
            "pte identity prepare-actionable-review-audio "
            f"--base-dir {shlex.quote(str(paths.root))}"
        )
    else:
        console.print(
            "Speaker pair selection: no prewarmed pool is available; "
            "building the evaluation selection from the corpus."
        )
    try:
        allowed_scopes = {"all", "development", "validation", "held_out"}
        if evaluation_scope not in allowed_scopes:
            raise ValueError(
                "evaluation scope must be one of: all, development, validation, held_out"
            )
        registry = load_source_family_registry(
            source_family_registry.expanduser().resolve()
        )
        drafts = _load_json_artifacts(sorted((root / "drafts").glob("*.json")))
        reviews = _load_json_artifacts(sorted((root / "reviews").glob("*/*.json")))
        fixtures = _load_json_artifacts(sorted((root / "fixtures").glob("*.json")))
        history = selection_history_from_artifacts(
            drafts=drafts,
            reviews=reviews,
            fixtures=fixtures,
            current_clip_activity_policy_version=(
                CLIP_ACTIVITY_POLICY_VERSION
            ),
        )
        lineage_review_candidate = (
            select_superseded_profile_member_review(
                database,
                profile_id=target_profile_id,
                excluded_pairs=history.excluded_pairs,
            )
            if target_profile_id is not None
            else None
        )
        automatic_profile_ready_ids = frozenset()
        if selection_objective in {
            SelectionGoal.AUTOMATION_READINESS,
            SelectionGoal.PROFILE_GROWTH,
        }:
            evidence = load_reviewed_speaker_evidence(root)
            automatic_profile_ready_ids = frozenset(
                profile.profile_id
                for profile in assess_profile_association_readiness(
                    database,
                    evidence,
                )
                if profile.automatic_profile_ready
            )
        effective_discovery_report = (
            discovery_report.expanduser().resolve()
            if discovery_report is not None
            else None
        )
        if (
            selection_objective
            in {
                SelectionGoal.AUTOMATION_READINESS,
                SelectionGoal.PROFILE_GROWTH,
            }
            and effective_discovery_report is None
        ):
            discovery_reports = list(
                discovery_root.expanduser().resolve().glob("*/*.json")
            )
            if discovery_reports:
                effective_discovery_report = max(
                    discovery_reports,
                    key=lambda path: (path.stat().st_mtime_ns, str(path)),
                )
        discovery_resolution_pairs = (
            load_discovery_resolution_pairs(effective_discovery_report)
            if (
                selection_objective == SelectionGoal.AUTOMATION_READINESS
                and effective_discovery_report is not None
            )
            else ()
        )
        profile_growth_acoustic_pairs = (
            load_discovery_acoustic_ranking_pairs(
                effective_discovery_report
            )
            if (
                selection_objective
                in {
                    SelectionGoal.PROFILE_GROWTH,
                    SelectionGoal.AUTOMATION_READINESS,
                }
                and effective_discovery_report is not None
            )
            else ()
        )
        missing_discovery_reviewed_constraints = 0
        if (
            selection_objective == SelectionGoal.PROFILE_GROWTH
            and effective_discovery_report is not None
        ):
            missing_discovery_reviewed_constraints = (
                count_missing_discovery_reviewed_constraints(
                    effective_discovery_report,
                    history.reviewed_identity_outcomes or {},
                )
            )
            if missing_discovery_reviewed_constraints:
                profile_growth_acoustic_pairs = tuple(
                    ranking
                    for ranking in profile_growth_acoustic_pairs
                    if ranking.outcome == "same_speaker"
                )
        association_confirmation_pairs = ()
        unmatched_association_fingerprints = frozenset()
        machine_report: Mapping[str, Any] | None = None
        if selection_objective in {
            SelectionGoal.PROFILE_GROWTH,
            SelectionGoal.AUTOMATION_READINESS,
        }:
            machine_report = machine_assignment_report(database)
            reviewable_machine_keys = {
                (
                    str(item["candidate_input_fingerprint"]),
                    int(item["profile_id"]),
                )
                for item in machine_report["assignments"]
                if item["state"]
                in {"active", "awaiting_activation", "blocked_policy"}
            }
            active_machine_keys = {
                (
                    str(row["candidate_input_fingerprint"]),
                    database.resolve_speaker_profile_id(
                        int(row["profile_id"])
                    ),
                )
                for row in active_machine_assignment_evidence(database)
            }
            association_cache_path = (
                cache_dir.expanduser().resolve()
                / "selector-context"
                / "association-nominations-v1.json"
            )
            prepared_association_context = (
                load_prepared_shadow_association_context(
                    association_cache_path
                )
                if use_prewarmed_pool
                else None
            )
            association_paths = (
                ()
                if use_prewarmed_pool
                else tuple(
                    association_root.expanduser().resolve().glob("*/*.json")
                )
            )
            prepared_nominations = (
                prepared_association_context[0]
                if prepared_association_context is not None
                else ()
            )
            current_association_nominations = []
            nominations = (
                prepared_nominations
                if use_prewarmed_pool
                else load_shadow_association_confirmation_pairs(
                    association_paths,
                    cache_path=association_cache_path,
                    progress_callback=(
                        lambda index, total, _path: console.print(
                            "Speaker pair selection: association artifact "
                            f"{index}/{total}."
                        )
                        if index == 1 or index == total or index % 50 == 0
                        else None
                    ),
                )
            )
            for nomination in nominations:
                try:
                    canonical_profile_id = (
                        database.resolve_speaker_profile_id(
                            nomination.profile_id
                        )
                    )
                except ValueError:
                    continue
                current_association_nominations.append(
                    replace(
                        nomination,
                        profile_id=canonical_profile_id,
                        provisional_assignment_active=(
                            (
                                nomination.candidate_fingerprint,
                                canonical_profile_id,
                            )
                            in active_machine_keys
                        ),
                        machine_assignment_reviewable=(
                            (
                                nomination.candidate_fingerprint,
                                canonical_profile_id,
                            )
                            in reviewable_machine_keys
                        ),
                    )
                )
            association_confirmation_pairs = tuple(
                current_association_nominations
            )
            unmatched_association_fingerprints = (
                prepared_association_context[1]
                if prepared_association_context is not None
                else (
                    frozenset()
                    if use_prewarmed_pool
                    else load_unmatched_association_fingerprints(
                        association_paths,
                        cache_path=association_cache_path,
                    )
                )
            )
        consistency_index = load_consistency_score_index(
            observation_consistency_report.expanduser().resolve()
        )
        different_fingerprints_by_observation_id: dict[int, set[str]] = {}
        for observation_a_id, observation_b_id in (
            database.list_effective_observation_difference_pairs()
        ):
            observation_a = database.get_speaker_observation(observation_a_id)
            observation_b = database.get_speaker_observation(observation_b_id)
            if observation_a is None or observation_b is None:
                continue
            different_fingerprints_by_observation_id.setdefault(
                observation_a_id, set()
            ).add(observation_b.input_fingerprint)
            different_fingerprints_by_observation_id.setdefault(
                observation_b_id, set()
            ).add(observation_a.input_fingerprint)

        candidates: list[PairCandidateObservation] = []
        unregistered_source_urls: set[str] = set()
        configured_bootstrap_by_source_id: dict[
            int, tuple[int, str] | None
        ] = {}
        prewarmed_video_ids = {
            observation.video_id
            for fingerprint in prewarmed_fingerprints
            if (
                observation := database.get_speaker_observation_by_fingerprint(
                    fingerprint
                )
            )
            is not None
        }
        for video in database.list_videos():
            if use_prewarmed_pool and video.id not in prewarmed_video_ids:
                continue
            source = database.get_source_by_id(video.source_id)
            if source is None:
                continue
            family = registry.resolve_source_url(source.url)
            if family is None:
                unregistered_source_urls.add(source.url)
                continue
            if (
                evaluation_scope != "all"
                and family.partition.value != evaluation_scope
            ):
                continue
            eligibility = assess_automatic_speaker_observation(
                database,
                video.id,
                verification_cache=verification_cache,
                verify_media=False,
            )
            if not eligibility.eligible:
                continue
            observation = eligibility.observation
            media = eligibility.media_artifact
            assert observation is not None
            assert media is not None
            claims = database.list_speaker_name_claims_for_video(video.id)
            title_hint = title_byline_selection_hint(video.title)
            if source.id not in configured_bootstrap_by_source_id:
                bootstrap: tuple[int, str] | None = None
                if source.pastor_id is not None:
                    configured_profile_id = (
                        database.get_pastor_speaker_profile_id(
                            source.pastor_id
                        )
                    )
                    pastor = database.get_pastor_by_id(source.pastor_id)
                    if (
                        configured_profile_id is not None
                        and pastor is not None
                    ):
                        canonical_profile_id = (
                            database.resolve_speaker_profile_id(
                                configured_profile_id
                            )
                        )
                        if not database.list_effective_observation_ids_for_profile(
                            canonical_profile_id
                        ):
                            bootstrap = (
                                canonical_profile_id,
                                pastor.display_name,
                            )
                configured_bootstrap_by_source_id[source.id] = bootstrap
            configured_bootstrap = configured_bootstrap_by_source_id[
                source.id
            ]
            configured_title_hint = (
                configured_target_title_selection_hint(
                    video.title,
                    configured_bootstrap[1],
                )
                if configured_bootstrap is not None
                else None
            )
            names = frozenset(
                claim.normalized_name
                for claim in claims
                if claim.observation_id == observation.id
                and claim.explicit_speaker_attribution
                and claim.normalized_name.strip()
            ) | (frozenset((title_hint,)) if title_hint else frozenset()) | (
                frozenset((configured_title_hint,))
                if configured_title_hint
                else frozenset()
            )
            reviewed_profile_ids = frozenset(
                database.resolve_speaker_profile_id(profile_id)
                for profile_id in (
                    database.list_effective_profile_ids_for_observation(
                        observation.id
                    )
                )
            )
            superseded_profile_ids = frozenset(
                database.resolve_speaker_profile_id(profile_id)
                for profile_id in (
                    database.list_effective_profile_ids_for_superseded_observations(
                        video_id=video.id,
                        current_observation_id=observation.id,
                    )
                )
            ) - reviewed_profile_ids
            candidate = PairCandidateObservation(
                input_fingerprint=observation.input_fingerprint,
                video_id=video.youtube_video_id,
                recording_date=video.published_at,
                explicit_attributions=names,
                quality_signature=(
                    media.format_name,
                    media.sample_rate_hz,
                    media.channel_count,
                ),
                source_family_id=family.source_family_id,
                evaluation_partition=family.partition.value,
                reviewed_profile_ids=reviewed_profile_ids,
                superseded_profile_ids=superseded_profile_ids,
                explicitly_different_from=frozenset(
                    different_fingerprints_by_observation_id.get(
                        observation.id, set()
                    )
                ),
                observation_consistency_score=consistency_index.scores.get(
                    observation.input_fingerprint
                ),
                configured_profile_bootstrap_id=(
                    configured_bootstrap[0]
                    if configured_bootstrap is not None
                    else None
                ),
                configured_target_title_match=bool(
                    configured_title_hint
                ),
            )
            candidates.append(candidate)

        lineage_selection: PairSelection | None = None
        if lineage_review_candidate is not None:
            lineage_observations = [
                database.get_speaker_observation(observation_id)
                for observation_id in (
                    lineage_review_candidate.anchor_observation_id,
                    lineage_review_candidate.replacement_observation_id,
                )
            ]
            if all(observation is not None for observation in lineage_observations):
                exact_candidates: list[PairCandidateObservation] = []
                for observation in lineage_observations:
                    assert observation is not None
                    video = database.get_video_by_id(observation.video_id)
                    source = (
                        database.get_source_by_id(video.source_id)
                        if video is not None
                        else None
                    )
                    if video is None or source is None:
                        exact_candidates = []
                        break
                    family = registry.resolve_source_url(source.url)
                    exact_candidates.append(
                        PairCandidateObservation(
                            input_fingerprint=observation.input_fingerprint,
                            video_id=video.youtube_video_id,
                            recording_date=video.published_at,
                            explicit_attributions=frozenset(
                                claim.normalized_name
                                for claim in (
                                    database.list_speaker_name_claims_for_video(
                                        video.id
                                    )
                                )
                                if claim.observation_id == observation.id
                                and claim.explicit_speaker_attribution
                                and claim.normalized_name.strip()
                            ),
                            source_family_id=(
                                family.source_family_id
                                if family is not None
                                else None
                            ),
                            evaluation_partition=(
                                family.partition.value
                                if family is not None
                                else None
                            ),
                            reviewed_profile_ids=frozenset(
                                database.resolve_speaker_profile_id(value)
                                for value in (
                                    database.list_effective_profile_ids_for_observation(
                                        observation.id
                                    )
                                )
                            ),
                            explicitly_different_from=frozenset(
                                different_fingerprints_by_observation_id.get(
                                    observation.id, set()
                                )
                            ),
                        )
                    )
                if len(exact_candidates) == 2 and (
                    evaluation_scope == "all"
                    or all(
                        item.evaluation_partition == evaluation_scope
                        for item in exact_candidates
                    )
                ):
                    observation_a, observation_b = exact_candidates
                    shared_attributions = sorted(
                        observation_a.explicit_attributions
                        & observation_b.explicit_attributions
                    )
                    source_relation = (
                        "same_source_family"
                        if observation_a.source_family_id is not None
                        and observation_a.source_family_id
                        == observation_b.source_family_id
                        else "cross_source_family"
                    )
                    lineage_selection = PairSelection(
                        observation_a=observation_a,
                        observation_b=observation_b,
                        manifest={
                            "selector_version": (
                                "speaker_pair_selector_lineage_bridge_v1"
                            ),
                            "selection_origin": "automatic",
                            "selected_observation_fingerprints": {
                                "a": observation_a.input_fingerprint,
                                "b": observation_b.input_fingerprint,
                            },
                            "selection_goal": "profile-growth",
                            "selection_objective": (
                                lineage_review_candidate.selection_kind
                            ),
                            "selection_stratum": (
                                "shared_attribution"
                                if shared_attributions
                                else "unattributed"
                            ),
                            "source_relation": source_relation,
                            "source_family_ids": {
                                "a": observation_a.source_family_id,
                                "b": observation_b.source_family_id,
                            },
                            "evaluation_partitions": {
                                "a": observation_a.evaluation_partition,
                                "b": observation_b.evaluation_partition,
                            },
                            "evaluation_scope": (
                                evaluation_scope
                                if evaluation_scope != "all"
                                else "all_partitions"
                            ),
                            "target_profile_id": target_profile_id,
                            "reason_codes": [
                                lineage_review_candidate.selection_kind,
                                "superseded_profile_lineage",
                                "human_review_required",
                            ],
                            "profile_consolidation": {
                                "profile_ids": sorted(
                                    value
                                    for value in (
                                        lineage_review_candidate.profile_id,
                                        lineage_review_candidate.successor_profile_id,
                                    )
                                    if value is not None
                                ),
                                "shared_explicit_attributions": (
                                    list(
                                        lineage_review_candidate.shared_normalized_names
                                    )
                                ),
                                "role": "human_review_nomination_only",
                                "identity_evidence": False,
                                "known_cross_profile_difference": False,
                                "membership_firewall": (
                                    "approved_pair_review_required"
                                ),
                            },
                        },
                    )

        def select_pair(
            remaining: Sequence[PairCandidateObservation],
        ) -> PairSelection:
            return select_next_speaker_pair(
                remaining,
                history,
                evaluation_partition=(
                    None if evaluation_scope == "all" else evaluation_scope
                ),
                selection_goal=selection_objective,
                discovery_resolution_pairs=discovery_resolution_pairs,
                profile_growth_acoustic_pairs=profile_growth_acoustic_pairs,
                association_confirmation_pairs=association_confirmation_pairs,
                automatic_profile_ready_ids=automatic_profile_ready_ids,
                unmatched_association_fingerprints=(
                    unmatched_association_fingerprints
                ),
                target_profile_id=target_profile_id,
            )

        verified_selection = None
        try:
            if lineage_selection is not None:
                selection = lineage_selection
            else:
                verified_selection = select_verified_automatic_speaker_pair(
                    database,
                    candidates,
                    select_pair=select_pair,
                    verification_cache=verification_cache,
                )
                selection = verified_selection.selection
        except ValueError as error:
            if use_prewarmed_pool:
                raise ValueError(
                    "prepared actionable review pool is exhausted or stale; "
                    "refresh it with:\n"
                    "pte identity prepare-actionable-review-audio "
                    f"--base-dir {shlex.quote(str(paths.root))}"
                ) from error
            if (
                selection_objective == SelectionGoal.PROFILE_GROWTH
                and missing_discovery_reviewed_constraints
                and "no actionable profile-growth pair" in str(error)
            ):
                raise ValueError(
                    "profile-growth discovery context is stale after "
                    f"{missing_discovery_reviewed_constraints} reviewed "
                    "same/different constraint(s); run `pte identity run --all "
                    f"--base-dir {paths.root}`, then retry"
                ) from error
            raise
        selection.manifest["media_verification_scope"] = (
            "review_packet_preparation"
            if verified_selection is None
            else "selected_pair"
        )
        selection.manifest["media_verification_attempts"] = (
            0
            if verified_selection is None
            else verified_selection.selection_attempts
        )
        if (
            verified_selection is not None
            and verified_selection.rejection_counts
        ):
            selection.manifest["media_verification_rejections"] = dict(
                sorted(verified_selection.rejection_counts.items())
            )
        if (
            consistency_index.report_sha256
            and selection.manifest.get("observation_consistency_scores")
        ):
            selection.manifest[
                "observation_consistency_report_sha256"
            ] = consistency_index.report_sha256
        if unregistered_source_urls:
            selection.manifest["unregistered_source_count"] = len(
                unregistered_source_urls
            )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise typer.BadParameter(str(error)) from error

    if selection.manifest.get("unregistered_source_count"):
        console.print(
            f"Skipped {selection.manifest['unregistered_source_count']} unregistered "
            "source(s); run `pte sync-source-families` before nomination."
        )
    console.print(
        f"Selected scope={selection.manifest['evaluation_scope']} "
        f"goal={selection.manifest['selection_goal']} "
        f"objective={selection.manifest['selection_objective']} "
        f"{selection.manifest['selection_stratum']}/"
        f"{selection.manifest['source_relation']} pair "
        f"({selection.observation_a.video_id}, {selection.observation_b.video_id}); "
        f"reasons={','.join(selection.manifest['reason_codes'])}"
    )
    consolidation = selection.manifest.get("profile_consolidation")
    if isinstance(consolidation, dict) and machine_report is not None:
        consolidation_profile_ids = consolidation.get("profile_ids")
        if isinstance(consolidation_profile_ids, list):
            consolidation["machine_assignment_safety"] = (
                _machine_safety_for_profiles(
                    machine_report,
                    [
                        value
                        for value in consolidation_profile_ids
                        if isinstance(value, int)
                    ],
                )
            )
    review_speaker_pair(
        video_a=selection.observation_a.video_id,
        video_b=selection.observation_b.video_id,
        reviewer=reviewer,
        evaluation_root=evaluation_root,
        cache_dir=cache_dir,
        open_packet=open_packet,
        prepare_only=prepare_only,
        base_dir=base_dir,
        selection_manifest_json=json.dumps(selection.manifest, sort_keys=True),
        observation_fingerprint_a=(
            selection.observation_a.input_fingerprint
        ),
        observation_fingerprint_b=(
            selection.observation_b.input_fingerprint
        ),
    )


def _path_status(path: Path) -> str:
    return "ok" if path.exists() else "missing"


def _tool_status(command: str) -> tuple[str, str]:
    resolved = shutil.which(command)
    if resolved is None:
        local_candidate = Path(sys.executable).parent / command
        if local_candidate.exists():
            resolved = str(local_candidate)
    return (resolved or command, "ok" if resolved else "missing")


def _package_status(distribution: str) -> tuple[str, str]:
    try:
        return (importlib_metadata.version(distribution), "ok")
    except importlib_metadata.PackageNotFoundError:
        return ("not installed", "missing")


def _default_transcribe_jobs() -> int:
    return _workflow_default_transcribe_jobs()


def _prepare_transcription_task(
    database: Database,
    paths,
    tools,
    video_id: int,
    stage_callback=None,
    allow_network: bool = True,
) -> PreparedTranscriptInput:
    return prepare_transcription_input(
        database,
        paths,
        tools,
        video_id,
        stage_callback=stage_callback,
        allow_network=allow_network,
    )


def _complete_transcription_task(
    database: Database,
    tools,
    prepared: PreparedTranscriptInput,
    progress_callback=None,
    stage_callback=None,
) -> None:
    complete_transcription_video(
        database,
        tools,
        prepared,
        progress_callback=progress_callback,
        stage_callback=stage_callback,
    )


class _TranscriptionRenderer:
    def __init__(self) -> None:
        self._terminal = console.is_terminal
        self._lock = Lock()
        self._progress: Progress | None = None
        self._task_ids: dict[int, TaskID] = {}
        self._started_video_ids: set[int] = set()

    def close(self) -> None:
        with self._lock:
            if self._progress is not None:
                self._progress.__exit__(None, None, None)
                self._progress = None
                self._task_ids.clear()
                self._started_video_ids.clear()

    def __call__(self, event: TranscriptionEvent) -> None:
        if isinstance(event, TranscriptionMessage):
            console.print(event.text)
        elif isinstance(event, TranscriptionBatchStarted):
            console.print(
                f"Transcribing {event.total} video(s) with {event.workers} worker(s)."
            )
            if self._terminal:
                self._start_progress()
        elif isinstance(event, TranscriptionVideoQueued):
            if not self._terminal:
                console.print(
                    f"[{event.index}/{event.total} queued] Transcribing video "
                    f"#{event.video_id}: {event.title}",
                    markup=False,
                )
        elif isinstance(event, TranscriptionTaskSubmitted):
            if self._terminal:
                self._add_task(event)
        elif isinstance(event, TranscriptionStageChanged):
            self._render_stage(event)
        elif isinstance(event, TranscriptionProgressed):
            self._render_progress(event)
        elif isinstance(event, TranscriptionVideoFinished):
            self._render_finished(event)
        elif isinstance(event, TranscriptionBatchFinished):
            self.close()
            result = event.result
            console.print(
                f"Transcribed {result.processed_count} video(s); "
                f"skipped {result.skipped_count}; failed {result.failed_count}."
            )
        elif isinstance(event, TranscriptionRetrying):
            console.print(
                f"Retrying {event.count} transcription failure(s) after the first pass."
            )

    def _start_progress(self) -> None:
        self.close()
        self._progress = Progress(
            TextColumn("{task.fields[status]:>7}", justify="right"),
            TextColumn("video #{task.fields[video_id]}"),
            TextColumn("{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            console=console,
            transient=False,
        )
        self._progress.__enter__()

    def _add_task(self, event: TranscriptionTaskSubmitted) -> None:
        with self._lock:
            if self._progress is None:
                return
            self._task_ids[event.video_id] = self._progress.add_task(
                event.title,
                total=100,
                completed=0,
                status=STAGE_QUEUED_PREP,
                video_id=event.video_id,
                start=False,
            )

    def _render_stage(self, event: TranscriptionStageChanged) -> None:
        if not self._terminal:
            console.print(
                f"[video #{event.video_id} stage] {event.stage}",
                markup=False,
            )
            return
        valid = {
            STAGE_QUEUED_PREP,
            STAGE_DOWNLOADING,
            STAGE_NORMALIZING,
            STAGE_QUEUED_TRANSCRIBE,
            STAGE_TRANSCRIBING,
            STAGE_DONE,
            STAGE_FAILED,
        }
        with self._lock:
            task_id = self._task_ids.get(event.video_id)
            if self._progress is None or task_id is None or event.stage not in valid:
                return
            if event.video_id not in self._started_video_ids:
                self._progress.start_task(task_id)
                self._started_video_ids.add(event.video_id)
            if event.stage == STAGE_TRANSCRIBING:
                self._progress.update(task_id, status=event.stage, completed=0)
            elif event.stage == STAGE_DONE:
                self._progress.update(task_id, status=event.stage, completed=100)
            else:
                self._progress.update(task_id, status=event.stage)

    def _render_progress(self, event: TranscriptionProgressed) -> None:
        if not self._terminal:
            console.print(
                f"[video #{event.video_id} progress] {event.percent}%",
                markup=False,
            )
            return
        with self._lock:
            task_id = self._task_ids.get(event.video_id)
            if self._progress is None or task_id is None:
                return
            update_kwargs: dict[str, object] = {"completed": event.percent}
            if event.video_id not in self._started_video_ids:
                update_kwargs["fields"] = {"status": "running"}
                self._started_video_ids.add(event.video_id)
            self._progress.update(task_id, **update_kwargs)

    def _render_finished(self, event: TranscriptionVideoFinished) -> None:
        if self._terminal:
            with self._lock:
                task_id = self._task_ids.pop(event.video_id, None)
                self._started_video_ids.discard(event.video_id)
                if self._progress is not None and task_id is not None:
                    self._progress.update(
                        task_id,
                        status=STAGE_FAILED if event.error else STAGE_DONE,
                        completed=100,
                    )
                    self._progress.remove_task(task_id)
            title = f" {event.title}" if event.error else f": {event.title}"
        else:
            title = ""
        if event.error:
            console.print(
                f"[{event.finished}/{event.total} finished] Failed to transcribe "
                f"video #{event.video_id}{title}: {event.error}",
                style="red",
                markup=False,
                highlight=False,
            )
        else:
            console.print(
                f"[{event.finished}/{event.total} finished] Transcribed "
                f"video #{event.video_id}{title}",
                markup=False,
                highlight=False,
            )

@app.command(
    "import-church-db",
    help="Import complete pastor/channel pairs from church-youtube-finder with stable provenance.",
)
def import_church_db(
    church_database: Path = typer.Argument(..., help="Path to the church-youtube-finder SQLite database."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report changes without importing records."),
    show_all: bool = typer.Option(False, help="Show unchanged records in addition to changes and conflicts."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    try:
        result = import_church_sources(
            database,
            church_database.expanduser().resolve(),
            dry_run=dry_run,
        )
    except (ChurchDatabaseImportError, OSError, ValueError) as error:
        raise typer.BadParameter(str(error)) from error

    table = Table(title="Church database import" + (" (dry run)" if dry_run else ""))
    table.add_column("Status")
    table.add_column("Church")
    table.add_column("Pastor")
    table.add_column("Source")
    table.add_column("Reason")
    for item in result.items:
        if item.status == "unchanged" and not show_all:
            continue
        table.add_row(
            item.status,
            item.record.church_name,
            item.record.pastor_name,
            item.record.channel_url,
            item.reason,
        )
    console.print(table)
    counts = ", ".join(
        f"{status}={count}" for status, count in sorted(result.counts.items())
    )
    console.print(f"Church import complete: {counts or 'no complete records'}.")


@app.command(
    "sync-imported-sources",
    help="Acquire recent transcripts and fallback audio for provenance-imported sources.",
)
def sync_imported_sources(
    provider: str = typer.Option(IMPORT_PROVIDER, help="Import provider to synchronize."),
    latest: int = typer.Option(6, min=1, help="Newest videos to retain per imported source."),
    jobs: int = typer.Option(
        _default_transcribe_jobs(),
        min=1,
        help="Concurrent local ASR and video extraction jobs.",
    ),
    download_jobs: int = typer.Option(
        DEFAULT_PREP_WORKERS,
        "--download-jobs",
        min=1,
        help="Concurrent audio download and normalization workers.",
    ),
    all_audio: bool = typer.Option(
        False,
        "--all-audio",
        help="Download and locally transcribe every eligible video, including captioned videos.",
    ),
    extract_new: bool = typer.Option(
        False,
        "--extract/--no-extract",
        help="Also create missing sermon extraction proposals for synchronized sources.",
    ),
    archive_sources: bool = typer.Option(
        False,
        "--archive-sources/--no-archive-sources",
        help=(
            "Register audio and queue verified source files to a background archive "
            "worker at the configured destination. Requires --extract."
        ),
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    app_paths = build_paths(base_dir, remember=True)
    try:
        sync_imported_sources_workflow(
            database,
            app_paths,
            SourceSyncRequest(
                provider=provider,
                latest=latest,
                jobs=jobs,
                download_jobs=download_jobs,
                all_audio=all_audio,
                extract_new=extract_new,
                archive_sources=archive_sources,
            ),
            base_dir=base_dir,
            progress_callback=lambda message: console.print(message, markup=False),
            dependencies=SourceSyncDependencies(
                list_imported_sources=imported_source_ids,
                discover=discover_sources_service,
                fetch_captions=fetch_captions_service,
                transcribe=transcribe_videos_service,
                extract=extract_batch,
                register_media=backfill_existing_media_artifacts,
                archive_source=archive_source_media,
                archive_lock_held=media_archive_lock_held,
                disk_usage=shutil.disk_usage,
                sleeper=time.sleep,
                minimum_free_fraction=MIN_SYNC_FREE_DISK_FRACTION,
                initial_wait_seconds=SYNC_ARCHIVE_WAIT_INITIAL_SECONDS,
                maximum_wait_seconds=SYNC_ARCHIVE_WAIT_MAX_SECONDS,
            ),
        )
    except SourceSyncConfigurationError as error:
        raise typer.BadParameter(str(error)) from error
    except SourceSyncDiskReserveError as error:
        raise typer.Exit(code=1) from error


@identity_app.command(
    "backfill",
    help="Create missing shadow identity and neutral speaker artifacts without reclassification.",
)
def identity_backfill(
    video_id: int | None = typer.Option(None, "--video-id", help="Only backfill one database video id."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    paths = build_paths(base_dir, remember=True)
    result = backfill_shadow_identity_assessments(database, paths, video_id=video_id)
    console.print(
        "Identity shadow backfill: "
        f"created {result.created}, reused {result.reused}, "
        f"skipped {result.skipped}, failed {result.failed}."
    )


@app.command(help="Validate local tool paths and app data directories.")
def doctor(
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    paths = build_paths(base_dir, remember=True)
    tools = build_tool_config()
    llm = build_llm_config()
    sermon_minimum = minimum_sermon_duration_seconds()
    sermon_maximum = maximum_sermon_duration_seconds()

    try:
        ensure_directories(paths)
        app_status = "ok"
    except PermissionError:
        app_status = "unwritable"

    rows = [
        ("app root", str(paths.root), app_status),
        ("database", str(paths.database), _path_status(paths.database)),
        ("pastors dir", str(paths.pastors), _path_status(paths.pastors)),
        ("whisper.cpp", str(tools.whisper_cpp_bin), _path_status(tools.whisper_cpp_bin)),
        ("whisper model", str(tools.whisper_model_path), _path_status(tools.whisper_model_path)),
        ("sermon minimum", f"{sermon_minimum:g} seconds", "configured"),
        ("sermon-video maximum", f"{sermon_maximum:g} seconds", "configured"),
    ]

    ffmpeg_resolved, ffmpeg_status = _tool_status(tools.ffmpeg_bin)
    yt_dlp_resolved, yt_dlp_status = _tool_status(tools.yt_dlp_bin)
    rows.append(("ffmpeg", ffmpeg_resolved, ffmpeg_status))
    rows.append(("yt-dlp", yt_dlp_resolved, yt_dlp_status))
    rows.append(
        (
            "yt-dlp js runtime",
            tools.yt_dlp_js_runtimes or "none detected",
            "ok" if tools.yt_dlp_js_runtimes else "missing",
        )
    )
    ejs_version, ejs_status = _package_status("yt-dlp-ejs")
    rows.append(("yt-dlp EJS solver", ejs_version, ejs_status))
    rows.append(("local LLM", llm.base_url, "enabled" if llm.enabled else "disabled"))
    rows.append(("local LLM model", llm.model, "configured" if llm.enabled else "inactive"))
    if llm.enabled:
        health = OllamaClient(llm).check_health()
        rows.append(("Ollama connectivity", health.detail, "ok" if health.reachable else "failed"))
        rows.append(("Ollama model installed", llm.model, "ok" if health.model_available else "failed"))
        rows.append(("Ollama structured output", health.detail, "ok" if health.structured_output else "failed"))

    table = Table(title="Doctor")
    table.add_column("Check")
    table.add_column("Resolved Path")
    table.add_column("Status")
    for check, resolved, status_value in rows:
        table.add_row(check, resolved, status_value)
    console.print(table)


def discover_sources_service(
    limit: int | None = DEFAULT_DISCOVER_LIMIT,
    all_videos: bool = False,
    source_id: int | None = None,
    base_dir: Path | None = None,
) -> DiscoveryServiceResult:
    return _discover_sources_service(
        limit,
        all_videos,
        source_id,
        base_dir,
        progress_callback=lambda message: console.print(message, markup=False),
        extract_videos=extract_discovered_videos,
    )


@app.command(help="Discover videos from queued sources with yt-dlp metadata.")
def discover(
    limit: int | None = typer.Option(
        DEFAULT_DISCOVER_LIMIT,
        "--limit",
        min=1,
        help="Only persist the first N discovered videos per source. Defaults to 26.",
    ),
    all_videos: bool = typer.Option(False, "--all", help="Persist all discovered videos for each source."),
    source_id: int | None = typer.Option(None, help="Only discover videos for a specific source id."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    discover_sources_service(limit, all_videos, source_id, base_dir)


def transcribe_videos_service(
    missing_only: bool = False,
    captions_missing_only: bool = True,
    jobs: int = DEFAULT_TRANSCRIBE_JOBS,
    source_id: int | None = None,
    base_dir: Path | None = None,
    prep_jobs: int = DEFAULT_PREP_WORKERS,
    video_ids: set[int] | None = None,
    allow_network: bool = True,
    _retry_failed_once: bool = True,
) -> TranscriptionResult:
    database = get_database(base_dir)
    app_paths = build_paths(base_dir, remember=True)
    renderer = _TranscriptionRenderer()
    try:
        return _transcribe_videos_service(
            missing_only=missing_only,
            captions_missing_only=captions_missing_only,
            jobs=jobs,
            source_id=source_id,
            base_dir=base_dir,
            prep_jobs=prep_jobs,
            video_ids=video_ids,
            allow_network=allow_network,
            _retry_failed_once=_retry_failed_once,
            event_callback=renderer,
            database=database,
            app_paths=app_paths,
            tool_config=build_tool_config(),
            prepare=_prepare_transcription_task,
            complete=_complete_transcription_task,
        )
    finally:
        renderer.close()
@app.command(help="Download or prepare local ASR transcripts for discovered videos.")
def transcribe(
    missing_only: bool = typer.Option(False, "--missing-only", help="Only transcribe videos without a local ASR artifact."),
    captions_missing_only: bool = typer.Option(
        True,
        "--captions-missing-only/--all-eligible",
        help="By default, only transcribe videos that do not already have a captions artifact. Use --all-eligible to transcribe all eligible videos.",
    ),
    jobs: int = typer.Option(
        _default_transcribe_jobs(),
        "--jobs",
        min=1,
        help="Number of videos to transcribe concurrently. Defaults to 2.",
    ),
    source_id: int | None = typer.Option(None, help="Only transcribe videos from a specific source id."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    transcribe_videos_service(missing_only, captions_missing_only, jobs, source_id, base_dir)


def fetch_captions_service(
    source_id: int | None = None,
    base_dir: Path | None = None,
    video_ids: set[int] | None = None,
    request_interval_seconds: float = 0.0,
    cookies_from_browser: str | None = None,
    cookies: Path | None = None,
) -> CaptionAcquisitionResult:
    return _fetch_captions_service(
        source_id=source_id,
        base_dir=base_dir,
        video_ids=video_ids,
        request_interval_seconds=request_interval_seconds,
        cookies_from_browser=cookies_from_browser,
        cookies=cookies,
        progress_callback=console.print,
        fetch_captions=fetch_captions_video,
        monotonic=time.monotonic,
        sleeper=time.sleep,
    )


@app.command(help="Fetch YouTube captions when available and persist them as transcript artifacts.")
def fetch(
    source_id: int | None = typer.Option(None, help="Only fetch captions for videos from a specific source id."),
    cookies_from_browser: str | None = typer.Option(
        None,
        "--cookies-from-browser",
        help="Pass an explicit browser profile to yt-dlp for YouTube authentication.",
    ),
    cookies: Path | None = typer.Option(
        None,
        "--cookies",
        exists=True,
        dir_okay=False,
        help="Pass an explicit Netscape-format cookie file to yt-dlp.",
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    try:
        fetch_captions_service(
            source_id,
            base_dir,
            cookies_from_browser=cookies_from_browser,
            cookies=cookies,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error


@app.command(help="Chunk transcript artifacts into reviewable segments and proposed Markdown.")
def extract(
    missing_only: bool = typer.Option(
        False,
        "--missing-only",
        help="Only extract videos without a proposed Markdown artifact.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Rebuild extraction artifacts even when a video is already marked extracted or exported.",
    ),
    source_id: int | None = typer.Option(None, help="Only extract videos from a specific source id."),
    classifier: str = typer.Option(
        "auto",
        "--classifier",
        help="Content classifier: auto, rules, or llm.",
    ),
    llm_model: str | None = typer.Option(None, "--llm-model", help="Override the configured local Ollama model."),
    recording_verifier_model: str = typer.Option(
        "gemma3:12b",
        "--recording-verifier-model",
        help="Ollama model used only for ambiguous recording-level decisions.",
    ),
    jobs: int = typer.Option(2, "--jobs", min=1, help="Concurrent video extraction jobs."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    paths = build_paths(base_dir, remember=True)
    try:
        result = extract_batch(
            database,
            paths,
            missing_only=missing_only,
            force=force,
            source_id=source_id,
            classifier=classifier,
            llm_model=llm_model,
            recording_verifier_model=recording_verifier_model,
            workers=jobs,
            event_callback=lambda message: console.print(message, markup=False),
            progress_callback=lambda stage, current, total: console.print(
                f"  {stage} block {current}/{total}"
            ),
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print(f"Extracted {result.processed} video(s); skipped {result.skipped}; failed {result.failed}.")


def _has_reusable_extraction_segments(extraction: object) -> bool:
    proposed_path = getattr(extraction, "proposed_json_path", None)
    if not isinstance(proposed_path, str) or not proposed_path.strip():
        return False
    try:
        payload = json.loads(Path(proposed_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    segments = payload.get("segments")
    if (
        not isinstance(segments, list)
        or not segments
        or any(
            not isinstance(segment, dict)
            or not isinstance(segment.get("text"), str)
            for segment in segments
        )
    ):
        return False
    return any(
        isinstance(segment, dict)
        and isinstance(segment.get("text"), str)
        and isinstance(segment.get("start_seconds"), (int, float))
        and not isinstance(segment.get("start_seconds"), bool)
        and isinstance(segment.get("end_seconds"), (int, float))
        and not isinstance(segment.get("end_seconds"), bool)
        and float(segment["end_seconds"]) > float(segment["start_seconds"])
        for segment in segments
    )


@app.command(
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
    recording_verifier_model: str = typer.Option(
        "gemma3:12b",
        "--recording-verifier-model",
        help="Ollama model used only for ambiguous recording-level decisions.",
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
    try:
        correction = load_fixture_window_correction(
            fixture_dir,
            youtube_video_id,
        )
    except FixtureValidationError as error:
        raise typer.BadParameter(str(error)) from error

    database = get_database(base_dir)
    paths = build_paths(base_dir, remember=True)
    video = database.get_video_by_youtube_id(youtube_video_id)
    if video is None:
        raise typer.BadParameter(
            f"Unknown YouTube video ID: {youtube_video_id}"
        )
    extraction = database.get_latest_extraction_result_for_video(video.id)
    if extraction is None or not _has_reusable_extraction_segments(extraction):
        raise typer.BadParameter(
            f"Video {youtube_video_id} has no reusable extraction segments"
        )

    video_paths = resolve_video_artifact_paths(database, paths, video)
    override_path = video_paths.review / "window_override.json"
    previous_observation = database.get_latest_speaker_observation_for_video(
        video.id
    )
    try:
        normalized_audio, _normalized_availability = (
            get_authoritative_normalized_media_artifact(database, video.id)
        )
    except AttributeError:
        # Compatibility for injected lightweight database adapters.
        normalized_audio = None
    persist_fixture_window_override(correction, override_path)
    console.print(
        f"Applied fixture {correction.fixture_path} as window override "
        f"{correction.start_seconds:.3f}-{correction.end_seconds:.3f}s."
    )

    llm_config = build_llm_config()
    if llm_model is not None:
        llm_config = replace(llm_config, model=llm_model)
    client = OllamaClient(llm_config)
    verifier_config = replace(llm_config, model=recording_verifier_model)
    verifier_client = OllamaClient(verifier_config)
    resolved_inference_cache_root = (
        inference_cache_root.expanduser().resolve()
        if inference_cache_root is not None
        else None
    )
    resolved_verifier_cache_root = (
        recording_verifier_cache_root.expanduser().resolve()
        if recording_verifier_cache_root is not None
        else None
    )
    try:
        result = reclassify_video(
            database,
            paths,
            video.id,
            llm_client=client,
            prompt_version=llm_config.prompt_version,
            force=True,
            progress=lambda stage, current, total: console.print(
                f"  video #{video.id} {stage} block {current}/{total}"
            ),
            model_digest=client.model_digest(),
            context_size=llm_config.context_size,
            inference_cache_dir=(
                resolved_inference_cache_root / video.youtube_video_id
                if resolved_inference_cache_root is not None
                else None
            ),
            recording_verifier_client=verifier_client,
            recording_verifier_model_digest=verifier_client.model_digest(),
            recording_verifier_cache_dir=resolved_verifier_cache_root,
        )
        proposed = json.loads(
            result.proposed_json_path.read_text(encoding="utf-8")
        )
        window = proposed.get("sermon_window")
        if not isinstance(window, dict):
            raise ValueError("reclassification did not persist a sermon window")
        persisted_start = window.get("start_seconds")
        persisted_end = window.get("end_seconds")
        if (
            window.get("source") != "override"
            or not isinstance(persisted_start, (int, float))
            or isinstance(persisted_start, bool)
            or not isinstance(persisted_end, (int, float))
            or isinstance(persisted_end, bool)
            or abs(float(persisted_start) - correction.start_seconds) > 1e-6
            or abs(float(persisted_end) - correction.end_seconds) > 1e-6
        ):
            raise ValueError(
                "reclassification did not preserve the fixture-derived override"
            )

        current_extraction = database.get_latest_extraction_result_for_video(
            video.id
        )
        if current_extraction is None:
            raise ValueError("latest extraction disappeared after reclassification")
        pastor = (
            database.get_pastor_by_id(video.pastor_id)
            if video.pastor_id is not None
            else None
        )
        speaker_record = record_neutral_speaker_evidence(
            database,
            paths,
            video=video,
            pastor=pastor,
            extraction_result=current_extraction,
            normalized_audio_artifact=normalized_audio,
        )
        observation = speaker_record.neutral_evidence.observation
        if observation is None:
            raise ValueError(
                "corrected extraction did not produce a speaker observation"
            )
        if (
            observation.extraction_result_id != current_extraction.id
            or abs(observation.start_seconds - correction.start_seconds) > 1e-6
            or abs(observation.end_seconds - correction.end_seconds) > 1e-6
        ):
            raise ValueError(
                "speaker observation does not match the corrected extraction window"
            )
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        raise typer.BadParameter(
            f"Fixture override was saved, but correction propagation failed: {error}"
        ) from error

    previous_fingerprint = (
        previous_observation.input_fingerprint
        if previous_observation is not None
        else None
    )
    fingerprint_state = (
        "reused"
        if previous_fingerprint == observation.input_fingerprint
        else "regenerated"
    )
    eligibility = assess_automatic_speaker_observation(database, video.id)
    disposition = proposed.get("final_disposition")
    disposition_status = (
        disposition.get("status")
        if isinstance(disposition, dict)
        else "unknown"
    )
    console.print(
        f"Corrected video #{video.id}: disposition={disposition_status}; "
        f"speaker_fingerprint_{fingerprint_state}="
        f"{observation.input_fingerprint}; "
        f"previous={previous_fingerprint or 'none'}; "
        f"automatic_pair_eligibility={eligibility.reason_code}."
    )


@app.command(help="Rerun local-LLM classification using existing extraction segments.")
def reclassify(
    video_id: int | None = typer.Option(None, "--video-id", help="Reclassify one database video id."),
    source_id: int | None = typer.Option(None, "--source-id", help="Reclassify extracted videos from one source id."),
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
    llm_model: str | None = typer.Option(None, "--llm-model", help="Override the configured local Ollama model."),
    recording_verifier_model: str = typer.Option(
        "gemma3:12b",
        "--recording-verifier-model",
        help="Ollama model used only for ambiguous recording-level decisions.",
    ),
    jobs: int = typer.Option(2, "--jobs", min=1, help="Concurrent video classification jobs."),
    inference_cache_root: Path | None = typer.Option(
        None,
        "--inference-cache-root",
        help="Use a separate per-video inference cache root, primarily for controlled comparisons.",
    ),
    recording_verifier_cache_root: Path | None = typer.Option(
        None,
        "--recording-verifier-cache-root",
        help="Use a shared recording-verifier cache root.",
    ),
    force: bool = typer.Option(False, "--force", help="Rerun even when model and prompt versions match."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    selector_count = sum(
        (
            video_id is not None,
            source_id is not None,
            fixture_dir is not None,
            review_required,
            all_videos,
        )
    )
    if selector_count != 1:
        raise typer.BadParameter(
            "Pass exactly one of --video-id, --source-id, --fixture-dir, "
            "--review-required, or --all."
        )
    database = get_database(base_dir)
    paths = build_paths(base_dir, remember=True)
    if video_id is not None:
        video = database.get_video_by_id(video_id)
        videos = [video] if video is not None else []
    elif source_id is not None:
        videos = database.list_videos_by_source_id(source_id)
    elif review_required:
        videos = []
        invalid_disposition_artifacts = 0
        for video in database.list_videos():
            extraction = database.get_latest_extraction_result_for_video(video.id)
            proposed_path = (
                getattr(extraction, "proposed_json_path", None)
                if extraction is not None
                else None
            )
            if not isinstance(proposed_path, str) or not proposed_path.strip():
                continue
            try:
                payload = json.loads(Path(proposed_path).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                invalid_disposition_artifacts += 1
                continue
            disposition = (
                payload.get("final_disposition")
                if isinstance(payload, dict)
                else None
            )
            if (
                isinstance(disposition, dict)
                and disposition.get("status") == REVIEW_REQUIRED
            ):
                videos.append(video)
        videos.sort(key=lambda video: video.id)
        console.print(
            f"Discovered {len(videos)} video(s) with a review_required "
            "final disposition."
        )
        if invalid_disposition_artifacts:
            console.print(
                f"Skipped {invalid_disposition_artifacts} invalid proposed "
                "artifact(s) while selecting review-required videos."
            )
        if not videos:
            console.print("No review-required videos remain to reclassify.")
            return
    elif all_videos:
        videos = database.list_videos()
        console.print(f"Discovered {len(videos)} video(s) in the corpus.")
    else:
        assert fixture_dir is not None
        fixtures = validate_fixture_directory(fixture_dir.expanduser().resolve())
        resolved = [
            (fixture, database.get_video_by_youtube_id(fixture.video_id))
            for fixture in fixtures
        ]
        missing_fixture_ids = [
            fixture.video_id for fixture, video in resolved if video is None
        ]
        if missing_fixture_ids:
            raise typer.BadParameter(
                "Fixture videos are missing from the database: "
                + ", ".join(missing_fixture_ids)
            )
        videos = [video for _, video in resolved if video is not None]
        console.print(
            f"Discovered {len(videos)} fixture video(s) in "
            f"{fixture_dir.expanduser().resolve()}."
        )
    if not videos:
        raise typer.BadParameter("No matching videos found.")
    llm_config = build_llm_config()
    if llm_model is not None:
        llm_config = replace(llm_config, model=llm_model)
    client = OllamaClient(llm_config)
    verifier_config = replace(llm_config, model=recording_verifier_model)
    raw_verifier_client = OllamaClient(verifier_config)
    verifier_lock = Lock()

    class LockedVerifierClient:
        model = raw_verifier_client.model

        def generate_json(self, prompt, schema):
            with verifier_lock:
                return raw_verifier_client.generate_json(prompt, schema)

    verifier_client = LockedVerifierClient()

    processed = 0
    reused = 0
    skipped = 0
    failed = 0
    eligible_videos = []
    minimum_duration = minimum_sermon_duration_seconds()
    maximum_duration = maximum_sermon_duration_seconds()
    for video in videos:
        # Frozen fixtures are explicit validation targets.  Do not silently
        # leave stale classifier artifacts because a fixture now falls outside
        # the production discovery eligibility policy.
        if fixture_dir is None and not _catalog_video_is_sermon_eligible(
            database,
            video,
            minimum_seconds=minimum_duration,
            maximum_seconds=maximum_duration,
        ):
            skipped += 1
            if all_videos or review_required:
                console.print(
                    f"Skipping video #{video.id}: video is outside the configured "
                    "sermon-video duration range or is a future event."
                )
            continue
        extraction = database.get_latest_extraction_result_for_video(video.id)
        if extraction is None:
            skipped += 1
            if all_videos or review_required:
                console.print(
                    f"Skipping video #{video.id}: no reusable extraction segments."
                )
            continue
        if (all_videos or review_required) and not _has_reusable_extraction_segments(
            extraction
        ):
            skipped += 1
            console.print(
                f"Skipping video #{video.id}: no reusable extraction segments."
            )
            continue
        eligible_videos.append(video)

    model_digest = client.model_digest() if eligible_videos else None
    verifier_model_digest = (
        raw_verifier_client.model_digest() if eligible_videos else None
    )
    resolved_cache_root = (
        inference_cache_root.expanduser().resolve()
        if inference_cache_root is not None
        else None
    )
    resolved_verifier_cache_root = (
        recording_verifier_cache_root.expanduser().resolve()
        if recording_verifier_cache_root is not None
        else None
    )

    def reclassify_one(video):
        return reclassify_video(
            database,
            paths,
            video.id,
            llm_client=client,
            prompt_version=llm_config.prompt_version,
            force=force,
            progress=lambda stage, current, total: console.print(
                f"  video #{video.id} {stage} block {current}/{total}"
            ),
            model_digest=model_digest,
            context_size=llm_config.context_size,
            inference_cache_dir=(
                resolved_cache_root / video.youtube_video_id
                if resolved_cache_root is not None
                else None
            ),
            recording_verifier_client=verifier_client,
            recording_verifier_model_digest=verifier_model_digest,
            recording_verifier_cache_dir=(
                resolved_verifier_cache_root
                if resolved_verifier_cache_root is not None
                else None
            ),
        )

    def record_result(video, result=None, error: Exception | None = None) -> None:
        nonlocal processed, reused, failed
        if error is not None:
            console.print(f"[red]Failed to reclassify[/red] video #{video.id}: {error}")
            failed += 1
            return
        assert result is not None
        if result.reused:
            console.print(
                f"Reused current classification for video #{video.id}: "
                f"disposition={result.disposition_status}."
            )
            reused += 1
        else:
            console.print(
                f"Reclassified video #{video.id}: confidence={result.confidence_tier}, "
                f"disposition={result.disposition_status}, "
                f"retained_segments={result.retained_segment_count}, "
                f"cache_hits={result.cache_hits}, cache_misses={result.cache_misses}, "
                f"recording_verifier="
                f"{getattr(result, 'recording_verifier_decision', None) or 'not_required'}, "
                f"verifier_cache_hit="
                f"{getattr(result, 'recording_verifier_cache_hit', False)}, "
                f"audit={result.classification_path}"
            )
            processed += 1

    for video in eligible_videos:
        console.print(f"Reclassifying video #{video.id}: {video.title}")

    max_workers = min(jobs, len(eligible_videos)) if eligible_videos else 1
    if max_workers == 1:
        for video in eligible_videos:
            try:
                result = reclassify_one(video)
            except Exception as error:
                record_result(video, error=error)
            else:
                record_result(video, result=result)
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_video = {
                executor.submit(reclassify_one, video): video
                for video in eligible_videos
            }
            for future in as_completed(future_to_video):
                video = future_to_video[future]
                try:
                    result = future.result()
                except Exception as error:
                    record_result(video, error=error)
                else:
                    record_result(video, result=result)
    console.print(
        f"Reclassified {processed} video(s); reused {reused}; skipped {skipped}; failed {failed}."
    )


@app.command(help="Build or refresh the pastor-scoped Markdown review file from extracted videos.", rich_help_panel="Workflows")
def review(
    pastor: str | None = typer.Argument(None, help="Pastor slug whose extracted videos should be assembled into review Markdown."),
    all_pastors: bool = typer.Option(False, "--all", help="Build a combined review across all pastors."),
    edit: bool = typer.Option(False, "--edit", help="Open the generated review Markdown in an editor."),
    classifier: str = typer.Option("auto", "--classifier", help="Content classifier for missing extractions: auto, rules, or llm."),
    llm_model: str | None = typer.Option(None, "--llm-model", help="Override the configured local Ollama model."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    paths = build_paths(base_dir, remember=True)
    if all_pastors and pastor is not None:
        raise typer.BadParameter("Do not pass a pastor slug when using --all.")
    if not all_pastors and pastor is None:
        raise typer.BadParameter("A pastor slug is required unless you use --all.")

    if pastor is not None and database.get_pastor_by_slug(pastor) is None:
        raise _unknown_pastor_error(pastor, base_dir)
    try:
        batch = prepare_review_exports(
            database,
            paths,
            pastor_slug=pastor,
            all_pastors=all_pastors,
            classifier=classifier,
            llm_model=llm_model,
            event_callback=lambda message: console.print(message, markup=False),
            progress_callback=lambda stage, current, total: console.print(
                f"  {stage} block {current}/{total}"
            ),
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error

    for pastor_result in batch.pastors:
        result = pastor_result.export
        console.print(f"Wrote pastor review markdown to {result.export_path}")
        console.print(f"Wrote review manifest to {result.manifest_path}")
        console.print(f"Included {result.video_count} video(s); skipped {result.skipped_count}.")
    if batch.prepared or batch.failed:
        console.print(f"Prepared {batch.prepared} video(s) for review; failed {batch.failed}.")
    if all_pastors:
        console.print(
            f"Built review artifacts for {len(batch.pastors)} pastor(s); "
            f"included {sum(item.export.video_count for item in batch.pastors)} video(s); "
            f"skipped {sum(item.export.skipped_count for item in batch.pastors)}."
        )

    if edit:
        assert pastor is not None
        review_path = build_pastor_paths(paths, pastor).exports / "review.md"
        editor = shutil.which("code") or shutil.which("nano") or shutil.which("vim")
        if editor is None:
            raise RuntimeError("No editor found on PATH")
        subprocess.run([editor, str(review_path)], check=True)


def _verify_audio_stage_manifest(
    database: Database,
    paths: AppPaths,
    manifest_path: Path,
) -> set[int]:
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

        video_ids = load_and_verify_audio_stage_manifest(
            database,
            manifest_path,
            progress_callback=report_stage_verification,
            verification_cache=MediaVerificationCache(
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


def _invoke_run_request(request: RunWorkflowRequest) -> None:
    def render_event(event: object) -> None:
        if isinstance(event, str):
            console.print(event, markup="[yellow]" in event)
        else:
            _print_review_batch(event)

    run_workflow(
        request,
        event_callback=render_event,
        dependencies=RunWorkflowDependencies(
            get_database=get_database,
            build_paths=build_paths,
            build_tools=build_tool_config,
            verify_manifest=_verify_audio_stage_manifest,
            audio_scope=AudioStageScopeDependencies(
                get_database=get_database,
                add_source=add_source_service,
                delete_source=delete_source_service,
                discover=discover_sources_service,
                select_existing=_select_existing_stage_video_ids,
            ),
            audio_stage=AudioStageDependencies(
                stage_video=stage_source_audio_for_video,
                write_manifest=write_audio_stage_manifest,
                fetch_captions=fetch_captions_service,
            ),
            resume_pipeline=ResumePipelineDependencies(
                fetch_captions=fetch_captions_service,
                transcribe=transcribe_videos_service,
                extract=extract_batch,
                ensure_media=_ensure_and_archive_run_media,
                run_identity=_run_post_content_identity,
                prepare_reviews=prepare_review_exports,
            ),
            online_pipeline=PipelineDependencies(
                get_database=get_database,
                build_paths=build_paths,
                add_source=add_source_service,
                delete_source=delete_source_service,
                discover=discover_sources_service,
                fetch_captions=fetch_captions_service,
                transcribe=transcribe_videos_service,
                extract=extract_batch,
                ensure_media=_ensure_and_archive_run_media,
                run_identity=_run_post_content_identity,
                prepare_reviews=prepare_review_exports,
            ),
        ),
    )


def run_workflow_service(
    url: str | None = None,
    pastor: str | None = None,
    all_sources: bool = False,
    failed_only: bool = False,
    replace_existing: bool = False,
    limit: int | None = DEFAULT_DISCOVER_LIMIT,
    all_videos: bool = False,
    captions_only: bool = False,
    transcribe_missing: bool = True,
    jobs: int = DEFAULT_TRANSCRIBE_JOBS,
    classifier: str = "auto",
    llm_model: str | None = None,
    skip_review: bool = False,
    run_identity: bool = False,
    base_dir: Path | None = None,
    source_ids: Sequence[int] | None = None,
    stage_audio_only: bool = False,
    skip_discovery: bool = False,
    resume_stage: Path | None = None,
    acquire_captions: bool = False,
    download_jobs: int = DEFAULT_PREP_WORKERS,
    cookies_from_browser: str | None = None,
    cookies: Path | None = None,
) -> None:
    _invoke_run_request(
        RunWorkflowRequest(
            url=url,
            pastor=pastor,
            all_sources=all_sources,
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
            source_ids=tuple(source_ids or ()),
            stage_audio_only=stage_audio_only,
            skip_discovery=skip_discovery,
            resume_stage=resume_stage,
            acquire_captions=acquire_captions,
            download_jobs=download_jobs,
            caption_request_interval_seconds=(
                CAPTION_BATCH_REQUEST_INTERVAL_SECONDS
            ),
            cookies_from_browser=cookies_from_browser,
            cookies=cookies,
        )
    )
def _run_post_content_identity(
    base_dir: Path | None,
    *,
    jobs: int = 2,
) -> None:
    run_post_content_identity(
        PostContentIdentityRequest(base_dir=base_dir, jobs=jobs),
        event_callback=lambda message: console.print(message, markup=False),
        identity_runner=run_identity_workflow_service,
    )


def _ensure_and_archive_run_media(
    database: Database,
    paths: AppPaths,
    *,
    video_ids: set[int] | None = None,
    allow_download: bool = True,
) -> None:
    _ensure_and_archive_run_media_workflow(
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
            has_isolated_sermon=video_has_isolated_sermon,
            get_verified_media=get_verified_normalized_media_artifact,
            build_tools=build_tool_config,
            ensure_audio=ensure_audio_for_video,
            archive_source=archive_source_media,
        ),
    )

def _print_review_batch(batch: ReviewBatchResult) -> None:
    for pastor_result in batch.pastors:
        result = pastor_result.export
        console.print(f"Wrote pastor review markdown to {result.export_path}")
        console.print(f"Wrote review manifest to {result.manifest_path}")
        console.print(f"Included {result.video_count} video(s); skipped {result.skipped_count}.")
    if batch.prepared or batch.failed:
        console.print(f"Prepared {batch.prepared} video(s) for review; failed {batch.failed}.")


_identity_review_commands.configure_ground_truth_reviewer(review_ground_truth)
_identity_coordination_commands.configure_shadow_associator(
    shadow_associate_speakers_command
)
_identity_workflow_commands.configure_identity_workflow(
    _invoke_identity_workflow_request
)
_pipeline_commands.configure_run_command(_invoke_run_request)



def main() -> int:
    app()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
