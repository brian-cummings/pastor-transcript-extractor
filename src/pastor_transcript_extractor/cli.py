from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, as_completed, wait
from dataclasses import dataclass, replace
from datetime import date
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from threading import Lock
from typing import Callable, Sequence
import webbrowser

import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, TaskID, TaskProgressColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from pastor_transcript_extractor.application import ReviewBatchResult, extract_batch, prepare_review_exports
from pastor_transcript_extractor.artifact_namespace import resolve_video_artifact_paths
from pastor_transcript_extractor.church_database_import import (
    IMPORT_PROVIDER,
    ChurchDatabaseImportError,
    import_church_sources,
    imported_source_ids,
)
from pastor_transcript_extractor.config import (
    build_llm_config,
    build_paths,
    build_pastor_paths,
    build_tool_config,
    ensure_directories,
)
from pastor_transcript_extractor.discovery import extract_discovered_videos, sort_discovered_videos_by_recency
from pastor_transcript_extractor.extraction import reclassify_video
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
from pastor_transcript_extractor.fixture_validation import validate_fixture_directory, validate_fixture_payload
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
from pastor_transcript_extractor.reviewed_speaker_evidence import (
    ReviewedSpeakerEvidence,
    ReviewedEvidenceSyncResult,
    load_reviewed_speaker_evidence,
    observation_review_queue_priority,
    qualification_conflict_requires_adjudication,
    sync_reviewed_speaker_evidence,
)
from pastor_transcript_extractor.identity import backfill_shadow_identity_assessments, persist_metadata_snapshot
from pastor_transcript_extractor.models import (
    SpeakerObservation,
    TranscriptSourceKind,
    VideoStatus,
)
from pastor_transcript_extractor.media import NoCaptionsAvailableError, VideoUnavailableError
from pastor_transcript_extractor.media_archive import (
    ArchivePreflightEvent,
    ArchiveProgressEvent,
    ArchiveRunResult,
    archive_source_media,
    archive_status,
    media_archive_lock_held,
)
from pastor_transcript_extractor.media_artifacts import (
    MediaVerificationCache,
    audit_media_coverage,
    backfill_existing_media_artifacts,
    ensure_audio_for_video,
    get_verified_normalized_media_artifact,
    resolve_normalized_audio_path,
    video_has_isolated_sermon,
)
from pastor_transcript_extractor.local_llm import OllamaClient
from pastor_transcript_extractor.sources import UnsupportedSourceError, detect_source_type
from pastor_transcript_extractor.speaker_pair_diagnostics import (
    AudioSpanCache,
    DecisionPolicy,
    EmbeddingCache,
    SherpaOnnxEmbeddingBackend,
    SpanSpec,
    analyze_observation_pair,
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
from pastor_transcript_extractor.speaker_pair_eligibility import (
    assess_automatic_speaker_observation,
)
from pastor_transcript_extractor.speaker_pair_review import (
    InsufficientSpeechActivityError,
    ObservationQualification,
    PairJudgment,
    STANDARD_VARIATION_TAGS,
    create_review_draft,
    prepare_review_observation,
    submit_review,
)
from pastor_transcript_extractor.speaker_pair_selector import (
    PairCandidateObservation,
    select_next_speaker_pair,
    selection_history_from_artifacts,
)
from pastor_transcript_extractor.speaker_profile_review import (
    ProfileReviewRepresentative,
    write_profile_review_packet,
)
from pastor_transcript_extractor.speaker_registry import (
    attach_reviewed_observation,
    create_anonymous_profile,
    record_observation_difference,
    record_observation_disposition,
    record_observation_grouping_review,
    record_observation_review,
)
from pastor_transcript_extractor.sermon_fixture_selector import (
    SermonSelectionHistory,
    select_next_sermon_fixture,
    sermon_candidate_from_proposal,
    sermon_duration_bucket,
)
from pastor_transcript_extractor.storage import Database
from pastor_transcript_extractor.source_ownership import (
    apply_source_ownership_schema,
    audit_source_ownership,
    backfill_source_ownership,
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
source_ownership_app = typer.Typer(help="Migrate and audit source ownership data.")
app.add_typer(pastor_app, name="pastor")
app.add_typer(organization_app, name="organization")
app.add_typer(source_app, name="source")
app.add_typer(video_app, name="video")
app.add_typer(identity_app, name="identity")
app.add_typer(media_app, name="media")
app.add_typer(source_ownership_app, name="source-ownership")
console = Console()
DEFAULT_DISCOVER_LIMIT = 26
DEFAULT_TRANSCRIBE_JOBS = 2
DEFAULT_PREP_WORKERS = 2
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
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            validate_reviewed_pair_fixture(payload)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise typer.BadParameter(f"{path}: {error}") from error
        pair_id = str(payload.get("pair_id", ""))
        if not pair_id or pair_id in pair_ids:
            raise typer.BadParameter(f"{path}: pair_id must be present and unique")
        pair_ids.add(pair_id)
    console.print(f"Validated {len(paths)} reviewed speaker-pair fixture(s).")


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
        fixtures = [json.loads(path.read_text(encoding="utf-8")) for path in fixture_paths]
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


@identity_app.command(
    "review-speaker-pair",
    help="Prepare and adjudicate a blinded, exact-span speaker-pair fixture.",
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
        True, "--open-packet/--no-open-packet", help="Open the blinded local HTML listening packet."
    ),
    prepare_only: bool = typer.Option(
        False, "--prepare-only", help="Create the packet without prompting for adjudication."
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
    selection_manifest_json: str | None = typer.Option(None, hidden=True),
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
    if observations[0] is None or observations[1] is None:
        raise typer.BadParameter("Both videos require immutable speaker observations")
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
    console.print(f"Prepared blinded packet: {draft.packet_path}")
    if open_packet:
        webbrowser.open(draft.packet_path.resolve().as_uri())
    if prepare_only:
        console.print("Draft preserved; rerun without --prepare-only to adjudicate it.")
        return

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
    fixture_eligible = both_qualified and pair_judgment in {
        PairJudgment.SAME_SPEAKER,
        PairJudgment.DIFFERENT_SPEAKER,
    }
    approval_confirmed = fixture_eligible and typer.confirm(
        "Freeze this exact-span binary judgment as an approved fixture?",
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
    else:
        console.print("Review was preserved but did not create a fixture.")


def _load_json_artifacts(paths: Sequence[Path]) -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"{path}: expected a JSON object")
        payloads.append(payload)
    return payloads


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
        f"missing={len(result.missing_observations)} "
        f"conflicts={len(result.conflicts)}"
    )
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
    "review-next-speaker-observation",
    help="Review the next observation into a curated anonymous speaker profile.",
)
def review_next_speaker_observation(
    source_family: str | None = typer.Option(
        None,
        "--source-family",
        help="Optional source-family queue filter; never identity evidence.",
    ),
    reviewer: str | None = typer.Option(
        None, help="Stable human reviewer identifier."
    ),
    youtube_video_id: str | None = typer.Option(
        None,
        "--video-id",
        help="Revisit one observation in the selected queue scope.",
    ),
    cache_dir: Path = typer.Option(
        Path("evaluation/speaker-pairs/cache"),
        help="Ignored exact-span audio cache shared with pair review.",
    ),
    evaluation_root: Path = typer.Option(
        Path("evaluation/speaker-pairs"),
        help="Speaker-pair review evidence synchronized before selection.",
    ),
    source_family_registry: Path = typer.Option(
        Path("evaluation/source-families.json"),
        help="Frozen registry used to resolve the optional queue filter.",
    ),
    open_packet: bool = typer.Option(
        True,
        "--open-packet/--no-open-packet",
        help="Open the local voice-review packet.",
    ),
    prepare_only: bool = typer.Option(
        False,
        "--prepare-only",
        help="Sync prior evidence and prepare a packet without a new interactive review.",
    ),
    review_event_key: str | None = typer.Option(
        None,
        help="Optional stable key for explicit idempotent replay.",
    ),
    base_dir: Path | None = typer.Option(
        None, help="Override app data directory."
    ),
) -> None:
    database = get_database(base_dir)
    cache_root = cache_dir.expanduser().resolve()
    verification_cache = MediaVerificationCache(cache_root)
    try:
        reviewed_evidence = load_reviewed_speaker_evidence(
            evaluation_root.expanduser().resolve()
        )
        sync_result = sync_reviewed_speaker_evidence(
            database, reviewed_evidence
        )
        registry = None
        if source_family is not None:
            registry = load_source_family_registry(
                source_family_registry.expanduser().resolve()
            )
            if source_family not in {
                family.source_family_id for family in registry.families
            }:
                raise ValueError(f"unknown source family: {source_family}")
        selected: tuple[
            int,
            object,
            SpeakerObservation,
            Path,
            str | None,
            bool,
        ] | None = None
        for video in database.list_videos():
            if (
                youtube_video_id is not None
                and video.youtube_video_id != youtube_video_id
            ):
                continue
            source = database.get_source_by_id(video.source_id)
            if source is None:
                continue
            if source_family is not None:
                assert registry is not None
                family = registry.resolve_source_url(source.url)
                if (
                    family is None
                    or family.source_family_id != source_family
                ):
                    continue
            eligibility = assess_automatic_speaker_observation(
                database,
                video.id,
                verification_cache=verification_cache,
            )
            if not eligibility.eligible or eligibility.observation is None:
                continue
            assert eligibility.media_artifact is not None
            observation = eligibility.observation
            qualification_action = (
                database.get_effective_observation_review_action(observation.id)
            )
            grouping_action = (
                database.get_effective_observation_grouping_action(
                    observation.id
                )
            )
            attached_profile_ids = (
                database.list_effective_profile_ids_for_observation(
                    observation.id
                )
            )
            qualification_conflict = (
                qualification_conflict_requires_adjudication(
                    database,
                    reviewed_evidence,
                    observation_id=observation.id,
                    observation_fingerprint=observation.input_fingerprint,
                )
            )
            priority = observation_review_queue_priority(
                qualification_action=qualification_action,
                grouping_action=grouping_action,
                attached_profile_ids=attached_profile_ids,
                qualification_conflict=qualification_conflict,
                explicitly_targeted=youtube_video_id is not None,
            )
            if priority is None:
                continue
            candidate = (
                priority,
                video,
                observation,
                Path(eligibility.media_artifact.artifact_path),
                qualification_action,
                qualification_conflict,
            )
            if (
                selected is None
                or (priority, observation.input_fingerprint)
                < (selected[0], selected[2].input_fingerprint)
            ):
                selected = candidate
        if selected is None:
            target = (
                f" for {youtube_video_id}"
                if youtube_video_id is not None
                else ""
            )
            scope = (
                f"source family {source_family}"
                if source_family is not None
                else "the global review queue"
            )
            raise ValueError(f"no eligible observation{target} remains in {scope}")
        (
            _priority,
            video,
            observation,
            audio_path,
            qualification_action,
            qualification_conflict,
        ) = selected
        span_cache = AudioSpanCache(cache_root)
        prepared = prepare_review_observation(
            observation=observation,
            audio_path=audio_path,
            span_cache=span_cache,
        )
        representatives: list[ProfileReviewRepresentative] = []
        representative_observations: dict[int, SpeakerObservation] = {}
        for profile in database.list_speaker_profiles():
            if (
                profile.lifecycle_state != "active"
                or profile.created_reason != "reviewed_anonymous_speaker"
            ):
                continue
            member_ids = database.list_effective_observation_ids_for_profile(
                profile.id
            )
            if not member_ids:
                continue
            representative = database.get_speaker_observation(member_ids[0])
            if representative is None:
                continue
            representative_video = database.get_video_by_id(
                representative.video_id
            )
            if representative_video is None:
                continue
            eligibility = assess_automatic_speaker_observation(
                database,
                representative_video.id,
                verification_cache=verification_cache,
            )
            if (
                not eligibility.eligible
                or eligibility.observation is None
                or eligibility.media_artifact is None
                or eligibility.observation.id != representative.id
            ):
                continue
            representative_prepared = prepare_review_observation(
                observation=representative,
                audio_path=Path(eligibility.media_artifact.artifact_path),
                span_cache=span_cache,
            )
            representatives.append(
                ProfileReviewRepresentative(
                    profile_id=profile.id,
                    observation_fingerprint=representative.input_fingerprint,
                    spans=representative_prepared.spans,
                )
            )
            representative_observations[profile.id] = representative
        packet_path = write_profile_review_packet(
            observation_fingerprint=observation.input_fingerprint,
            spans=prepared.spans,
            representatives=representatives,
            output_root=cache_root,
            qualification_already_reviewed=(
                qualification_action == "qualified_single_speaker"
                and not qualification_conflict
            ),
        )
    except (
        OSError,
        RuntimeError,
        ValueError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ) as error:
        raise typer.BadParameter(str(error)) from error

    _print_reviewed_evidence_summary(reviewed_evidence, sync_result)
    scope = (
        f"source family {source_family}"
        if source_family is not None
        else "the global review queue"
    )
    console.print(
        f"Selected {video.youtube_video_id} from {scope}; "
        f"prepared packet: {packet_path}"
    )
    if representatives:
        console.print(
            "Available anonymous profiles: "
            + ", ".join(str(item.profile_id) for item in representatives)
        )
    else:
        console.print("No anonymous profile with a reviewable member exists yet.")
    if open_packet:
        webbrowser.open(packet_path.resolve().as_uri())
    if prepare_only:
        console.print(
            "Existing pair evidence was synchronized; no new interactive "
            "review was recorded."
        )
        return

    reviewer_value: str | None = None
    reason: str | None = None
    needs_qualification = (
        qualification_action != "qualified_single_speaker"
        or qualification_conflict
    )
    if needs_qualification:
        if qualification_conflict:
            console.print(
                "[yellow]Existing pair reviews conflict on this observation's "
                "qualification; adjudication is required.[/yellow]"
            )
        qualification_choice = _prompt_review_choice(
            "Observation qualification",
            {
                "single": "qualified_single_speaker",
                "multiple": "multiple_speakers",
                "invalid": "invalid",
                "cannot": "unresolved",
            },
        )
        reviewer_value = (reviewer or typer.prompt("Reviewed by")).strip()
        reason = typer.prompt("Review reason").strip()
        qualification_key = review_event_key or (
            f"anonymous-speaker-qualification-v2:"
            f"{observation.input_fingerprint}:{reviewer_value}:"
            f"{qualification_choice}:{reason}"
        )
        try:
            record_observation_disposition(
                database,
                observation_id=observation.id,
                action=str(qualification_choice),
                reviewer=reviewer_value,
                reason=reason,
                review_event_key=f"{qualification_key}:qualification",
            )
        except ValueError as error:
            raise typer.BadParameter(str(error)) from error
        if qualification_choice != "qualified_single_speaker":
            console.print(
                f"Recorded {qualification_choice} for observation "
                f"#{observation.id}; no grouping decision was requested."
            )
            return

    grouping_choices = {
        "separate": "separate",
        "unresolved": "unresolved",
    }
    if representatives:
        grouping_choices = {
            "same": "same",
            "different": "different",
            **grouping_choices,
        }
        console.print(
            "Grouping actions:\n"
            "  same       explicitly matches one displayed profile representative\n"
            "  different  explicitly differs from one displayed representative\n"
            "  separate   create a conservative profile bucket without asserting difference\n"
            "  unresolved leave qualified but ungrouped"
        )
    else:
        console.print(
            "Grouping actions:\n"
            "  separate   seed a conservative anonymous profile bucket\n"
            "  unresolved leave qualified but ungrouped"
        )
    grouping_action = _prompt_review_choice(
        "Grouping action",
        grouping_choices,
    )
    if reviewer_value is None:
        reviewer_value = (reviewer or typer.prompt("Reviewed by")).strip()
    if reason is None:
        reason = typer.prompt("Review reason").strip()
    profile_id: int | None = None
    if grouping_action in {"same", "different"}:
        profile_id = typer.prompt("Anonymous profile id", type=int)
        if profile_id not in representative_observations:
            raise typer.BadParameter(
                f"profile #{profile_id} has no representative in this packet"
            )
    event_key = review_event_key or (
        f"anonymous-speaker-grouping-v2:{observation.input_fingerprint}:"
        f"{reviewer_value}:{grouping_action}:{profile_id}:{reason}"
    )
    try:
        if grouping_action == "separate":
            profile = create_anonymous_profile(
                database,
                reviewer=reviewer_value,
                reason=reason,
                review_event_key=f"{event_key}:profile",
            )
            profile_id = profile.id
            attach_reviewed_observation(
                database,
                profile_id=profile.id,
                observation_id=observation.id,
                reviewer=reviewer_value,
                reason=reason,
                review_event_key=event_key,
            )
        elif grouping_action == "same":
            assert profile_id is not None
            attach_reviewed_observation(
                database,
                profile_id=profile_id,
                observation_id=observation.id,
                reviewer=reviewer_value,
                reason=reason,
                review_event_key=event_key,
            )
        elif grouping_action == "different":
            assert profile_id is not None
            representative = representative_observations[profile_id]
            record_observation_difference(
                database,
                observation_a_id=observation.id,
                observation_b_id=representative.id,
                different=True,
                reviewer=reviewer_value,
                reason=reason,
                review_event_key=f"{event_key}:different",
            )
            record_observation_grouping_review(
                database,
                observation_id=observation.id,
                deferred=True,
                reviewer=reviewer_value,
                reason=reason,
                review_event_key=f"{event_key}:grouping-defer",
            )
        else:
            record_observation_grouping_review(
                database,
                observation_id=observation.id,
                deferred=True,
                reviewer=reviewer_value,
                reason=reason,
                review_event_key=f"{event_key}:grouping-defer",
            )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    if profile_id is not None:
        if grouping_action == "same":
            console.print(
                f"Observation #{observation.id} is attached to anonymous "
                f"profile #{profile_id} by append-only review events."
            )
        else:
            console.print(
                f"Recorded an exact different-speaker constraint against "
                f"profile #{profile_id}'s displayed representative; the "
                "observation remains ungrouped."
            )
    elif grouping_action == "separate":
        console.print(
            f"Observation #{observation.id} seeded anonymous profile "
            f"#{profile.id}; this does not assert difference from other profiles."
        )
    else:
        console.print(
            f"Observation #{observation.id} remains qualified but ungrouped."
        )


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
        inputs: list[tuple[str, SpeakerObservation, Path]] = []
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
                (video.youtube_video_id, observation, Path(media.artifact_path))
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
    for index, (youtube_video_id, observation, audio_path) in enumerate(
        inputs,
        start=1,
    ):
        try:
            prepared = prepare_review_observation(
                observation=observation,
                audio_path=audio_path,
                span_cache=span_cache,
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
    "review-next-speaker-pair",
    help="Deterministically nominate and adjudicate the next unseen blinded speaker pair.",
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
        True, "--open-packet/--no-open-packet", help="Open the blinded local HTML listening packet."
    ),
    prepare_only: bool = typer.Option(
        False, "--prepare-only", help="Create the selected packet without prompting for adjudication."
    ),
    evaluation_scope: str = typer.Option(
        "all",
        "--evaluation-scope",
        help="Nominate only from all, development, validation, or held_out source families.",
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    paths = build_paths(base_dir)
    if not paths.database.exists():
        raise typer.BadParameter(f"Application database does not exist: {paths.database}")
    database = Database(paths.database, readonly=True)
    root = evaluation_root.expanduser().resolve()
    verification_cache = MediaVerificationCache(cache_dir.expanduser().resolve())
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
            claims = database.list_speaker_name_claims_for_video(video.id)
            names = frozenset(
                claim.normalized_name
                for claim in claims
                if claim.observation_id == observation.id
                and claim.explicit_speaker_attribution
                and claim.normalized_name.strip()
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
            )
            candidates.append(candidate)
        selection = select_next_speaker_pair(
            candidates,
            history,
            evaluation_partition=(
                None if evaluation_scope == "all" else evaluation_scope
            ),
        )
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
        for video in database.list_videos():
            if not video_has_isolated_sermon(database, video.id)[0]:
                continue
            if get_verified_normalized_media_artifact(database, video.id) is not None:
                continue
            videos.append(video)
        if limit is not None:
            videos = videos[:limit]
    counts = {"verified": 0, "unavailable": 0, "failed": 0, "skipped": 0}
    downloaded = 0
    for index, video in enumerate(videos, start=1):
        result = ensure_audio_for_video(
            database,
            paths,
            tools,
            video_id=video.id,
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
    "archive-status",
    help="Report the configured archive destination and persisted source-audio archive state.",
)
def media_archive_status(
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    report = archive_status(database)
    if report.destination is None:
        console.print("No media archive destination is configured.")
        return
    counts = report.counts
    console.print(
        f"Archive root={report.destination.archive_root}; "
        f"accessible={report.destination_accessible}; entries={len(report.entries)}; "
        f"archived={counts['archived']}; pending={counts['pending']}; failed={counts['failed']}."
    )


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


def _is_terminal_unavailable(video_status: VideoStatus, failure_reason: str | None) -> bool:
    if video_status is not VideoStatus.FAILED or not failure_reason:
        return False
    lowered = failure_reason.lower()
    return "video unavailable" in lowered or "not available" in lowered


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
    if _is_terminal_unavailable(video.status, video.failure_reason):
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
) -> PreparedTranscriptInput:
    return prepare_transcription_input(
        database,
        paths,
        tools,
        video_id,
        stage_callback=stage_callback,
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
            source.url,
        )
    console.print(table)


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
    ]

    ffmpeg_resolved, ffmpeg_status = _tool_status(tools.ffmpeg_bin)
    yt_dlp_resolved, yt_dlp_status = _tool_status(tools.yt_dlp_bin)
    rows.append(("ffmpeg", ffmpeg_resolved, ffmpeg_status))
    rows.append(("yt-dlp", yt_dlp_resolved, yt_dlp_status))
    rows.append(("yt-dlp js runtimes", tools.yt_dlp_js_runtimes or "(default)", "ok"))
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
    if not sources:
        console.print("No sources queued.")
        return DiscoveryServiceResult({})

    discovered_count = 0
    skipped_count = 0
    excluded_count = 0
    found_count = 0
    effective_limit = None if all_videos else limit
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
        found_count += len(discovered_videos)
        source_found_count = len(discovered_videos)
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
    _recover_stale_transcribing_videos(database, videos)
    videos = [database.get_video_by_id(video.id) or video for video in videos]

    processed = 0
    skipped = 0
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

    processed = 0
    skipped = 0
    unavailable = 0
    failed = 0
    for video in videos:
        transcript_artifacts = database.list_transcript_artifacts_for_video(video.id)
        if any(artifact.source_kind == TranscriptSourceKind.CAPTIONS for artifact in transcript_artifacts):
            skipped += 1
            continue

        try:
            console.print(f"Fetching captions for video #{video.id}: {video.title}")
            result = fetch_captions_video(database, paths, tools, video.id)
        except NoCaptionsAvailableError:
            console.print(f"No captions for video #{video.id}; leaving it for local transcription.")
            unavailable += 1
            continue
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
        f"Fetched captions for {processed} video(s); skipped {skipped}; unavailable {unavailable}; failed {failed}."
    )


