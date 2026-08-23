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
from threading import Lock
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
from pastor_transcript_extractor.config import (
    AppPaths,
    build_llm_config,
    build_paths,
    build_pastor_paths,
    build_tool_config,
    ensure_directories,
)
from pastor_transcript_extractor.discovery import extract_discovered_videos, sort_discovered_videos_by_recency
from pastor_transcript_extractor.extraction import reclassify_video
from pastor_transcript_extractor.sermon_policy import (
    duration_meets_sermon_minimum,
    minimum_sermon_duration_seconds,
    publication_is_not_future,
    video_is_sermon_eligible,
)
from pastor_transcript_extractor.exporting import export_organization_review_markdown
from pastor_transcript_extractor.evaluation import (
    allocate_evaluation_run_directory,
    build_failure_analysis,
    build_failure_markdown,
    build_markdown_report,
    create_evaluation_run,
    evaluate_fixture_payload,
)
from pastor_transcript_extractor.evaluation_baseline import validate_localization_baseline
from pastor_transcript_extractor.evaluation_partitioning import (
    SourceFamilyRegistryError,
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
from pastor_transcript_extractor.interaction_diagnostics import (
    DEFAULT_SENTINELS,
    DiagnosticInferenceCache,
    build_diagnostic_report,
    create_diagnostic_run,
    load_sentinel_blocks,
    run_model_diagnostics,
)
from pastor_transcript_extractor.recording_verifier import (
    RecordingVerifierCache,
    build_report as build_recording_verifier_report,
    create_run as create_recording_verifier_run,
    load_cases as load_recording_verifier_cases,
    run_diagnostics as run_recording_verifier_diagnostics,
    validate_partition_access,
)
from pastor_transcript_extractor.profile_analysis import (
    PROFILE_ANALYZER_KEY,
    PROFILE_ANALYZER_VERSION,
    build_profile_scripture_analysis,
    resolve_profile_sermon_scope,
)
from pastor_transcript_extractor.benchmark import (
    EligibilityPolicy,
    build_snapshot,
    create_panel,
    effective_membership,
    record_membership,
    snapshot_document,
)
from pastor_transcript_extractor.reviewed_speaker_evidence import (
    ReviewedSpeakerEvidence,
    ReviewedEvidenceSyncResult,
    load_reviewed_speaker_evidence,
    sync_reviewed_speaker_evidence,
)
from pastor_transcript_extractor.identity import (
    backfill_shadow_identity_assessments,
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
    load_shadow_association_confirmation_pairs,
    load_unmatched_association_fingerprints,
    write_identity_coordination_report,
)
from pastor_transcript_extractor.models import (
    MediaArtifact,
    SpeakerObservation,
    TranscriptSourceKind,
    VideoStatus,
)
from pastor_transcript_extractor.media import (
    NoCaptionsAvailableError,
    VideoNotYetAvailableError,
    VideoUnavailableError,
    YtDlpConfigurationError,
    YtDlpRateLimitError,
)
from pastor_transcript_extractor.media_archive import (
    ArchivePreflightEvent,
    ArchiveProgressEvent,
    ArchiveRunResult,
    AudioSweepProgressEvent,
    CanonicalAudioPreparationProgressEvent,
    archive_normalized_media,
    archive_source_media,
    archive_status,
    media_archive_lock_held,
    prepare_canonical_audio,
    sweep_local_audio,
    write_canonical_clip_preparation_manifest,
)
from pastor_transcript_extractor.media_artifacts import (
    ArchivedMediaUnavailableError,
    MediaVerificationCache,
    audit_media_coverage,
    audit_normalized_audio_provenance,
    backfill_existing_media_artifacts,
    ensure_audio_for_video,
    get_verified_normalized_media_artifact,
    get_authoritative_normalized_media_artifact,
    stage_source_audio_for_video,
    repair_normalized_audio_provenance,
    resolve_normalized_audio_path,
    video_has_isolated_sermon,
)
from pastor_transcript_extractor.local_llm import LocalLlmError, OllamaClient
from pastor_transcript_extractor.sources import UnsupportedSourceError, detect_source_type
from pastor_transcript_extractor.speaker_pair_diagnostics import (
    AudioSpanCache,
    DecisionPolicy,
    EmbeddingCache,
    PairDiagnosticCache,
    SherpaOnnxEmbeddingBackend,
    SpanSpec,
    analyze_observation_pair,
    build_embedding_centroid,
    evaluate_reviewed_pair_results,
    validate_reviewed_pair_fixture,
    write_pair_result,
)
from pastor_transcript_extractor.speaker_model_bakeoff import (
    BakeoffModel,
    build_bakeoff_preflight,
    evaluate_experimental_policy_candidate,
    execute_bakeoff_plan,
    load_experimental_policy_candidate,
    load_bakeoff_manifest,
    load_namespaced_bakeoff_results,
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
    ReviewEvidenceMode,
    STANDARD_VARIATION_TAGS,
    audit_review_selection_artifacts,
    create_observation_review_packet,
    create_review_draft,
    prepare_review_observation,
    submit_review,
)
from pastor_transcript_extractor.speaker_observation_consistency import (
    build_observation_consistency_plan,
    collect_reviewed_observation_examples,
    evaluate_observation_consistency_examples,
    load_consistency_score_index,
    load_discovery_consistency_policy,
    write_observation_consistency_report,
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
    invalidate_reviews_for_videos,
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
    machine_assignment_status,
    plan_machine_assignments,
    reconcile_machine_assignments,
    rollback_machine_assignments,
)
from pastor_transcript_extractor.speaker_negative_window_audit import (
    audit_speaker_negative_windows,
)
from pastor_transcript_extractor.speaker_profile_attribution import (
    apply_reviewed_profile_attribution,
    get_profile_attribution_candidate,
    load_profile_attribution_clip_timestamps,
    load_profile_attribution_deferrals,
    list_unnamed_profile_attribution_candidates,
    record_profile_attribution_deferral,
    write_profile_attribution_packet,
)
from pastor_transcript_extractor.speaker_profile_metadata_attribution import (
    load_profile_metadata_attributions,
    profile_metadata_candidate_profile_ids,
    run_profile_metadata_attribution,
)
from pastor_transcript_extractor.speaker_profile_discovery import (
    ActivityQualifiedSelectionCache,
    DiscoveryCandidate,
    TRANSCRIPT_GROUNDED_SPAN_SELECTION_VERSION,
    build_discovery_signature,
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
from pastor_transcript_extractor.speaker_shadow_association import (
    ShadowExemplar,
    assess_profile_association_readiness,
    build_shadow_association_input_fingerprint,
    evaluate_shadow_association,
    load_reusable_shadow_association,
    load_shadow_policy,
    select_profile_exemplars,
    select_routed_association_profiles,
    select_staged_association_profiles,
    summarize_shadow_associations,
    write_shadow_association,
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
from pastor_transcript_extractor.sermon_analysis import (
    ANALYZER_KEY as SERMON_ANALYZER_KEY,
    ANALYZER_VERSION as SERMON_ANALYZER_VERSION,
    analyze_sermon,
)
from pastor_transcript_extractor.scripture_reference_evaluation import (
    evaluate_scripture_detector,
)
from pastor_transcript_extractor.scripture_alignment_evaluation import (
    evaluate_scripture_alignment,
)
from pastor_transcript_extractor.style_analysis import (
    STYLE_ANALYZER_KEY,
    STYLE_ANALYZER_VERSION,
    STYLE_PROMPT_VERSION,
    analyze_sermon_style,
)
from pastor_transcript_extractor.style_evaluation import evaluate_style_model
from pastor_transcript_extractor.style_profile_analysis import (
    STYLE_PROFILE_ANALYZER_KEY,
    STYLE_PROFILE_ANALYZER_VERSION,
    build_profile_style_analysis,
)
from pastor_transcript_extractor.style_review import (
    create_style_review_packet,
    evaluate_style_boundaries,
    finalize_style_review,
)
from pastor_transcript_extractor.storage import Database
from pastor_transcript_extractor.source_ownership import (
    apply_source_ownership_schema,
    audit_source_ownership,
    backfill_source_ownership,
)
from pastor_transcript_extractor.source_processing_report import (
    generate_source_processing_report,
)
from pastor_transcript_extractor.transcription import (
    PreparedTranscriptInput,
    complete_transcription_video,
    fetch_captions_video,
    prepare_transcription_input,
)

app = typer.Typer(help="Pastor Transcript Extractor CLI")
pastor_app = typer.Typer(help="Manage pastors.")
organization_app = typer.Typer(help="Manage publishing organizations.")
source_app = typer.Typer(help="Manage queued sources.")
video_app = typer.Typer(help="Manage discovered videos.")
identity_app = typer.Typer(help="Manage speaker identity shadow artifacts.")
media_app = typer.Typer(help="Manage transcript-independent local media artifacts.")
analysis_app = typer.Typer(help="Analyze already-identified sermon content.")
source_ownership_app = typer.Typer(help="Migrate and audit source ownership data.")
benchmark_app = typer.Typer(help="Manage reviewed profile reference panels.")
app.add_typer(pastor_app, name="pastor")
app.add_typer(organization_app, name="organization")
app.add_typer(source_app, name="source")
app.add_typer(video_app, name="video")
app.add_typer(identity_app, name="identity")
app.add_typer(media_app, name="media")
app.add_typer(analysis_app, name="analysis")
app.add_typer(source_ownership_app, name="source-ownership")
app.add_typer(benchmark_app, name="benchmark")
console = Console()
DEFAULT_DISCOVER_LIMIT = 26
DEFAULT_TRANSCRIBE_JOBS = 2
DEFAULT_PREP_WORKERS = 2
CAPTION_BATCH_REQUEST_INTERVAL_SECONDS = 5.0
CAPTION_RATE_LIMIT_BACKOFF_SECONDS = (15.0, 30.0, 60.0)
MIN_SYNC_FREE_DISK_FRACTION = 0.20
SYNC_ARCHIVE_WAIT_INITIAL_SECONDS = 1.0
SYNC_ARCHIVE_WAIT_MAX_SECONDS = 30.0
SYNC_AUDIO_RESERVATION_BYTES_PER_SECOND = 250_000
SYNC_UNKNOWN_VIDEO_DURATION_SECONDS = 2 * 60 * 60
STAGE_QUEUED_PREP = "q-prep"
STAGE_DOWNLOADING = "dl"
STAGE_NORMALIZING = "norm"
STAGE_QUEUED_TRANSCRIBE = "q-xcribe"
STAGE_TRANSCRIBING = "xcribe"
STAGE_DONE = "done"
STAGE_FAILED = "failed"
STAGE_LABELS = {
    "queued": STAGE_QUEUED_PREP,
    "downloading": STAGE_DOWNLOADING,
    "normalizing": STAGE_NORMALIZING,
    "queued_transcribing": STAGE_QUEUED_TRANSCRIBE,
    "transcribing": STAGE_TRANSCRIBING,
    "done": STAGE_DONE,
    "failed": STAGE_FAILED,
}

DEFAULT_SPEAKER_MODEL_SHA256 = "357a834f702b80161e5b981182c038e18553c1f2ca752ed6cec2052365d4129b"


@dataclass(frozen=True, slots=True)
class DiscoveryServiceResult:
    selected_video_ids_by_source: dict[int, tuple[int, ...]]


def _selected_discovery_video_ids(
    discovery: DiscoveryServiceResult | object | None,
    source_ids: Sequence[int],
) -> set[int]:
    selected_by_source = getattr(discovery, "selected_video_ids_by_source", {})
    if not isinstance(selected_by_source, Mapping):
        return set()
    return {
        video_id
        for source_id in source_ids
        for video_id in selected_by_source.get(source_id, ())
    }


@app.command(help="Validate manually reviewed sermon evaluation fixtures.")
def validate_fixtures(
    fixture_dir: Path = typer.Argument(
        Path("evaluation/fixtures"),
        help="Directory containing manually reviewed fixture JSON files.",
    ),
) -> None:
    fixtures = validate_fixture_directory(fixture_dir.expanduser().resolve())
    console.print(f"Validated {len(fixtures)} fixture(s); all video IDs are unique.")


@app.command(help="Validate a frozen sermon-localization baseline and its exact fixture corpus.")
def validate_baseline(
    manifest: Path = typer.Argument(
        Path("evaluation/baselines/sermon-localization-v1.json"),
        help="Frozen localization baseline manifest.",
    ),
    fixture_dir: Path = typer.Option(
        Path("evaluation/fixtures"),
        help="Directory containing the baseline fixture corpus.",
    ),
) -> None:
    baseline = validate_localization_baseline(
        manifest.expanduser().resolve(),
        fixture_dir.expanduser().resolve(),
    )
    console.print(
        f"Validated {baseline.baseline_id}: {baseline.fixture_count} fixture(s), "
        f"fingerprint={baseline.corpus_fingerprint}."
    )


@app.command(help="Validate source-family coverage and family-level evaluation partitions.")
def validate_source_families(
    registry_path: Path = typer.Argument(
        Path("evaluation/source-families.json"),
        help="Source-family registry JSON.",
    ),
    fixture_dir: Path = typer.Option(
        Path("evaluation/fixtures"),
        help="Fixture corpus whose source-family coverage should be checked.",
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    try:
        registry = load_source_family_registry(registry_path.expanduser().resolve())
        fixtures = validate_fixture_directory(fixture_dir.expanduser().resolve())
        paths = build_paths(base_dir)
        if not paths.database.exists():
            raise SourceFamilyRegistryError(
                f"application database does not exist: {paths.database}"
            )
        database = Database(paths.database, readonly=True)
        assignments = []
        for fixture in fixtures:
            video = database.get_video_by_youtube_id(fixture.video_id)
            if video is None:
                raise SourceFamilyRegistryError(f"fixture video is not in the database: {fixture.video_id}")
            source = database.get_source_by_id(video.source_id)
            if source is None:
                raise SourceFamilyRegistryError(f"video source is missing: {fixture.video_id}")
            transcript = database.get_latest_transcript_artifact_for_video(video.id)
            assignments.append(
                assign_recording_partition(
                    registry=registry,
                    video_id=fixture.video_id,
                    source_url=source.url,
                    caption_source=transcript.source_kind.value if transcript else "unknown",
                    recording_date=video.published_at,
                )
            )
    except (OSError, SourceFamilyRegistryError, ValueError) as error:
        raise typer.BadParameter(str(error)) from error

    partition_counts: dict[str, int] = {}
    for assignment in assignments:
        partition_counts[assignment.partition.value] = (
            partition_counts.get(assignment.partition.value, 0) + 1
        )
    family_count = len({assignment.source_family_id for assignment in assignments})
    condition_count = len({assignment.recording_condition_group_id for assignment in assignments})
    counts = ", ".join(
        f"{partition}={count}" for partition, count in sorted(partition_counts.items())
    )
    console.print(
        f"Validated {len(assignments)} fixture(s) across {family_count} source families and "
        f"{condition_count} recording-condition groups; {counts}."
    )


@app.command(help="Deterministically register new database sources for evaluation partitioning.")
def sync_source_families(
    registry_path: Path = typer.Argument(
        Path("evaluation/source-families.json"),
        help="Source-family registry JSON to extend without changing existing assignments.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report additions without writing."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    path = registry_path.expanduser().resolve()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise SourceFamilyRegistryError("source-family registry must be a JSON object")
        registry = load_source_family_registry(path)
        database = Database(build_paths(base_dir).database, readonly=True)
        extension = extend_source_family_registry(
            registry,
            payload,
            [(source.url, source.source_identity_key) for source in database.list_sources()],
        )
        if not dry_run and (extension.families_added or extension.aliases_added):
            write_json(path, extension.payload)
            load_source_family_registry(path)
    except (OSError, json.JSONDecodeError, SourceFamilyRegistryError) as error:
        raise typer.BadParameter(str(error)) from error
    action = "Would add" if dry_run else "Added"
    console.print(
        f"{action} {extension.families_added} source family(s) and "
        f"{extension.aliases_added} URL alias(es); "
        f"total={len(extension.payload['source_families'])}."
    )


@app.command(help="Evaluate existing production classification artifacts against frozen fixtures.")
def evaluate(
    fixture_dir: Path = typer.Option(Path("evaluation/fixtures"), help="Approved fixture directory."),
    results_dir: Path = typer.Option(Path("evaluation/results"), help="Generated result root."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    fixture_root = fixture_dir.expanduser().resolve()
    fixtures = validate_fixture_directory(fixture_root)
    results: list[dict[str, object]] = []
    failure_inputs: dict[str, tuple[dict[str, object], dict[str, object]]] = {}
    for validated in fixtures:
        fixture_path = validated.path
        fixture_payload = json.loads(fixture_path.read_text(encoding="utf-8"))
        video = database.get_video_by_youtube_id(validated.video_id)
        if video is None:
            results.append(
                {
                    "video_id": validated.video_id,
                    "status": "video_not_in_database",
                    "fixture_path": str(fixture_path),
                }
            )
            continue
        extraction = database.get_latest_extraction_result_for_video(video.id)
        if extraction is None or not extraction.proposed_json_path:
            results.append(
                {
                    "video_id": validated.video_id,
                    "status": "missing_extraction_artifact",
                    "fixture_path": str(fixture_path),
                }
            )
            continue
        proposed_path = Path(extraction.proposed_json_path)
        try:
            proposed_payload = json.loads(proposed_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            results.append(
                {
                    "video_id": validated.video_id,
                    "status": "invalid_extraction_artifact",
                    "fixture_path": str(fixture_path),
                    "proposed_path": str(proposed_path),
                }
            )
            continue
        result = evaluate_fixture_payload(
            fixture_payload,
            proposed_payload,
            fixture_path=fixture_path,
            proposed_path=proposed_path,
        )
        results.append(result)
        if result.get("catastrophic_omission") or result.get("false_high_confidence_acceptance"):
            failure_inputs[validated.video_id] = (fixture_payload, proposed_payload)
    run = create_evaluation_run(results)
    output_dir = allocate_evaluation_run_directory(
        results_dir.expanduser().resolve(), run
    )
    json_path = output_dir / "results.json"
    markdown_path = output_dir / "report.md"
    json_path.write_text(json.dumps(run, indent=2, sort_keys=True), encoding="utf-8")
    markdown_path.write_text(build_markdown_report(run), encoding="utf-8")
    if failure_inputs:
        failure_dir = output_dir / "failures"
        failure_dir.mkdir()
        for video_id, (fixture_payload, proposed_payload) in failure_inputs.items():
            analysis = build_failure_analysis(fixture_payload, proposed_payload)
            (failure_dir / f"{video_id}.json").write_text(
                json.dumps(analysis, indent=2, sort_keys=True), encoding="utf-8"
            )
            (failure_dir / f"{video_id}.md").write_text(
                build_failure_markdown(analysis), encoding="utf-8"
            )
    aggregate = run["aggregate"]
    console.print(f"Wrote evaluation JSON to {json_path}")
    console.print(f"Wrote evaluation report to {markdown_path}")
    if failure_inputs:
        console.print(f"Wrote {len(failure_inputs)} failure analysis report(s) to {output_dir / 'failures'}")
    console.print(
        f"Evaluated {aggregate['evaluated_fixture_count']}/{aggregate['fixture_count']} fixture(s); "
        f"missing artifacts {aggregate['missing_artifact_count']}."
    )


@app.command(
    "diagnose-interaction",
    help="Compare local models on deduplicated interaction evidence without changing production artifacts.",
)
def diagnose_interaction(
    models: list[str] | None = typer.Option(
        None, "--model", help="Ollama model to compare; repeat for multiple models."
    ),
    output_root: Path = typer.Option(
        Path("evaluation/interaction-diagnostics"), help="Generated diagnostic result root."
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    selected_models = models or [build_llm_config().model]
    sentinels = [
        (video_id, *load_sentinel_blocks(database, video_id))
        for video_id in DEFAULT_SENTINELS
    ]
    root = output_root.expanduser().resolve()
    cache = DiagnosticInferenceCache(root / "cache")
    llm_config = build_llm_config()
    model_results: list[dict[str, object]] = []
    for model in selected_models:
        client = OllamaClient(replace(llm_config, enabled=True, model=model))
        try:
            digest = client.model_digest()
        except Exception as error:
            raise typer.BadParameter(
                f"Could not use Ollama model {model!r}; install it before comparison: {error}"
            ) from error
        console.print(f"Running offline interaction diagnostics with {model}")
        model_results.append(run_model_diagnostics(
            client,
            model_digest=digest,
            sentinels=sentinels,
            cache=cache,
            progress=lambda current_model, video_id, current, total: console.print(
                f"  {current_model} {video_id} block {current}/{total}"
            ),
        ))
    run = create_diagnostic_run(model_results)
    output_dir = root / str(run["run_id"])
    output_dir.mkdir(parents=True, exist_ok=False)
    json_path = output_dir / "results.json"
    report_path = output_dir / "report.md"
    json_path.write_text(json.dumps(run, indent=2, sort_keys=True), encoding="utf-8")
    report_path.write_text(build_diagnostic_report(run), encoding="utf-8")
    console.print(f"Wrote interaction diagnostic JSON to {json_path}")
    console.print(f"Wrote interaction diagnostic report to {report_path}")


@app.command(
    "diagnose-recording-verifier",
    help="Test one recording-level sermon decision on a non-held-out fixture partition.",
)
def diagnose_recording_verifier(
    model: str = typer.Option("gemma3:12b", "--model", help="Ollama model to test."),
    partition: str = typer.Option(
        "development",
        "--partition",
        help="Fixture partition to test. Use development while tuning.",
    ),
    confirm_frozen_policy: bool = typer.Option(
        False,
        "--confirm-frozen-policy",
        help="Required to unseal the held-out partition for final validation.",
    ),
    fixture_dir: Path = typer.Option(
        Path("evaluation/fixtures"), help="Approved fixture directory."
    ),
    output_root: Path = typer.Option(
        Path("evaluation/recording-verifier"),
        help="Generated diagnostic result root.",
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    try:
        validate_partition_access(
            partition,
            confirm_frozen_policy=confirm_frozen_policy,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    database = get_database(base_dir)
    fixture_root = fixture_dir.expanduser().resolve()
    cases = load_recording_verifier_cases(
        database,
        fixture_root,
        partition=partition,
    )
    if not cases:
        raise typer.BadParameter(f"No fixtures found in partition {partition!r}.")
    root = output_root.expanduser().resolve()
    llm_config = build_llm_config()
    client = OllamaClient(replace(llm_config, enabled=True, model=model))
    try:
        digest = client.model_digest()
    except Exception as error:
        raise typer.BadParameter(
            f"Could not use Ollama model {model!r}; install it before comparison: {error}"
        ) from error
    console.print(
        f"Running recording-level verifier with {model} on "
        f"{len(cases)} {partition} fixture(s)."
    )
    model_result = run_recording_verifier_diagnostics(
        client,
        model_digest=digest,
        cases=cases,
        cache=RecordingVerifierCache(root / "cache"),
        progress=lambda video_id, current, total: console.print(
            f"  {video_id} case {current}/{total}"
        ),
    )
    run = create_recording_verifier_run(model_result, partition=partition)
    output_dir = root / str(run["run_id"])
    output_dir.mkdir(parents=True, exist_ok=False)
    json_path = output_dir / "results.json"
    report_path = output_dir / "report.md"
    json_path.write_text(json.dumps(run, indent=2, sort_keys=True), encoding="utf-8")
    report_path.write_text(
        build_recording_verifier_report(run),
        encoding="utf-8",
    )
    console.print(f"Wrote recording verifier JSON to {json_path}")
    console.print(f"Wrote recording verifier report to {report_path}")


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


@benchmark_app.command("create", help="Create an idempotent named reference panel.")
def benchmark_create(
    key: str = typer.Option(..., "--key", help="Stable lowercase panel key."),
    name: str = typer.Option(..., "--name", help="Panel display name."),
    description: str = typer.Option(..., "--description", help="Panel purpose."),
    provenance: str = typer.Option(
        "manual-review", "--provenance", help="How this analytical selection originated."
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    try:
        panel, created = create_panel(
            database,
            key=key,
            name=name,
            description=description,
            provenance=provenance,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print(
        f"Reference panel {panel.key!r} {'created' if created else 'reused'} (#{panel.id})."
    )


def _benchmark_membership_command(
    *,
    panel_key: str,
    profile_id: int,
    reviewer: str,
    reason: str,
    action: str,
    base_dir: Path | None,
) -> None:
    database = get_database(base_dir)
    try:
        outcome = record_membership(
            database,
            panel_key=panel_key,
            profile_id=profile_id,
            action=action,
            reviewer=reviewer,
            rationale=reason,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print(
        f"Membership event #{outcome.event.id} "
        f"{'created' if outcome.created else 'reused'}: "
        f"{action} profile #{profile_id}."
    )


@benchmark_app.command("add-profile", help="Append a reviewed profile attachment event.")
def benchmark_add_profile(
    panel_key: str = typer.Argument(..., help="Reference panel key."),
    profile_id: int = typer.Option(..., "--profile-id", help="Speaker profile id."),
    reviewer: str = typer.Option(..., "--reviewer", help="Reviewer name."),
    reason: str = typer.Option(..., "--reason", help="Selection rationale."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    _benchmark_membership_command(
        panel_key=panel_key,
        profile_id=profile_id,
        reviewer=reviewer,
        reason=reason,
        action="attach",
        base_dir=base_dir,
    )


@benchmark_app.command("remove-profile", help="Append a reviewed profile detachment event.")
def benchmark_remove_profile(
    panel_key: str = typer.Argument(..., help="Reference panel key."),
    profile_id: int = typer.Option(..., "--profile-id", help="Speaker profile id."),
    reviewer: str = typer.Option(..., "--reviewer", help="Reviewer name."),
    reason: str = typer.Option(..., "--reason", help="Removal rationale."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    _benchmark_membership_command(
        panel_key=panel_key,
        profile_id=profile_id,
        reviewer=reviewer,
        reason=reason,
        action="detach",
        base_dir=base_dir,
    )


@benchmark_app.command("list", help="List named reference panels.")
def benchmark_list(
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    table = Table(title="Reference Panels")
    table.add_column("Key")
    table.add_column("Name")
    table.add_column("Members", justify="right")
    table.add_column("Latest snapshot", justify="right")
    for panel in database.list_reference_panels():
        snapshot = database.get_latest_reference_panel_snapshot(panel.id)
        table.add_row(
            panel.key,
            panel.display_name,
            str(len(effective_membership(database, panel))),
            f"#{snapshot.id}" if snapshot is not None else "—",
        )
    console.print(table)


@benchmark_app.command("show", help="Inspect panel metadata and effective membership.")
def benchmark_show(
    panel_key: str = typer.Argument(..., help="Reference panel key."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    panel = database.get_reference_panel(panel_key)
    if panel is None:
        raise typer.BadParameter(f"Unknown reference panel: {panel_key}")
    console.print(f"{panel.display_name} ({panel.key})")
    console.print(f"Description: {panel.description}")
    console.print(f"Provenance: {panel.provenance}")
    table = Table(title="Effective Reviewed Membership")
    table.add_column("Reviewed profile id(s)")
    table.add_column("Redirect-resolved profile")
    table.add_column("Reviewer")
    table.add_column("Rationale")
    for membership in effective_membership(database, panel):
        reviews = membership["membership_reviews"]
        table.add_row(
            ", ".join(str(value) for value in membership["requested_profile_ids"]),
            str(membership["resolved_profile_id"]),
            "; ".join(str(review["reviewer"]) for review in reviews),
            "; ".join(str(review["rationale"]) for review in reviews),
        )
    console.print(table)


@benchmark_app.command("build", help="Build or reuse an immutable panel snapshot.")
def benchmark_build(
    panel_key: str = typer.Argument(..., help="Reference panel key."),
    minimum_analyzed_sermons: int = typer.Option(3, "--min-analyzed-sermons"),
    minimum_total_sermon_words: int = typer.Option(10_000, "--min-total-words"),
    minimum_analysis_coverage: float = typer.Option(0.8, "--min-coverage"),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    if minimum_analyzed_sermons < 0 or minimum_total_sermon_words < 0:
        raise typer.BadParameter("Eligibility minimums must not be negative")
    if not 0.0 <= minimum_analysis_coverage <= 1.0:
        raise typer.BadParameter("--min-coverage must be between 0 and 1")
    database = get_database(base_dir)
    policy = EligibilityPolicy(
        minimum_analyzed_sermons=minimum_analyzed_sermons,
        minimum_total_sermon_words=minimum_total_sermon_words,
        minimum_analysis_coverage=minimum_analysis_coverage,
    )
    try:
        outcome = build_snapshot(database, panel_key, policy=policy)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    panel = database.get_reference_panel(panel_key)
    assert panel is not None
    document = snapshot_document(database, panel, outcome.snapshot)
    eligible = sum(
        member["eligibility_status"] == "eligible" for member in document["members"]
    )
    console.print(
        f"Snapshot #{outcome.snapshot.id} "
        f"{'created' if outcome.created else 'reused'}; "
        f"eligible={eligible}; excluded={len(document['members']) - eligible}."
    )
    console.print(
        f"Fingerprint: {outcome.snapshot.input_fingerprint}; "
        f"profile analyzer: {outcome.snapshot.profile_analyzer_key}@"
        f"{outcome.snapshot.profile_analyzer_version}; "
        f"features: {outcome.snapshot.feature_schema_version}; "
        f"eligibility: {outcome.snapshot.eligibility_policy_version}."
    )


@benchmark_app.command("show-snapshot", help="Inspect the latest immutable panel snapshot.")
def benchmark_show_snapshot(
    panel_key: str = typer.Argument(..., help="Reference panel key."),
    json_output: bool = typer.Option(False, "--json", help="Emit stable JSON and feature matrix."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    panel = database.get_reference_panel(panel_key)
    if panel is None:
        raise typer.BadParameter(f"Unknown reference panel: {panel_key}")
    snapshot = database.get_latest_reference_panel_snapshot(panel.id)
    if snapshot is None:
        raise typer.BadParameter(
            f"Reference panel {panel_key!r} has no snapshot. Run 'pte benchmark build' first."
        )
    document = snapshot_document(database, panel, snapshot)
    if json_output:
        console.print_json(json.dumps(document, sort_keys=True))
        return
    console.print(
        f"Snapshot #{snapshot.id}: {snapshot.input_fingerprint}\n"
        f"Profile analyzer: {snapshot.profile_analyzer_key}@{snapshot.profile_analyzer_version}\n"
        f"Feature schema: {snapshot.feature_schema_version}\n"
        f"Eligibility policy: {snapshot.eligibility_policy_version}"
    )
    table = Table(title=f"Snapshot Members — {panel.key}")
    table.add_column("Reviewed")
    table.add_column("Resolved")
    table.add_column("Display label")
    table.add_column("Profile analysis")
    table.add_column("Status")
    table.add_column("Reasons")
    for member in document["members"]:
        table.add_row(
            ", ".join(str(value) for value in member["requested_profile_ids"]),
            str(member["resolved_profile_id"]),
            str(member["resolved_display_label"]),
            (
                f"#{member['profile_analysis_run_id']}"
                if member["profile_analysis_run_id"] is not None
                else "—"
            ),
            str(member["eligibility_status"]),
            ", ".join(member["exclusion_reasons"]) or "—",
        )
    console.print(table)
    console.print(
        "Comparison features (ordered): "
        + ", ".join(document["snapshot"]["comparison_feature_names"])
    )
    console.print(
        "Coverage diagnostics (excluded from comparison): "
        + ", ".join(document["snapshot"]["coverage_feature_names"])
    )


def _analysis_videos(
    database: Database,
    *,
    video_id: int | None,
    youtube_video_id: str | None,
    profile_id: int | None,
    pastor_slug: str | None,
) -> tuple[list, int | None]:
    if sum(
        value is not None
        for value in (video_id, youtube_video_id, profile_id, pastor_slug)
    ) != 1:
        raise typer.BadParameter(
            "Choose exactly one scope: --video-id, --youtube-video-id, "
            "--profile-id, or --pastor."
        )
    if video_id is not None:
        video = database.get_video_by_id(video_id)
        if video is None:
            raise typer.BadParameter(f"Unknown database video id: {video_id}")
        return [video], None
    if youtube_video_id is not None:
        video = database.get_video_by_youtube_id(youtube_video_id)
        if video is None:
            raise typer.BadParameter(f"Unknown YouTube video ID: {youtube_video_id}")
        return [video], None

    if pastor_slug is not None:
        pastor = database.get_pastor_by_slug(pastor_slug)
        if pastor is None:
            raise _unknown_pastor_error(pastor_slug)
        profile_id = database.get_pastor_speaker_profile_id(pastor.id)
        if profile_id is None:
            raise typer.BadParameter(
                f"Pastor {pastor_slug} is not bound to a speaker profile. "
                "Use --profile-id after identity review establishes one."
            )

    assert profile_id is not None
    try:
        scope = resolve_profile_sermon_scope(database, profile_id)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    return list(scope.videos), scope.profile_id


@analysis_app.command(
    "run", help="Analyze one identified sermon or a speaker profile's attached sermons."
)
def analysis_run(
    video_id: int | None = typer.Option(None, "--video-id", help="Database video id."),
    youtube_video_id: str | None = typer.Option(
        None, "--youtube-video-id", help="YouTube video id."
    ),
    profile_id: int | None = typer.Option(
        None,
        "--profile-id",
        help="Canonical speaker profile id; selects effectively attached sermons.",
    ),
    pastor: str | None = typer.Option(
        None,
        "--pastor",
        help="Compatibility alias resolved through the pastor's speaker-profile binding.",
    ),
    analyzer_version: str = typer.Option(
        SERMON_ANALYZER_VERSION,
        "--analyzer-version",
        help="Version recorded in provenance; change this when analyzer behavior changes.",
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    videos, resolved_profile_id = _analysis_videos(
        database,
        video_id=video_id,
        youtube_video_id=youtube_video_id,
        profile_id=profile_id,
        pastor_slug=pastor,
    )
    if resolved_profile_id is not None:
        console.print(f"Speaker profile #{resolved_profile_id}: {len(videos)} sermon(s).")
    created = reused = skipped = 0
    for video in videos:
        try:
            outcome = analyze_sermon(
                database, video, analyzer_version=analyzer_version
            )
        except ValueError as error:
            if len(videos) == 1:
                raise typer.BadParameter(str(error)) from error
            skipped += 1
            console.print(f"Skipped {video.youtube_video_id}: {error}", markup=False)
            continue
        if outcome.created:
            created += 1
            state = "created"
        else:
            reused += 1
            state = "reused"
        console.print(
            f"{video.youtube_video_id}: analysis #{outcome.run.id} {state} "
            f"({outcome.run.analyzer_key}@{outcome.run.analyzer_version})"
        )
    console.print(
        f"Analysis complete: created={created}, reused={reused}, skipped={skipped}."
    )


@analysis_app.command("show", help="Inspect persisted sermon measurements and Scripture evidence.")
def analysis_show(
    video_id: int | None = typer.Option(None, "--video-id", help="Database video id."),
    youtube_video_id: str | None = typer.Option(
        None, "--youtube-video-id", help="YouTube video id."
    ),
    profile_id: int | None = typer.Option(
        None,
        "--profile-id",
        help="Canonical speaker profile id; selects effectively attached sermons.",
    ),
    pastor: str | None = typer.Option(
        None,
        "--pastor",
        help="Compatibility alias resolved through the pastor's speaker-profile binding.",
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    videos, resolved_profile_id = _analysis_videos(
        database,
        video_id=video_id,
        youtube_video_id=youtube_video_id,
        profile_id=profile_id,
        pastor_slug=pastor,
    )
    title = (
        f"Sermon Analysis — Speaker Profile #{resolved_profile_id}"
        if resolved_profile_id is not None
        else "Sermon Analysis"
    )
    summary = Table(title=title)
    summary.add_column("Video")
    summary.add_column("Version")
    summary.add_column("Words", justify="right")
    summary.add_column("Duration", justify="right")
    summary.add_column("References", justify="right")
    summary.add_column("Text alignments", justify="right")
    summary.add_column("Books", justify="right")
    found: list[tuple[object, object]] = []
    for video in videos:
        run = database.get_latest_sermon_analysis_run(video.id, SERMON_ANALYZER_KEY)
        if run is None:
            continue
        values = {
            item.metric_key: json.loads(item.value_json)
            for item in database.list_sermon_analysis_measurements(run.id)
        }
        duration = values.get("sermon_duration_seconds")
        duration_text = (
            format_timestamp(float(duration)) if isinstance(duration, (int, float)) else "—"
        )
        summary.add_row(
            video.youtube_video_id,
            run.analyzer_version,
            str(values.get("word_count", "—")),
            duration_text,
            str(values.get("scripture_reference_mentions", "—")),
            str(values.get("scripture_text_alignment_count", "—")),
            str(values.get("distinct_scripture_books", "—")),
        )
        found.append((video, run))
    if not found:
        console.print("No sermon analysis results found. Run 'pte analysis run' first.")
        return
    console.print(summary)

    if len(found) == 1:
        video, run = found[0]
        references = Table(title=f"Scripture Evidence — {video.youtube_video_id}")
        references.add_column("Reference")
        references.add_column("Class")
        references.add_column("Confidence")
        references.add_column("Time")
        references.add_column("Segment", justify="right")
        references.add_column("Transcript match")
        alignment_sources: set[str] = set()
        for item in database.list_sermon_analysis_evidence(run.id):
            payload = json.loads(item.payload_json)
            bible_source = payload.get("bible_source")
            if isinstance(bible_source, dict):
                alignment_sources.add(
                    f"{bible_source.get('translation_name', 'unknown')} "
                    f"({bible_source.get('translation_version', 'unknown')}; "
                    f"{bible_source.get('artifact_version', 'unknown')})"
                )
            references.add_row(
                str(payload.get("canonical_reference", "—")),
                str(
                    payload.get("detection_class")
                    or payload.get("alignment_class", "—")
                ),
                str(
                    payload.get("detection_confidence")
                    or payload.get("alignment_score", "—")
                ),
                format_timestamp(item.start_seconds) if item.start_seconds is not None else "—",
                str(item.segment_index) if item.segment_index is not None else "—",
                item.excerpt,
            )
        console.print(references)
        for source in sorted(alignment_sources):
            console.print(f"Bible alignment source: {source}")
        console.print(
            f"Provenance: run=#{run.id}; extraction=#{run.extraction_result_id}; "
            f"source_sha256={run.source_content_sha256}; input={run.input_fingerprint}"
        )


def _profile_analysis_values(database: Database, run_id: int) -> dict[str, object]:
    return {
        item.metric_key: json.loads(item.value_json)
        for item in database.list_speaker_profile_analysis_measurements(run_id)
    }


def _print_profile_scripture_summary(database: Database, run) -> None:
    values = _profile_analysis_values(database, run.id)
    coverage = Table(title=f"Scripture Usage — Speaker Profile #{run.profile_id}")
    coverage.add_column("Coverage")
    coverage.add_column("Value", justify="right")
    attached = values.get("sermons_attached", 0)
    analyzed = values.get("sermons_analyzed", 0)
    date_start = values.get("date_range_start")
    date_end = values.get("date_range_end")
    date_range = f"{date_start or '—'} to {date_end or '—'}"
    coverage.add_row("Sermons analyzed", f"{analyzed} / {attached}")
    coverage.add_row("Total sermon words", f"{values.get('total_sermon_words', 0):,}")
    coverage.add_row("Date range", date_range)
    coverage.add_row("Detected references", str(values.get("reference_mentions", 0)))
    coverage.add_row(
        "Explicit references", str(values.get("explicit_reference_mentions", 0))
    )
    coverage.add_row(
        "Contextual references", str(values.get("contextual_reference_mentions", 0))
    )
    coverage.add_row(
        "Scripture text alignments", str(values.get("scripture_text_alignments", 0))
    )
    coverage.add_row(
        "Aligned transcript span words",
        str(values.get("scripture_aligned_transcript_span_words", 0)),
    )
    diagnostics = values.get("reference_detection_diagnostics", {})
    if isinstance(diagnostics, dict):
        coverage.add_row(
            "Zero-reference sermons",
            str(diagnostics.get("sermons_with_zero_detected_references", 0)),
        )
        coverage.add_row(
            "Detection scope", str(diagnostics.get("detection_scope", "—"))
        )
        coverage.add_row(
            "Confidence counts",
            json.dumps(diagnostics.get("detection_confidence_counts", {}), sort_keys=True),
        )
        coverage.add_row(
            "References with placement",
            f"{diagnostics.get('references_with_placement', 0)} / "
            f"{values.get('reference_mentions', 0)}",
        )
    console.print(coverage)

    usage = Table(title="Usage")
    usage.add_column("Measurement")
    usage.add_column("Value", justify="right")
    usage.add_row(
        "References / 1k words",
        str(values.get("references_per_1000_words", 0.0)),
    )
    usage.add_row(
        "Old Testament",
        f"{values.get('old_testament_mentions', 0)} "
        f"({values.get('old_testament_percent', 0.0)}%)",
    )
    usage.add_row(
        "New Testament",
        f"{values.get('new_testament_mentions', 0)} "
        f"({values.get('new_testament_percent', 0.0)}%)",
    )
    console.print(usage)

    books = Table(title="Top Books")
    books.add_column("Book")
    books.add_column("Mentions", justify="right")
    top_books = values.get("top_scripture_books", [])
    if isinstance(top_books, list):
        for item in top_books[:10]:
            if isinstance(item, dict):
                books.add_row(str(item.get("book", "—")), str(item.get("mentions", 0)))
    console.print(books)

    repeated = Table(title="Repeated Chapters")
    repeated.add_column("Passage")
    repeated.add_column("Sermons", justify="right")
    repeated.add_column("Mentions", justify="right")
    repeated_chapters = values.get("repeated_scripture_chapters", [])
    if isinstance(repeated_chapters, list):
        for item in repeated_chapters:
            if isinstance(item, dict):
                repeated.add_row(
                    str(item.get("passage", "—")),
                    str(item.get("sermon_count", 0)),
                    str(item.get("mentions", 0)),
                )
    console.print(repeated)

    placement = Table(title="Placement")
    placement.add_column("Quarter")
    placement.add_column("Mentions", justify="right")
    placement.add_column("Percent", justify="right")
    placement_values = values.get("reference_placement_by_quarter", {})
    if isinstance(placement_values, dict):
        for quarter in ("Q1", "Q2", "Q3", "Q4"):
            item = placement_values.get(quarter, {})
            if isinstance(item, dict):
                placement.add_row(
                    quarter,
                    str(item.get("mentions", 0)),
                    f"{item.get('percent', 0.0)}%",
                )
    console.print(placement)

    structural = Table(title="Structural Scripture Features")
    structural.add_column("Feature")
    structural.add_column("Value", justify="right")
    structural_values = values.get("structural_scripture_features", {})
    if isinstance(structural_values, dict):
        for feature in (
            "book_breadth_per_10_references",
            "chapter_breadth_per_10_references",
            "book_concentration_hhi",
            "effective_book_count",
            "sustained_chapter_reference_ratio",
            "multi_verse_reference_ratio",
            "cross_sermon_anchor_coverage",
            "mean_pairwise_book_distribution_cosine",
            "reference_density_consistency",
            "scripture_text_engagement_fraction",
            "sermons_with_text_alignment_fraction",
            "anchored_text_alignment_fraction",
            "mean_scripture_text_alignment_score",
            "aligned_passage_concentration_hhi",
        ):
            value = structural_values.get(feature)
            structural.add_row(
                feature,
                "insufficient coverage" if value is None else str(value),
            )
    console.print(structural)

    emphasis = Table(title="Canonical Emphasis")
    emphasis.add_column("Division")
    emphasis.add_column("Mentions", justify="right")
    emphasis.add_column("Share", justify="right")
    division_values = values.get("canonical_division_emphasis", {})
    if isinstance(division_values, dict):
        for division, item in division_values.items():
            if isinstance(item, dict):
                share = item.get("share")
                emphasis.add_row(
                    str(division),
                    str(item.get("mentions", 0)),
                    "insufficient coverage" if share is None else str(share),
                )
    console.print(emphasis)

    structural_coverage = values.get("structural_coverage_diagnostics", {})
    if isinstance(structural_coverage, dict):
        console.print(
            "Structural coverage: "
            f"reference-bearing sermons="
            f"{structural_coverage.get('sermons_with_detected_references', 0)}/"
            f"{structural_coverage.get('sermons_analyzed', 0)}; "
            f"book-distribution pairs="
            f"{structural_coverage.get('reference_bearing_sermon_pairs_compared', 0)}; "
            f"text-aligned sermons="
            f"{structural_coverage.get('sermons_with_scripture_text_alignments', 0)}/"
            f"{structural_coverage.get('sermons_analyzed', 0)}; "
            "null means insufficient evidence."
        )
    console.print(
        f"Provenance: profile_analysis=#{run.id}; version={run.analyzer_version}; "
        f"membership={run.membership_fingerprint}; input={run.input_fingerprint}"
    )


@analysis_app.command(
    "summarize-profile",
    help="Materialize a deterministic Scripture-usage summary for a speaker profile.",
)
def analysis_summarize_profile(
    profile_id: int = typer.Option(..., "--profile-id", help="Speaker profile id."),
    analyzer_version: str = typer.Option(
        PROFILE_ANALYZER_VERSION,
        "--analyzer-version",
        help="Profile analyzer version recorded in provenance.",
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    try:
        outcome = build_profile_scripture_analysis(
            database, profile_id, analyzer_version=analyzer_version
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print(
        f"Profile analysis #{outcome.run.id} "
        f"{'created' if outcome.created else 'reused'}."
    )
    _print_profile_scripture_summary(database, outcome.run)


@analysis_app.command(
    "show-profile",
    help="Inspect the latest materialized Scripture summary for a speaker profile.",
)
def analysis_show_profile(
    profile_id: int = typer.Option(..., "--profile-id", help="Speaker profile id."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    try:
        scope = resolve_profile_sermon_scope(database, profile_id)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    run = database.get_latest_speaker_profile_analysis_run(
        scope.profile_id, PROFILE_ANALYZER_KEY
    )
    if run is None:
        raise typer.BadParameter(
            f"Speaker profile {scope.profile_id} has no materialized profile analysis. "
            "Run 'pte analysis summarize-profile' first."
        )
    _print_profile_scripture_summary(database, run)


@analysis_app.command(
    "evaluate-scripture-detector",
    help="Evaluate explicit and contextual detection against the reviewed fixture.",
)
def analysis_evaluate_scripture_detector(
    fixture: Path = typer.Argument(
        Path("evaluation/scripture-references/contextual-v1.json"),
        help="Reviewed Scripture-reference evaluation fixture.",
    ),
) -> None:
    try:
        result = evaluate_scripture_detector(fixture)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    table = Table(title=f"Scripture Detector Evaluation — {result.corpus_version}")
    table.add_column("Class")
    table.add_column("TP", justify="right")
    table.add_column("FP", justify="right")
    table.add_column("FN", justify="right")
    table.add_column("Precision", justify="right")
    table.add_column("Recall", justify="right")
    for label, metrics in (("overall", result.overall), *result.by_class.items()):
        table.add_row(
            label,
            str(metrics.true_positive),
            str(metrics.false_positive),
            str(metrics.false_negative),
            f"{metrics.precision:.3f}",
            f"{metrics.recall:.3f}",
        )
    console.print(table)
    console.print(
        f"Cases passed: {result.passed_case_count}/{result.case_count}; "
        f"negative controls passed: {result.overall.true_negative_cases}; "
        f"methods={json.dumps(result.method_detection_counts, sort_keys=True)}"
    )
    for failure in result.failures:
        console.print(
            f"Miss: {failure['case_id']}; expected={failure['expected']}; "
            f"detected={failure['detected']}",
            markup=False,
        )


@analysis_app.command(
    "evaluate-scripture-alignment",
    help="Evaluate conservative Bible-text alignment against the reviewed fixture.",
)
def analysis_evaluate_scripture_alignment(
    fixture: Path = typer.Argument(
        Path("evaluation/scripture-alignments/reviewed-v1.json"),
        help="Reviewed Scripture-text alignment evaluation fixture.",
    ),
) -> None:
    try:
        result = evaluate_scripture_alignment(fixture)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    table = Table(title=f"Scripture Alignment Evaluation — {result.corpus_version}")
    table.add_column("Class")
    table.add_column("TP", justify="right")
    table.add_column("FP", justify="right")
    table.add_column("FN", justify="right")
    table.add_column("Precision", justify="right")
    table.add_column("Recall", justify="right")
    for label, metrics in (("overall", result.overall), *result.by_class.items()):
        table.add_row(
            label,
            str(metrics.true_positive),
            str(metrics.false_positive),
            str(metrics.false_negative),
            f"{metrics.precision:.3f}",
            f"{metrics.recall:.3f}",
        )
    console.print(table)
    console.print(
        f"Cases passed: {result.passed_case_count}/{result.case_count}; "
        f"negative controls passed: {result.overall.true_negative_cases}; "
        f"Bible source={result.bible_source['translation_name']} "
        f"({result.bible_source['translation_version']}, "
        f"{result.bible_source['artifact_version']})."
    )
    for failure in result.failures:
        console.print(
            f"Miss: {failure['case_id']}; expected={failure['expected']}; "
            f"detected={failure['detected']}",
            markup=False,
        )


@analysis_app.command(
    "style-run",
    help="Generate validated style support and candidate runs for a sermon or profile.",
)
def analysis_style_run(
    video_id: int | None = typer.Option(None, "--video-id", help="Database video id."),
    youtube_video_id: str | None = typer.Option(
        None, "--youtube-video-id", help="YouTube video id."
    ),
    profile_id: int | None = typer.Option(None, "--profile-id", help="Speaker profile id."),
    pastor: str | None = typer.Option(None, "--pastor", help="Compatibility profile alias."),
    model: str | None = typer.Option(None, "--model", help="Override configured Ollama model."),
    analyzer_version: str = typer.Option(
        STYLE_ANALYZER_VERSION, "--analyzer-version", help="Semantic analyzer version."
    ),
    prompt_version: str = typer.Option(
        STYLE_PROMPT_VERSION, "--prompt-version", help="Semantic prompt version."
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    videos, resolved_profile_id = _analysis_videos(
        database,
        video_id=video_id,
        youtube_video_id=youtube_video_id,
        profile_id=profile_id,
        pastor_slug=pastor,
    )
    config = build_llm_config()
    if model is not None:
        config = replace(config, enabled=True, model=model)
    if not config.enabled:
        raise typer.BadParameter("Local LLM is disabled; enable it or pass --model.")
    client = OllamaClient(config)
    try:
        model_digest = client.model_digest()
    except LocalLlmError as error:
        raise typer.BadParameter(str(error)) from error
    if resolved_profile_id is not None:
        console.print(f"Speaker profile #{resolved_profile_id}: {len(videos)} sermon(s).")
    created = reused = skipped = 0
    for video in videos:
        try:
            outcome = analyze_sermon_style(
                database,
                video,
                client,
                model_digest=model_digest,
                context_size=config.context_size,
                analyzer_version=analyzer_version,
                prompt_version=prompt_version,
            )
        except (LocalLlmError, ValueError) as error:
            if len(videos) == 1:
                raise typer.BadParameter(str(error)) from error
            skipped += 1
            console.print(f"Skipped {video.youtube_video_id}: {error}", markup=False)
            continue
        created += int(outcome.created)
        reused += int(not outcome.created)
        console.print(
            f"{video.youtube_video_id}: style analysis #{outcome.run.id} "
            f"{'created' if outcome.created else 'reused'} "
            f"({outcome.run.analyzer_key}@{outcome.run.analyzer_version})"
        )
    console.print(
        f"Style analysis complete: created={created}, reused={reused}, skipped={skipped}."
    )


@analysis_app.command(
    "style-show", help="Inspect persisted semantic style evidence and measurements."
)
def analysis_style_show(
    video_id: int | None = typer.Option(None, "--video-id", help="Database video id."),
    youtube_video_id: str | None = typer.Option(
        None, "--youtube-video-id", help="YouTube video id."
    ),
    profile_id: int | None = typer.Option(None, "--profile-id", help="Speaker profile id."),
    pastor: str | None = typer.Option(None, "--pastor", help="Compatibility profile alias."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    videos, resolved_profile_id = _analysis_videos(
        database,
        video_id=video_id,
        youtube_video_id=youtube_video_id,
        profile_id=profile_id,
        pastor_slug=pastor,
    )
    summary = Table(
        title=(
            f"Style Evidence — Speaker Profile #{resolved_profile_id}"
            if resolved_profile_id is not None
            else "Style Evidence"
        )
    )
    summary.add_column("Video")
    summary.add_column("Version")
    summary.add_column("Accepted evidence", justify="right")
    summary.add_column("Candidate runs", justify="right")
    summary.add_column("Analyzed", justify="right")
    found = []
    for video in videos:
        run = database.get_latest_sermon_analysis_run(video.id, STYLE_ANALYZER_KEY)
        if run is None:
            continue
        values = {
            item.metric_key: json.loads(item.value_json)
            for item in database.list_sermon_analysis_measurements(run.id)
        }
        summary.add_row(
            video.youtube_video_id,
            run.analyzer_version,
            str(values.get("semantic_evidence_count", 0)),
            str(values.get("candidate_style_run_count", 0)),
            f"{100 * float(values.get('semantic_analysis_coverage_fraction', 0)):.1f}%",
        )
        found.append((video, run, values))
    if not found:
        console.print("No style analysis found. Run 'pte analysis style-run' first.")
        return
    console.print(summary)
    if len(found) == 1:
        video, run, values = found[0]
        evidence_table = Table(title=f"Accepted Style Evidence — {video.youtube_video_id}")
        evidence_table.add_column("Dimension")
        evidence_table.add_column("Time")
        evidence_table.add_column("Scripture")
        evidence_table.add_column("Transcript evidence")
        for evidence in database.list_sermon_analysis_evidence(run.id):
            if evidence.evidence_kind != "semantic_style_evidence":
                continue
            payload = json.loads(evidence.payload_json)
            corroboration = payload.get("scripture_corroboration", [])
            references = sorted(
                {
                    str(item.get("canonical_reference"))
                    for item in corroboration
                    if isinstance(item, dict) and item.get("canonical_reference")
                }
            ) if isinstance(corroboration, list) else []
            evidence_table.add_row(
                str(payload.get("dimension", "—")),
                (
                    f"{format_timestamp(evidence.start_seconds)}–"
                    f"{format_timestamp(evidence.end_seconds)}"
                    if evidence.start_seconds is not None and evidence.end_seconds is not None
                    else "—"
                ),
                ", ".join(references) or "—",
                evidence.excerpt,
            )
        console.print(evidence_table)
        runs_table = Table(title=f"Candidate Representative Style Runs — {video.youtube_video_id}")
        runs_table.add_column("Dimension")
        runs_table.add_column("Time")
        runs_table.add_column("Boundary status")
        runs_table.add_column("Transcript run")
        for evidence in database.list_sermon_analysis_evidence(run.id):
            if evidence.evidence_kind != "semantic_style_run":
                continue
            payload = json.loads(evidence.payload_json)
            runs_table.add_row(
                str(payload.get("dimension", "—")),
                (
                    f"{format_timestamp(evidence.start_seconds)}–"
                    f"{format_timestamp(evidence.end_seconds)}"
                    if evidence.start_seconds is not None and evidence.end_seconds is not None
                    else "—"
                ),
                str(payload.get("boundary_status", "unreviewed")),
                evidence.excerpt,
            )
        console.print(runs_table)
        console.print(
            f"Provenance: run=#{run.id}; model="
            f"{json.dumps(values.get('model_provenance', {}), sort_keys=True)}; "
            f"prompt={json.dumps(values.get('prompt_provenance', {}), sort_keys=True)}"
        )


def _print_style_profile(database: Database, run) -> None:
    values = {
        item.metric_key: json.loads(item.value_json)
        for item in database.list_speaker_profile_analysis_measurements(run.id)
    }
    coverage = Table(title=f"Style Profile — Speaker Profile #{run.profile_id}")
    coverage.add_column("Coverage")
    coverage.add_column("Value", justify="right")
    coverage.add_row(
        "Sermons analyzed",
        f"{values.get('sermons_analyzed', 0)} / {values.get('sermons_attached', 0)}",
    )
    fraction = values.get("semantic_analysis_coverage_fraction")
    coverage.add_row(
        "Timestamped transcript analyzed",
        "insufficient coverage" if fraction is None else f"{100 * float(fraction):.1f}%",
    )
    console.print(coverage)
    styles = Table(title="Evidence-backed Style Dimensions")
    styles.add_column("Dimension")
    styles.add_column("Evidence", justify="right")
    styles.add_column("Sermons", justify="right")
    styles.add_column("Accepted evidence duration", justify="right")
    styles.add_column("Accepted evidence coverage", justify="right")
    styles.add_column("Candidate runs", justify="right")
    styles.add_column("Candidate run coverage", justify="right")
    dimensions = values.get("style_dimension_profiles", {})
    if isinstance(dimensions, dict):
        for dimension, metrics in dimensions.items():
            if not isinstance(metrics, dict):
                continue
            evidence_duration = metrics.get(
                "accepted_evidence_duration_seconds",
                metrics.get("duration_seconds", 0),
            )
            evidence_coverage = metrics.get(
                "accepted_evidence_coverage_fraction",
                metrics.get("duration_coverage_fraction"),
            )
            run_coverage = metrics.get("candidate_style_run_coverage_fraction")
            run_count = metrics.get("candidate_style_run_count")
            styles.add_row(
                str(dimension),
                str(metrics.get("evidence_count", 0)),
                f"{metrics.get('sermons_with_evidence', 0)}/{values.get('sermons_analyzed', 0)}",
                f"{float(evidence_duration):.1f}s",
                "—" if evidence_coverage is None else f"{100 * float(evidence_coverage):.1f}%",
                "—" if run_count is None else str(run_count),
                "—" if run_coverage is None else f"{100 * float(run_coverage):.1f}%*",
            )
    console.print(styles)
    console.print(
        "* Candidate run coverage uses unreviewed model boundaries; do not interpret it "
        "as representative profile coverage until boundary evaluation is complete."
    )
    console.print(
        f"Provenance: profile_analysis=#{run.id}; version={run.analyzer_version}; "
        f"membership={run.membership_fingerprint}; input={run.input_fingerprint}"
    )


@analysis_app.command(
    "style-summarize-profile",
    help="Materialize a profile summary from accepted sermon style evidence.",
)
def analysis_style_summarize_profile(
    profile_id: int = typer.Option(..., "--profile-id", help="Speaker profile id."),
    analyzer_version: str = typer.Option(
        STYLE_PROFILE_ANALYZER_VERSION,
        "--analyzer-version",
        help="Style profile analyzer version.",
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    try:
        outcome = build_profile_style_analysis(
            database, profile_id, analyzer_version=analyzer_version
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print(
        f"Style profile analysis #{outcome.run.id} "
        f"{'created' if outcome.created else 'reused'}."
    )
    _print_style_profile(database, outcome.run)


@analysis_app.command(
    "style-show-profile", help="Inspect the latest materialized style profile."
)
def analysis_style_show_profile(
    profile_id: int = typer.Option(..., "--profile-id", help="Speaker profile id."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    try:
        scope = resolve_profile_sermon_scope(database, profile_id)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    run = database.get_latest_speaker_profile_analysis_run(
        scope.profile_id, STYLE_PROFILE_ANALYZER_KEY
    )
    if run is None:
        raise typer.BadParameter(
            "No materialized style profile. Run 'pte analysis style-summarize-profile' first."
        )
    _print_style_profile(database, run)


@analysis_app.command(
    "style-review-create",
    help="Create a full-sermon style-run adjudication packet.",
)
def analysis_style_review_create(
    youtube_video_id: str = typer.Option(
        ..., "--youtube-video-id", help="YouTube video id."
    ),
    output: Path = typer.Option(..., "--output", help="Review draft JSON path."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    video = database.get_video_by_youtube_id(youtube_video_id)
    if video is None:
        raise typer.BadParameter(f"Unknown YouTube video: {youtube_video_id}")
    try:
        payload = create_style_review_packet(database, video, output)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print(
        f"Created full-sermon style review draft with "
        f"{len(payload['segments'])} transcript segments and "
        f"{len(payload['candidate_style_runs'])} candidate runs: {output} "
        f"(inspection view: {output.with_suffix('.md')})"
    )


@analysis_app.command(
    "style-review-finalize",
    help="Validate an edited style review draft and mark it reviewed.",
)
def analysis_style_review_finalize(
    draft: Path = typer.Argument(..., help="Edited review draft JSON."),
    output: Path = typer.Option(..., "--output", help="Final reviewed JSON path."),
    reviewer: str = typer.Option(..., "--reviewer", help="Reviewer identity."),
) -> None:
    try:
        payload = finalize_style_review(draft, output, reviewer=reviewer)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        raise typer.BadParameter(str(error)) from error
    console.print(
        f"Finalized style review with {len(payload['candidate_style_runs'])} "
        f"candidate adjudications and {len(payload['missed_style_runs'])} missed runs: "
        f"{output}"
    )


@analysis_app.command(
    "evaluate-style-boundaries",
    help="Evaluate run detection and boundaries from full-sermon reviewed packets.",
)
def analysis_evaluate_style_boundaries(
    reviews: list[Path] = typer.Argument(..., help="Reviewed style packet JSON files."),
) -> None:
    try:
        result = evaluate_style_boundaries(reviews)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        raise typer.BadParameter(str(error)) from error
    table = Table(title=f"Style Run Boundary Evaluation — {result.sermon_count} sermon(s)")
    table.add_column("Dimension")
    table.add_column("Run P", justify="right")
    table.add_column("Run R", justify="right")
    table.add_column("Reviewed duration recovered", justify="right")
    table.add_column("Accepted duration correct", justify="right")
    table.add_column("Duration IoU", justify="right")
    for label, metrics in (("overall", result.overall), *result.by_dimension.items()):
        table.add_row(
            label,
            f"{metrics.run_precision:.3f}",
            f"{metrics.run_recall:.3f}",
            f"{metrics.reviewed_duration_recall:.3f}",
            f"{metrics.accepted_duration_precision:.3f}",
            f"{metrics.duration_intersection_over_union:.3f}",
        )
    console.print(table)
    console.print(
        f"Judgments: {json.dumps(result.judgment_counts, sort_keys=True)}",
        markup=False,
    )


@analysis_app.command(
    "evaluate-style", help="Evaluate the configured semantic style model on reviewed cases."
)
def analysis_evaluate_style(
    fixture: Path = typer.Argument(
        Path("evaluation/sermon-style/reviewed-v2.json"), help="Reviewed style fixture."
    ),
    model: str | None = typer.Option(None, "--model", help="Override configured Ollama model."),
) -> None:
    config = build_llm_config()
    if model is not None:
        config = replace(config, enabled=True, model=model)
    client = OllamaClient(config)
    try:
        digest = client.model_digest()
        result = evaluate_style_model(fixture, client, model_digest=digest)
    except (LocalLlmError, ValueError) as error:
        raise typer.BadParameter(str(error)) from error
    table = Table(title=f"Style Evaluation — {result.corpus_version}")
    table.add_column("Dimension")
    table.add_column("TP", justify="right")
    table.add_column("FP", justify="right")
    table.add_column("FN", justify="right")
    table.add_column("Precision", justify="right")
    table.add_column("Recall", justify="right")
    for label, metrics in (("overall", result.overall), *result.by_dimension.items()):
        table.add_row(
            label,
            str(metrics.true_positive),
            str(metrics.false_positive),
            str(metrics.false_negative),
            f"{metrics.precision:.3f}",
            f"{metrics.recall:.3f}",
        )
    console.print(table)
    console.print(
        f"Cases passed: {result.passed_case_count}/{result.case_count}; "
        f"negative controls passed: {result.overall.true_negative_cases}; "
        f"rejected proposals={result.rejected_proposal_count}; model={result.model}; "
        f"digest={result.model_digest}; prompt={result.prompt_version}."
    )
    for failure in result.failures:
        console.print(
            f"Miss: {failure['case_id']}; expected={failure['expected']}; "
            f"detected={failure['detected']}",
            markup=False,
        )


@identity_app.command(
    "compare-speakers",
    help="Run a read-only, abstention-first acoustic comparison of two speaker observations.",
)
def compare_speakers(
    video_a: str = typer.Argument(..., help="First YouTube video ID."),
    video_b: str = typer.Argument(..., help="Second YouTube video ID."),
    model_path: Path = typer.Option(
        Path("evaluation/speaker-pairs/models/3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx"),
        help="Local ONNX speaker-embedding model.",
    ),
    model_sha256: str = typer.Option(
        DEFAULT_SPEAKER_MODEL_SHA256,
        help="Required checksum for the local model.",
    ),
    cache_dir: Path = typer.Option(
        Path("evaluation/speaker-pairs/cache"), help="Ignored cache for exact WAV spans and embeddings."
    ),
    output_path: Path | None = typer.Option(
        None, help="Result JSON path; defaults to the ignored speaker-pair run directory."
    ),
    policy_path: Path | None = typer.Option(
        None,
        help="Explicitly approved decision policy; without one the comparison always abstains.",
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    paths = build_paths(base_dir)
    if not paths.database.exists():
        raise typer.BadParameter(f"Application database does not exist: {paths.database}")
    database = Database(paths.database, readonly=True)
    videos = [database.get_video_by_youtube_id(value) for value in (video_a, video_b)]
    missing = [value for value, video in zip((video_a, video_b), videos) if video is None]
    if missing:
        raise typer.BadParameter(f"Unknown YouTube video ID(s): {', '.join(missing)}")
    observations = [database.get_latest_speaker_observation_for_video(video.id) for video in videos]
    audio_paths = [resolve_normalized_audio_path(database, video.id) for video in videos]
    try:
        backend = SherpaOnnxEmbeddingBackend(
            model_path.expanduser().resolve(), expected_sha256=model_sha256
        )
        policy = DecisionPolicy.from_path(policy_path.expanduser().resolve()) if policy_path else None
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        raise typer.BadParameter(str(error)) from error
    cache_root = cache_dir.expanduser().resolve()
    result = analyze_observation_pair(
        observation_a=observations[0],
        observation_b=observations[1],
        audio_path_a=audio_paths[0],
        audio_path_b=audio_paths[1],
        span_cache=AudioSpanCache(cache_root),
        embedding_cache=EmbeddingCache(cache_root),
        backend=backend,
        policy=policy,
    )
    result["videos"] = {"a": video_a, "b": video_b}
    destination = (
        output_path.expanduser().resolve()
        if output_path
        else Path("evaluation/speaker-pairs/runs").resolve() / f"{video_a}--{video_b}.json"
    )
    write_pair_result(destination, result)
    console.print(f"{result['outcome']}: {result['reason']}")
    console.print(f"Wrote deterministic diagnostic evidence to {destination}")


@identity_app.command(
    "evaluate-observation-consistency",
    help=(
        "Plan or run threshold-free within-observation acoustic calibration "
        "against human qualification labels."
    ),
)
def evaluate_observation_consistency(
    evaluation_root: Path = typer.Option(
        Path("evaluation/speaker-pairs"),
        help="Speaker-pair drafts and review events root.",
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
    cache_dir: Path = typer.Option(
        Path("evaluation/speaker-pairs/cache"),
        help="Ignored embedding cache.",
    ),
    output_path: Path = typer.Option(
        Path(
            "evaluation/speaker-pairs/runs/"
            "observation-consistency-v1.json"
        ),
        help="Threshold-free calibration report.",
    ),
    execute: bool = typer.Option(
        False,
        "--execute",
        help="Run acoustic embeddings; without this flag only print the plan.",
    ),
) -> None:
    root = evaluation_root.expanduser().resolve()
    drafts = _load_json_artifacts(sorted((root / "drafts").glob("*.json")))
    reviews = _load_json_artifacts(
        sorted((root / "reviews").glob("*/*.json"))
    )
    examples, conflicts = collect_reviewed_observation_examples(
        drafts=drafts,
        reviews=reviews,
    )
    plan = build_observation_consistency_plan(
        examples=examples,
        conflicts=conflicts,
    )
    counts = plan["qualification_counts"]
    console.print(
        "Observation consistency calibration: "
        f"examples={plan['reviewed_example_count']} "
        f"single={counts['qualified_single_speaker']} "
        f"multiple={counts['multiple_speakers']} "
        f"invalid={counts['invalid_audio']} "
        f"conflicts={plan['conflict_count']}"
    )
    if not execute:
        console.print(
            "Plan only; no embeddings or report artifacts were created."
        )
        return
    try:
        backend = SherpaOnnxEmbeddingBackend(
            model_path.expanduser().resolve(),
            expected_sha256=model_sha256,
        )
        report = evaluate_observation_consistency_examples(
            examples=examples,
            conflicts=conflicts,
            embedding_cache=EmbeddingCache(
                cache_dir.expanduser().resolve()
            ),
            backend=backend,
        )
        destination = output_path.expanduser().resolve()
        write_observation_consistency_report(destination, report)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        raise typer.BadParameter(str(error)) from error
    console.print(
        f"Scored {report['scored_case_count']} reviewed observation(s)."
    )
    console.print(
        "Threshold-free only; automatic qualification and registry mutation "
        "remain disabled."
    )
    console.print(f"Wrote observation consistency report to {destination}")


@identity_app.command(
    "run-speaker-model-bakeoff",
    help="Preflight and execute the resumable exact-span speaker-model bake-off.",
)
def run_speaker_model_bakeoff(
    fixture_dir: Path = typer.Option(
        Path("evaluation/speaker-pairs/fixtures"),
        help="Approved exact-span speaker-pair fixtures.",
    ),
    manifest_path: Path = typer.Option(
        Path("evaluation/speaker-pairs/bakeoff-models.json"),
        help="Experimental candidate model manifest.",
    ),
    result_root: Path = typer.Option(
        Path("evaluation/speaker-pairs/runs/by-model"),
        help="Model-fingerprint-qualified deterministic result root.",
    ),
    cache_dir: Path = typer.Option(
        Path("evaluation/speaker-pairs/cache"),
        help="Ignored exact-span and embedding cache.",
    ),
    preflight_path: Path = typer.Option(
        Path("evaluation/speaker-pairs/reports/bakeoff-preflight.json"),
        help="Persisted preflight and execution plan.",
    ),
    report_path: Path = typer.Option(
        Path("evaluation/speaker-pairs/reports/bakeoff-latest.json"),
        help="Threshold-free model comparison report.",
    ),
    preflight_only: bool = typer.Option(
        False,
        "--preflight-only",
        help="Validate and persist the plan without running acoustic models.",
    ),
    evaluation_scope: str = typer.Option(
        "development",
        "--evaluation-scope",
        help=(
            "Fixture partition to execute: development, validation, held_out, or all. "
            "Development also includes legacy unassigned fixtures."
        ),
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    repository_root = Path.cwd().resolve()
    fixture_root = fixture_dir.expanduser().resolve()
    manifest = manifest_path.expanduser().resolve()
    results_destination = result_root.expanduser().resolve()
    try:
        fixture_paths = sorted(fixture_root.glob("*.json"))
        if not fixture_paths:
            raise ValueError(f"no reviewed pair fixtures found in {fixture_root}")
        all_fixtures = _load_json_artifacts(fixture_paths)
        fixtures = _select_bakeoff_fixtures(all_fixtures, evaluation_scope)
        models = load_bakeoff_manifest(manifest)
        preflight = build_bakeoff_preflight(
            fixtures,
            models,
            repository_root=repository_root,
            result_root=results_destination,
        )
        preflight["fixture_scope"] = {
            "requested": evaluation_scope,
            "selected_fixture_count": len(fixtures),
            "corpus_fixture_count": len(all_fixtures),
            "legacy_unassigned_included": evaluation_scope == "development",
        }
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise typer.BadParameter(str(error)) from error

    preflight_destination = preflight_path.expanduser().resolve()
    preflight_destination.parent.mkdir(parents=True, exist_ok=True)
    preflight_destination.write_text(
        json.dumps(preflight, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    console.print(
        f"Preflight: fixtures={len(fixtures)}/{len(all_fixtures)} "
        f"scope={evaluation_scope} models={len(models)} "
        f"jobs={len(preflight['plan']['jobs'])}; "
        f"report={preflight_destination}"
    )
    if not preflight["execution_allowed"]:
        raise typer.BadParameter(
            "bake-off preflight blocked execution: "
            + ", ".join(preflight["blocking_reasons"])
        )
    if preflight_only:
        console.print("Preflight passed; acoustic execution was not requested.")
        return

    paths = build_paths(base_dir)
    if not paths.database.exists():
        raise typer.BadParameter(f"Application database does not exist: {paths.database}")
    database = Database(paths.database, readonly=True)
    backends: dict[str, SherpaOnnxEmbeddingBackend] = {}
    try:
        for model in models:
            _validate_bakeoff_preprocessing(model, fixtures)
            model_file = Path(model.model_path)
            if not model_file.is_absolute():
                model_file = repository_root / model_file
            backend = SherpaOnnxEmbeddingBackend(
                model_file,
                expected_sha256=model.model_sha256,
            )
            _validate_bakeoff_backend(model, backend)
            backends[model.stable_key] = backend
    except (OSError, RuntimeError, ValueError) as error:
        raise typer.BadParameter(f"bake-off backend preflight failed: {error}") from error

    span_cache = AudioSpanCache(cache_dir.expanduser().resolve())
    embedding_cache = EmbeddingCache(cache_dir.expanduser().resolve())

    def analyze_fixture(
        fixture: dict[str, object],
        model: BakeoffModel,
    ) -> dict[str, object]:
        observations = [
            database.get_speaker_observation_by_fingerprint(
                str(fixture["observations"][side]["input_fingerprint"])
            )
            for side in ("a", "b")
        ]
        audio_paths = [
            (
                resolve_normalized_audio_path(database, observation.video_id)
                if observation is not None
                else None
            )
            for observation in observations
        ]
        span_specs = [
            [
                SpanSpec(
                    float(span["start_seconds"]),
                    float(span["end_seconds"]),
                )
                for span in fixture["observations"][side]["reviewed_spans"]
            ]
            for side in ("a", "b")
        ]
        result = analyze_observation_pair(
            observation_a=observations[0],
            observation_b=observations[1],
            audio_path_a=audio_paths[0],
            audio_path_b=audio_paths[1],
            span_cache=span_cache,
            embedding_cache=embedding_cache,
            backend=backends[model.stable_key],
            policy=None,
            span_specs_a=span_specs[0],
            span_specs_b=span_specs[1],
        )
        # Even a technical failure must remain tied to the exact intended
        # reviewed evidence so it is reported as analysis_failed, not missing.
        result.setdefault(
            "observations",
            {
                side: fixture["observations"][side]["input_fingerprint"]
                for side in ("a", "b")
            },
        )
        result.setdefault(
            "spans",
            {
                side: list(fixture["observations"][side]["reviewed_spans"])
                for side in ("a", "b")
            },
        )
        return result

    def show_progress(index: int, total: int, model_key: str, pair_id: str) -> None:
        console.print(f"[{index}/{total}] {model_key}: {pair_id}")

    try:
        execution = execute_bakeoff_plan(
            fixtures,
            models,
            plan=preflight["plan"],
            analyze_fixture=analyze_fixture,
            progress=show_progress,
        )
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        raise typer.BadParameter(str(error)) from error
    destination = report_path.expanduser().resolve()
    execution["report"]["fixture_scope"] = preflight["fixture_scope"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(execution["report"], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    console.print(
        f"Bake-off complete: new={execution['jobs_completed']} "
        f"replayed={execution['jobs_replayed']}; report={destination}"
    )


@identity_app.command(
    "evaluate-speaker-policy-candidate",
    help="Replay a non-approved policy on development bake-off metrics only.",
)
def evaluate_speaker_policy_candidate(
    policy_path: Path = typer.Option(
        Path(
            "evaluation/speaker-pairs/policies/"
            "campplus-development-candidate-v1.json"
        ),
        help="Development-derived experimental policy candidate.",
    ),
    fixture_dir: Path = typer.Option(
        Path("evaluation/speaker-pairs/fixtures"),
        help="Approved exact-span speaker-pair fixtures.",
    ),
    manifest_path: Path = typer.Option(
        Path("evaluation/speaker-pairs/bakeoff-models.json"),
        help="Experimental candidate model manifest.",
    ),
    result_root: Path = typer.Option(
        Path("evaluation/speaker-pairs/runs/by-model"),
        help="Existing model-fingerprint-qualified bake-off results.",
    ),
    report_path: Path = typer.Option(
        Path(
            "evaluation/speaker-pairs/reports/"
            "campplus-development-candidate-v1.json"
        ),
        help="Development-only experimental policy report.",
    ),
) -> None:
    try:
        fixture_paths = sorted(fixture_dir.expanduser().resolve().glob("*.json"))
        all_fixtures = _load_json_artifacts(fixture_paths)
        fixtures = _select_bakeoff_fixtures(all_fixtures, "development")
        models = load_bakeoff_manifest(manifest_path.expanduser().resolve())
        candidate, model = load_experimental_policy_candidate(
            policy_path.expanduser().resolve(),
            fixtures=fixtures,
            models=models,
        )
        results = load_namespaced_bakeoff_results(
            result_root.expanduser().resolve(),
            model,
            pair_ids=[str(fixture["pair_id"]) for fixture in fixtures],
        )
        report = evaluate_experimental_policy_candidate(
            fixtures,
            results,
            candidate,
            model,
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise typer.BadParameter(str(error)) from error
    destination = report_path.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    counts = report["evaluation"]["counts"]
    console.print(
        f"Development replay: true_same={counts['true_same']} "
        f"true_different={counts['true_different']} "
        f"false_same={counts['false_same']} "
        f"false_different={counts['false_different']} "
        f"abstained={counts['insufficient_evidence']} "
        f"failed={counts['analysis_failed']}; report={destination}"
    )
    console.print("Policy remains experimental, non-gating, and unapproved.")


def _select_bakeoff_fixtures(
    fixtures: Sequence[dict[str, object]],
    evaluation_scope: str,
) -> list[dict[str, object]]:
    allowed = {"development", "validation", "held_out", "all"}
    if evaluation_scope not in allowed:
        raise ValueError(
            "evaluation scope must be one of: development, validation, held_out, all"
        )
    if evaluation_scope == "all":
        selected = list(fixtures)
    elif evaluation_scope == "development":
        selected = [
            fixture
            for fixture in fixtures
            if fixture.get("evaluation_partition") in {None, "development"}
        ]
    else:
        selected = [
            fixture
            for fixture in fixtures
            if fixture.get("evaluation_partition") == evaluation_scope
        ]
    if not selected:
        raise ValueError(f"no fixtures are assigned to evaluation scope {evaluation_scope}")
    return selected


def _validate_bakeoff_backend(
    model: BakeoffModel,
    backend: SherpaOnnxEmbeddingBackend,
) -> None:
    if (
        backend.spec.backend != model.backend
        or backend.spec.model_name != model.model_name
        or backend.spec.model_sha256 != model.model_sha256
        or backend.spec.runtime_version != model.runtime_version
    ):
        raise ValueError(
            f"{model.stable_key} backend does not match its manifest execution"
        )


def _validate_bakeoff_preprocessing(
    model: BakeoffModel,
    fixtures: Sequence[dict[str, object]],
) -> None:
    supported = {
        "sample_rate_hz": 16_000,
        "channels": 1,
        "sample_format": "pcm_s16le",
        "span_extractor_version": "speaker_span_v1",
    }
    for key, expected in supported.items():
        if model.preprocessing.get(key) != expected:
            raise ValueError(
                f"{model.stable_key} uses unsupported {key}: "
                f"{model.preprocessing.get(key)!r}"
            )
    duration = model.preprocessing.get("span_duration_seconds")
    if not isinstance(duration, (int, float)) or duration <= 0:
        raise ValueError(f"{model.stable_key} requires a positive span duration")
    for fixture in fixtures:
        for side in ("a", "b"):
            for span in fixture["observations"][side]["reviewed_spans"]:
                actual = float(span["end_seconds"]) - float(span["start_seconds"])
                if abs(actual - float(duration)) > 0.001:
                    raise ValueError(
                        f"{fixture['pair_id']} reviewed span duration does not match "
                        f"{model.stable_key} preprocessing"
                    )


@identity_app.command(
    "validate-pair-fixtures",
    help="Validate explicitly reviewed same/different-speaker evaluation fixtures.",
)
def validate_pair_fixtures(
    fixture_dir: Path = typer.Argument(Path("evaluation/speaker-pairs/fixtures")),
) -> None:
    root = fixture_dir.expanduser().resolve()
    paths = sorted(root.glob("*.json"))
    if not paths:
        raise typer.BadParameter(f"No speaker-pair fixtures found in {root}")
    pair_ids: set[str] = set()
    revocations = load_review_revocations(root.parent)
    validated_count = 0
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if pair_artifact_is_revoked(payload, revocations):
                continue
            validate_reviewed_pair_fixture(payload)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise typer.BadParameter(f"{path}: {error}") from error
        pair_id = str(payload.get("pair_id", ""))
        if not pair_id or pair_id in pair_ids:
            raise typer.BadParameter(f"{path}: pair_id must be present and unique")
        pair_ids.add(pair_id)
        validated_count += 1
    console.print(f"Validated {validated_count} active reviewed speaker-pair fixture(s).")


@identity_app.command(
    "audit-speaker-review-selection",
    help="Verify automatic review drafts used the exact observations selected.",
)
def audit_speaker_review_selection(
    evaluation_root: Path = typer.Option(
        Path("evaluation/speaker-pairs"),
        help="Speaker-pair drafts and review events root.",
    ),
) -> None:
    try:
        audit = audit_review_selection_artifacts(evaluation_root)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise typer.BadParameter(str(error)) from error
    console.print(
        "Speaker review selection audit: "
        f"drafts={audit.draft_count} automatic={audit.automatic_count} "
        f"reviewed={audit.reviewed_count} exact={audit.exact_verified_count} "
        f"legacy_checked={audit.legacy_checked_count} "
        f"unverifiable={audit.unverifiable_count} "
        f"mismatches={len(audit.issues)}"
    )
    for issue in audit.issues:
        console.print(
            f"Mismatch {issue.pair_id}: reason={issue.reason_code} "
            f"reviewed={issue.reviewed} draft={issue.draft_path}"
        )
    console.print("Audit is read-only; no review evidence was changed.")


@identity_app.command(
    "evaluate-pair-results",
    help="Measure pairwise errors and abstention against exact reviewed audio spans.",
)
def evaluate_pair_results(
    fixture_dir: Path = typer.Option(Path("evaluation/speaker-pairs/fixtures")),
    result_dir: Path = typer.Option(Path("evaluation/speaker-pairs/runs")),
    output_path: Path = typer.Option(Path("evaluation/speaker-pairs/reports/latest.json")),
) -> None:
    try:
        fixture_paths = sorted(fixture_dir.expanduser().resolve().glob("*.json"))
        result_paths = sorted(result_dir.expanduser().resolve().glob("*.json"))
        fixtures = _load_json_artifacts(fixture_paths)
        results = [json.loads(path.read_text(encoding="utf-8")) for path in result_paths]
        if not fixtures:
            raise ValueError("no reviewed pair fixtures found")
        report = evaluate_reviewed_pair_results(fixtures, results)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise typer.BadParameter(str(error)) from error
    destination = output_path.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    counts = report["counts"]
    console.print(
        f"false_same={counts['false_same']} false_different={counts['false_different']} "
        f"abstained={counts['insufficient_evidence']} failed={counts['analysis_failed']}"
    )
    console.print(f"promotion_ready={report['gates']['promotion_ready']}; report={destination}")


def _prompt_review_choice(prompt: str, choices: dict[str, object]) -> object:
    choice_text = "/".join(choices)
    while True:
        value = typer.prompt(f"{prompt} [{choice_text}]").strip().lower()
        if value in choices:
            return choices[value]
        console.print(f"Choose one of: {', '.join(choices)}")


def _normalize_review_terminal_input() -> None:
    """Restore Enter-to-newline translation before interactive review prompts."""
    try:
        import termios
    except ImportError:
        return

    try:
        stdin_fd = sys.stdin.fileno()
        if not os.isatty(stdin_fd):
            return
        attributes = termios.tcgetattr(stdin_fd)
        input_flags = attributes[0]
        normalized_flags = (input_flags | termios.ICRNL) & ~(
            termios.IGNCR | termios.INLCR
        )
        if normalized_flags == input_flags:
            return
        attributes[0] = normalized_flags
        termios.tcsetattr(stdin_fd, termios.TCSANOW, attributes)
    except (OSError, ValueError, termios.error):
        # Non-POSIX, detached, and test streams need no terminal repair.
        return


@identity_app.command(
    "audit-speaker-negative-windows",
    help="Read-only audit of exact observations reviewed as multiple-speaker or invalid audio.",
)
def audit_speaker_negative_windows_command(
    evaluation_root: Path = typer.Option(
        Path("evaluation/speaker-pairs"), help="Speaker-pair artifact root."
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Print the complete machine-readable audit."
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    paths = build_paths(base_dir)
    if not paths.database.exists():
        raise typer.BadParameter(f"Application database does not exist: {paths.database}")
    database = Database(paths.database, readonly=True)
    try:
        audit = audit_speaker_negative_windows(
            database, evaluation_root.expanduser().resolve()
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise typer.BadParameter(str(error)) from error
    if json_output:
        console.print_json(json.dumps(audit.to_dict(), sort_keys=True))
        return
    table = Table(title="Speaker-negative sermon windows")
    table.add_column("Video")
    table.add_column("Qualification")
    table.add_column("Reviewed window")
    table.add_column("Current window")
    table.add_column("State")
    table.add_column("Signals")
    for record in audit.records:
        table.add_row(
            record.youtube_video_id,
            ",".join(record.qualifications),
            _format_window(record.reviewed_start_seconds, record.reviewed_end_seconds),
            _format_optional_window(record.current_start_seconds, record.current_end_seconds),
            (
                "apply"
                if "approved_fixture_pending_apply" in record.reason_codes
                else "review"
                if record.actionable
                else "stale"
                if "stale_observation" in record.reason_codes
                else "resolved"
            ),
            ",".join(
                reason
                for reason in record.reason_codes
                if reason not in record.qualifications
            ) or "negative_qualification",
        )
    console.print(table)
    payload = audit.to_dict()["counts"]
    assert isinstance(payload, dict)
    console.print(
        "Speaker-negative window audit: "
        f"observations={payload['negative_observations']} "
        f"actionable={payload['actionable']} stale={payload['stale']} "
        f"broad_actionable={payload['broad_actionable']}."
    )


@identity_app.command(
    "review-next-speaker-negative-window",
    help="Review the next current sermon window implicated by a negative speaker qualification.",
)
def review_next_speaker_negative_window(
    reviewer: str | None = typer.Option(
        None, help="Human reviewer name or stable reviewer identifier."
    ),
    evaluation_root: Path = typer.Option(
        Path("evaluation/speaker-pairs"), help="Speaker-pair artifact root."
    ),
    ground_truth_root: Path = typer.Option(
        Path("evaluation"), help="Root containing sermon drafts/ and fixtures/."
    ),
    open_video: bool = typer.Option(
        True, "--open-video/--no-open-video", help="Open the selected YouTube window."
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    paths = build_paths(base_dir)
    if not paths.database.exists():
        raise typer.BadParameter(f"Application database does not exist: {paths.database}")
    database = Database(paths.database, readonly=True)
    try:
        audit = audit_speaker_negative_windows(
            database, evaluation_root.expanduser().resolve()
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise typer.BadParameter(str(error)) from error
    if not audit.actionable:
        console.print("No current speaker-negative sermon windows require review.")
        return
    record = audit.actionable[0]
    console.print(
        f"Selected {record.youtube_video_id}: "
        f"window={_format_window(record.reviewed_start_seconds, record.reviewed_end_seconds)}; "
        f"qualification={','.join(record.qualifications)}; "
        f"signals={','.join(record.reason_codes)}."
    )
    fixture_dir = ground_truth_root.expanduser().resolve() / "fixtures"
    fixture_path = fixture_dir / f"{record.youtube_video_id}.json"
    if not _fixture_supplies_continuous_sermon_window(fixture_path):
        manifest = {
            "selection_origin": "speaker_negative_window_audit",
            "observation_fingerprint": record.observation_fingerprint,
            "qualifications": list(record.qualifications),
            "reason_codes": list(record.reason_codes),
            "reviewed_window": {
                "start_seconds": record.reviewed_start_seconds,
                "end_seconds": record.reviewed_end_seconds,
            },
        }
        review_ground_truth(
            youtube_video_id=record.youtube_video_id,
            reviewer=reviewer,
            evaluation_dir=ground_truth_root,
            open_video=open_video,
            base_dir=base_dir,
            selection_manifest_json=json.dumps(manifest, sort_keys=True),
        )
    if _fixture_supplies_continuous_sermon_window(fixture_path):
        console.print(
            "Apply the approved correction:\n"
            f"pte apply-fixture-correction {record.youtube_video_id} "
            f"--fixture-dir {shlex.quote(str(fixture_dir))} "
            f"--base-dir {shlex.quote(str(paths.root))}"
        )
    elif fixture_path.exists():
        console.print(
            "The approved fixture is not one continuous sermon window; "
            "automatic correction is intentionally unavailable."
        )


def _fixture_supplies_continuous_sermon_window(path: Path) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    return (
        isinstance(payload, dict)
        and payload.get("expected_outcome") == "sermon"
        and isinstance(payload.get("expected_spans"), list)
        and len(payload["expected_spans"]) == 1
        and payload.get("allowed_interruptions") == []
    )


def _format_window(start: float, end: float) -> str:
    return f"{format_timestamp(start)}–{format_timestamp(end)} ({(end - start) / 60.0:.1f}m)"


def _format_optional_window(start: float | None, end: float | None) -> str:
    if start is None or end is None or end <= start:
        return "unavailable"
    return _format_window(start, end)


@identity_app.command(
    "review-observation",
    help="Present one observation's clips with exact YouTube URLs and timestamps.",
)
def review_observation(
    youtube_video_id: str | None = typer.Option(
        None, "--youtube-video-id", help="Review one YouTube video observation."
    ),
    observation_fingerprint: str | None = typer.Option(
        None,
        "--observation-fingerprint",
        help="Review one exact immutable observation instead of selecting the latest.",
    ),
    all_affected: bool = typer.Option(
        False,
        "--all-affected",
        help="Prepare packets for the exact observations invalidated by provenance repair.",
    ),
    evaluation_root: Path = typer.Option(
        Path("evaluation/speaker-pairs"), help="Review packet root."
    ),
    cache_dir: Path = typer.Option(
        Path("evaluation/speaker-pairs/cache"), help="Provenance-bound clip cache."
    ),
    open_packet: bool = typer.Option(
        True, "--open-packet/--no-open-packet", help="Open each local HTML packet."
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    selection_count = sum(
        (youtube_video_id is not None, observation_fingerprint is not None, all_affected)
    )
    if selection_count != 1:
        raise typer.BadParameter(
            "Pass exactly one of --youtube-video-id, --observation-fingerprint, "
            "or --all-affected."
        )
    paths = build_paths(base_dir)
    if not paths.database.exists():
        raise typer.BadParameter(f"Application database does not exist: {paths.database}")
    database = Database(paths.database, readonly=True)
    if observation_fingerprint is not None:
        observation = database.get_speaker_observation_by_fingerprint(
            observation_fingerprint
        )
        if observation is None:
            raise typer.BadParameter(
                f"Unknown observation fingerprint: {observation_fingerprint}"
            )
        video = database.get_video_by_id(observation.video_id)
        if video is None:
            raise typer.BadParameter(
                f"Observation video is unavailable: {observation_fingerprint}"
            )
        review_inputs = [(video, observation)]
    elif youtube_video_id is not None:
        video = database.get_video_by_youtube_id(youtube_video_id)
        if video is None:
            raise typer.BadParameter(f"Unknown YouTube video ID: {youtube_video_id}")
        observation = database.get_latest_speaker_observation_for_video(video.id)
        review_inputs = [(video, observation)]
    else:
        revocations = load_review_revocations(
            evaluation_root.expanduser().resolve()
        )
        observations = [
            database.get_speaker_observation_by_fingerprint(fingerprint)
            for fingerprint in sorted(
                revocations.affected_observation_fingerprints
            )
        ]
        review_inputs = [
            (video, observation)
            for observation in observations
            if observation is not None
            and (video := database.get_video_by_id(observation.video_id))
            is not None
        ]
    if not review_inputs:
        console.print("No provenance-invalidated observations require review.")
        return
    span_cache = AudioSpanCache(cache_dir.expanduser().resolve())
    for video, observation in review_inputs:
        try:
            artifact = get_verified_normalized_media_artifact(database, video.id)
        except ArchivedMediaUnavailableError as error:
            retry = (
                "pte identity review-observation "
                f"--youtube-video-id {video.youtube_video_id} "
                f"--base-dir {shlex.quote(str(paths.root))}"
            )
            if all_affected:
                console.print(
                    f"{video.youtube_video_id}: deferred "
                    f"(archived_media_unavailable); retry: {retry}"
                )
                continue
            raise typer.BadParameter(f"{error}. Retry: {retry}") from error
        if observation is None or artifact is None:
            console.print(
                f"{video.youtube_video_id}: skipped (observation or verified audio unavailable)"
            )
            continue
        try:
            packet = create_observation_review_packet(
                observation=observation,
                youtube_video_id=video.youtube_video_id,
                audio_path=Path(artifact.artifact_path),
                span_cache=span_cache,
                evaluation_root=evaluation_root.expanduser().resolve(),
            )
            write_canonical_clip_preparation_manifest(
                paths,
                artifact,
                observation,
                clip_paths=tuple(
                    Path(item["wav_path"]) for item in packet.payload["clips"]
                ),
            )
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
            raise typer.BadParameter(
                f"{video.youtube_video_id}: {error}"
            ) from error
        console.print(
            f"{video.youtube_video_id}: window "
            f"{observation.start_seconds:.3f}-{observation.end_seconds:.3f}s; "
            f"video=https://www.youtube.com/watch?v={video.youtube_video_id}; "
            f"packet={packet.packet_path}"
        )
        if open_packet:
            webbrowser.open(packet.packet_path.resolve().as_uri())


@identity_app.command(
    "review-speaker-pair",
    help="Prepare and adjudicate an exact-span speaker-pair review.",
)
def review_speaker_pair(
    video_a: str = typer.Argument(..., help="First candidate YouTube video ID."),
    video_b: str = typer.Argument(..., help="Second candidate YouTube video ID."),
    reviewer: str | None = typer.Option(None, help="Stable human reviewer identifier."),
    evaluation_root: Path = typer.Option(
        Path("evaluation/speaker-pairs"), help="Speaker-pair drafts, reviews, and fixtures root."
    ),
    cache_dir: Path = typer.Option(
        Path("evaluation/speaker-pairs/cache"), help="Ignored exact-span audio cache."
    ),
    open_packet: bool = typer.Option(
        True, "--open-packet/--no-open-packet", help="Open the local HTML review packet."
    ),
    prepare_only: bool = typer.Option(
        False, "--prepare-only", help="Create the packet without prompting for adjudication."
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
    selection_manifest_json: str | None = typer.Option(None, hidden=True),
    observation_fingerprint_a: str | None = typer.Option(None, hidden=True),
    observation_fingerprint_b: str | None = typer.Option(None, hidden=True),
) -> None:
    paths = build_paths(base_dir)
    if not paths.database.exists():
        raise typer.BadParameter(f"Application database does not exist: {paths.database}")
    database = Database(paths.database, readonly=True)
    videos = [database.get_video_by_youtube_id(value) for value in (video_a, video_b)]
    missing = [value for value, video in zip((video_a, video_b), videos) if video is None]
    if missing:
        raise typer.BadParameter(f"Unknown YouTube video ID(s): {', '.join(missing)}")
    requested_fingerprints = (
        observation_fingerprint_a,
        observation_fingerprint_b,
    )
    if any(requested_fingerprints) and not all(requested_fingerprints):
        raise typer.BadParameter(
            "automatic review requires both selected observation fingerprints"
        )
    observations = (
        [
            database.get_speaker_observation_by_fingerprint(fingerprint)
            for fingerprint in requested_fingerprints
        ]
        if all(requested_fingerprints)
        else [
            database.get_latest_speaker_observation_for_video(video.id)
            for video in videos
        ]
    )
    if observations[0] is None or observations[1] is None:
        raise typer.BadParameter("Both videos require immutable speaker observations")
    if all(requested_fingerprints) and any(
        observation.video_id != video.id
        for observation, video in zip(observations, videos)
    ):
        raise typer.BadParameter(
            "selected observation fingerprint does not belong to its video"
        )
    verification_cache = MediaVerificationCache(cache_dir.expanduser().resolve())
    audio_paths = [
        resolve_normalized_audio_path(
            database,
            video.id,
            verification_cache=verification_cache,
        )
        for video in videos
    ]
    if any(path is None for path in audio_paths):
        raise typer.BadParameter("Both observations require local audio")
    try:
        selection_manifest = (
            json.loads(selection_manifest_json) if selection_manifest_json is not None else None
        )
        if selection_manifest is not None and not isinstance(selection_manifest, dict):
            raise ValueError("selection manifest must be a JSON object")
        if all(requested_fingerprints):
            selected = (
                selection_manifest.get("selected_observation_fingerprints")
                if selection_manifest is not None
                else None
            )
            if selected != {
                "a": observation_fingerprint_a,
                "b": observation_fingerprint_b,
            }:
                raise ValueError(
                    "selection manifest does not match selected observations"
                )
        draft = create_review_draft(
            observation_a=observations[0],
            observation_b=observations[1],
            video_id_a=video_a,
            video_id_b=video_b,
            audio_path_a=audio_paths[0],
            audio_path_b=audio_paths[1],
            span_cache=AudioSpanCache(cache_dir.expanduser().resolve()),
            evaluation_root=evaluation_root.expanduser().resolve(),
            selection_manifest=selection_manifest,
        )
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        raise typer.BadParameter(str(error)) from error
    evidence_mode = ReviewEvidenceMode(
        draft.payload.get(
            "review_evidence_mode",
            ReviewEvidenceMode.AUDIO_ONLY,
        )
    )
    console.print(
        f"Prepared {evidence_mode.value} packet: {draft.packet_path}"
    )
    if open_packet:
        webbrowser.open(draft.packet_path.resolve().as_uri())
    if prepare_only:
        console.print("Draft preserved; rerun without --prepare-only to adjudicate it.")
        return

    _normalize_review_terminal_input()

    qualification_choices = {
        "single": ObservationQualification.QUALIFIED_SINGLE_SPEAKER,
        "multiple": ObservationQualification.MULTIPLE_SPEAKERS,
        "invalid": ObservationQualification.INVALID_AUDIO,
        "cannot": ObservationQualification.CANNOT_DETERMINE,
    }
    console.print(
        "Observation classifications:\n"
        "  single   every clip contains one consistent principal speaker\n"
        "  multiple clips contain different principal speakers\n"
        "  invalid  audio is unusable or lacks reviewable speech\n"
        "  cannot   insufficient confidence to classify"
    )
    qualification_a = _prompt_review_choice(
        "Classify Observation A",
        qualification_choices,
    )
    qualification_b = _prompt_review_choice(
        "Classify Observation B",
        qualification_choices,
    )
    both_qualified = (
        qualification_a == ObservationQualification.QUALIFIED_SINGLE_SPEAKER
        and qualification_b == ObservationQualification.QUALIFIED_SINGLE_SPEAKER
    )
    if both_qualified:
        pair_judgment = _prompt_review_choice(
            "Pair judgment",
            {
                "same": PairJudgment.SAME_SPEAKER,
                "different": PairJudgment.DIFFERENT_SPEAKER,
                "cannot": PairJudgment.CANNOT_DETERMINE,
            },
        )
    else:
        pair_judgment = PairJudgment.CANNOT_DETERMINE
        console.print("At least one observation is unqualified; pair judgment is cannot_determine.")
    reviewer_value = reviewer or typer.prompt("Reviewed by").strip()
    console.print(
        "Standard variation tags (use only when known): "
        + ", ".join(STANDARD_VARIATION_TAGS)
    )
    tags_text = typer.prompt(
        "Variation tags (comma-separated, or blank when unknown)",
        default="",
        show_default=False,
    )
    notes = typer.prompt("Review notes", default="", show_default=False)
    identity_evidence_eligible = both_qualified and pair_judgment in {
        PairJudgment.SAME_SPEAKER,
        PairJudgment.DIFFERENT_SPEAKER,
    }
    approval_confirmed = False
    if identity_evidence_eligible:
        approval_confirmed = typer.confirm(
            (
                "Freeze this exact-span binary judgment as an approved "
                "acoustic fixture?"
                if evidence_mode == ReviewEvidenceMode.AUDIO_ONLY
                else (
                    "Approve this audio-plus-visual judgment as profile "
                    "identity evidence?"
                )
            ),
            default=True,
        )
    try:
        submission = submit_review(
            draft=draft.payload,
            qualification_a=qualification_a,
            qualification_b=qualification_b,
            pair_judgment=pair_judgment,
            reviewer=reviewer_value,
            reviewed_at=None,
            variation_tags=tags_text.split(","),
            notes=notes,
            approval_confirmed=approval_confirmed,
            evaluation_root=evaluation_root.expanduser().resolve(),
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise typer.BadParameter(str(error)) from error
    console.print(f"Wrote append-only review event: {submission.event_path}")
    if submission.fixture_status == "created":
        console.print(f"Created frozen fixture: {submission.fixture_path}")
    elif submission.fixture_status == "existing_consistent":
        console.print("Existing frozen fixture agrees; it was not overwritten.")
    elif submission.fixture_status == "existing_conflict_preserved":
        console.print("Review conflicts with the frozen fixture; both were preserved for adjudication.")
    elif submission.fixture_status == "identity_only":
        console.print(
            "Approved identity evidence; no acoustic fixture was created."
        )
    else:
        console.print("Review was preserved but did not create a fixture.")


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
    "sync-reviewed-speaker-evidence",
    help="Replay confirmed pair reviews into curated anonymous registry state.",
)
def sync_reviewed_speaker_evidence_command(
    evaluation_root: Path = typer.Option(
        Path("evaluation/speaker-pairs"),
        help="Speaker-pair drafts, reviews, and fixtures root.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Derive and report reviewed evidence without registry mutations.",
    ),
    base_dir: Path | None = typer.Option(
        None, help="Override app data directory."
    ),
) -> None:
    try:
        evidence = load_reviewed_speaker_evidence(
            evaluation_root.expanduser().resolve()
        )
        result = None
        if not dry_run:
            database = get_database(base_dir)
            result = sync_reviewed_speaker_evidence(database, evidence)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise typer.BadParameter(str(error)) from error
    _print_reviewed_evidence_summary(evidence, result)
    if dry_run:
        console.print("Dry run complete; no reviewed evidence was synchronized.")


@identity_app.command(
    "profile-status",
    help="Report the reviewed identity pipeline and what each profile needs next.",
)
def profile_status_command(
    evaluation_root: Path = typer.Option(
        Path("evaluation/speaker-pairs"),
        help="Speaker-pair drafts, reviews, and fixtures root.",
    ),
    discovery_root: Path = typer.Option(
        Path("evaluation/speaker-profile-discovery/shadow-runs"),
        help="Shadow profile-discovery reports to include in status.",
    ),
    base_dir: Path | None = typer.Option(
        None, help="Override app data directory."
    ),
) -> None:
    paths = build_paths(base_dir)
    if not paths.database.exists():
        raise typer.BadParameter(
            f"Application database does not exist: {paths.database}"
        )
    try:
        evidence = load_reviewed_speaker_evidence(
            evaluation_root.expanduser().resolve()
        )
        discovery_report = None
        discovery_report_path = None
        invalid_discovery_artifacts = 0
        discovery_paths = sorted(
            discovery_root.expanduser().resolve().glob("*/*.json"),
            key=lambda path: (path.stat().st_mtime_ns, str(path)),
            reverse=True,
        )
        for candidate_path in discovery_paths:
            try:
                discovery_report = load_verified_shadow_profile_discovery(
                    candidate_path
                )
            except (OSError, ValueError, json.JSONDecodeError):
                invalid_discovery_artifacts += 1
                continue
            discovery_report_path = candidate_path
            break
        database = Database(paths.database, readonly=True)
        eligible_automatic_observation_ids = frozenset(
            eligibility.observation.id
            for video in database.list_videos()
            if (
                eligibility := assess_automatic_speaker_observation(
                    database,
                    video.id,
                    verify_media=False,
                )
            ).eligible
            and eligibility.observation is not None
        )
        status = build_profile_pipeline_status(
            database,
            evidence,
            discovery_report=discovery_report,
            discovery_report_path=discovery_report_path,
            eligible_automatic_observation_ids=(
                eligible_automatic_observation_ids
            ),
        )
        negative_window_audit = audit_speaker_negative_windows(
            database, evaluation_root.expanduser().resolve()
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise typer.BadParameter(str(error)) from error

    qualifications = status.qualification_counts
    console.print("[bold]Speaker identity status[/bold]")
    console.print(
        f"Observations: {status.registry_observation_count} | "
        f"single={qualifications.get('qualified_single_speaker', 0)} "
        f"multiple={qualifications.get('multiple_speakers', 0)} "
        f"invalid={qualifications.get('invalid', 0)} "
        f"unresolved={qualifications.get('unresolved', 0)} "
        f"unreviewed={qualifications.get('unreviewed', 0)}"
    )
    console.print(
        f"Evidence: reviews={status.review_event_count} "
        f"relations={status.pair_relation_count} "
        f"conflicts={status.evidence_conflict_count} | pending_sync="
        f"{status.pending_qualification_count + status.pending_same_component_count + status.pending_difference_count} "
        f"(qualifications={status.pending_qualification_count} "
        f"same_components={status.pending_same_component_count} "
        f"different_relations={status.pending_difference_count} "
        f"missing={status.missing_reviewed_observation_count})"
    )
    console.print(
        f"Profiles: canonical={status.canonical_profile_count} "
        f"shadow_ready={status.shadow_ready_profile_count} "
        f"human_on_loop={status.automatic_profile_ready_count} "
        f"linked={status.configured_identity_count}"
    )
    console.print(
        f"Backlog: "
        f"ungrouped={status.ungrouped_single_count} "
        f"unmatched_named={status.unmatched_named_ungrouped_single_count} "
        f"unnamed={status.unnamed_ungrouped_single_count} "
        f"stale_or_ineligible={status.stale_or_ineligible_ungrouped_single_count} "
        f"window_review={len(negative_window_audit.actionable)}"
    )
    if status.discovery_report_path is not None:
        console.print(
            "Shadow discovery: "
            f"candidates={status.shadow_discovery_candidate_count} "
            f"promoted={status.promoted_discovery_candidate_count} "
            f"stale={status.stale_discovery_candidate_count} "
            f"blocked={status.blocked_discovery_component_count} "
            f"review_frontiers={status.actionable_discovery_frontier_component_count} "
            f"report={status.discovery_result_sha256[:12]}"
        )
    else:
        console.print(
            "Shadow discovery: no valid report found "
            f"(invalid_artifacts_skipped={invalid_discovery_artifacts})"
        )

    table = Table(title="Canonical and promoted profiles")
    table.add_column("Profile", justify="right", no_wrap=True)
    table.add_column("State", no_wrap=True)
    table.add_column("Evidence", no_wrap=True)
    table.add_column("Automation", no_wrap=True)
    table.add_column("Identity evidence")
    blocker_labels = {
        "fewer_than_three_profile_members": "need 3 members",
        "fewer_than_three_distinct_recordings": "need 3 recordings",
        "fewer_than_three_reviewed_members": "need reinforced core",
        "reviewed_same_graph_disconnected": "no reinforced core",
        "reviewed_same_graph_contains_bridge": "no reinforced core",
        "discovery_candidate_unconfirmed": "needs confirmation",
        "discovery_promotion_provenance_missing": "missing promotion evidence",
        "conflicting_explicit_attribution": "conflicting names",
        "conflicting_name_claim_review": "conflicting name review",
        "internal_reviewed_difference": "speaker conflict",
        "attribution_spans_multiple_profiles": "duplicate attributed profile",
        "member_observation_missing": "missing observation",
    }
    for profile in status.profiles:
        identity = ", ".join(
            profile.configured_identities or profile.names
        ) or "unnamed"
        table.add_row(
            str(profile.profile_id),
            profile.state,
            (
                f"{profile.member_count} obs / "
                f"{profile.recording_count} rec / "
                f"{profile.source_count} src"
            ),
            (
                "human-on-loop"
                if profile.automatic_profile_ready
                else "building"
                if profile.shadow_ready
                else "blocked"
            ),
            identity,
        )
    console.print(table)

    blocker_priority = (
        "internal_reviewed_difference",
        "conflicting_explicit_attribution",
        "conflicting_name_claim_review",
        "attribution_spans_multiple_profiles",
        "member_observation_missing",
        "discovery_promotion_provenance_missing",
        "discovery_candidate_unconfirmed",
        "fewer_than_three_distinct_recordings",
        "fewer_than_three_profile_members",
        "fewer_than_three_reviewed_members",
        "reviewed_same_graph_disconnected",
        "reviewed_same_graph_contains_bridge",
    )
    profiles_by_primary_blocker: dict[str, list[int]] = {}
    for profile in status.profiles:
        if profile.automatic_profile_ready or not profile.automatic_blockers:
            continue
        blocker = next(
            (
                candidate
                for candidate in blocker_priority
                if candidate in profile.automatic_blockers
            ),
            profile.automatic_blockers[0],
        )
        label = blocker_labels.get(blocker, blocker)
        profiles_by_primary_blocker.setdefault(label, []).append(
            profile.profile_id
        )
    if profiles_by_primary_blocker:
        console.print("[bold]Why profiles are not human-on-loop[/bold]")
        for label, profile_ids in sorted(profiles_by_primary_blocker.items()):
            console.print(
                f"  {label}: "
                + ", ".join(str(profile_id) for profile_id in profile_ids)
            )

    partial_cores = [
        profile
        for profile in status.profiles
        if (
            profile.automatic_profile_ready
            and profile.certified_exemplar_count < profile.member_count
        )
    ]
    if partial_cores:
        console.print(
            "[bold]Ready profiles with peripheral members excluded from "
            "automatic exemplars[/bold]"
        )
        console.print(
            "  "
            + ", ".join(
                f"{profile.profile_id} "
                f"({profile.certified_exemplar_count}/{profile.member_count})"
                for profile in partial_cores
            )
        )

    if status.discovered_profiles:
        discovery_table = Table(title="Auto-discovered profile candidates")
        discovery_table.add_column("Component", no_wrap=True)
        discovery_table.add_column("State", no_wrap=True)
        discovery_table.add_column("Evidence", no_wrap=True)
        discovery_table.add_column("Identity evidence")
        discovery_table.add_column("Next need")
        for profile in status.discovered_profiles:
            discovery_table.add_row(
                profile.component_id[:12],
                profile.state,
                (
                    f"{profile.member_count} obs / "
                    f"{profile.recording_count} rec / "
                    f"{profile.source_count} src"
                ),
                ", ".join(profile.names) or "unnamed",
                profile.next_need,
            )
        console.print(discovery_table)

    console.print("[bold]Guidance[/bold]")
    console.print(
        "- Building/blocked profiles: human review supplies identity evidence."
    )
    console.print(
        "- Human-on-loop profiles: the identity run associates eligible sermons; "
        "humans handle exceptions, conflicts, and attribution."
    )
    console.print("[bold]Next actions[/bold]")
    if negative_window_audit.actionable:
        console.print(
            f"- Review {len(negative_window_audit.actionable)} current sermon window(s) "
            "implicated by multiple-speaker or invalid-audio observations."
        )
    for action in status.actions:
        console.print(f"- {action.message}")
    all_needs = (
        *status.actions,
        *(need for profile in status.profiles for need in profile.needs),
    )
    commands = applicable_status_commands(all_needs)
    if commands:
        console.print("[bold]Applicable commands[/bold]")
        for command in commands:
            console.print(f"- {command}")
    if negative_window_audit.actionable:
        if not commands:
            console.print("[bold]Applicable commands[/bold]")
        console.print(
            "- pte identity review-next-speaker-negative-window "
            "--reviewer REVIEWER_ID --base-dir BASE_DIR"
        )
    console.print("Read-only status; use the commands above to make changes.")


@identity_app.command(
    "review-profile-attribution",
    help="Present an unnamed profile's backing videos and record its reviewed name.",
)
def review_profile_attribution_command(
    reviewer: str = typer.Option(..., help="Stable human reviewer identifier."),
    profile_id: int | None = typer.Option(
        None,
        help="Exact canonical profile; default selects the largest unnamed profile.",
    ),
    representative_videos: int = typer.Option(
        6,
        min=1,
        help="Maximum backing videos shown in the review packet.",
    ),
    open_packet: bool = typer.Option(
        True,
        "--open-packet/--no-open-packet",
        help="Open the local HTML packet containing timestamped videos.",
    ),
    cache_dir: Path = typer.Option(
        Path("evaluation/speaker-pairs/cache"),
        help="Persisted identity clip-selection cache used for timestamps.",
    ),
    base_dir: Path | None = typer.Option(
        None,
        help="Override app data directory.",
    ),
) -> None:
    paths = build_paths(base_dir, remember=True)
    database = get_database(base_dir)
    deferral_root = paths.logs / "profile-attribution-reviews" / "deferrals"
    metadata_attributions = load_profile_metadata_attributions(
        paths.logs / "profile-metadata-attribution"
    )
    clip_timestamps = load_profile_attribution_clip_timestamps(cache_dir)
    console.print(
        "Attribution timing: loaded "
        f"{len(clip_timestamps)} persisted identity clip timestamp(s)."
    )
    try:
        if profile_id is None:
            deferred = load_profile_attribution_deferrals(deferral_root)
            candidates = tuple(
                candidate
                for candidate in list_unnamed_profile_attribution_candidates(
                    database,
                    representative_limit=representative_videos,
                    clip_timestamps=clip_timestamps,
                    metadata_attributions=metadata_attributions,
                )
                if candidate.membership_fingerprint not in deferred
            )
            if not candidates:
                console.print(
                    "No non-deferred unnamed profile has reviewable backing "
                    "videos. Pass --profile-id to revisit a deferred profile."
                )
                return
        else:
            candidates = (
                get_profile_attribution_candidate(
                    database,
                    profile_id,
                    representative_limit=representative_videos,
                    clip_timestamps=clip_timestamps,
                    metadata_attributions=metadata_attributions,
                ),
            )
    except (OSError, ValueError) as error:
        raise typer.BadParameter(str(error)) from error

    for queue_index, candidate in enumerate(candidates, start=1):
        console.print(
            f"Selected profile {candidate.profile_id}: "
            f"members={candidate.member_count} "
            f"queue={queue_index}/{len(candidates)}"
        )
        try:
            packet_path = write_profile_attribution_packet(
                candidate,
                paths.logs
                / "profile-attribution-reviews"
                / f"profile-{candidate.profile_id}.html",
            )
        except OSError as error:
            raise typer.BadParameter(str(error)) from error

        table = Table(title=f"Profile {candidate.profile_id} backing videos")
        table.add_column("#", justify="right")
        table.add_column("Title")
        table.add_column("Timestamped video")
        for index, evidence in enumerate(candidate.evidence, start=1):
            table.add_row(
                str(index),
                evidence.title,
                youtube_timestamp_url(
                    evidence.video_url,
                    evidence.timestamp_seconds,
                ),
            )
        console.print(table)
        console.print(f"Prepared profile attribution packet: {packet_path}")
        metadata_attribution = candidate.metadata_attribution
        suggested_name = ""
        if metadata_attribution is not None:
            if (
                metadata_attribution.decision == "propose_name"
                and metadata_attribution.proposed_name
            ):
                suggested_name = metadata_attribution.proposed_name
                console.print(
                    "Metadata attribution: proposed "
                    f"{suggested_name!r} from "
                    f"{metadata_attribution.supporting_recording_count} "
                    "recording(s); human confirmation required."
                )
            else:
                console.print(
                    "Metadata attribution: "
                    f"{metadata_attribution.decision}; routed for human review "
                    f"(reasons={','.join(metadata_attribution.reason_codes)})."
                )
        if open_packet:
            webbrowser.open(packet_path.as_uri())
        name = typer.prompt(
            "Speaker name (blank or 'skip' defers this evidence set)",
            default=suggested_name,
            show_default=bool(suggested_name),
        ).strip()
        if not name or name.casefold() in {"s", "skip", "cannot"}:
            try:
                deferral_path = record_profile_attribution_deferral(
                    candidate,
                    reviewer=reviewer,
                    root=deferral_root,
                )
            except (OSError, ValueError) as error:
                raise typer.BadParameter(str(error)) from error
            console.print(
                "Attribution deferred for this exact profile membership; "
                f"event={deferral_path}"
            )
            if profile_id is not None:
                return
            continue
        evidence_number = typer.prompt(
            "Backing video number",
            default=1,
            type=int,
        )
        if evidence_number < 1 or evidence_number > len(candidate.evidence):
            raise typer.BadParameter("backing video number is outside the packet")
        evidence = candidate.evidence[evidence_number - 1]
        reason = typer.prompt(
            "Evidence/reason",
            default=(
                "Visually identified in backing video "
                f"{evidence.youtube_video_id} at "
                f"{evidence.timestamp_seconds} seconds"
            ),
        ).strip()
        if not typer.confirm(
            f"Attach {name!r} to profile {candidate.profile_id}?",
            default=False,
        ):
            console.print("Attribution cancelled; no registry mutation occurred.")
            return
        try:
            result = apply_reviewed_profile_attribution(
                database,
                profile_id=candidate.profile_id,
                observation_id=evidence.observation_id,
                display_name=name,
                reviewer=reviewer,
                reason=reason,
                packet_path=packet_path,
            )
        except ValueError as error:
            raise typer.BadParameter(str(error)) from error
        console.print(
            f"Attributed profile {candidate.profile_id}: "
            f"name={result.normalized_name} claim={result.claim_id} "
            f"link_status={result.link_status}"
        )
        if result.linked_pastor_slug is not None:
            console.print(
                f"Linked configured pastor: {result.linked_pastor_slug}"
            )
        return

    console.print("All currently reviewable unnamed profiles were deferred.")


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
) -> None:
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
        if database.list_effective_profile_ids_for_observation(observation.id):
            excluded_reasons["already_profiled"] = (
                excluded_reasons.get("already_profiled", 0) + 1
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

    def compare(
        observation_a: SpeakerObservation,
        observation_b: SpeakerObservation,
        audio_path_a: Path,
        audio_path_b: Path,
    ) -> dict[str, object]:
        nonlocal pair_index
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


def _held_out_speaker_fixture_fingerprints(
    fixture_dir: Path,
) -> frozenset[str]:
    fingerprints: set[str] = set()
    for path in sorted(fixture_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        manifest = payload.get("selection_manifest")
        partitions = (
            manifest.get("evaluation_partitions")
            if isinstance(manifest, dict)
            else None
        )
        is_held_out = payload.get("evaluation_partition") == "held_out" or (
            isinstance(partitions, dict)
            and "held_out" in partitions.values()
        )
        observations = payload.get("observations")
        if not is_held_out or not isinstance(observations, dict):
            continue
        for side in ("a", "b"):
            observation = observations.get(side)
            fingerprint = (
                observation.get("input_fingerprint")
                if isinstance(observation, dict)
                else None
            )
            if isinstance(fingerprint, str) and fingerprint:
                fingerprints.add(fingerprint)
    return frozenset(fingerprints)


@dataclass(frozen=True, slots=True)
class ActionableReviewAudioPreparation:
    requested: int
    prepared: int
    already_cached: int
    excluded: int
    failed: int
    ready_fingerprints: tuple[str, ...] = ()


ACTIONABLE_REVIEW_PREWARM_VERSION = "actionable_review_prewarm_v1"


def _actionable_review_prewarm_path(cache_dir: Path) -> Path:
    return (
        cache_dir.expanduser().resolve()
        / "selector-context"
        / "actionable-review-prewarm-v1.json"
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
        for nomination in load_shadow_association_confirmation_pairs(
            association_reports,
            progress_callback=association_progress_callback,
            cache_path=association_cache_path,
        ):
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
    fingerprints = _actionable_review_fingerprints(
        discovery_report=discovery_report,
        association_reports=association_reports,
        automatic_profile_ready_ids=automatic_profile_ready_ids,
        association_progress_callback=association_progress_callback,
        association_cache_path=(
            cache_dir.expanduser().resolve()
            / "selector-context"
            / "association-nominations-v1.json"
        ),
    )[:limit]
    span_cache = AudioSpanCache(cache_dir.expanduser().resolve())
    verification_cache = MediaVerificationCache(
        cache_dir.expanduser().resolve()
    )
    prepared = 0
    already_cached = 0
    excluded = 0
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
        requested=len(fingerprints),
        prepared=prepared,
        already_cached=already_cached,
        excluded=excluded,
        failed=failed,
        ready_fingerprints=tuple(ready_fingerprints),
    )


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
) -> None:
    if (youtube_video_id is None) == (not all_extractions):
        raise ValueError("Pass exactly one YouTube video ID or --all.")
    effective_apply_confirmations = apply_automatic or apply_confirmations
    effective_apply_promotions = apply_automatic or apply_promotions
    effective_apply_machine = apply_automatic or apply_machine_canary
    if plan_only and (
        apply_automatic
        or apply_confirmations
        or apply_promotions
        or apply_machine_canary
    ):
        raise ValueError(
            "--plan-only cannot be combined with registry mutation flags"
        )
    if not all_extractions and effective_apply_promotions:
        raise ValueError("automatic profile promotion requires --all")
    if not all_extractions and apply_machine_canary:
        raise ValueError("machine canary activation requires --all")
    if review_prewarm_limit < 0:
        raise ValueError("review prewarm limit cannot be negative")
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
        f"mode={'plan' if plan_only else 'execute'}"
    )
    try:
        reviewed_evidence = load_reviewed_speaker_evidence(
            Path("evaluation/speaker-pairs").resolve()
        )
        if plan_only:
            sync_result = None
        else:
            writable_database = Database(paths.database)
            writable_database.initialize()
            sync_result = sync_reviewed_speaker_evidence(
                writable_database,
                reviewed_evidence,
            )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise ValueError(f"reviewed-evidence sync failed: {error}") from error
    _print_reviewed_evidence_summary(reviewed_evidence, sync_result)
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
    if plan_only:
        console.print(
            "Machine assignment reconciliation: plan-only; no events were written."
        )
    else:
        reconciliation = reconcile_machine_assignments(
            Database(paths.database),
            verification_cache=machine_cache,
        )
        console.print(
            "Machine assignment reconciliation: "
            f"confirmed={reconciliation.confirmed} "
            f"revoked={reconciliation.revoked} "
            f"circuit_revoked={reconciliation.circuit_breaker_revoked} "
            f"unchanged={reconciliation.unchanged}."
        )

    current_association_reports = shadow_associate_speakers_command(
        youtube_video_id=youtube_video_id,
        all_eligible=all_extractions,
        limit=None,
        plan_only=plan_only,
        minimum_profile_members=3,
        maximum_exemplars=3,
        minimum_same_exemplars=2,
        maximum_global_profiles=3,
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
        output_root=Path("evaluation/speaker-associations/shadow-runs"),
        base_dir=base_dir,
    )

    machine_policy = load_machine_assignment_policy(
        machine_assignment_policy_path
        or Path(
            "evaluation/speaker-associations/policies/"
            "machine-assignment-human-on-loop-v1.json"
        )
    )
    machine_database = Database(paths.database, readonly=True)
    machine_readiness = assess_profile_association_readiness(
        machine_database,
        reviewed_evidence,
    )
    scoped_observation_ids = None
    if database_video_id is not None:
        scoped_observation = (
            machine_database.get_latest_speaker_observation_for_video(
                database_video_id
            )
        )
        scoped_observation_ids = frozenset(
            (scoped_observation.id,)
            if scoped_observation is not None
            else ()
        )
    machine_plan = plan_machine_assignments(
        machine_database,
        current_association_reports,
        readiness=machine_readiness,
        policy=machine_policy,
        verification_cache=machine_cache,
        excluded_observation_fingerprints=(
            _held_out_speaker_fixture_fingerprints(
                Path("evaluation/speaker-pairs/fixtures").resolve()
            )
        ),
        included_observation_ids=scoped_observation_ids,
    )
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
    if plan_only:
        console.print(
            "Machine assignment evidence: plan-only; no ledger rows or "
            "provisional assignments were written."
        )
    else:
        machine_apply = apply_machine_assignment_plan(
            Database(paths.database),
            machine_plan,
            activate_canary=effective_apply_machine,
        )
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
    if all_extractions and not skip_discovery:
        shadow_discover_profiles_command(
            plan_only=plan_only,
            limit=None,
            nearest_neighbors=8,
            maximum_pairs=None,
            closure_candidates_per_same_pair=8,
            source_complete_link_limit=12,
            source_nearest_neighbors=4,
            borderline_deferred_minimum=0.50,
            borderline_deferred_maximum=0.60,
            borderline_deferred_candidates_per_same_pair=4,
            staged_review_candidates_per_component=2,
            staged_review_maximum_same_boundary_distance=0.15,
            minimum_component_members=3,
            consistency_report=None,
            minimum_consistency_score=None,
            consistency_policy=Path(
                "evaluation/speaker-pairs/policies/"
                "observation-consistency-discovery-v1.json"
            ),
            include_deferred=False,
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
            output_root=discovery_root,
            base_dir=base_dir,
        )
    elif all_extractions:
        console.print("Discovery: skipped by --skip-discovery.")
    else:
        console.print("Discovery: deferred to a corpus-wide identity run.")

    discovery_reports = list(discovery_root.resolve().glob("*/*.json"))
    latest_discovery = (
        max(
            discovery_reports,
            key=lambda path: (path.stat().st_mtime_ns, str(path)),
        )
        if discovery_reports
        else None
    )
    if all_extractions and latest_discovery is not None:
        promote_discovered_profiles_command(
            discovery_report=latest_discovery,
            apply=effective_apply_promotions and not plan_only,
            base_dir=base_dir,
        )
    elif all_extractions:
        console.print("Discovery promotion: no completed report available.")

    metadata_attribution_root = paths.logs / "profile-metadata-attribution"
    if plan_only:
        metadata_candidate_count = len(
            profile_metadata_candidate_profile_ids(
                Database(paths.database, readonly=True)
            )
        )
        console.print(
            "Profile metadata attribution: plan-only; "
            f"eligible={metadata_candidate_count}; no Ollama calls or artifacts "
            "were created."
        )
    else:
        metadata_config = build_llm_config()
        if not metadata_config.enabled:
            console.print(
                "Profile metadata attribution: skipped — local LLM is disabled."
            )
        else:
            metadata_database = Database(paths.database, readonly=True)
            scoped_profile_ids = None
            if database_video_id is not None:
                scoped_observation = (
                    metadata_database.get_latest_speaker_observation_for_video(
                        database_video_id
                    )
                )
                scoped_profile_ids = frozenset(
                    metadata_database.resolve_speaker_profile_id(profile_id)
                    for profile_id in (
                        metadata_database.list_effective_profile_ids_for_observation(
                            scoped_observation.id
                        )
                        if scoped_observation is not None
                        else ()
                    )
                )
            candidate_profile_ids = profile_metadata_candidate_profile_ids(
                metadata_database,
                profile_ids=scoped_profile_ids,
            )
            if not candidate_profile_ids:
                console.print(
                    "Profile metadata attribution: eligible=0; no Ollama calls."
                )
            else:
                try:
                    metadata_client = OllamaClient(metadata_config)
                    metadata_run = run_profile_metadata_attribution(
                        metadata_database,
                        metadata_attribution_root,
                        metadata_client,
                        model_digest=metadata_client.model_digest(),
                        profile_ids=frozenset(candidate_profile_ids),
                        progress_callback=(
                            lambda index, total, profile_id, outcome: console.print(
                                "Profile metadata attribution "
                                f"[{index}/{total}] profile={profile_id}: "
                                f"{outcome}"
                            )
                        ),
                    )
                except (LocalLlmError, OSError, ValueError) as error:
                    console.print(
                        "Profile metadata attribution: skipped — "
                        f"{type(error).__name__}: {error}"
                    )
                else:
                    console.print(
                        "Profile metadata attribution: "
                        f"eligible={metadata_run.eligible} "
                        f"proposed={metadata_run.proposed} "
                        f"insufficient_evidence="
                        f"{metadata_run.insufficient_evidence} "
                        f"conflicting_evidence="
                        f"{metadata_run.conflicting_evidence} "
                        f"invalid_metadata={metadata_run.invalid_metadata} "
                        f"cache_hits={metadata_run.cache_hits} "
                        f"model_calls={metadata_run.model_calls} "
                        f"failed={metadata_run.failed}."
                    )

    coordinate_identity_command(
        youtube_video_id=youtube_video_id,
        all_extractions=all_extractions,
        execute_shadow=False,
        discovery_report=latest_discovery,
        discovery_root=discovery_root,
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
        association_root=Path(
            "evaluation/speaker-associations/shadow-runs"
        ),
        output_root=None,
        base_dir=base_dir,
    )
    if plan_only:
        console.print(
            "Review audio prewarm: plan-only; actionable review clips were "
            "not prepared."
        )
    elif all_extractions and review_prewarm_limit:
        try:
            review_preparation = _prepare_actionable_review_audio(
                Database(paths.database, readonly=True),
                paths,
                discovery_report=latest_discovery,
                association_reports=current_association_reports,
                limit=review_prewarm_limit,
                automatic_profile_ready_ids=frozenset(
                    item.profile_id
                    for item in machine_readiness
                    if item.automatic_profile_ready
                ),
            )
        except (OSError, ValueError, json.JSONDecodeError) as error:
            console.print(
                "Review audio prewarm: skipped — "
                f"{type(error).__name__}: {error}"
            )
        else:
            console.print(
                "Review audio prewarm: "
                f"requested={review_preparation.requested} "
                f"prepared={review_preparation.prepared} "
                f"cached={review_preparation.already_cached} "
                f"excluded={review_preparation.excluded} "
                f"failed={review_preparation.failed}."
            )
    elif all_extractions:
        console.print("Review audio prewarm: disabled by limit=0.")
    else:
        console.print(
            "Review audio prewarm: deferred to a corpus-wide identity run."
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
    "run",
    help=(
        "Sync reviewed evidence, then run backfill, shadow association, "
        "discovery, final coordination, and eligible normalized archival."
    ),
)
def identity_run_command(
    youtube_video_id: str | None = typer.Argument(
        None,
        help="One YouTube video ID; omit when using --all.",
    ),
    all_extractions: bool = typer.Option(
        False,
        "--all",
        help="Run across all current extractions and include corpus discovery.",
    ),
    plan_only: bool = typer.Option(
        False,
        "--plan-only",
        help="Show all stages without acoustic execution or registry mutation.",
    ),
    skip_discovery: bool = typer.Option(
        False,
        "--skip-discovery",
        help="Skip corpus profile discovery during an --all run.",
    ),
    apply_automatic: bool = typer.Option(
        False,
        "--apply-automatic",
        help=(
            "Apply validated confirmations, promotions, and policy-gated "
            "human-on-loop provisional assignments. Requires --all."
        ),
    ),
    apply_confirmations: bool = typer.Option(
        False,
        "--apply-confirmations",
        help="Apply validated independent provisional-profile confirmations.",
    ),
    apply_promotions: bool = typer.Option(
        False,
        "--apply-promotions",
        help="Promote verified discovery components into provisional profiles.",
    ),
    apply_machine_canary: bool = typer.Option(
        False,
        "--apply-machine-canary",
        help=(
            "Activate only eligible reversible machine assignments without "
            "also applying profile confirmations or promotions. Requires --all."
        ),
    ),
    machine_assignment_policy: Path | None = typer.Option(
        None,
        "--machine-assignment-policy",
        help=(
            "Use a versioned machine-assignment policy artifact. The default "
            "checked-in policy is shadow-only."
        ),
    ),
    review_prewarm_limit: int = typer.Option(
        24,
        "--review-prewarm-limit",
        min=0,
        help=(
            "Precompute exact clips for this many current actionable review "
            "observations during an --all run; use 0 to disable."
        ),
    ),
    base_dir: Path | None = typer.Option(
        None,
        help="Override app data directory.",
    ),
) -> None:
    try:
        run_identity_workflow_service(
            youtube_video_id=youtube_video_id,
            all_extractions=all_extractions,
            plan_only=plan_only,
            skip_discovery=skip_discovery,
            apply_automatic=apply_automatic,
            apply_confirmations=apply_confirmations,
            apply_promotions=apply_promotions,
            apply_machine_canary=apply_machine_canary,
            machine_assignment_policy_path=machine_assignment_policy,
            review_prewarm_limit=review_prewarm_limit,
            base_dir=base_dir,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error


@identity_app.command(
    "machine-assignment-status",
    help="Report reversible machine evidence and provisional assignment state.",
)
def machine_assignment_status_command(
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
    status = machine_assignment_status(
        Database(paths.database, readonly=True)
    )
    counts = status["counts"]
    console.print(
        "Machine assignments: "
        f"evidence={status['evidence_count']} "
        f"events={status['event_count']} "
        f"evidence_only={counts['evidence_only']} "
        f"active={counts['active']} "
        f"confirmed={counts['confirmed']} "
        f"revoked={counts['revoked']} "
        f"tripped_policies="
        f"{len(status['tripped_policy_fingerprints'])}."
    )
    console.print(
        "Machine assignments remain separate from reviewed profile membership."
    )
    for policy_fingerprint, policy_counts in status["policies"].items():
        console.print(
            f"  policy={policy_fingerprint} "
            f"evidence_only={policy_counts['evidence_only']} "
            f"active={policy_counts['active']} "
            f"confirmed={policy_counts['confirmed']} "
            f"revoked={policy_counts['revoked']}"
        )


@identity_app.command(
    "rollback-machine-assignments",
    help="Plan or append revocations for one machine policy fingerprint.",
)
def rollback_machine_assignments_command(
    policy_fingerprint: str = typer.Option(
        ...,
        "--policy-fingerprint",
        help="Exact machine evidence policy fingerprint to revoke.",
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Append rollback events; otherwise print the plan only.",
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
    readonly = Database(paths.database, readonly=True)
    eligible = sum(
        row["policy_fingerprint"] == policy_fingerprint
        for row in active_machine_assignment_evidence(readonly)
    )
    console.print(
        f"Machine rollback plan: policy={policy_fingerprint} active={eligible}."
    )
    if not apply:
        console.print("Plan only; pass --apply to append revocation events.")
        return
    database = Database(paths.database)
    database.initialize()
    revoked = rollback_machine_assignments(
        database,
        policy_fingerprint=policy_fingerprint,
    )
    console.print(f"Machine rollback complete: revoked={revoked}.")


@identity_app.command(
    "coordinate",
    help="Plan or execute the non-mutating identity workflow for current extractions.",
)
def coordinate_identity_command(
    youtube_video_id: str | None = typer.Option(
        None,
        "--youtube-video-id",
        help="Coordinate one newly extracted YouTube video.",
    ),
    all_extractions: bool = typer.Option(
        False,
        "--all",
        help="Build a read-only coordination report for all latest extractions.",
    ),
    execute_shadow: bool = typer.Option(
        False,
        "--execute-shadow",
        help=(
            "Run missing shadow association for the requested video; never "
            "apply registry mutations."
        ),
    ),
    discovery_report: Path | None = typer.Option(
        None,
        "--discovery-report",
        exists=True,
        dir_okay=False,
        readable=True,
        help="Optional discovery artifact to include in promotion planning.",
    ),
    discovery_root: Path = typer.Option(
        Path("evaluation/speaker-profile-discovery/shadow-runs"),
        help="Discovery artifacts used to avoid redundant batch work.",
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
        help="Pinned shadow decision policy.",
    ),
    evaluation_root: Path = typer.Option(
        Path("evaluation/speaker-pairs"),
        help="Speaker-pair review and fixture root.",
    ),
    cache_dir: Path = typer.Option(
        Path("evaluation/speaker-pairs/cache"),
        help="Ignored acoustic and media-verification cache.",
    ),
    association_root: Path = typer.Option(
        Path("evaluation/speaker-associations/shadow-runs"),
        help="Versioned shadow-association artifact root.",
    ),
    output_root: Path | None = typer.Option(
        None,
        help="Coordination report directory; defaults under application logs.",
    ),
    base_dir: Path | None = typer.Option(
        None,
        help="Override app data directory.",
    ),
) -> None:
    if (youtube_video_id is None) == (not all_extractions):
        raise typer.BadParameter(
            "Pass exactly one of --youtube-video-id or --all."
        )
    if execute_shadow and youtube_video_id is None:
        raise typer.BadParameter(
            "--execute-shadow currently requires --youtube-video-id; "
            "corpus discovery remains a separately scheduled batch."
        )
    paths = build_paths(base_dir)
    if not paths.database.exists():
        raise typer.BadParameter(
            f"Application database does not exist: {paths.database}"
        )
    coordination_root = (
        output_root.expanduser().resolve()
        if output_root is not None
        else paths.logs / "identity-coordination"
    )
    audit_root = paths.logs / "association-audits"
    verification_cache = MediaVerificationCache(
        cache_dir.expanduser().resolve() / "media-verification"
    )
    try:
        policy_spec = load_shadow_policy(policy_path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise typer.BadParameter(str(error)) from error

    def audit() -> object:
        return audit_speaker_association_coverage(
            Database(paths.database, readonly=True),
            association_root=association_root,
            output_root=audit_root,
            verification_cache=verification_cache,
            required_policy_sha256=policy_spec.artifact_sha256,
        )

    effective_discovery_report = (
        discovery_report.expanduser().resolve()
        if discovery_report is not None
        else None
    )
    if effective_discovery_report is None:
        discovery_reports = list(
            discovery_root.expanduser().resolve().glob("*/*.json")
        )
        if discovery_reports:
            effective_discovery_report = max(
                discovery_reports,
                key=lambda path: (path.stat().st_mtime_ns, str(path)),
            )
    try:
        discovery_states = (
            load_discovery_observation_states(effective_discovery_report)
            if effective_discovery_report is not None
            else {}
        )
        audit_result = audit()
        preliminary = build_identity_coordination_report(
            audit_result.payload,
            youtube_video_id=youtube_video_id,
            discovery_observation_states=discovery_states,
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise typer.BadParameter(str(error)) from error

    executed_association = False
    association_execution_error: str | None = None
    if execute_shadow:
        case = preliminary["cases"][0]
        if case["next_action"] == "run_shadow_association":
            try:
                shadow_associate_speakers_command(
                    youtube_video_id=youtube_video_id,
                    all_eligible=False,
                    limit=None,
                    plan_only=False,
                    minimum_profile_members=3,
                    maximum_exemplars=3,
                    minimum_same_exemplars=2,
                    maximum_global_profiles=3,
                    model_path=model_path,
                    model_sha256=model_sha256,
                    policy_path=policy_path,
                    evaluation_root=evaluation_root,
                    cache_dir=cache_dir,
                    output_root=association_root,
                    base_dir=base_dir,
                )
                executed_association = True
                audit_result = audit()
            except (OSError, RuntimeError, ValueError, typer.BadParameter) as error:
                association_execution_error = str(error)
                console.print(
                    "Shadow association could not execute: "
                    f"{association_execution_error}"
                )
        else:
            console.print(
                "Shadow association not run: current next action is "
                f"{case['next_action']}."
            )

    association_paths = sorted(
        association_root.expanduser().resolve().glob("*/*.json")
    )
    confirmation_plan = plan_candidate_confirmations(
        Database(paths.database, readonly=True),
        association_paths,
    )
    promotion_summary = None
    if discovery_report is not None:
        try:
            promotion_plan = plan_discovery_promotions(
                Database(paths.database, readonly=True),
                discovery_report,
            )
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise typer.BadParameter(str(error)) from error
        promotion_summary = {
            "discovery_report": str(
                discovery_report.expanduser().resolve()
            ),
            "eligible_components": len(promotion_plan.candidates),
            "skipped_components": len(promotion_plan.skipped),
            "apply_allowed_by_coordinator": False,
        }
    report = build_identity_coordination_report(
        audit_result.payload,
        youtube_video_id=youtube_video_id,
        confirmation_observation_ids=(
            candidate.observation_id
            for candidate in confirmation_plan.candidates
        ),
        discovery_observation_states=discovery_states,
        promotion_summary=promotion_summary,
        execution_summary={
            "association_requested": execute_shadow,
            "association_executed": executed_association,
            "association_error": association_execution_error,
            "registry_mutations": 0,
        },
    )
    destination = write_identity_coordination_report(
        coordination_root,
        report,
    )
    counts = report["counts"]
    console.print(
        "Identity coordination: "
        f"extractions={counts['extractions']} "
        f"terminal={counts['terminal']} "
        f"waiting={counts['waiting_for_evidence']} "
        f"action_required={counts['action_required']} "
        f"association_executed={executed_association}"
    )
    console.print(
        "Workflow states: "
        + ", ".join(
            f"{state}={count}"
            for state, count in report["workflow_state_counts"].items()
        )
    )
    console.print(
        "Next actions: "
        + ", ".join(
            f"{action}={count}"
            for action, count in report["next_action_counts"].items()
        )
    )
    console.print(f"Wrote identity coordination report to {destination}")
    if effective_discovery_report is not None:
        console.print(
            "Discovery coverage source: "
            f"{effective_discovery_report}"
        )
    console.print(
        "Coordinator policy: shadow-only; registry mutations=0. "
        "Discovery remains a separately scheduled corpus batch."
    )


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
        3,
        min=1,
        help=(
            "Maximum globally retrieved profiles per candidate in addition "
            "to every same-source or explicit-name profile."
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
    if (youtube_video_id is None) == (not all_eligible):
        raise typer.BadParameter(
            "Pass exactly one of --youtube-video-id or --all-eligible."
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
    ) -> tuple[SpanSpec, ...]:
        extraction = database.get_latest_extraction_result_for_video(video_id)
        if extraction is None or not extraction.proposed_json_path:
            return ()
        try:
            payload = json.loads(
                Path(extraction.proposed_json_path).read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, json.JSONDecodeError):
            return ()
        if not isinstance(payload, dict):
            return ()
        candidates = select_transcript_grounded_span_candidates(
            payload,
            observation,
        )
        if not candidates or plan_only:
            return candidates
        assert backend is not None
        assert embedding_cache is not None
        qualified = activity_selection_cache.get_or_prepare(
            observation=observation,
            source_audio_sha256=source_audio_sha256,
            audio_path=audio_path,
            span_cache=span_cache,
            candidate_specs=candidates,
            embedding_cache=embedding_cache,
            backend=backend,
            policy=policy_spec.policy,
        )
        span_selection_by_observation_id[observation.id] = (
            qualified.selection
        )
        return qualified.span_specs

    videos_by_id = {video.id: video for video in database.list_videos()}
    source_id_by_video_id = {
        video_id: video.source_id for video_id, video in videos_by_id.items()
    }
    eligible_exemplars: list[ShadowExemplar] = []
    span_specs_by_observation_id: dict[int, tuple[SpanSpec, ...]] = {}
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
                verification_cache=verification_cache,
            )
            if (
                not eligibility.eligible
                or eligibility.observation is None
                or eligibility.media_artifact is None
                or eligibility.observation.id != observation.id
            ):
                continue
            audio_path = Path(eligibility.media_artifact.artifact_path)
            span_cache.remember_verified_source(
                audio_path,
                eligibility.media_artifact.content_sha256,
            )
            try:
                span_specs = transcript_grounded_spans(
                    observation.video_id,
                    observation,
                    audio_path,
                    eligibility.media_artifact.content_sha256,
                )
            except (OSError, RuntimeError, ValueError):
                continue
            if not span_specs:
                continue
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

    requested_videos = []
    if youtube_video_id is not None:
        video = database.get_video_by_youtube_id(youtube_video_id)
        if video is None:
            raise typer.BadParameter(
                f"Unknown YouTube video ID: {youtube_video_id}"
            )
        requested_videos = [video]
    else:
        requested_videos = list(videos_by_id.values())

    candidates = []
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
                f"eligible_so_far={len(candidates)} "
                f"excluded_so_far={sum(ineligible_reasons.values())}"
            )
        eligibility = assess_automatic_speaker_observation(
            database,
            video.id,
            verification_cache=verification_cache,
        )
        if not eligibility.eligible or eligibility.observation is None:
            ineligible_reasons[eligibility.reason_code] = (
                ineligible_reasons.get(eligibility.reason_code, 0) + 1
            )
            continue
        if database.list_effective_profile_ids_for_observation(
            eligibility.observation.id
        ):
            ineligible_reasons["already_profiled"] = (
                ineligible_reasons.get("already_profiled", 0) + 1
            )
            continue
        review_action = database.get_effective_observation_review_action(
            eligibility.observation.id
        )
        if review_action not in {None, "qualified_single_speaker"}:
            reason = f"reviewed_{review_action}"
            ineligible_reasons[reason] = ineligible_reasons.get(reason, 0) + 1
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
            continue
        if eligibility.media_artifact is None:
            ineligible_reasons["verified_normalized_media_unavailable"] = (
                ineligible_reasons.get(
                    "verified_normalized_media_unavailable",
                    0,
                )
                + 1
            )
            continue
        audio_path = Path(eligibility.media_artifact.artifact_path)
        span_cache.remember_verified_source(
            audio_path,
            eligibility.media_artifact.content_sha256,
        )
        try:
            span_specs = transcript_grounded_spans(
                video.id,
                eligibility.observation,
                audio_path,
                eligibility.media_artifact.content_sha256,
            )
        except (OSError, RuntimeError, ValueError) as error:
            reason = str(error) or "activity_qualified_spans_unavailable"
            ineligible_reasons[reason] = (
                ineligible_reasons.get(reason, 0) + 1
            )
            continue
        if not span_specs:
            ineligible_reasons["speech_grounded_spans_unavailable"] = (
                ineligible_reasons.get(
                    "speech_grounded_spans_unavailable", 0
                )
                + 1
            )
            continue
        span_specs_by_observation_id[eligibility.observation.id] = span_specs
        candidates.append((video, eligibility, span_specs))
        if all_eligible and limit is not None and len(candidates) >= limit:
            break

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
    if plan_only:
        console.print(
            "Plan only; no acoustic comparisons or association artifacts were created."
        )
        return ()
    if not usable_profiles:
        raise typer.BadParameter(
            "No review-ready profile has enough eligible acoustic exemplars."
        )
    if not candidates:
        raise typer.BadParameter(
            "No eligible unassigned candidate observation was selected."
        )

    assert backend is not None
    assert embedding_cache is not None
    assert pair_diagnostic_cache is not None
    exemplar_centroids: dict[int, tuple[float, ...]] = {}
    console.print(
        "Association preprocessing: building retrieval centroids for "
        f"{sum(len(exemplars) for _profile, exemplars in usable_profiles)} "
        "selected exemplar(s)."
    )
    for _profile, exemplars in usable_profiles:
        for exemplar in exemplars:
            if exemplar.observation.id in exemplar_centroids:
                continue
            exemplar_centroids[exemplar.observation.id] = (
                build_embedding_centroid(
                    observation=exemplar.observation,
                    audio_path=exemplar.audio_path,
                    span_specs=span_specs_by_observation_id[
                        exemplar.observation.id
                    ],
                    span_cache=span_cache,
                    embedding_cache=embedding_cache,
                    backend=backend,
                )
            )
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
    written_reports: list[Path] = []
    for index, (video, eligibility, _span_specs) in enumerate(
        candidates,
        start=1,
    ):
        observation = eligibility.observation
        media_artifact = eligibility.media_artifact
        if observation is None or media_artifact is None:
            continue
        explicit_candidate_names = set(
            candidate_names_by_observation.get(observation.id, ())
        )
        title_hint = title_byline_selection_hint(video.title)
        routing_names = explicit_candidate_names | (
            {title_hint} if title_hint else set()
        )
        legacy_routed_profiles = select_routed_association_profiles(
            usable_profiles,
            candidate_source_id=video.source_id,
            candidate_normalized_names=sorted(routing_names),
            source_id_by_video_id=source_id_by_video_id,
        )
        candidate_centroid = build_embedding_centroid(
            observation=observation,
            audio_path=Path(media_artifact.artifact_path),
            span_specs=span_specs_by_observation_id[observation.id],
            span_cache=span_cache,
            embedding_cache=embedding_cache,
            backend=backend,
        )
        routing = select_staged_association_profiles(
            usable_profiles,
            candidate_source_id=video.source_id,
            candidate_normalized_names=sorted(routing_names),
            source_id_by_video_id=source_id_by_video_id,
            candidate_centroid=candidate_centroid,
            exemplar_centroids=exemplar_centroids,
            maximum_global_profiles=maximum_global_profiles,
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
        }

        def evaluate_profiles(
            selected_profiles,
            routing_payload,
        ):
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
            return evaluate_shadow_association(
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
            ), None

        report, reusable_path = evaluate_profiles(
            candidate_profiles, initial_routing_payload
        )
        if reusable_path is None:
            detailed_profile_comparisons += len(candidate_profiles)
        if report["outcome"] == "proposed_match" and not routing.exhaustive:
            report, reusable_path = evaluate_profiles(
                legacy_routed_profiles,
                {
                    "route": "exhaustive_validation_after_shortlist_proposal",
                    "exhaustive": True,
                    "priority_profile_ids": list(
                        routing.priority_profile_ids
                    ),
                    "shortlisted_profile_ids": list(
                        routing.shortlisted_profile_ids
                    ),
                    "total_routable_profiles": len(legacy_routed_profiles),
                    "maximum_global_profiles": maximum_global_profiles,
                    "retrieval_evidence_only": False,
                    "initial_shortlist_result": "proposed_match",
                },
            )
            if reusable_path is None:
                detailed_profile_comparisons += len(legacy_routed_profiles)
        final_routing = report["routing"]
        routing_route = str(final_routing["route"])
        routing_counts[routing_route] = routing_counts.get(routing_route, 0) + 1
        destination = reusable_path or write_shadow_association(
            output_root, report
        )
        reused_associations += int(reusable_path is not None)
        written_reports.append(destination)
        outcome = str(report["outcome"])
        outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1
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
            "Shadow-association artifacts used for blinded profile-match "
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
    ignore_prewarm: bool = typer.Option(False, hidden=True),
) -> None:
    paths = build_paths(base_dir)
    if not paths.database.exists():
        raise typer.BadParameter(f"Application database does not exist: {paths.database}")
    database = Database(paths.database, readonly=True)
    root = evaluation_root.expanduser().resolve()
    verification_cache = MediaVerificationCache(cache_dir.expanduser().resolve())
    prewarmed_fingerprints = (
        ()
        if ignore_prewarm
        else _load_actionable_review_prewarm(cache_dir)
    )
    if prewarmed_fingerprints:
        console.print(
            "Speaker pair selection: using prewarmed pool with "
            f"{len(prewarmed_fingerprints)} observation(s); corpus fallback "
            "will run only if this pool is exhausted or stale."
        )
    else:
        console.print(
            "Speaker pair selection: no prewarmed pool is available; "
            "building selection from the corpus."
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
        if selection_objective in {
            SelectionGoal.PROFILE_GROWTH,
            SelectionGoal.AUTOMATION_READINESS,
        }:
            active_machine_keys = {
                (
                    str(row["candidate_input_fingerprint"]),
                    database.resolve_speaker_profile_id(
                        int(row["profile_id"])
                    ),
                )
                for row in active_machine_assignment_evidence(database)
            }
            association_paths = tuple(
                association_root.expanduser().resolve().glob("*/*.json")
            )
            association_cache_path = (
                cache_dir.expanduser().resolve()
                / "selector-context"
                / "association-nominations-v1.json"
            )
            current_association_nominations = []
            for nomination in load_shadow_association_confirmation_pairs(
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
            ):
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
                    )
                )
            association_confirmation_pairs = tuple(
                current_association_nominations
            )
            unmatched_association_fingerprints = (
                load_unmatched_association_fingerprints(
                    association_paths,
                    cache_path=association_cache_path,
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
            if prewarmed_fingerprints and video.id not in prewarmed_video_ids:
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
                reviewed_profile_ids=frozenset(
                    database.list_effective_profile_ids_for_observation(
                        observation.id
                    )
                ),
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
            )

        try:
            verified_selection = select_verified_automatic_speaker_pair(
                database,
                candidates,
                select_pair=select_pair,
                verification_cache=verification_cache,
            )
            selection = verified_selection.selection
        except ValueError as error:
            if prewarmed_fingerprints:
                console.print(
                    "Speaker pair selection: prewarmed pool is exhausted or "
                    "stale; rebuilding from the full corpus now."
                )
                review_next_speaker_pair(
                    reviewer=reviewer,
                    evaluation_root=evaluation_root,
                    cache_dir=cache_dir,
                    source_family_registry=source_family_registry,
                    open_packet=open_packet,
                    prepare_only=prepare_only,
                    evaluation_scope=evaluation_scope,
                    selection_objective=selection_objective,
                    discovery_report=discovery_report,
                    discovery_root=discovery_root,
                    association_root=association_root,
                    observation_consistency_report=(
                        observation_consistency_report
                    ),
                    base_dir=base_dir,
                    ignore_prewarm=True,
                )
                return
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
        selection.manifest["media_verification_scope"] = "selected_pair"
        selection.manifest["media_verification_attempts"] = (
            verified_selection.selection_attempts
        )
        if verified_selection.rejection_counts:
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


@media_app.command(
    "backfill",
    help="Register existing audio as reconstructed immutable media artifacts without moving files.",
)
def media_backfill(
    video_id: int | None = typer.Option(None, help="Only migrate one database video id."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    result = backfill_existing_media_artifacts(
        database,
        build_paths(base_dir),
        video_id=video_id,
    )
    console.print(
        f"Examined {result.videos_examined} video(s); registered "
        f"{result.artifacts_registered} media artifact(s) and "
        f"{result.attempts_registered} acquisition result(s); "
        f"missing historical paths={result.missing_paths}."
    )


@media_app.command(
    "ensure-audio",
    help="Ensure isolated sermons have verified audio without running local ASR.",
)
def media_ensure_audio(
    video_id: int | None = typer.Option(None, help="Only process one database video id."),
    all_eligible: bool = typer.Option(
        False,
        "--all-eligible",
        help="Process unresolved videos with a valid isolated sermon window.",
    ),
    limit: int | None = typer.Option(None, min=1, help="Maximum eligible videos to process."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    if (video_id is None) == (not all_eligible):
        raise typer.BadParameter("Pass exactly one of --video-id or --all-eligible.")
    database = get_database(base_dir)
    paths = build_paths(base_dir)
    tools = build_tool_config()
    if video_id is not None:
        videos = [database.get_video_by_id(video_id)]
        if videos[0] is None:
            raise typer.BadParameter(f"Unknown video id: {video_id}")
    else:
        videos = []
        inventory = database.list_videos()
        verification_cache_root = Path(
            "evaluation/speaker-pairs/cache"
        ).resolve()
        verification_cache = MediaVerificationCache(
            verification_cache_root,
            fallback_roots=(
                verification_cache_root / "media-verification",
            ),
        )
        existing = 0
        console.print(
            "Audio ensure inventory: scanning "
            f"{len(inventory)} video(s) for isolated sermons missing "
            "verified normalized audio."
        )
        for inventory_index, video in enumerate(inventory, start=1):
            if (
                inventory_index == 1
                or inventory_index == len(inventory)
                or inventory_index % 25 == 0
            ):
                console.print(
                    "Audio ensure inventory: "
                    f"video={inventory_index}/{len(inventory)} "
                    f"queued={len(videos)} existing={existing}"
                )
            if not video_has_isolated_sermon(database, video.id)[0]:
                continue
            try:
                verified = get_verified_normalized_media_artifact(
                    database,
                    video.id,
                    verification_cache=verification_cache,
                )
            except ArchivedMediaUnavailableError:
                existing += 1
                continue
            if verified is not None:
                existing += 1
                continue
            videos.append(video)
        if limit is not None:
            videos = videos[:limit]
        console.print(
            "Audio ensure inventory complete: "
            f"queued={len(videos)} existing={existing}."
        )
    counts = {"verified": 0, "unavailable": 0, "failed": 0, "skipped": 0}
    downloaded = 0
    for index, video in enumerate(videos, start=1):
        console.print(
            f"Audio ensure [{index}/{len(videos)}] "
            f"{video.youtube_video_id}: starting"
        )
        result = ensure_audio_for_video(
            database,
            paths,
            tools,
            video_id=video.id,
            event_callback=lambda message, index=index, video=video: (
                console.print(
                    f"Audio ensure [{index}/{len(videos)}] "
                    f"{video.youtube_video_id}: {message}",
                    markup=False,
                )
            ),
        )
        counts[result.outcome] += 1
        downloaded += int(result.downloaded)
        console.print(
            f"[{index}/{len(videos)}] {video.youtube_video_id}: "
            f"{result.outcome} ({result.reason_code})"
        )
    console.print(
        "Audio ensure complete: "
        f"verified={counts['verified']} (downloaded={downloaded}), "
        f"unavailable={counts['unavailable']}, failed={counts['failed']}, "
        f"skipped={counts['skipped']}."
    )


@media_app.command(
    "audit",
    help="Report isolated-sermon audio coverage without downloading or modifying media.",
)
def media_audit(
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    report = audit_media_coverage(database)
    console.print(
        f"Isolated sermons={report.isolated_sermons}; verified={len(report.verified)}; "
        f"unavailable={len(report.unavailable)}; failed={len(report.failed)}; "
        f"corrupt={len(report.corrupt)}; missing={len(report.missing)}."
    )
    for label, values in (
        ("unavailable", report.unavailable),
        ("failed", report.failed),
        ("corrupt", report.corrupt),
        ("missing", report.missing),
    ):
        if values:
            console.print(f"{label}: {', '.join(values)}")


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


@media_app.command(
    "archive-sources",
    help="Archive comparison-independent source audio and replace local files with verified symlinks.",
)
def media_archive_sources(
    archive_root: Path | None = typer.Option(
        None,
        "--archive-root",
        help="NAS archive root. Supplying it records and activates the destination for later retries.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Record eligible entries and show destinations without copying or replacing files.",
    ),
    limit: int | None = typer.Option(None, min=1, help="Maximum eligible source artifacts to process."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    try:
        with Progress(
            TextColumn("{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task_id = progress.add_task("Verifying normalized-audio eligibility", total=None)

            def report_archive_preflight(event: ArchivePreflightEvent) -> None:
                progress.console.print(
                    f"Preflight {event.check}: {event.status} — {event.detail}",
                    markup=False,
                )
                if event.check == "eligibility" and event.status == "running":
                    progress.update(task_id, description="Verifying normalized-audio eligibility")

            def update_archive_progress(event: ArchiveProgressEvent) -> None:
                if event.stage == "complete":
                    detail = f" ({event.detail})" if event.detail else ""
                    progress.console.print(
                        f"[{event.index}/{event.total}] media artifact #{event.media_artifact_id}: "
                        f"{event.outcome} -> {event.archive_path}{detail}",
                        markup=False,
                    )
                    progress.update(
                        task_id,
                        total=event.total,
                        completed=event.index,
                        description=f"Archived source audio ({event.index}/{event.total})",
                    )
                    return
                progress.update(
                    task_id,
                    total=event.total,
                    completed=event.index - 1,
                    description=(
                        f"[{event.index}/{event.total}] {event.source_path.name}: {event.stage}"
                    ),
                )

            result = archive_source_media(
                database,
                build_paths(base_dir),
                archive_root=archive_root,
                dry_run=dry_run,
                limit=limit,
                progress_callback=update_archive_progress,
                preflight_callback=report_archive_preflight,
            )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    counts = result.counts
    console.print(
        f"Archive root={result.destination.archive_root}; eligible={result.eligible}; "
        f"archived={counts['archived']}; already_archived={counts['already_archived']}; "
        f"unavailable={counts['destination_unavailable']}; failed={counts['failed']}; "
        f"would_archive={counts['would_archive']}."
    )


@media_app.command(
    "prepare-canonical-audio",
    help="Prepare current canonical speaker clips without running comparisons.",
)
def media_prepare_canonical_audio(
    dry_run: bool = typer.Option(False, "--dry-run"),
    limit: int | None = typer.Option(None, min=1),
    youtube_video_id: str | None = typer.Option(None, "--youtube-video-id"),
    all_eligible: bool = typer.Option(False, "--all-eligible"),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    if (youtube_video_id is None) == (not all_eligible):
        raise typer.BadParameter(
            "Pass exactly one of --youtube-video-id or --all-eligible."
        )
    database = get_database(base_dir)
    paths = build_paths(base_dir)
    video_ids = None
    if youtube_video_id is not None:
        video = database.get_video_by_youtube_id(youtube_video_id)
        if video is None:
            raise typer.BadParameter(f"Unknown YouTube video ID: {youtube_video_id}")
        video_ids = {video.id}

    with Progress(
        TextColumn("{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task_id = progress.add_task("Scanning canonical audio", total=None)

        def report(event: CanonicalAudioPreparationProgressEvent) -> None:
            if event.stage == "complete":
                progress.console.print(
                    f"[{event.index}/{event.total}] {event.youtube_video_id}: "
                    f"{event.outcome} — {event.detail}",
                    markup=False,
                )
                progress.update(
                    task_id,
                    total=event.total,
                    completed=event.index,
                    description=(
                        f"Canonical audio ({event.index}/{event.total})"
                    ),
                )
                return
            progress.update(
                task_id,
                total=event.total,
                completed=event.index - 1,
                description=(
                    f"[{event.index}/{event.total}] "
                    f"{event.youtube_video_id}: {event.stage}"
                ),
            )

        try:
            result = prepare_canonical_audio(
                database,
                paths,
                cache_root=Path("evaluation/speaker-pairs/cache"),
                video_ids=video_ids,
                all_eligible=all_eligible,
                dry_run=dry_run,
                limit=limit,
                wait_for_lock=True,
                progress_callback=report,
            )
        except ValueError as error:
            raise typer.BadParameter(str(error)) from error

    deferred = next(
        (item for item in result.items if item.outcome == "deferred"),
        None,
    )
    if youtube_video_id is not None and deferred is not None:
        retry = (
            "pte media prepare-canonical-audio "
            f"--youtube-video-id {youtube_video_id} "
            f"--base-dir {shlex.quote(str(paths.root))}"
        )
        raise typer.BadParameter(
            f"archived_media_unavailable for {youtube_video_id}. Retry: {retry}"
        )
    counts = result.counts
    console.print(
        "Canonical audio preparation: "
        f"prepared={counts['prepared']} "
        f"would_prepare={counts['would_prepare']} "
        f"already_prepared={counts['already_prepared']} "
        f"deferred={counts['deferred']} blocked={counts['blocked']} "
        f"failed={counts['failed']}."
    )


@media_app.command(
    "archive-normalized",
    help="Archive eligible normalized audio after canonical speaker inputs are prepared.",
)
def media_archive_normalized(
    archive_root: Path | None = typer.Option(None, "--archive-root"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    limit: int | None = typer.Option(None, min=1),
    youtube_video_id: str | None = typer.Option(None, "--youtube-video-id"),
    all_eligible: bool = typer.Option(False, "--all-eligible"),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    if (youtube_video_id is None) == (not all_eligible):
        raise typer.BadParameter(
            "Pass exactly one of --youtube-video-id or --all-eligible."
        )
    database = get_database(base_dir)
    video_ids = None
    if youtube_video_id is not None:
        video = database.get_video_by_youtube_id(youtube_video_id)
        if video is None:
            raise typer.BadParameter(f"Unknown YouTube video ID: {youtube_video_id}")
        video_ids = {video.id}
    try:
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
                    f"Preflight {event.check}: {event.status} — {event.detail}",
                    markup=False,
                )

            def report_progress(event: ArchiveProgressEvent) -> None:
                if event.stage == "complete":
                    detail = f" ({event.detail})" if event.detail else ""
                    progress.console.print(
                        f"[{event.index}/{event.total}] normalized artifact "
                        f"#{event.media_artifact_id}: {event.outcome} -> "
                        f"{event.archive_path}{detail}",
                        markup=False,
                    )
                    progress.update(
                        task_id,
                        total=event.total,
                        completed=event.index,
                        description=(
                            f"Normalized archive ({event.index}/{event.total})"
                        ),
                    )
                    return
                progress.update(
                    task_id,
                    total=event.total,
                    completed=event.index - 1,
                    description=(
                        f"[{event.index}/{event.total}] "
                        f"{event.source_path.name}: {event.stage}"
                    ),
                )

            result = archive_normalized_media(
                database,
                build_paths(base_dir),
                archive_root=archive_root,
                dry_run=dry_run,
                limit=limit,
                video_ids=video_ids,
                all_eligible=all_eligible,
                progress_callback=report_progress,
                preflight_callback=report_preflight,
            )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    for item in result.eligibility:
        state = "eligible" if item.eligible else "blocked"
        console.print(
            f"{item.youtube_video_id}: {state}; {item.reason}; "
            f"clip_preparation={item.clip_preparation_status}"
        )
    counts = result.counts
    console.print(
        f"Normalized archive root={result.destination.archive_root}; eligible={result.eligible}; "
        f"archived={counts['archived']}; already_archived={counts['already_archived']}; "
        f"unavailable={counts['destination_unavailable']}; failed={counts['failed']}; "
        f"would_archive={counts['would_archive']}."
    )


@media_app.command(
    "archive-status",
    help="Report source and normalized archive state and normalized eligibility.",
)
def media_archive_status(
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    report = archive_status(database, build_paths(base_dir))
    if report.destination is None:
        console.print("No media archive destination is configured.")
        return
    counts = report.counts
    source_counts = {
        status: sum(entry.status == status for entry in report.source_entries)
        for status in ("pending", "archived", "failed")
    }
    normalized_counts = {
        status: sum(entry.status == status for entry in report.normalized_entries)
        for status in ("pending", "archived", "failed")
    }
    eligible = sum(item.eligible for item in report.normalized_eligibility)
    stale = sum(
        item.clip_preparation_status == "stale"
        for item in report.normalized_eligibility
    )
    blocked = sum(
        item.clip_preparation_status == "missing"
        for item in report.normalized_eligibility
    )
    console.print(
        f"Archive root={report.destination.archive_root}; "
        f"accessible={report.destination_accessible}; entries={len(report.entries)}; "
        f"archived={counts['archived']}; pending={counts['pending']}; failed={counts['failed']}."
    )
    console.print(
        f"Source audio: entries={len(report.source_entries)}; archived={source_counts['archived']}; "
        f"pending={source_counts['pending']}; failed={source_counts['failed']}."
    )
    console.print(
        f"Normalized audio: entries={len(report.normalized_entries)}; "
        f"archived={normalized_counts['archived']}; pending={normalized_counts['pending']}; "
        f"failed={normalized_counts['failed']}; unavailable="
        f"{normalized_counts['archived'] if not report.destination_accessible else 0}; "
        f"eligible={eligible}; stale_clip_preparation={stale}; "
        f"blocked_clip_fingerprint_generation={blocked}."
    )


@media_app.command(
    "sweep-audio",
    help=(
        "Audit physical local audio and optionally replace byte-identical archived "
        "duplicates with symlinks. Dry-run is the default."
    ),
)
def media_sweep_audio(
    apply: bool = typer.Option(
        False,
        "--apply",
        help=(
            "Replace only byte-identical, checksum-verified archived duplicates "
            "with symlinks. Unmatched files are never removed."
        ),
    ),
    report: Path | None = typer.Option(
        None,
        "--report",
        help="Write the complete machine-readable audit as JSON.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        help="Print every retained file in addition to reclaimable files.",
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    paths = build_paths(base_dir)
    last_stage: tuple[Path, str] | None = None

    with Progress(
        TextColumn("{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task_id = progress.add_task("Inventorying physical local audio", total=None)

        def report_progress(event: AudioSweepProgressEvent) -> None:
            nonlocal last_stage
            current = (event.path, event.stage)
            if current == last_stage:
                return
            last_stage = current
            progress.update(
                task_id,
                total=event.total,
                completed=event.index - 1,
                description=(
                    f"[{event.index}/{event.total}] {event.path.name}: {event.stage}"
                ),
            )

        try:
            result = sweep_local_audio(
                database,
                paths,
                apply=apply,
                progress_callback=report_progress,
            )
        except (OSError, RuntimeError, ValueError) as error:
            raise typer.BadParameter(str(error)) from error
        progress.update(
            task_id,
            completed=len(result.items),
            total=len(result.items),
            description="Local audio sweep complete",
        )

    for item in result.items:
        if not verbose and item.outcome not in {
            "would_link_to_archive",
            "linked_to_archive",
            "retained_link_failed",
        }:
            continue
        destination = f" -> {item.archive_path}" if item.archive_path else ""
        console.print(
            f"{item.outcome}: {_format_sync_bytes(item.byte_size)} "
            f"{item.path}{destination} ({item.detail})",
            markup=False,
        )

    summary = Table(title="Local audio sweep")
    summary.add_column("Outcome")
    summary.add_column("Files", justify="right")
    summary.add_column("Bytes", justify="right")
    for outcome, count in sorted(result.counts.items()):
        summary.add_row(
            outcome,
            str(count),
            _format_sync_bytes(result.bytes_by_outcome[outcome]),
        )
    console.print(summary)
    action = "reclaimed" if apply else "reclaimable"
    console.print(
        f"Sweep mode={'apply' if apply else 'dry-run'}; {action}="
        f"{_format_sync_bytes(result.reclaimable_bytes)}. "
        "Registered unarchived and failed items remain for the normal archive commands."
    )

    if report is not None:
        report_path = report.expanduser().resolve(strict=False)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "mode": "apply" if apply else "dry-run",
            "reclaimable_bytes": result.reclaimable_bytes,
            "counts": result.counts,
            "bytes_by_outcome": result.bytes_by_outcome,
            "items": [
                {
                    "path": str(item.path),
                    "byte_size": item.byte_size,
                    "category": item.category,
                    "outcome": item.outcome,
                    "detail": item.detail,
                    "media_artifact_id": item.media_artifact_id,
                    "archive_path": (
                        str(item.archive_path) if item.archive_path else None
                    ),
                }
                for item in result.items
            ],
        }
        report_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        console.print(f"Report written: {report_path}", markup=False)


def _unknown_pastor_error(pastor_slug: str, base_dir: Path | None = None) -> typer.BadParameter:
    resolved_root = build_paths(base_dir).root
    return typer.BadParameter(f"Unknown pastor slug: {pastor_slug} (app root: {resolved_root})")


def _discover_candidate_window(
    *,
    discovered_videos,
    existing_source_videos,
    effective_limit: int | None,
):
    if effective_limit is None:
        return discovered_videos

    candidates = list(discovered_videos[:effective_limit])
    candidate_ids = {video.youtube_video_id for video in candidates}
    retained_published_values = sorted(
        [video.published_at.isoformat() for video in existing_source_videos if video.published_at is not None]
    )
    if not retained_published_values:
        return candidates

    oldest_retained_published_at = retained_published_values[0]
    for video in discovered_videos[effective_limit:]:
        if video.published_at is None or video.published_at < oldest_retained_published_at:
            continue
        if video.youtube_video_id in candidate_ids:
            continue
        candidates.append(video)
        candidate_ids.add(video.youtube_video_id)
    return candidates


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


def _is_terminal_unavailable(video_status: VideoStatus, failure_reason: str | None) -> bool:
    if video_status is not VideoStatus.FAILED or not failure_reason:
        return False
    lowered = failure_reason.lower()
    return "video unavailable" in lowered


def _is_retryable_fetch_failure(video_status: VideoStatus, failure_reason: str | None) -> bool:
    if video_status is not VideoStatus.FAILED or not failure_reason:
        return False
    lowered = failure_reason.lower()
    return "has not started yet" in lowered or "cannot solve youtube javascript challenges" in lowered


def _default_transcribe_jobs() -> int:
    cpu_count = os.cpu_count() or 1
    return min(DEFAULT_TRANSCRIBE_JOBS, max(1, cpu_count))


def _should_transcribe_video(
    database: Database,
    video_id: int,
    *,
    missing_only: bool,
    captions_missing_only: bool,
) -> bool:
    video = database.get_video_by_id(video_id)
    if video is None:
        return False
    if not video_is_sermon_eligible(video.duration_seconds, video.published_at):
        return False
    if _is_terminal_unavailable(video.status, video.failure_reason) or _is_retryable_fetch_failure(
        video.status, video.failure_reason
    ):
        return False

    latest_artifact = database.get_latest_transcript_artifact_for_video(video.id)
    if missing_only and latest_artifact is not None:
        return False
    if captions_missing_only and latest_artifact is not None and latest_artifact.source_kind == TranscriptSourceKind.CAPTIONS:
        return False
    if latest_artifact is not None and latest_artifact.source_kind == TranscriptSourceKind.LOCAL_ASR and video.status in {
        VideoStatus.TRANSCRIBING_LOCAL,
        VideoStatus.TRANSCRIBED_LOCAL,
        VideoStatus.EXTRACTED,
        VideoStatus.EXPORTED,
    }:
        return False
    return True


def _claim_video_for_transcription(database: Database, video_id: int) -> bool:
    video = database.get_video_by_id(video_id)
    if video is None:
        return False
    return database.update_video_status_if_current(
        video_id,
        current_status=video.status,
        new_status=VideoStatus.TRANSCRIBING_LOCAL,
        failure_reason=f"transcription_previous_status:{video.status.value}",
    )


def _recover_stale_transcribing_videos(database: Database, videos: list) -> None:
    for video in videos:
        if video.status != VideoStatus.TRANSCRIBING_LOCAL:
            continue
        latest_artifact = database.get_latest_transcript_artifact_for_video(video.id)
        if latest_artifact is not None and latest_artifact.source_kind == TranscriptSourceKind.LOCAL_ASR:
            database.update_video_status(video.id, VideoStatus.TRANSCRIBED_LOCAL)
            continue
        marker = video.failure_reason or ""
        if marker.startswith("transcription_previous_status:"):
            previous_value = marker.partition(":")[2]
            try:
                previous_status = VideoStatus(previous_value)
            except ValueError:
                previous_status = None
            if previous_status is not None and previous_status is not VideoStatus.TRANSCRIBING_LOCAL:
                database.update_video_status(video.id, previous_status)
                continue
        latest_extraction = database.get_latest_extraction_result_for_video(video.id)
        if latest_extraction is not None:
            database.update_video_status(video.id, VideoStatus.EXTRACTED)
            continue
        if latest_artifact is not None and latest_artifact.source_kind == TranscriptSourceKind.CAPTIONS:
            database.update_video_status(video.id, VideoStatus.TRANSCRIPT_FETCHED)
            continue
        database.update_video_status(video.id, VideoStatus.DISCOVERED)


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


def _build_transcription_progress_callback(video_id: int) -> Callable[[int], None]:
    lock = Lock()
    state = {"last_percent": -1}

    def progress_callback(percent: int) -> None:
        bounded = max(0, min(percent, 100))
        with lock:
            if bounded <= state["last_percent"]:
                return
            state["last_percent"] = bounded
        console.print(f"[video #{video_id} progress] {bounded}%", markup=False)

    return progress_callback


def _build_transcription_stage_callback(video_id: int) -> Callable[[str], None]:
    lock = Lock()
    state = {"last_stage": STAGE_QUEUED_PREP}

    def stage_callback(stage: str) -> None:
        label = STAGE_LABELS.get(stage, stage)
        with lock:
            if label == state["last_stage"]:
                return
            state["last_stage"] = label
        console.print(f"[video #{video_id} stage] {label}", markup=False)

    return stage_callback


def _build_live_transcription_progress_callback(
    progress: Progress,
    task_id: TaskID,
    lock: Lock,
) -> Callable[[int], None]:
    state = {"last_percent": -1, "started": False}

    def progress_callback(percent: int) -> None:
        bounded = max(0, min(percent, 100))
        with lock:
            if bounded <= state["last_percent"]:
                return
            state["last_percent"] = bounded
            update_kwargs = {"completed": bounded}
            if not state["started"]:
                update_kwargs["fields"] = {"status": "running"}
                state["started"] = True
            progress.update(task_id, **update_kwargs)

    return progress_callback


def _build_live_transcription_stage_callback(
    progress: Progress,
    task_id: TaskID,
    lock: Lock,
) -> Callable[[str], None]:
    valid_statuses = {
        STAGE_QUEUED_PREP,
        STAGE_DOWNLOADING,
        STAGE_NORMALIZING,
        STAGE_QUEUED_TRANSCRIBE,
        STAGE_TRANSCRIBING,
        STAGE_DONE,
        STAGE_FAILED,
    }
    active_statuses = {
        STAGE_DOWNLOADING,
        STAGE_NORMALIZING,
        STAGE_QUEUED_TRANSCRIBE,
        STAGE_TRANSCRIBING,
        STAGE_DONE,
        STAGE_FAILED,
    }

    def stage_callback(stage: str) -> None:
        label = STAGE_LABELS.get(stage, stage)
        if label not in valid_statuses:
            return
        with lock:
            task = progress.tasks[task_id]
            if label in active_statuses and task.start_time is None:
                progress.start_task(task_id)
            if label == STAGE_TRANSCRIBING:
                progress.update(task_id, status=label, completed=0)
            elif label == STAGE_DONE:
                progress.update(task_id, status=label, completed=100)
            else:
                progress.update(task_id, status=label)

    return stage_callback


def _delete_video_tree(database: Database, paths: Path, video_id: int) -> None:
    video = database.get_video_by_id(video_id)
    if video is None:
        raise typer.BadParameter(f"Unknown video id: {video_id}")

    video_paths = resolve_video_artifact_paths(database, paths, video)
    if video_paths.root.exists():
        shutil.rmtree(video_paths.root)
    database.delete_video(video.id)


def _delete_source_tree(database: Database, paths: Path, source_id: int) -> int:
    source = database.get_source_by_id(source_id)
    if source is None:
        raise typer.BadParameter(f"Unknown source id: {source_id}")

    videos = database.list_videos_by_source_id(source_id)
    deleted_count = 0
    for video in videos:
        video_paths = resolve_video_artifact_paths(database, paths, video)
        if video_paths.root.exists():
            shutil.rmtree(video_paths.root)
        database.delete_video(video.id)
        deleted_count += 1

    database.delete_source(source_id)
    return deleted_count


@app.command(help="Initialize the app data directory and SQLite database.")
def init(
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    paths = build_paths(base_dir, remember=True)
    ensure_directories(paths)
    database = Database(paths.database)
    database.initialize()
    console.print(f"Initialized app data at [bold]{paths.root}[/bold]")


@source_ownership_app.command(
    "migrate",
    help="Apply or preview the replayable source-ownership migration.",
)
def source_ownership_migrate(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Run the migration and audit inside a rolled-back savepoint.",
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    paths = build_paths(base_dir, remember=True)
    if not paths.database.exists():
        raise typer.BadParameter(
            f"Database does not exist: {paths.database}. Run 'pte init' first."
        )
    database = Database(paths.database)
    with database.connect() as connection:
        if connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'sources'"
        ).fetchone() is None:
            raise typer.BadParameter(
                "Database is not initialized; run 'pte init' first."
            )
        if dry_run:
            connection.execute("SAVEPOINT source_ownership_preview")
        try:
            apply_source_ownership_schema(connection)
            result = backfill_source_ownership(connection)
            report = audit_source_ownership(connection, app_root=paths.root)
        finally:
            if dry_run:
                connection.execute("ROLLBACK TO source_ownership_preview")
                connection.execute("RELEASE source_ownership_preview")
    mode = "preview" if dry_run else "applied"
    console.print(
        f"Source ownership migration {mode}: "
        f"organizations={result.organizations_created}, "
        f"snapshots={result.snapshots_created}, "
        f"claims={result.affiliation_claims_created}, "
        f"source_targets={result.source_target_policies_created}, "
        f"video_targets={result.video_target_contexts_created}, "
        f"artifact_namespaces={result.artifact_namespaces_created}."
    )
    console.print(
        "Projected audit passed." if report.ok else "Projected audit failed."
    )
    if not report.ok:
        raise typer.Exit(code=1)


@source_ownership_app.command(
    "audit",
    help="Validate organization, target-context, and artifact-namespace projections.",
)
def source_ownership_audit(
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Exit unsuccessfully when any ownership invariant fails.",
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    paths = build_paths(base_dir)
    with database.connect() as connection:
        report = audit_source_ownership(connection, app_root=paths.root)
    values = {
        "Foreign-key violations": report.foreign_key_violations,
        "Legacy imports without external refs": report.imported_refs_without_external_ref,
        "Imported links without organization": report.imported_links_without_organization,
        "Legacy sources without target policy": report.legacy_sources_without_target_policy,
        "Legacy videos without target context": report.legacy_videos_without_target_context,
        "Videos without artifact namespace": report.videos_without_artifact_namespace,
        "Artifact namespace path mismatches": report.artifact_namespace_path_mismatches,
    }
    table = Table(title="Source ownership audit")
    table.add_column("Invariant")
    table.add_column("Failures", justify="right")
    for label, value in values.items():
        table.add_row(label, str(value))
    console.print(table)
    console.print("Source ownership audit passed." if report.ok else "Source ownership audit failed.")
    if strict and not report.ok:
        raise typer.Exit(code=1)


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
    paths = build_paths(base_dir, remember=True)
    if archive_sources and not extract_new:
        raise typer.BadParameter("--archive-sources requires --extract.")
    if archive_sources and database.get_active_media_archive_destination() is None:
        raise typer.BadParameter(
            "No media archive destination is configured. Run "
            "'pte media archive-sources --archive-root PATH' first."
        )
    source_ids = imported_source_ids(database, provider)
    if not source_ids:
        raise typer.BadParameter(f"No imported sources found for provider {provider!r}.")
    archive_executor = ThreadPoolExecutor(max_workers=1) if archive_sources else None
    pending_archives: list[tuple[int, Future[ArchiveRunResult]]] = []

    def finish_archive(source_id: int, future: Future[ArchiveRunResult]) -> None:
        try:
            archive = future.result()
        except (OSError, RuntimeError, ValueError) as error:
            console.print(f"Archive worker failed for source #{source_id}: {error}")
            return
        counts = archive.counts
        console.print(
            f"Archived source #{source_id}: archived={counts['archived']}, "
            f"already_archived={counts['already_archived']}, "
            f"unavailable={counts['destination_unavailable']}, failed={counts['failed']}."
        )
        if counts["destination_unavailable"] or counts["failed"]:
            console.print(
                "Some source audio remains local and will be retried by the next "
                "archive run; download admission remains governed by disk reserve."
            )

    def reap_archives(*, block_one: bool = False) -> None:
        if block_one and pending_archives:
            source_id, future = pending_archives.pop(0)
            finish_archive(source_id, future)
        completed = [item for item in pending_archives if item[1].done()]
        for source_id, future in completed:
            pending_archives.remove((source_id, future))
            finish_archive(source_id, future)

    def require_disk_reserve(source_id: int, projected_bytes: int) -> None:
        reap_archives()
        wait_seconds = SYNC_ARCHIVE_WAIT_INITIAL_SECONDS
        while True:
            disk = shutil.disk_usage(paths.root)
            required_free = int(disk.total * MIN_SYNC_FREE_DISK_FRACTION)
            projected_free = disk.free - projected_bytes
            if projected_free >= required_free:
                console.print(
                    f"Disk admission for source #{source_id}: "
                    f"{disk.free / disk.total:.1%} free, "
                    f"reserving {_format_sync_bytes(projected_bytes)}, "
                    f"projected={projected_free / disk.total:.1%}."
                )
                return
            archive_active = bool(pending_archives) or media_archive_lock_held(paths.root)
            if archive_active:
                console.print(
                    f"Waiting for archival before source #{source_id}: projected local "
                    f"free space would be {projected_free / disk.total:.1%}; "
                    f"checking again in {wait_seconds:g}s."
                )
                if pending_archives:
                    wait(
                        {future for _, future in pending_archives},
                        timeout=wait_seconds,
                        return_when=FIRST_COMPLETED,
                    )
                    reap_archives()
                else:
                    time.sleep(wait_seconds)
                wait_seconds = min(
                    wait_seconds * 2,
                    SYNC_ARCHIVE_WAIT_MAX_SECONDS,
                )
                continue
            console.print(
                f"Stopping before audio download for source #{source_id}: projected "
                f"local free space would be {projected_free / disk.total:.1%}; "
                f"synchronization requires at least "
                f"{MIN_SYNC_FREE_DISK_FRACTION:.1%}."
            )
            raise typer.Exit(code=1)

    try:
        for index, source_id in enumerate(source_ids, start=1):
            reap_archives()
            require_disk_reserve(source_id, 0)
            console.print(
                f"[{index}/{len(source_ids)}] Synchronizing imported source #{source_id}"
            )
            _recover_stale_transcribing_videos(
                database, database.list_videos_by_source_id(source_id)
            )
            discovery = discover_sources_service(
                limit=latest, source_id=source_id, base_dir=base_dir
            )
            selected_video_ids = set(
                discovery.selected_video_ids_by_source.get(source_id, ())
            )
            if not selected_video_ids:
                console.print(
                    f"No videos selected in the current latest-{latest} window for "
                    f"source #{source_id}; skipping downstream processing."
                )
                continue
            console.print(
                f"Selected {len(selected_video_ids)} video(s) for downstream processing "
                f"from source #{source_id}."
            )
            fetch_captions_service(
                source_id=source_id,
                base_dir=base_dir,
                video_ids=selected_video_ids,
            )
            projected_bytes = _projected_transcription_disk_bytes(
                database,
                source_id=source_id,
                captions_missing_only=not all_audio,
                video_ids=selected_video_ids,
            )
            require_disk_reserve(source_id, projected_bytes)
            transcribe_videos_service(
                missing_only=False,
                captions_missing_only=not all_audio,
                jobs=jobs,
                prep_jobs=download_jobs,
                source_id=source_id,
                base_dir=base_dir,
                video_ids=selected_video_ids,
            )
            if extract_new:
                extraction = extract_batch(
                    database,
                    paths,
                    source_id=source_id,
                    video_ids=selected_video_ids,
                    classifier="auto",
                    llm_model=None,
                    workers=jobs,
                    event_callback=lambda message: console.print(message, markup=False),
                    progress_callback=lambda stage, current, total: console.print(
                        f"  {stage} block {current}/{total}"
                    ),
                )
                console.print(
                    f"Extracted {extraction.processed} video(s); "
                    f"skipped {extraction.skipped}; failed {extraction.failed}."
                )
            source_videos = [
                video
                for video in database.list_videos_by_source_id(source_id)
                if video.id in selected_video_ids
            ]
            registration = [
                backfill_existing_media_artifacts(database, paths, video_id=video.id)
                for video in source_videos
            ]
            console.print(
                f"Registered {sum(item.artifacts_registered for item in registration)} "
                f"media artifact(s) for source #{source_id}; "
                f"missing paths={sum(item.missing_paths for item in registration)}."
            )
            if archive_executor is not None:
                video_ids = {video.id for video in source_videos}
                future = archive_executor.submit(
                    archive_source_media,
                    database,
                    paths,
                    video_ids=video_ids,
                    wait_for_lock=True,
                )
                pending_archives.append((source_id, future))
                console.print(
                    f"Queued source #{source_id} for archival "
                    f"({len(pending_archives)} pending)."
                )
    finally:
        while pending_archives:
            reap_archives(block_one=True)
        if archive_executor is not None:
            archive_executor.shutdown(wait=True)
    console.print(
        f"Synchronized {len(source_ids)} imported source(s); latest={latest}, "
        f"download_jobs={download_jobs}, transcription_jobs={jobs}, "
        f"extraction_jobs={jobs}, all_audio={all_audio}, extract={extract_new}, "
        f"archive_sources={archive_sources}."
    )


def _projected_transcription_disk_bytes(
    database: Database,
    *,
    source_id: int,
    captions_missing_only: bool,
    video_ids: set[int] | None = None,
) -> int:
    projected = 0
    for video in database.list_videos_by_source_id(source_id):
        if video_ids is not None and video.id not in video_ids:
            continue
        if not _should_transcribe_video(
            database,
            video.id,
            missing_only=False,
            captions_missing_only=captions_missing_only,
        ):
            continue
        duration = video.duration_seconds or SYNC_UNKNOWN_VIDEO_DURATION_SECONDS
        projected += int(duration * SYNC_AUDIO_RESERVATION_BYTES_PER_SECOND)
    return projected


def _format_sync_bytes(value: int) -> str:
    amount = float(max(0, value))
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if amount < 1024 or unit == "TiB":
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{amount:.1f} TiB"


def add_source_service(
    url: str,
    pastor: str | None,
    notes: str | None = None,
    base_dir: Path | None = None,
    organization: str | None = None,
) -> None:
    database = get_database(base_dir)
    try:
        source_type = detect_source_type(url)
    except UnsupportedSourceError as error:
        raise ValueError(str(error)) from error

    pastor_record = database.get_pastor_by_slug(pastor) if pastor is not None else None
    if pastor is not None and pastor_record is None:
        raise ValueError(
            f"Unknown pastor slug: {pastor} (app root: {build_paths(base_dir).root})"
        )
    organization_record = (
        database.get_organization_by_slug(organization)
        if organization is not None
        else None
    )
    if organization is not None and organization_record is None:
        raise ValueError(f"Unknown organization slug: {organization}")

    source = database.add_source(
        url=url,
        source_type=source_type,
        pastor_id=pastor_record.id if pastor_record is not None else None,
        organization_id=(
            organization_record.id if organization_record is not None else None
        ),
        notes=notes,
    )
    if organization_record is not None:
        if (
            source.organization_id is not None
            and source.organization_id != organization_record.id
        ):
            current = database.get_organization_by_id(source.organization_id)
            current_label = current.slug if current is not None else source.organization_id
            raise ValueError(
                f"Source #{source.id} is already attached to organization "
                f"{current_label}; use 'pte source set-organization' to correct it"
            )
        database.set_source_organization(
            source.id,
            organization_record.id,
            actor="manual",
            reason="Organization selected while adding source",
            event_key=f"source-add:{source.id}:{organization_record.id}",
        )
        source = database.get_source_by_id(source.id) or source
    context = []
    if organization_record is not None:
        context.append(f"organization: {organization_record.slug}")
    if pastor_record is not None:
        context.append(f"target pastor: {pastor_record.slug}")
    suffix = f" ({', '.join(context)})" if context else " (organization unknown)"
    console.print(
        f"Added source #{source.id}: {source.source_type.value} -> {source.url}{suffix}"
    )


@app.command(help="Add a YouTube video, playlist, or channel source for a pastor.")
def add(
    url: str = typer.Argument(..., help="YouTube video, playlist, or channel URL."),
    pastor: str = typer.Option(..., help="Pastor slug to associate with this source."),
    notes: str | None = typer.Option(None, help="Optional notes for this source."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    try:
        add_source_service(url, pastor, notes, base_dir)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error


@organization_app.command("add", help="Create a publishing organization.")
def organization_add(
    slug: str = typer.Argument(..., help="Stable organization slug."),
    display_name: str = typer.Argument(..., help="Human-readable organization name."),
    organization_type: str = typer.Option(
        "church",
        "--type",
        help="Organization type, such as church, conference, ministry, school, or network.",
    ),
    notes: str | None = typer.Option(None, help="Optional organization notes."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    organization = database.add_organization(
        slug=slug,
        display_name=display_name,
        organization_type=organization_type,
        notes=notes,
    )
    console.print(
        f"Added organization #{organization.id}: {organization.slug} -> "
        f"{organization.display_name} ({organization.organization_type})"
    )


@organization_app.command("list", help="List publishing organizations.")
def organization_list(
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    organizations = database.list_organizations()
    if not organizations:
        console.print("No organizations configured.")
        return
    table = Table(title="Organizations")
    table.add_column("ID", justify="right")
    table.add_column("Slug")
    table.add_column("Type")
    table.add_column("Display Name")
    for organization in organizations:
        table.add_row(
            str(organization.id),
            organization.slug,
            organization.organization_type,
            organization.display_name,
        )
    console.print(table)


@organization_app.command(
    "review",
    help="Build a publisher-scoped review without asserting speaker identity.",
)
def organization_review(
    organization: str = typer.Argument(..., help="Organization slug."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    paths = build_paths(base_dir, remember=True)
    try:
        result = export_organization_review_markdown(
            database,
            paths,
            organization,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print(f"Wrote organization review markdown to {result.export_path}")
    console.print(f"Wrote organization review manifest to {result.manifest_path}")
    console.print(
        f"Included {result.video_count} video(s); skipped {result.skipped_count}."
    )


@organization_app.command(
    "claims",
    help="List imported affiliation claims without linking people by name.",
)
def organization_claims(
    organization: str | None = typer.Option(
        None,
        help="Only show claims for one organization slug.",
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    organization_id = None
    if organization is not None:
        organization_record = database.get_organization_by_slug(organization)
        if organization_record is None:
            raise typer.BadParameter(f"Unknown organization slug: {organization}")
        organization_id = organization_record.id
    claims = database.list_organization_affiliation_claims(organization_id)
    if not claims:
        console.print("No affiliation claims matched.")
        return
    table = Table(title="Organization Affiliation Claims")
    table.add_column("ID", justify="right")
    table.add_column("Organization")
    table.add_column("Claimed Name")
    table.add_column("Role")
    table.add_column("Review")
    for claim in claims:
        table.add_row(
            str(claim["id"]),
            str(claim["organization_slug"]),
            str(claim["claimed_person_name"]),
            str(claim["claimed_role"]),
            str(claim["review_status"] or "unreviewed"),
        )
    console.print(table)


@organization_app.command(
    "reject-affiliation-claim",
    help="Append a reviewed rejection without creating or linking a person.",
)
def organization_reject_affiliation_claim(
    claim_id: int = typer.Argument(..., help="Affiliation claim id."),
    reviewer: str = typer.Option(..., help="Reviewer name."),
    reason: str = typer.Option(..., help="Reason for rejection."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    try:
        event_id = database.review_organization_affiliation_claim(
            claim_id=claim_id,
            pastor_id=None,
            attach=False,
            reviewer=reviewer,
            reason=reason,
            review_event_key=f"reject:{claim_id}:{reviewer}:{reason}",
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print(f"Recorded affiliation claim rejection event #{event_id}.")


@source_app.command(
    "add",
    help="Add a source with an optional publisher and optional target pastor.",
)
def source_add(
    url: str = typer.Argument(..., help="YouTube video, playlist, or channel URL."),
    organization: str | None = typer.Option(
        None,
        help="Publishing organization slug; omit when unknown.",
    ),
    target_pastor: str | None = typer.Option(
        None,
        "--target-pastor",
        help="Optional pastor query target; this is not source ownership.",
    ),
    notes: str | None = typer.Option(None, help="Optional source notes."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    try:
        add_source_service(
            url,
            target_pastor,
            notes,
            base_dir,
            organization=organization,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error


@source_app.command(
    "set-organization",
    help="Attach or correct a source's current publishing organization.",
)
def source_set_organization(
    source_id: int = typer.Argument(..., help="Source id to update."),
    organization: str = typer.Argument(..., help="Publishing organization slug."),
    reason: str = typer.Option(
        "Manual publisher correction",
        help="Audit reason for the association.",
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    organization_record = database.get_organization_by_slug(organization)
    if organization_record is None:
        raise typer.BadParameter(f"Unknown organization slug: {organization}")
    try:
        database.set_source_organization(
            source_id,
            organization_record.id,
            actor="manual",
            reason=reason,
            event_key=f"manual-attach:{source_id}:{organization_record.id}:{reason}",
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print(
        f"Attached source #{source_id} to organization {organization_record.slug}."
    )


@source_app.command(
    "clear-organization",
    help="Mark a source's current publishing organization as unknown.",
)
def source_clear_organization(
    source_id: int = typer.Argument(..., help="Source id to update."),
    reason: str = typer.Option(
        "Manual publisher correction",
        help="Audit reason for clearing the association.",
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    try:
        database.set_source_organization(
            source_id,
            None,
            actor="manual",
            reason=reason,
            event_key=f"manual-detach:{source_id}:{reason}",
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print(f"Cleared the publishing organization for source #{source_id}.")


def _set_source_processing_enabled(
    source_id: int,
    enabled: bool,
    base_dir: Path | None,
) -> None:
    database = get_database(base_dir)
    try:
        source = database.set_source_processing_enabled(source_id, enabled)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    state = "enabled" if enabled else "disabled"
    scope = "included in" if enabled else "excluded from"
    console.print(
        f"Source #{source.id} is {state} and will be {scope} all-source processing: "
        f"{source.url}"
    )


@source_app.command(
    "disable",
    help="Exclude a source from all-source processing such as `pte run --all`.",
)
def source_disable(
    source_id: int = typer.Argument(..., help="Source id to disable."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    _set_source_processing_enabled(source_id, False, base_dir)


@source_app.command(
    "enable",
    help="Include a source in all-source processing such as `pte run --all`.",
)
def source_enable(
    source_id: int = typer.Argument(..., help="Source id to enable."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    _set_source_processing_enabled(source_id, True, base_dir)


@app.command(help="Show database counts and queued sources.")
def status(
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    counts = database.counts_by_table()
    sources = database.list_sources()

    summary = Table(title="Pastor Transcript Extractor")
    summary.add_column("Metric")
    summary.add_column("Value", justify="right")
    summary.add_row("Organizations", str(counts["organizations"]))
    summary.add_row(
        "Imported Affiliation Claims",
        str(counts["organization_affiliation_claims"]),
    )
    summary.add_row(
        "Pastor Affiliations",
        str(counts["pastor_organization_affiliations"]),
    )
    summary.add_row(
        "Affiliation Claim Reviews",
        str(counts["affiliation_claim_review_events"]),
    )
    summary.add_row("Sources", str(counts["sources"]))
    summary.add_row(
        "Processing-enabled Sources",
        str(sum(source.processing_enabled for source in sources)),
    )
    summary.add_row(
        "Processing-disabled Sources",
        str(sum(not source.processing_enabled for source in sources)),
    )
    summary.add_row("Imported Source References", str(counts["source_import_refs"]))
    summary.add_row("Pastors", str(counts["pastors"]))
    summary.add_row("Videos", str(counts["videos"]))
    summary.add_row("Transcripts", str(counts["transcript_artifacts"]))
    summary.add_row("Media Artifacts", str(counts["media_artifacts"]))
    summary.add_row("Media Acquisition Attempts", str(counts["media_acquisition_attempts"]))
    summary.add_row("Media Archive Entries", str(counts["media_archive_entries"]))
    summary.add_row("Media Archive Attempts", str(counts["media_archive_attempts"]))
    summary.add_row("Segments", str(counts["transcript_segments"]))
    summary.add_row("Extraction", str(counts["extraction_results"]))
    summary.add_row("Metadata Snapshots", str(counts["metadata_artifacts"]))
    summary.add_row("Identity Evidence", str(counts["identity_evidence"]))
    summary.add_row("Identity Assessments", str(counts["identity_assessments"]))
    summary.add_row("Speaker Profiles", str(counts["speaker_profiles"]))
    summary.add_row("Speaker Observations", str(counts["speaker_observations"]))
    summary.add_row("Speaker Name Claims", str(counts["speaker_name_claims"]))
    summary.add_row("Excluded", str(counts["excluded_videos"]))
    console.print(summary)

    if not sources:
        console.print("No sources queued.")
        return

    table = Table(title="Queued Sources")
    table.add_column("ID", justify="right")
    table.add_column("Organization")
    table.add_column("Target Pastor")
    table.add_column("Type")
    table.add_column("Processing")
    table.add_column("URL")
    for source in sources:
        organization_name = "-"
        if source.organization_id is not None:
            organization_record = database.get_organization_by_id(
                source.organization_id
            )
            organization_name = (
                organization_record.slug
                if organization_record is not None
                else str(source.organization_id)
            )
        pastor_name = "-"
        if source.pastor_id is not None:
            pastor_record = database.get_pastor_by_id(source.pastor_id)
            if pastor_record is not None:
                pastor_name = pastor_record.slug
            else:
                pastor_name = str(source.pastor_id)
        table.add_row(
            str(source.id),
            organization_name,
            pastor_name,
            source.source_type.value,
            "enabled" if source.processing_enabled else "disabled",
            source.url,
        )
    console.print(table)


@app.command(
    "source-processing-report",
    help="Write read-only per-source processing reports as Markdown and JSON.",
)
def source_processing_report(
    database_path: Path | None = typer.Option(
        None,
        "--database",
        help="Explicit application database path; defaults to the configured app database.",
    ),
    markdown_path: Path = typer.Option(
        Path("source_processing_report.md"),
        "--markdown",
        help="Markdown report output path.",
    ),
    json_path: Path = typer.Option(
        Path("source_processing_report.json"),
        "--json",
        help="JSON report output path.",
    ),
    base_dir: Path | None = typer.Option(
        None,
        help="Override app data directory when --database is not supplied.",
    ),
) -> None:
    if database_path is not None and base_dir is not None:
        raise typer.BadParameter("use either --database or --base-dir, not both")
    resolved_database = (
        database_path.expanduser().resolve()
        if database_path is not None
        else build_paths(base_dir).database
    )
    try:
        report = generate_source_processing_report(
            resolved_database,
            markdown_path=markdown_path,
            json_path=json_path,
        )
    except (OSError, RuntimeError, ValueError, sqlite3.Error) as error:
        raise typer.BadParameter(str(error)) from error

    summary = report["summary"]
    console.print(f"Wrote Markdown report to {markdown_path.expanduser().resolve()}")
    console.print(f"Wrote JSON report to {json_path.expanduser().resolve()}")
    console.print(
        f"Reported {summary['total_sources']} source(s) and "
        f"{summary['total_cataloged_videos']} cataloged video(s)."
    )


@source_app.command("list", help="List configured sources.")
def source_list(
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    sources = database.list_sources()

    if not sources:
        console.print("No sources configured.")
        return

    table = Table(title="Sources")
    table.add_column("ID", justify="right")
    table.add_column("Organization")
    table.add_column("Target Pastor")
    table.add_column("Type")
    table.add_column("Processing")
    table.add_column("URL")
    for source in sources:
        organization_name = "-"
        if source.organization_id is not None:
            organization_record = database.get_organization_by_id(
                source.organization_id
            )
            organization_name = (
                organization_record.slug
                if organization_record is not None
                else str(source.organization_id)
            )
        pastor_name = "-"
        if source.pastor_id is not None:
            pastor_record = database.get_pastor_by_id(source.pastor_id)
            pastor_name = pastor_record.slug if pastor_record is not None else str(source.pastor_id)
        table.add_row(
            str(source.id),
            organization_name,
            pastor_name,
            source.source_type.value,
            "enabled" if source.processing_enabled else "disabled",
            source.url,
        )
    console.print(table)


def delete_source_service(
    source_id: int,
    force: bool = False,
    base_dir: Path | None = None,
) -> None:
    database = get_database(base_dir)
    paths = build_paths(base_dir, remember=True)
    source = database.get_source_by_id(source_id)
    if source is None:
        raise ValueError(f"Unknown source id: {source_id}")

    videos = database.list_videos_by_source_id(source_id)
    if videos and not force:
        raise ValueError(
            f"Source #{source_id} has {len(videos)} linked video(s). Use --force to delete them too."
        )

    deleted_videos = _delete_source_tree(database, paths, source_id)
    console.print(
        f"Deleted source #{source_id} ({source.url}); removed {deleted_videos} linked video(s) and artifacts."
    )


@source_app.command("delete", help="Delete a source and optionally all dependent videos and artifacts.")
def source_delete(
    source_id: int = typer.Argument(..., help="Source id to delete."),
    force: bool = typer.Option(False, "--force", help="Delete dependent videos and all related artifacts."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    try:
        delete_source_service(source_id, force, base_dir)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error


@video_app.command("list", help="List discovered videos.")
def video_list(
    pastor: str | None = typer.Option(None, help="Filter by pastor slug."),
    organization: str | None = typer.Option(
        None,
        help="Filter by publishing organization slug.",
    ),
    source_id: int | None = typer.Option(None, help="Filter by source id."),
    status: VideoStatus | None = typer.Option(None, help="Filter by video status."),
    limit: int = typer.Option(50, min=1, help="Maximum number of videos to show."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    videos = database.list_videos()

    if pastor is not None:
        pastor_record = database.get_pastor_by_slug(pastor)
        if pastor_record is None:
            raise _unknown_pastor_error(pastor, base_dir)
        target_video_ids = database.list_video_ids_for_target_pastor(
            pastor_record.id
        )
        videos = [video for video in videos if video.id in target_video_ids]

    if organization is not None:
        organization_record = database.get_organization_by_slug(organization)
        if organization_record is None:
            raise typer.BadParameter(
                f"Unknown organization slug: {organization}"
            )
        source_ids = {
            source.id
            for source in database.list_sources()
            if source.organization_id == organization_record.id
        }
        videos = [video for video in videos if video.source_id in source_ids]

    if source_id is not None:
        videos = [video for video in videos if video.source_id == source_id]

    if status is not None:
        videos = [video for video in videos if video.status == status]

    if not videos:
        console.print("No videos matched.")
        return

    videos = videos[:limit]
    table = Table(title="Videos")
    table.add_column("ID", justify="right")
    table.add_column("Publisher")
    table.add_column("Target Pastor")
    table.add_column("Status")
    table.add_column("Title")
    table.add_column("YouTube ID")

    for video in videos:
        source = database.get_source_by_id(video.source_id)
        publisher_name = "-"
        if source is not None and source.organization_id is not None:
            organization_record = database.get_organization_by_id(
                source.organization_id
            )
            publisher_name = (
                organization_record.slug
                if organization_record is not None
                else str(source.organization_id)
            )
        pastor_name = "-"
        if video.pastor_id is not None:
            pastor_record = database.get_pastor_by_id(video.pastor_id)
            pastor_name = pastor_record.slug if pastor_record is not None else str(video.pastor_id)
        table.add_row(
            str(video.id),
            publisher_name,
            pastor_name,
            video.status.value,
            video.title,
            video.youtube_video_id,
        )

    console.print(table)


@video_app.command("exclude", help="Delete a video's local artifacts and prevent it from being rediscovered.")
def video_exclude(
    video_id: int = typer.Argument(..., help="Video id to exclude."),
    notes: str | None = typer.Option(None, help="Optional exclusion notes."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    paths = build_paths(base_dir)
    video = database.get_video_by_id(video_id)
    if video is None:
        raise typer.BadParameter(f"Unknown video id: {video_id}")

    database.add_excluded_video(
        pastor_id=video.pastor_id,
        source_id=video.source_id,
        youtube_video_id=video.youtube_video_id,
        title=video.title,
        url=video.url,
        notes=notes,
    )
    _delete_video_tree(database, paths, video.id)
    console.print(f"Excluded video #{video_id}: {video.title} ({video.youtube_video_id})")


@video_app.command("unexclude", help="Allow an excluded YouTube video to be rediscovered again.")
def video_unexclude(
    youtube_video_id: str = typer.Argument(..., help="YouTube video id to remove from the exclusion list."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    excluded = database.get_excluded_video_by_youtube_id(youtube_video_id)
    if excluded is None:
        raise typer.BadParameter(f"Unknown excluded video id: {youtube_video_id}")
    database.delete_excluded_video(youtube_video_id)
    console.print(f"Removed exclusion for {youtube_video_id}: {excluded.title}")


@video_app.command("excluded", help="List excluded YouTube videos.")
def video_excluded(
    pastor: str | None = typer.Option(None, help="Filter by pastor slug."),
    limit: int = typer.Option(50, min=1, help="Maximum number of excluded videos to show."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    excluded_videos = database.list_excluded_videos()

    if pastor is not None:
        pastor_record = database.get_pastor_by_slug(pastor)
        if pastor_record is None:
            raise _unknown_pastor_error(pastor, base_dir)
        excluded_videos = [video for video in excluded_videos if video.pastor_id == pastor_record.id]

    if not excluded_videos:
        console.print("No excluded videos matched.")
        return

    table = Table(title="Excluded Videos")
    table.add_column("Pastor")
    table.add_column("Excluded")
    table.add_column("Title")
    table.add_column("YouTube ID")
    for video in excluded_videos[:limit]:
        pastor_name = "-"
        if video.pastor_id is not None:
            pastor_record = database.get_pastor_by_id(video.pastor_id)
            pastor_name = pastor_record.slug if pastor_record is not None else str(video.pastor_id)
        table.add_row(
            pastor_name,
            video.excluded_at.date().isoformat(),
            video.title,
            video.youtube_video_id,
        )
    console.print(table)


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


@pastor_app.command("add", help="Create a pastor profile and folder namespace.")
def pastor_add(
    slug: str = typer.Argument(..., help="Slug for this pastor, used in folder paths."),
    display_name: str = typer.Argument(..., help="Human-readable pastor name."),
    notes: str | None = typer.Option(None, help="Optional notes for this pastor."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    pastor = database.add_pastor(slug=slug, display_name=display_name, notes=notes)
    console.print(f"Added pastor #{pastor.id}: {pastor.slug} -> {pastor.display_name}")


@pastor_app.command("list", help="List configured pastors.")
def pastor_list(
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    pastors = database.list_pastors()

    if not pastors:
        console.print("No pastors configured.")
        return

    table = Table(title="Pastors")
    table.add_column("ID", justify="right")
    table.add_column("Slug")
    table.add_column("Display Name")
    for pastor in pastors:
        table.add_row(str(pastor.id), pastor.slug, pastor.display_name)
    console.print(table)


@pastor_app.command(
    "affiliate",
    help="Record a reviewed or manually grounded organization affiliation.",
)
def pastor_affiliate(
    pastor: str = typer.Argument(..., help="Pastor slug."),
    organization: str = typer.Argument(..., help="Organization slug."),
    role: str = typer.Option("pastor", help="Role held at the organization."),
    started_on: str | None = typer.Option(
        None,
        "--from",
        help="Inclusive start date in YYYY-MM-DD format.",
    ),
    ended_on: str | None = typer.Option(
        None,
        "--to",
        help="Exclusive end date in YYYY-MM-DD format.",
    ),
    temporal_status: str | None = typer.Option(
        None,
        "--status",
        help="Temporal status: current, former, bounded, or unknown.",
    ),
    notes: str | None = typer.Option(None, help="Optional affiliation notes."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    pastor_record = database.get_pastor_by_slug(pastor)
    if pastor_record is None:
        raise _unknown_pastor_error(pastor, base_dir)
    organization_record = database.get_organization_by_slug(organization)
    if organization_record is None:
        raise typer.BadParameter(f"Unknown organization slug: {organization}")
    try:
        start_date = date.fromisoformat(started_on) if started_on is not None else None
        end_date = date.fromisoformat(ended_on) if ended_on is not None else None
    except ValueError as error:
        raise typer.BadParameter("Affiliation dates must use YYYY-MM-DD.") from error
    if start_date is not None and end_date is not None and end_date <= start_date:
        raise typer.BadParameter("--to must be later than --from.")
    inferred_status = (
        "bounded"
        if end_date is not None and start_date is not None
        else "former"
        if end_date is not None
        else "current"
        if start_date is not None
        else "unknown"
    )
    resolved_status = temporal_status or inferred_status
    if resolved_status not in {"current", "former", "bounded", "unknown"}:
        raise typer.BadParameter(
            "--status must be current, former, bounded, or unknown."
        )
    role_label = role.strip()
    if not role_label:
        raise typer.BadParameter("--role cannot be empty.")
    role_key = re.sub(r"[^a-z0-9]+", "_", role_label.lower()).strip("_")
    affiliation = database.add_pastor_organization_affiliation(
        pastor_id=pastor_record.id,
        organization_id=organization_record.id,
        role_key=role_key,
        role_label=role_label,
        started_on=started_on,
        ended_on=ended_on,
        temporal_status=resolved_status,
        provenance_kind="manual",
        notes=notes,
    )
    console.print(
        f"Recorded affiliation #{affiliation.id}: {pastor_record.slug} -> "
        f"{organization_record.slug} ({role_label}, {resolved_status})."
    )


@pastor_app.command(
    "affiliate-claim",
    help="Explicitly attach an imported affiliation claim to a selected pastor.",
)
def pastor_affiliate_claim(
    pastor: str = typer.Argument(..., help="Existing curated pastor slug."),
    claim_id: int = typer.Argument(..., help="Imported affiliation claim id."),
    reviewer: str = typer.Option(..., help="Reviewer name."),
    reason: str = typer.Option(..., help="Grounded reason for the attachment."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    pastor_record = database.get_pastor_by_slug(pastor)
    if pastor_record is None:
        raise _unknown_pastor_error(pastor, base_dir)
    try:
        event_id = database.review_organization_affiliation_claim(
            claim_id=claim_id,
            pastor_id=pastor_record.id,
            attach=True,
            reviewer=reviewer,
            reason=reason,
            review_event_key=(
                f"attach:{claim_id}:{pastor_record.id}:{reviewer}:{reason}"
            ),
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print(
        f"Attached affiliation claim #{claim_id} to pastor "
        f"{pastor_record.slug} with review event #{event_id}."
    )


@app.command(help="Validate local tool paths and app data directories.")
def doctor(
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    paths = build_paths(base_dir, remember=True)
    tools = build_tool_config()
    llm = build_llm_config()
    sermon_minimum = minimum_sermon_duration_seconds()

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
    database = get_database(base_dir)
    app_paths = build_paths(base_dir)
    tool_config = build_tool_config()
    sources = database.list_sources()
    if source_id is not None:
        sources = [source for source in sources if source.id == source_id]
    else:
        sources = [source for source in sources if source.processing_enabled]
    if not sources:
        console.print("No sources queued.")
        return DiscoveryServiceResult({})

    discovered_count = 0
    skipped_count = 0
    excluded_count = 0
    below_minimum_count = 0
    future_count = 0
    found_count = 0
    effective_limit = None if all_videos else limit
    minimum_duration = minimum_sermon_duration_seconds()
    existing_ids = {
        video.youtube_video_id for video in database.list_videos()
    }
    excluded_ids = {
        video.youtube_video_id for video in database.list_excluded_videos()
    }
    total_sources = len(sources)
    selected_video_ids_by_source: dict[int, tuple[int, ...]] = {}
    for index, source in enumerate(sources, start=1):
        pastor_record = (
            database.get_pastor_by_id(source.pastor_id)
            if source.pastor_id is not None
            else None
        )
        organization_record = (
            database.get_organization_by_id(source.organization_id)
            if source.organization_id is not None
            else None
        )
        publisher_label = (
            organization_record.slug
            if organization_record is not None
            else "organization-unknown"
        )
        if pastor_record is not None:
            context_label = (
                f"for pastor {pastor_record.slug} target; "
                f"publisher {publisher_label}"
            )
        else:
            context_label = f"for publisher {publisher_label}"
        console.print(
            f"[{index}/{total_sources}] Discovering source #{source.id} "
            f"{context_label}: {source.url}",
            markup=False,
        )
        try:
            discovered_videos = extract_discovered_videos(
                source.url,
                tool_config.yt_dlp_bin,
                tool_config.yt_dlp_js_runtimes,
            )
        except Exception as error:
            console.print(f"[red]Failed to discover[/red] {source.url}: {error}")
            selected_video_ids_by_source[source.id] = ()
            continue

        discovered_videos = sort_discovered_videos_by_recency(discovered_videos)
        source_found_count = len(discovered_videos)
        short_videos = [
            video
            for video in discovered_videos
            if not duration_meets_sermon_minimum(
                video.duration_seconds,
                minimum_seconds=minimum_duration,
            )
            and publication_is_not_future(video.published_at)
        ]
        future_videos = [
            video
            for video in discovered_videos
            if not publication_is_not_future(video.published_at)
        ]
        discovered_videos = [
            video
            for video in discovered_videos
            if video_is_sermon_eligible(
                video.duration_seconds,
                video.published_at,
                minimum_seconds=minimum_duration,
            )
        ]
        selected_discovered = (
            discovered_videos
            if effective_limit is None
            else discovered_videos[:effective_limit]
        )
        selected_youtube_ids = {
            video.youtube_video_id
            for video in selected_discovered
            if video.youtube_video_id not in excluded_ids
        }
        found_count += source_found_count
        below_minimum_count += len(short_videos)
        future_count += len(future_videos)
        existing_source_videos = database.list_videos_by_source_id(source.id)
        discovered_videos = _discover_candidate_window(
            discovered_videos=discovered_videos,
            existing_source_videos=existing_source_videos,
            effective_limit=effective_limit,
        )

        source_discovered_count = 0
        source_skipped_count = 0
        source_excluded_count = 0
        for discovered in discovered_videos:
            if discovered.youtube_video_id in excluded_ids:
                excluded_count += 1
                source_excluded_count += 1
                continue
            if discovered.youtube_video_id in existing_ids:
                skipped_count += 1
                source_skipped_count += 1
                continue
            video = database.add_video(
                source_id=source.id,
                pastor_id=source.pastor_id,
                youtube_video_id=discovered.youtube_video_id,
                title=discovered.title,
                url=discovered.url,
                channel_name=discovered.channel_name,
                published_at=discovered.published_at,
                duration_seconds=discovered.duration_seconds,
                status=VideoStatus.DISCOVERED,
            )
            persist_metadata_snapshot(
                database,
                app_paths,
                video=video,
                pastor=pastor_record,
                source_kind="yt_dlp_flat_playlist",
                raw_metadata=discovered.metadata,
            )
            discovered_count += 1
            source_discovered_count += 1
            existing_ids.add(discovered.youtube_video_id)
        source_summary = (
            f"[{index}/{total_sources}] Finished source #{source.id}: found {source_found_count}, "
            f"queued {source_discovered_count}, skipped {source_skipped_count}"
        )
        if short_videos:
            source_summary += f", below minimum {len(short_videos)}"
        if future_videos:
            source_summary += f", future {len(future_videos)}"
        if source_excluded_count:
            source_summary += f", excluded {source_excluded_count}"
        console.print(f"{source_summary}.", markup=False)
        selected_video_ids_by_source[source.id] = tuple(
            video.id
            for video in database.list_videos_by_source_id(source.id)
            if video.youtube_video_id in selected_youtube_ids
        )

    if effective_limit is not None:
        summary = (
            f"Found {found_count} video(s); queued {discovered_count} new video(s) after limit {effective_limit}; "
            f"skipped {skipped_count} duplicate(s)."
        )
    else:
        summary = f"Found {found_count} video(s); queued {discovered_count} new video(s); skipped {skipped_count} duplicate(s)."
    if excluded_count:
        summary = f"{summary[:-1]}; excluded {excluded_count} video(s)."
    if below_minimum_count:
        summary = (
            f"{summary[:-1]}; bypassed {below_minimum_count} video(s) below the "
            f"configured {minimum_duration:g}-second sermon minimum."
        )
    if future_count:
        summary = f"{summary[:-1]}; bypassed {future_count} future event(s)."
    console.print(summary)
    return DiscoveryServiceResult(selected_video_ids_by_source)


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
) -> None:
    database = get_database(base_dir)
    paths = build_paths(base_dir, remember=True)
    tools = build_tool_config()
    videos = database.list_videos()
    if source_id is not None:
        videos = [video for video in videos if video.source_id == source_id]
    if video_ids is not None:
        videos = [video for video in videos if video.id in video_ids]
    if not videos:
        console.print("No videos queued.")
        return

    minimum_duration = minimum_sermon_duration_seconds()
    future_events = sum(
        1 for video in videos if not publication_is_not_future(video.published_at)
    )
    below_minimum = sum(
        1
        for video in videos
        if not video_is_sermon_eligible(
            video.duration_seconds,
            video.published_at,
            minimum_seconds=minimum_duration,
        )
        and publication_is_not_future(video.published_at)
    )
    if below_minimum:
        console.print(
            f"Bypassing {below_minimum} video(s) below the configured "
            f"{minimum_duration:g}-second sermon minimum."
        )
    if future_events:
        console.print(f"Bypassing {future_events} future event(s).")
    videos = [
        video
        for video in videos
        if video_is_sermon_eligible(
            video.duration_seconds,
            video.published_at,
            minimum_seconds=minimum_duration,
        )
    ]
    _recover_stale_transcribing_videos(database, videos)
    videos = [database.get_video_by_id(video.id) or video for video in videos]

    processed = 0
    skipped = below_minimum + future_events
    failed = 0
    claimed_videos = []
    for video in videos:
        if not _should_transcribe_video(
            database,
            video.id,
            missing_only=missing_only,
            captions_missing_only=captions_missing_only,
        ):
            skipped += 1
            continue
        if not _claim_video_for_transcription(database, video.id):
            skipped += 1
            continue
        claimed_videos.append(video)

    if not claimed_videos:
        console.print(f"Transcribed {processed} video(s); skipped {skipped}; failed {failed}.")
        return

    max_workers = min(jobs, len(claimed_videos))
    total_claimed = len(claimed_videos)
    console.print(f"Transcribing {total_claimed} video(s) with {max_workers} worker(s).")
    prep_workers = min(prep_jobs, total_claimed)
    if console.is_terminal:
        progress_lock = Lock()
        progress = Progress(
            TextColumn("{task.fields[status]:>7}", justify="right"),
            TextColumn("video #{task.fields[video_id]}"),
            TextColumn("{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            console=console,
            transient=False,
        )
        task_ids: dict[int, TaskID] = {}
        prep_future_to_video: dict[Future[PreparedTranscriptInput], object] = {}
        transcribe_future_to_video: dict[Future[None], object] = {}
        pending_videos = iter(claimed_videos)

        def submit_prep(executor: ThreadPoolExecutor) -> bool:
            video = next(pending_videos, None)
            if video is None:
                return False
            prep_future = executor.submit(
                _prepare_transcription_task,
                database,
                paths,
                tools,
                video.id,
                _build_live_transcription_stage_callback(progress, task_ids[video.id], progress_lock),
                allow_network,
            )
            prep_future_to_video[prep_future] = video
            return True

        with progress, ThreadPoolExecutor(max_workers=prep_workers) as prep_executor, ThreadPoolExecutor(
            max_workers=max_workers
        ) as transcribe_executor:
            for video in claimed_videos:
                task_ids[video.id] = progress.add_task(
                    video.title,
                    total=100,
                    completed=0,
                    status=STAGE_QUEUED_PREP,
                    video_id=video.id,
                    start=False,
                )
            for _ in range(prep_workers):
                if not submit_prep(prep_executor):
                    break

            while prep_future_to_video or transcribe_future_to_video:
                if prep_future_to_video:
                    prep_done, _ = wait(set(prep_future_to_video), timeout=0.05, return_when=FIRST_COMPLETED)
                    for future in prep_done:
                        video = prep_future_to_video.pop(future)
                        try:
                            prepared = future.result()
                        except Exception as error:
                            database.update_video_status(video.id, VideoStatus.FAILED, str(error))
                            failed += 1
                            with progress_lock:
                                progress.update(task_ids[video.id], status="failed", completed=100)
                            console.print(
                                f"[{processed + failed}/{total_claimed} finished] Failed to transcribe video #{video.id}: {error}",
                                style="red",
                                markup=False,
                            )
                        else:
                            with progress_lock:
                                progress.update(task_ids[video.id], status=STAGE_QUEUED_TRANSCRIBE)
                            transcribe_future = transcribe_executor.submit(
                                _complete_transcription_task,
                                database,
                                tools,
                                prepared,
                                _build_live_transcription_progress_callback(progress, task_ids[video.id], progress_lock),
                                _build_live_transcription_stage_callback(progress, task_ids[video.id], progress_lock),
                            )
                            transcribe_future_to_video[transcribe_future] = video
                        submit_prep(prep_executor)
                if transcribe_future_to_video:
                    transcribe_done, _ = wait(set(transcribe_future_to_video), timeout=0.05, return_when=FIRST_COMPLETED)
                    for future in transcribe_done:
                        video = transcribe_future_to_video.pop(future)
                        task_id = task_ids[video.id]
                        try:
                            future.result()
                        except Exception as error:
                            database.update_video_status(video.id, VideoStatus.FAILED, str(error))
                            failed += 1
                            with progress_lock:
                                progress.update(task_id, status=STAGE_FAILED, completed=100)
                            console.print(
                                f"[{processed + failed}/{total_claimed} finished] Failed to transcribe video #{video.id}: {error}",
                                style="red",
                                markup=False,
                            )
                            continue
                        processed += 1
                        with progress_lock:
                            progress.update(task_id, status=STAGE_DONE, completed=100)
                        console.print(f"[{processed + failed}/{total_claimed} finished] Transcribed video #{video.id}", markup=False)
    else:
        prep_future_to_video: dict[Future[PreparedTranscriptInput], object] = {}
        transcribe_future_to_video: dict[Future[None], object] = {}
        pending_videos = iter(claimed_videos)
        for index, video in enumerate(claimed_videos, start=1):
            console.print(f"[{index}/{total_claimed} queued] Transcribing video #{video.id}: {video.title}", markup=False)

        def submit_prep(executor: ThreadPoolExecutor) -> bool:
            video = next(pending_videos, None)
            if video is None:
                return False
            prep_future = executor.submit(
                _prepare_transcription_task,
                database,
                paths,
                tools,
                video.id,
                _build_transcription_stage_callback(video.id),
                allow_network,
            )
            prep_future_to_video[prep_future] = video
            return True

        with ThreadPoolExecutor(max_workers=prep_workers) as prep_executor, ThreadPoolExecutor(max_workers=max_workers) as transcribe_executor:
            for _ in range(prep_workers):
                if not submit_prep(prep_executor):
                    break

            while prep_future_to_video or transcribe_future_to_video:
                if prep_future_to_video:
                    prep_done, _ = wait(set(prep_future_to_video), timeout=0.05, return_when=FIRST_COMPLETED)
                    for future in prep_done:
                        video = prep_future_to_video.pop(future)
                        try:
                            prepared = future.result()
                        except Exception as error:
                            database.update_video_status(video.id, VideoStatus.FAILED, str(error))
                            failed += 1
                            console.print(
                                f"[{processed + failed}/{total_claimed} finished] Failed to transcribe video #{video.id}: {error}",
                                style="red",
                                markup=False,
                            )
                        else:
                            _build_transcription_stage_callback(video.id)(STAGE_QUEUED_TRANSCRIBE)
                            transcribe_future = transcribe_executor.submit(
                                _complete_transcription_task,
                                database,
                                tools,
                                prepared,
                                _build_transcription_progress_callback(video.id),
                                _build_transcription_stage_callback(video.id),
                            )
                            transcribe_future_to_video[transcribe_future] = video
                        submit_prep(prep_executor)
                if transcribe_future_to_video:
                    transcribe_done, _ = wait(set(transcribe_future_to_video), timeout=0.05, return_when=FIRST_COMPLETED)
                    for future in transcribe_done:
                        video = transcribe_future_to_video.pop(future)
                        try:
                            future.result()
                        except Exception as error:
                            database.update_video_status(video.id, VideoStatus.FAILED, str(error))
                            failed += 1
                            console.print(
                                f"[{processed + failed}/{total_claimed} finished] Failed to transcribe video #{video.id}: {error}",
                                style="red",
                                markup=False,
                            )
                            continue
                        processed += 1
                        console.print(f"[{processed + failed}/{total_claimed} finished] Transcribed video #{video.id}", markup=False)

    console.print(f"Transcribed {processed} video(s); skipped {skipped}; failed {failed}.")


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
) -> None:
    database = get_database(base_dir)
    paths = build_paths(base_dir, remember=True)
    tools = build_tool_config()
    videos = database.list_videos()
    if source_id is not None:
        videos = [video for video in videos if video.source_id == source_id]
    if video_ids is not None:
        videos = [video for video in videos if video.id in video_ids]
    if not videos:
        console.print("No videos queued.")
        return

    minimum_duration = minimum_sermon_duration_seconds()
    future_events = sum(
        1 for video in videos if not publication_is_not_future(video.published_at)
    )
    below_minimum = sum(
        1
        for video in videos
        if not video_is_sermon_eligible(
            video.duration_seconds,
            video.published_at,
            minimum_seconds=minimum_duration,
        )
        and publication_is_not_future(video.published_at)
    )
    if below_minimum:
        console.print(
            f"Bypassing {below_minimum} video(s) below the configured "
            f"{minimum_duration:g}-second sermon minimum."
        )
    if future_events:
        console.print(f"Bypassing {future_events} future event(s).")

    processed = 0
    skipped = below_minimum + future_events
    unavailable = 0
    deferred = 0
    failed = 0
    last_request_started: float | None = None

    def fetch_with_rate_limit_retry(video):
        nonlocal last_request_started
        for attempt in range(len(CAPTION_RATE_LIMIT_BACKOFF_SECONDS) + 1):
            if last_request_started is not None and request_interval_seconds > 0:
                elapsed = time.monotonic() - last_request_started
                remaining = request_interval_seconds - elapsed
                if remaining > 0:
                    time.sleep(remaining)
            last_request_started = time.monotonic()
            try:
                return fetch_captions_video(database, paths, tools, video.id)
            except YtDlpRateLimitError:
                if attempt >= len(CAPTION_RATE_LIMIT_BACKOFF_SECONDS):
                    raise
                backoff = CAPTION_RATE_LIMIT_BACKOFF_SECONDS[attempt]
                console.print(
                    f"Caption request rate limited for video #{video.id}; "
                    f"retrying in {backoff:g}s."
                )
                time.sleep(backoff)
        raise AssertionError("unreachable caption retry state")

    for video in videos:
        if not video_is_sermon_eligible(
            video.duration_seconds,
            video.published_at,
            minimum_seconds=minimum_duration,
        ):
            continue
        transcript_artifacts = database.list_transcript_artifacts_for_video(video.id)
        if any(artifact.source_kind == TranscriptSourceKind.CAPTIONS for artifact in transcript_artifacts):
            skipped += 1
            continue

        try:
            console.print(f"Fetching captions for video #{video.id}: {video.title}")
            result = fetch_with_rate_limit_retry(video)
        except NoCaptionsAvailableError:
            if _is_terminal_unavailable(video.status, video.failure_reason) or _is_retryable_fetch_failure(
                video.status, video.failure_reason
            ):
                database.update_video_status(video.id, VideoStatus.DISCOVERED)
            console.print(f"No captions for video #{video.id}; leaving it for local transcription.")
            unavailable += 1
            continue
        except VideoNotYetAvailableError as error:
            database.update_video_status(video.id, VideoStatus.FAILED, str(error))
            console.print(f"Video #{video.id} has not started yet; deferring it.")
            deferred += 1
            continue
        except YtDlpConfigurationError as error:
            database.update_video_status(video.id, VideoStatus.FAILED, str(error))
            console.print(f"[red]yt-dlp configuration error[/red] for video #{video.id}: {error}")
            failed += 1
            continue
        except YtDlpRateLimitError as error:
            raise ValueError(
                "YouTube repeatedly rate limited caption acquisition after retries. "
                "Wait for the limit to clear and rerun the same command; captions "
                "already persisted will be skipped."
            ) from error
        except VideoUnavailableError as error:
            database.update_video_status(video.id, VideoStatus.FAILED, str(error))
            console.print(f"Video unavailable for video #{video.id}; skipping it.")
            failed += 1
            continue
        except Exception as error:
            database.update_video_status(video.id, VideoStatus.FAILED, str(error))
            console.print(f"[red]Failed to fetch captions[/red] video #{video.id}: {error}")
            failed += 1
            continue
        console.print(f"Fetched captions for video #{video.id}: {result.raw_text_path}")
        processed += 1

    console.print(
        f"Fetched captions for {processed} video(s); skipped {skipped}; unavailable {unavailable}; "
        f"deferred {deferred}; failed {failed}."
    )


@app.command(help="Fetch YouTube captions when available and persist them as transcript artifacts.")
def fetch(
    source_id: int | None = typer.Option(None, help="Only fetch captions for videos from a specific source id."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    try:
        fetch_captions_service(source_id, base_dir)
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
    jobs: int = typer.Option(1, "--jobs", min=1, help="Concurrent video extraction jobs."),
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
    jobs: int = typer.Option(1, "--jobs", min=1, help="Concurrent video classification jobs."),
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
            all_videos,
        )
    )
    if selector_count != 1:
        raise typer.BadParameter(
            "Pass exactly one of --video-id, --source-id, --fixture-dir, or --all."
        )
    database = get_database(base_dir)
    paths = build_paths(base_dir, remember=True)
    if video_id is not None:
        video = database.get_video_by_id(video_id)
        videos = [video] if video is not None else []
    elif source_id is not None:
        videos = database.list_videos_by_source_id(source_id)
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
    for video in videos:
        if not video_is_sermon_eligible(
            video.duration_seconds,
            video.published_at,
            minimum_seconds=minimum_duration,
        ):
            skipped += 1
            if all_videos:
                console.print(
                    f"Skipping video #{video.id}: video is below the configured "
                    "sermon minimum or is a future event."
                )
            continue
        extraction = database.get_latest_extraction_result_for_video(video.id)
        if extraction is None:
            skipped += 1
            if all_videos:
                console.print(
                    f"Skipping video #{video.id}: no reusable extraction segments."
                )
            continue
        if all_videos and not _has_reusable_extraction_segments(extraction):
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
    resume_stage: Path | None = None,
    acquire_captions: bool = False,
    download_jobs: int = DEFAULT_PREP_WORKERS,
) -> None:
    selected_source_ids = tuple(dict.fromkeys(source_ids or ()))
    if stage_audio_only and resume_stage is not None:
        raise ValueError("Use either --stage-audio-only or --resume-stage, not both.")
    if acquire_captions and resume_stage is None:
        raise ValueError("--acquire-captions is only valid with --resume-stage.")
    if resume_stage is not None:
        if url is not None or pastor is not None or all_sources or selected_source_ids or failed_only:
            raise ValueError("--resume-stage supplies the exact video scope; do not pass another scope.")
        if replace_existing:
            raise ValueError("--replace-existing is not valid with --resume-stage.")
        database = get_database(base_dir)
        paths = build_paths(base_dir, remember=True)
        console.print(
            "Resume checkpoint: verifying every checksum-pinned staged source artifact."
        )
        with Progress(
            TextColumn("{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            verification_task = progress.add_task(
                "Reading audio-stage manifest", total=None
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
                resume_stage,
                progress_callback=report_stage_verification,
            )
            progress.update(
                verification_task,
                total=len(video_ids),
                completed=len(video_ids),
                description=f"Verified {len(video_ids)} staged source artifact(s)",
            )
        console.print(
            f"Resuming {len(video_ids)} video(s) from verified audio stage {resume_stage}."
        )
        if acquire_captions:
            console.print(
                "Resume checkpoint: reconciling requested online captions; "
                "persisted caption artifacts will be skipped."
            )
            fetch_captions_service(
                base_dir=base_dir,
                video_ids=video_ids,
                request_interval_seconds=CAPTION_BATCH_REQUEST_INTERVAL_SECONDS,
            )
        else:
            console.print(
                "Resume checkpoint: skipping caption acquisition; persisted captions "
                "remain available and caption misses will use staged audio."
            )
        if not captions_only:
            console.print(
                "Resume checkpoint: reconciling local transcripts; completed transcript "
                "artifacts will be skipped."
            )
            transcribe_videos_service(
                missing_only=False,
                captions_missing_only=transcribe_missing,
                jobs=jobs,
                base_dir=base_dir,
                video_ids=video_ids,
                allow_network=False,
            )
        else:
            console.print("Resume checkpoint: local transcription disabled by --captions-only.")
        console.print(
            "Resume checkpoint: reconciling sermon extraction; completed extraction "
            "artifacts will be skipped."
        )
        extraction = extract_batch(
            database,
            paths,
            video_ids=video_ids,
            classifier=classifier,
            llm_model=llm_model,
            workers=jobs,
            event_callback=lambda message: console.print(message, markup=False),
            progress_callback=lambda stage, current, total: console.print(
                f"  {stage} block {current}/{total}"
            ),
        )
        console.print(
            f"Extracted {extraction.processed} video(s); skipped {extraction.skipped}; "
            f"failed {extraction.failed}."
        )
        console.print(
            "Resume checkpoint: ensuring normalized audio and archiving eligible "
            "source artifacts."
        )
        _ensure_and_archive_run_media(
            database, paths, video_ids=video_ids, allow_download=False
        )
        if not skip_review:
            console.print("Resume checkpoint: refreshing review exports.")
            pastor_slugs = {
                record.slug
                for video_id in video_ids
                for video in [database.get_video_by_id(video_id)]
                if video is not None and video.pastor_id is not None
                for record in [database.get_pastor_by_id(video.pastor_id)]
                if record is not None
            }
            for pastor_slug in sorted(pastor_slugs):
                _print_review_batch(
                    prepare_review_exports(
                        database,
                        paths,
                        pastor_slug=pastor_slug,
                        classifier=classifier,
                        llm_model=llm_model,
                        event_callback=lambda message: console.print(message, markup=False),
                    )
                )
        else:
            console.print("Resume checkpoint: review export skipped by --skip-review.")
        if run_identity:
            console.print("Resume checkpoint: starting the requested identity workflow.")
            _run_post_content_identity(base_dir)
        else:
            console.print("Resume complete; identity was not requested.")
        return

    if stage_audio_only:
        if failed_only:
            raise ValueError("--stage-audio-only requires a source scope, not --failed-only.")
        if captions_only:
            raise ValueError("--captions-only is not meaningful with --stage-audio-only.")
        if run_identity:
            raise ValueError("--identity runs during --resume-stage, not audio staging.")
        database = get_database(base_dir)
        if selected_source_ids:
            if url is not None or pastor is not None or all_sources:
                raise ValueError("Use only one source scope with --stage-audio-only.")
            unknown = [value for value in selected_source_ids if database.get_source_by_id(value) is None]
            if unknown:
                raise ValueError("Unknown source id(s): " + ", ".join(map(str, unknown)))
            selected_video_ids: set[int] = set()
            for source_id in selected_source_ids:
                discovery = discover_sources_service(
                    limit, all_videos, source_id, base_dir
                )
                selected_video_ids.update(
                    _selected_discovery_video_ids(discovery, (source_id,))
                )
        elif all_sources:
            if url is not None or pastor is not None:
                raise ValueError("Do not pass a URL or pastor when using --all.")
            enabled_source_ids = {
                source.id for source in database.list_processing_enabled_sources()
            }
            if not enabled_source_ids:
                console.print("No processing-enabled sources configured.")
                return
            discovery = discover_sources_service(limit, all_videos, None, base_dir)
            selected_video_ids = _selected_discovery_video_ids(
                discovery, tuple(enabled_source_ids)
            )
        else:
            if url is None or pastor is None:
                raise ValueError("Audio staging requires URL plus --pastor, --source-id, or --all.")
            if replace_existing:
                existing_source = database.get_source_by_url(url)
                if existing_source is not None:
                    delete_source_service(existing_source.id, True, base_dir)
                    database = get_database(base_dir)
            add_source_service(url, pastor, None, base_dir)
            source = database.get_source_by_url(url)
            if source is None:
                raise RuntimeError("Added source could not be reloaded.")
            discovery = discover_sources_service(limit, all_videos, source.id, base_dir)
            selected_video_ids = _selected_discovery_video_ids(
                discovery, (source.id,)
            )
        if not selected_video_ids:
            console.print("No videos selected for audio staging.")
            return
        paths = build_paths(base_dir, remember=True)
        tools = build_tool_config()
        workers = min(download_jobs, len(selected_video_ids))
        console.print(f"Staging source audio for {len(selected_video_ids)} video(s) with {workers} worker(s).")
        results = []
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    stage_source_audio_for_video,
                    database,
                    paths,
                    tools,
                    video_id=video_id,
                ): video_id
                for video_id in selected_video_ids
            }
            for index, future in enumerate(as_completed(futures), start=1):
                result = future.result()
                results.append(result)
                console.print(
                    f"Audio stage [{index}/{len(futures)}] {result.youtube_video_id}: "
                    f"{result.outcome} ({result.reason_code})"
                )
        manifest = write_audio_stage_manifest(paths.logs, results)
        verified = sum(result.outcome == "verified" for result in results)
        verified_video_ids = {
            result.video_id for result in results if result.outcome == "verified"
        }
        if verified_video_ids:
            console.print(
                f"Fetching available captions for {len(verified_video_ids)} "
                "verified staged video(s)."
            )
            fetch_captions_service(
                base_dir=base_dir,
                video_ids=verified_video_ids,
                request_interval_seconds=CAPTION_BATCH_REQUEST_INTERVAL_SECONDS,
            )
        console.print(f"Audio stage complete: verified={verified}, failed={len(results) - verified}.")
        console.print(f"Manifest: {manifest}")
        console.print(
            "Offline resume: pte run "
            f"--resume-stage {shlex.quote(str(manifest))} --jobs {jobs} "
            f"--base-dir {shlex.quote(str(paths.root))}"
        )
        return
    if failed_only:
        if url is not None:
            raise ValueError("Do not pass a URL when using --failed-only.")
        if pastor is not None:
            raise ValueError("Do not pass --pastor when using --failed-only.")
        if all_sources:
            raise ValueError("Use either --all or --failed-only, not both.")
        if selected_source_ids:
            raise ValueError("Use either --source-id or --failed-only, not both.")
        if replace_existing:
            raise ValueError("--replace-existing is not valid with --failed-only.")
        database = get_database(base_dir)
        paths = build_paths(base_dir, remember=True)
        failed_videos = [video for video in database.list_videos() if video.status is VideoStatus.FAILED]
        failed_video_ids = {video.id for video in failed_videos}
        if not failed_video_ids:
            console.print("No failed videos to reprocess.")
            return

        console.print(f"Reprocessing {len(failed_video_ids)} failed video(s) systemwide.")
        fetch_captions_service(base_dir=base_dir, video_ids=failed_video_ids)
        if not captions_only:
            transcribe_videos_service(
                missing_only=True,
                captions_missing_only=transcribe_missing,
                jobs=jobs,
                base_dir=base_dir,
                video_ids=failed_video_ids,
            )
        extraction = extract_batch(
            database,
            paths,
            missing_only=True,
            video_ids=failed_video_ids,
            classifier=classifier,
            llm_model=llm_model,
            workers=jobs,
            event_callback=lambda message: console.print(message, markup=False),
            progress_callback=lambda stage, current, total: console.print(
                f"  {stage} block {current}/{total}"
            ),
        )
        console.print(
            f"Extracted {extraction.processed} video(s); "
            f"skipped {extraction.skipped}; failed {extraction.failed}."
        )
        _ensure_and_archive_run_media(
            database,
            paths,
            video_ids=failed_video_ids,
        )
        if not skip_review:
            pastor_slugs = {
                pastor_record.slug
                for video in failed_videos
                if video.pastor_id is not None
                for pastor_record in [database.get_pastor_by_id(video.pastor_id)]
                if pastor_record is not None
            }
            for pastor_slug in sorted(pastor_slugs):
                reviews = prepare_review_exports(
                    database,
                    paths,
                    pastor_slug=pastor_slug,
                    classifier=classifier,
                    llm_model=llm_model,
                    event_callback=lambda message: console.print(message, markup=False),
                )
                _print_review_batch(reviews)
        if run_identity:
            _run_post_content_identity(base_dir)
        return

    if selected_source_ids:
        if url is not None:
            raise ValueError("Do not pass a URL when using --source-id.")
        if pastor is not None:
            raise ValueError("Do not pass --pastor when using --source-id.")
        if all_sources:
            raise ValueError("Use either --all or --source-id, not both.")
        if replace_existing:
            raise ValueError("--replace-existing is only valid for URL runs.")
        database = get_database(base_dir)
        unknown_source_ids = [
            source_id
            for source_id in selected_source_ids
            if database.get_source_by_id(source_id) is None
        ]
        if unknown_source_ids:
            rendered = ", ".join(str(source_id) for source_id in unknown_source_ids)
            raise ValueError(f"Unknown source id(s): {rendered}")

        console.print(
            f"Running {len(selected_source_ids)} selected source(s): "
            f"{', '.join(str(source_id) for source_id in selected_source_ids)}."
        )
        selected_video_ids: set[int] = set()
        for source_id in selected_source_ids:
            discovery = discover_sources_service(
                limit=limit,
                all_videos=all_videos,
                source_id=source_id,
                base_dir=base_dir,
            )
            selected_video_ids.update(
                _selected_discovery_video_ids(discovery, (source_id,))
            )
        fetch_captions_service(
            base_dir=base_dir,
            video_ids=selected_video_ids,
        )
        if not captions_only:
            transcribe_videos_service(
                missing_only=False,
                captions_missing_only=transcribe_missing,
                jobs=jobs,
                base_dir=base_dir,
                video_ids=selected_video_ids,
            )
        paths = build_paths(base_dir, remember=True)
        extraction = extract_batch(
            database,
            paths,
            video_ids=selected_video_ids,
            classifier=classifier,
            llm_model=llm_model,
            event_callback=lambda message: console.print(message, markup=False),
            progress_callback=lambda stage, current, total: console.print(
                f"  {stage} block {current}/{total}"
            ),
        )
        console.print(
            f"Extracted {extraction.processed} video(s); "
            f"skipped {extraction.skipped}; failed {extraction.failed}."
        )
        _ensure_and_archive_run_media(
            database,
            paths,
            video_ids=selected_video_ids,
        )
        if not skip_review:
            pastor_slugs = {
                pastor_record.slug
                for video_id in selected_video_ids
                for video in [database.get_video_by_id(video_id)]
                if video is not None and video.pastor_id is not None
                for pastor_record in [database.get_pastor_by_id(video.pastor_id)]
                if pastor_record is not None
            }
            for pastor_slug in sorted(pastor_slugs):
                reviews = prepare_review_exports(
                    database,
                    paths,
                    pastor_slug=pastor_slug,
                    classifier=classifier,
                    llm_model=llm_model,
                    event_callback=lambda message: console.print(
                        message, markup=False
                    ),
                )
                _print_review_batch(reviews)
        if run_identity:
            _run_post_content_identity(base_dir)
        return

    if all_sources:
        if url is not None:
            raise ValueError("Do not pass a URL when using --all. Run either a global sync or a single-source workflow.")
        if pastor is not None:
            raise ValueError("Do not pass --pastor when using --all.")
        if replace_existing:
            raise ValueError("--replace-existing is only valid for single-source runs.")
        database = get_database(base_dir)
        enabled_sources = database.list_processing_enabled_sources()
        if not enabled_sources:
            console.print("No processing-enabled sources configured.")
            return
        enabled_source_ids = {source.id for source in enabled_sources}
        disabled_count = len(database.list_sources()) - len(enabled_sources)
        console.print(
            f"Running all {len(enabled_sources)} processing-enabled source(s); "
            f"skipping {disabled_count} disabled source(s)."
        )
        discovery = discover_sources_service(
            limit=limit,
            all_videos=all_videos,
            source_id=None,
            base_dir=base_dir,
        )
        selected_video_ids = _selected_discovery_video_ids(
            discovery, tuple(enabled_source_ids)
        )
        fetch_captions_service(base_dir=base_dir, video_ids=selected_video_ids)
        if not captions_only and transcribe_missing:
            transcribe_videos_service(
                missing_only=False,
                captions_missing_only=True,
                jobs=jobs,
                base_dir=base_dir,
                video_ids=selected_video_ids,
            )
        elif not captions_only:
            transcribe_videos_service(
                missing_only=False,
                captions_missing_only=False,
                jobs=jobs,
                base_dir=base_dir,
                video_ids=selected_video_ids,
            )
        paths = build_paths(base_dir, remember=True)
        extraction = extract_batch(
            database,
            paths,
            video_ids=selected_video_ids,
            classifier=classifier,
            llm_model=llm_model,
            event_callback=lambda message: console.print(message, markup=False),
            progress_callback=lambda stage, current, total: console.print(f"  {stage} block {current}/{total}"),
        )
        console.print(f"Extracted {extraction.processed} video(s); skipped {extraction.skipped}; failed {extraction.failed}.")
        _ensure_and_archive_run_media(database, paths, video_ids=selected_video_ids)
        if not skip_review:
            pastor_slugs = {
                pastor_record.slug
                for video_id in selected_video_ids
                for video in [database.get_video_by_id(video_id)]
                if video is not None and video.pastor_id is not None
                for pastor_record in [database.get_pastor_by_id(video.pastor_id)]
                if pastor_record is not None
            }
            for pastor_slug in sorted(pastor_slugs):
                reviews = prepare_review_exports(
                    database,
                    paths,
                    pastor_slug=pastor_slug,
                    video_ids=selected_video_ids,
                    classifier=classifier,
                    llm_model=llm_model,
                    event_callback=lambda message: console.print(
                        message, markup=False
                    ),
                )
                _print_review_batch(reviews)
        if run_identity:
            _run_post_content_identity(base_dir)
        return

    if url is None:
        raise ValueError(
            "A URL is required unless you use --all, --source-id, or --failed-only."
        )
    if pastor is None:
        raise ValueError("--pastor is required unless you use --all.")

    database = get_database(base_dir)
    if replace_existing:
        existing_source = database.get_source_by_url(url)
        if existing_source is not None:
            delete_source_service(source_id=existing_source.id, force=True, base_dir=base_dir)
            database = get_database(base_dir)
    add_source_service(url=url, pastor=pastor, notes=None, base_dir=base_dir)
    source = database.get_source_by_url(url)
    source_id = source.id if source is not None else None
    discovery = discover_sources_service(
        limit=limit,
        all_videos=all_videos,
        source_id=source_id,
        base_dir=base_dir,
    )
    selected_video_ids = _selected_discovery_video_ids(
        discovery,
        (source_id,) if source_id is not None else (),
    )
    fetch_captions_service(
        source_id=source_id,
        base_dir=base_dir,
        video_ids=selected_video_ids,
    )
    if not captions_only and transcribe_missing:
        transcribe_videos_service(missing_only=False, captions_missing_only=True, jobs=jobs, source_id=source_id, base_dir=base_dir, video_ids=selected_video_ids)
    elif not captions_only:
        transcribe_videos_service(missing_only=False, captions_missing_only=False, jobs=jobs, source_id=source_id, base_dir=base_dir, video_ids=selected_video_ids)
    paths = build_paths(base_dir, remember=True)
    extraction = extract_batch(
        database,
        paths,
        source_id=source_id,
        video_ids=selected_video_ids,
        classifier=classifier,
        llm_model=llm_model,
        event_callback=lambda message: console.print(message, markup=False),
        progress_callback=lambda stage, current, total: console.print(f"  {stage} block {current}/{total}"),
    )
    console.print(f"Extracted {extraction.processed} video(s); skipped {extraction.skipped}; failed {extraction.failed}.")
    _ensure_and_archive_run_media(
        database,
        paths,
        video_ids=selected_video_ids,
    )
    if not skip_review:
        reviews = prepare_review_exports(
            database,
            paths,
            pastor_slug=pastor,
            classifier=classifier,
            llm_model=llm_model,
            event_callback=lambda message: console.print(message, markup=False),
        )
        _print_review_batch(reviews)
    if run_identity:
        _run_post_content_identity(base_dir)


def _run_post_content_identity(base_dir: Path | None) -> None:
    console.print(
        "Run identity stage: refreshing reviewed evidence, profile "
        "associations, anonymous discovery, and coordination."
    )
    run_identity_workflow_service(
        youtube_video_id=None,
        all_extractions=True,
        plan_only=False,
        skip_discovery=False,
        apply_automatic=False,
        apply_confirmations=False,
        apply_promotions=False,
        base_dir=base_dir,
    )


def _ensure_and_archive_run_media(
    database: Database,
    paths: AppPaths,
    *,
    video_ids: set[int] | None = None,
    allow_download: bool = True,
) -> None:
    videos = [
        video
        for video in database.list_videos()
        if video_ids is None or video.id in video_ids
    ]
    eligible = [
        video
        for video in videos
        if video_has_isolated_sermon(database, video.id)[0]
        and get_verified_normalized_media_artifact(database, video.id) is None
    ]
    tools = build_tool_config() if eligible else None
    counts = {"verified": 0, "unavailable": 0, "failed": 0, "skipped": 0}
    downloaded = 0
    for index, video in enumerate(eligible, start=1):
        assert tools is not None
        result = ensure_audio_for_video(
            database,
            paths,
            tools,
            video_id=video.id,
            allow_download=allow_download,
        )
        counts[result.outcome] += 1
        downloaded += int(result.downloaded)
        console.print(
            f"Run audio [{index}/{len(eligible)}] {video.youtube_video_id}: "
            f"{result.outcome} ({result.reason_code})"
        )
    console.print(
        "Run audio ensure complete: "
        f"eligible={len(eligible)}, verified={counts['verified']} "
        f"(downloaded={downloaded}), unavailable={counts['unavailable']}, "
        f"failed={counts['failed']}, skipped={counts['skipped']}."
    )

    if database.get_active_media_archive_destination() is None:
        console.print("Run media archive skipped: no archive destination is configured.")
        return

    def report_preflight(event: ArchivePreflightEvent) -> None:
        console.print(
            f"Run archive preflight {event.check}: {event.status} — {event.detail}",
            markup=False,
        )

    def report_progress(event: ArchiveProgressEvent) -> None:
        if event.stage == "complete":
            detail = f" ({event.detail})" if event.detail else ""
            console.print(
                f"Run archive [{event.index}/{event.total}] artifact "
                f"#{event.media_artifact_id}: {event.outcome}{detail}",
                markup=False,
            )
            return
        console.print(
            f"Run archive [{event.index}/{event.total}] "
            f"{event.source_path.name}: {event.stage}",
            markup=False,
        )

    archive = archive_source_media(
        database,
        paths,
        video_ids=video_ids,
        wait_for_lock=True,
        progress_callback=report_progress,
        preflight_callback=report_preflight,
    )
    archive_counts = archive.counts
    console.print(
        f"Run media archive complete: eligible={archive.eligible}, "
        f"archived={archive_counts['archived']}, "
        f"already_archived={archive_counts['already_archived']}, "
        f"unavailable={archive_counts['destination_unavailable']}, "
        f"failed={archive_counts['failed']}."
    )


def _print_review_batch(batch: ReviewBatchResult) -> None:
    for pastor_result in batch.pastors:
        result = pastor_result.export
        console.print(f"Wrote pastor review markdown to {result.export_path}")
        console.print(f"Wrote review manifest to {result.manifest_path}")
        console.print(f"Included {result.video_count} video(s); skipped {result.skipped_count}.")
    if batch.prepared or batch.failed:
        console.print(f"Prepared {batch.prepared} video(s) for review; failed {batch.failed}.")


@app.command(
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
    replace_existing: bool = typer.Option(False, "--replace-existing", help="Replace a matching source first."),
    limit: int | None = typer.Option(DEFAULT_DISCOVER_LIMIT, "--limit", min=1, help="Videos per source; defaults to 26."),
    all_videos: bool = typer.Option(False, "--all-videos", help="Process all discovered videos."),
    captions_only: bool = typer.Option(False, "--captions-only", help="Do not run local transcription."),
    transcribe_missing: bool = typer.Option(True, "--transcribe-missing/--no-transcribe-missing", help="Only transcribe caption misses by default."),
    jobs: int = typer.Option(_default_transcribe_jobs(), "--jobs", min=1, help="Concurrent transcription jobs."),
    classifier: str = typer.Option("auto", "--classifier", help="Content classifier: auto, rules, or llm."),
    llm_model: str | None = typer.Option(None, "--llm-model", help="Override the configured Ollama model."),
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
            "After content processing, run the corpus identity workflow so "
            "new shadow associations and review nominations are available."
        ),
    ),
    stage_audio_only: bool = typer.Option(
        False,
        "--stage-audio-only",
        "--stage-offline-inputs",
        help=(
            "Discover the selected scope, download immutable source audio and "
            "available captions, write a resume manifest, and stop."
        ),
    ),
    resume_stage: Path | None = typer.Option(
        None,
        "--resume-stage",
        exists=True,
        dir_okay=False,
        help="Process exactly the videos in a verified audio-stage manifest without network downloads.",
    ),
    acquire_captions: bool = typer.Option(
        False,
        "--acquire-captions",
        help=(
            "With --resume-stage, fetch available captions for the verified "
            "manifest scope before offline-only local transcription."
        ),
    ),
    download_jobs: int = typer.Option(
        DEFAULT_PREP_WORKERS,
        "--download-jobs",
        min=1,
        help="Concurrent source-audio downloads during --stage-audio-only.",
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    if stage_audio_only:
        console.print(
            "Run will discover the selected scope, stage immutable source audio and "
            "available captions, write a checksum-pinned resume manifest, and stop."
        )
    elif resume_stage is not None:
        if acquire_captions:
            console.print(
                "Run will verify the staged source manifest, acquire available captions, "
                "then finish local transcription, extraction, media assurance, archival, "
                "and review without further network downloads."
            )
        else:
            console.print(
                "Run will verify the staged source manifest and finish transcription, extraction, "
                "media assurance, archival, and review without network downloads."
            )
    else:
        console.print(
            "Run adds the source, discovers videos, fetches captions, optionally transcribes, "
            "extracts, ensures isolated-sermon audio, archives eligible sources when configured, "
            "and writes disposition-aware pastor review artifacts."
        )
    try:
        run_workflow_service(
            url=url,
            pastor=pastor,
            all_sources=all_sources,
            source_ids=source_ids,
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
            resume_stage=resume_stage,
            acquire_captions=acquire_captions,
            download_jobs=download_jobs,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error


def main() -> int:
    app()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