@app.command(help="Fetch YouTube captions when available and persist them as transcript artifacts.")
def fetch(
    source_id: int | None = typer.Option(None, help="Only fetch captions for videos from a specific source id."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    fetch_captions_service(source_id, base_dir)


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
    for video in videos:
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
    replace_existing: bool = False,
    limit: int | None = DEFAULT_DISCOVER_LIMIT,
    all_videos: bool = False,
    captions_only: bool = False,
    transcribe_missing: bool = True,
    jobs: int = DEFAULT_TRANSCRIBE_JOBS,
    classifier: str = "auto",
    llm_model: str | None = None,
    skip_review: bool = False,
    base_dir: Path | None = None,
) -> None:
    if all_sources:
        if url is not None:
            raise ValueError("Do not pass a URL when using --all. Run either a global sync or a single-source workflow.")
        if pastor is not None:
            raise ValueError("Do not pass --pastor when using --all.")
        if replace_existing:
            raise ValueError("--replace-existing is only valid for single-source runs.")
        discover_sources_service(limit=limit, all_videos=all_videos, source_id=None, base_dir=base_dir)
        fetch_captions_service(source_id=None, base_dir=base_dir)
        if not captions_only and transcribe_missing:
            transcribe_videos_service(missing_only=False, captions_missing_only=True, jobs=jobs, source_id=None, base_dir=base_dir)
        elif not captions_only:
            transcribe_videos_service(missing_only=False, captions_missing_only=False, jobs=jobs, source_id=None, base_dir=base_dir)
        database = get_database(base_dir)
        paths = build_paths(base_dir, remember=True)
        extraction = extract_batch(
            database,
            paths,
            classifier=classifier,
            llm_model=llm_model,
            event_callback=lambda message: console.print(message, markup=False),
            progress_callback=lambda stage, current, total: console.print(f"  {stage} block {current}/{total}"),
        )
        console.print(f"Extracted {extraction.processed} video(s); skipped {extraction.skipped}; failed {extraction.failed}.")
        if not skip_review:
            reviews = prepare_review_exports(
                database,
                paths,
                all_pastors=True,
                classifier=classifier,
                llm_model=llm_model,
                event_callback=lambda message: console.print(message, markup=False),
            )
            _print_review_batch(reviews)
        return

    if url is None:
        raise ValueError("A URL is required unless you use --all.")
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
    discover_sources_service(limit=limit, all_videos=all_videos, source_id=source_id, base_dir=base_dir)
    fetch_captions_service(source_id=source_id, base_dir=base_dir)
    if not captions_only and transcribe_missing:
        transcribe_videos_service(missing_only=False, captions_missing_only=True, jobs=jobs, source_id=source_id, base_dir=base_dir)
    elif not captions_only:
        transcribe_videos_service(missing_only=False, captions_missing_only=False, jobs=jobs, source_id=source_id, base_dir=base_dir)
    paths = build_paths(base_dir, remember=True)
    extraction = extract_batch(
        database,
        paths,
        source_id=source_id,
        classifier=classifier,
        llm_model=llm_model,
        event_callback=lambda message: console.print(message, markup=False),
        progress_callback=lambda stage, current, total: console.print(f"  {stage} block {current}/{total}"),
    )
    console.print(f"Extracted {extraction.processed} video(s); skipped {extraction.skipped}; failed {extraction.failed}.")
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


def _print_review_batch(batch: ReviewBatchResult) -> None:
    for pastor_result in batch.pastors:
        result = pastor_result.export
        console.print(f"Wrote pastor review markdown to {result.export_path}")
        console.print(f"Wrote review manifest to {result.manifest_path}")
        console.print(f"Included {result.video_count} video(s); skipped {result.skipped_count}.")
    if batch.prepared or batch.failed:
        console.print(f"Prepared {batch.prepared} video(s) for review; failed {batch.failed}.")


@app.command(help="Run intake through disposition-aware pastor review export.", rich_help_panel="Workflows")
def run(
    url: str | None = typer.Argument(None, help="YouTube video, playlist, or channel URL."),
    pastor: str | None = typer.Option(None, help="Pastor slug to associate with this source."),
    all_sources: bool = typer.Option(False, "--all", help="Run across all configured sources."),
    replace_existing: bool = typer.Option(False, "--replace-existing", help="Replace a matching source first."),
    limit: int | None = typer.Option(DEFAULT_DISCOVER_LIMIT, "--limit", min=1, help="Videos per source; defaults to 26."),
    all_videos: bool = typer.Option(False, "--all-videos", help="Process all discovered videos."),
    captions_only: bool = typer.Option(False, "--captions-only", help="Do not run local transcription."),
    transcribe_missing: bool = typer.Option(True, "--transcribe-missing/--no-transcribe-missing", help="Only transcribe caption misses by default."),
    jobs: int = typer.Option(_default_transcribe_jobs(), "--jobs", min=1, help="Concurrent transcription jobs."),
    classifier: str = typer.Option("auto", "--classifier", help="Content classifier: auto, rules, or llm."),
    llm_model: str | None = typer.Option(None, "--llm-model", help="Override the configured Ollama model."),
    skip_review: bool = typer.Option(False, "--skip-review", help="Stop after extraction without writing review exports."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    console.print(
        "Run adds the source, discovers videos, fetches captions, optionally transcribes, extracts, "
        "and writes disposition-aware pastor review artifacts."
    )
    try:
        run_workflow_service(
            url=url,
            pastor=pastor,
            all_sources=all_sources,
            replace_existing=replace_existing,
            limit=limit,
            all_videos=all_videos,
            captions_only=captions_only,
            transcribe_missing=transcribe_missing,
            jobs=jobs,
            classifier=classifier,
            llm_model=llm_model,
            skip_review=skip_review,
            base_dir=base_dir,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error


def main() -> int:
    app()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
