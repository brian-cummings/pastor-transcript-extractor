from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import sys
from threading import Lock
from typing import Callable

import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, TaskID, TaskProgressColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from pastor_transcript_extractor.application import ReviewBatchResult, extract_batch, prepare_review_exports
from pastor_transcript_extractor.config import (
    build_llm_config,
    build_paths,
    build_pastor_paths,
    build_tool_config,
    build_video_artifact_paths,
    ensure_directories,
)
from pastor_transcript_extractor.discovery import extract_discovered_videos, sort_discovered_videos_by_recency
from pastor_transcript_extractor.extraction import reclassify_video
from pastor_transcript_extractor.evaluation import (
    build_failure_analysis,
    build_failure_markdown,
    build_markdown_report,
    create_evaluation_run,
    evaluate_fixture_payload,
)
from pastor_transcript_extractor.fixture_validation import validate_fixture_directory, validate_fixture_payload
from pastor_transcript_extractor.ground_truth_review import (
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
from pastor_transcript_extractor.identity import backfill_shadow_identity_assessments, persist_metadata_snapshot
from pastor_transcript_extractor.models import TranscriptSourceKind, VideoStatus
from pastor_transcript_extractor.media import NoCaptionsAvailableError, VideoUnavailableError
from pastor_transcript_extractor.local_llm import OllamaClient
from pastor_transcript_extractor.sources import UnsupportedSourceError, detect_source_type
from pastor_transcript_extractor.storage import Database
from pastor_transcript_extractor.transcription import (
    PreparedTranscriptInput,
    complete_transcription_video,
    fetch_captions_video,
    prepare_transcription_input,
)

app = typer.Typer(help="Pastor Transcript Extractor CLI")
pastor_app = typer.Typer(help="Manage pastors.")
source_app = typer.Typer(help="Manage queued sources.")
video_app = typer.Typer(help="Manage discovered videos.")
identity_app = typer.Typer(help="Manage speaker identity shadow artifacts.")
app.add_typer(pastor_app, name="pastor")
app.add_typer(source_app, name="source")
app.add_typer(video_app, name="video")
app.add_typer(identity_app, name="identity")
console = Console()
DEFAULT_DISCOVER_LIMIT = 26
DEFAULT_TRANSCRIBE_JOBS = 2
DEFAULT_PREP_WORKERS = 1
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


@app.command(help="Validate manually reviewed sermon evaluation fixtures.")
def validate_fixtures(
    fixture_dir: Path = typer.Argument(
        Path("evaluation/fixtures"),
        help="Directory containing manually reviewed fixture JSON files.",
    ),
) -> None:
    fixtures = validate_fixture_directory(fixture_dir.expanduser().resolve())
    console.print(f"Validated {len(fixtures)} fixture(s); all video IDs are unique.")


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
    output_dir = results_dir.expanduser().resolve() / str(run["run_id"])
    output_dir.mkdir(parents=True, exist_ok=False)
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


@app.command(help="Review and approve sermon ground truth without treating detector output as truth.")
def review_ground_truth(
    youtube_video_id: str = typer.Argument(..., help="YouTube video ID already present in the database."),
    reviewer: str | None = typer.Option(None, help="Human reviewer name or stable reviewer identifier."),
    evaluation_dir: Path = typer.Option(Path("evaluation"), help="Root containing drafts/ and fixtures/."),
    open_video: bool = typer.Option(False, "--open-video", help="Open the YouTube start link in a browser."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
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
    write_json(
        draft_path,
        draft_payload(
            video_id=youtube_video_id,
            source_url=video.url,
            start_seconds=suggested_start,
            end_seconds=suggested_end,
            proposal_source=proposal_source,
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
        if not typer.confirm(
            "Have you reviewed the entire video and confirmed there is no worship-service sermon?",
            default=False,
        ):
            console.print("Review stopped; no negative fixture was written.")
            return
        reviewer_value = reviewer or typer.prompt("Reviewed by")
        failure_mode = typer.prompt("Failure mode", default="non_sermon_event")
        notes = typer.prompt("Review notes", default="No worship-service sermon found.")
        fixture = approved_negative_fixture_payload(
            video_id=youtube_video_id,
            reviewer=reviewer_value,
            failure_mode=failure_mode,
            notes=notes,
        )
        validate_fixture_payload(fixture, path=fixture_path)
        if fixture_path.exists() and not typer.confirm(
            f"Overwrite existing fixture {fixture_path}?", default=False
        ):
            console.print("Existing fixture preserved.")
            return
        if not typer.confirm("Write this manually approved negative fixture?", default=False):
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
    if not typer.confirm("Have you reviewed the entire sermon envelope for missing sermon content?", default=False):
        console.print("Review stopped; the unreviewed draft was preserved and no fixture was written.")
        return
    if not typer.confirm("Are all listed interruptions genuinely non-sermon content?", default=not interruptions):
        console.print("Review stopped; adjust interruptions before approving ground truth.")
        return
    reviewer_value = reviewer or typer.prompt("Reviewed by")
    failure_mode = typer.prompt("Failure mode", default="unknown")
    notes = typer.prompt("Review notes", default="")
    fixture = approved_fixture_payload(
        video_id=youtube_video_id,
        start_seconds=start,
        end_seconds=end,
        interruptions=interruptions,
        reviewer=reviewer_value,
        failure_mode=failure_mode,
        notes=notes,
    )
    validate_fixture_payload(fixture, path=fixture_path)
    if fixture_path.exists() and not typer.confirm(f"Overwrite existing fixture {fixture_path}?", default=False):
        console.print("Existing fixture preserved.")
        return
    if not typer.confirm("Write this manually approved ground-truth fixture?", default=False):
        console.print("Approval cancelled; the unreviewed draft was preserved.")
        return
    write_json(fixture_path, fixture)
    console.print(f"Wrote manually approved fixture to {fixture_path}")


def get_database(base_dir: Path | None = None) -> Database:
    paths = build_paths(base_dir, remember=True)
    ensure_directories(paths)
    database = Database(paths.database)
    database.initialize()
    return database


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
    if video is None or video.pastor_id is None:
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
        failure_reason=None,
    )


def _recover_stale_transcribing_videos(database: Database, videos: list) -> None:
    for video in videos:
        if video.status != VideoStatus.TRANSCRIBING_LOCAL:
            continue
        latest_artifact = database.get_latest_transcript_artifact_for_video(video.id)
        if latest_artifact is not None and latest_artifact.source_kind == TranscriptSourceKind.LOCAL_ASR:
            database.update_video_status(video.id, VideoStatus.TRANSCRIBED_LOCAL)
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

    pastor = database.get_pastor_by_id(video.pastor_id) if video.pastor_id is not None else None
    if pastor is not None:
        video_paths = build_video_artifact_paths(paths, pastor.slug, video.youtube_video_id)
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
        pastor = database.get_pastor_by_id(video.pastor_id) if video.pastor_id is not None else None
        if pastor is not None:
            video_paths = build_video_artifact_paths(paths, pastor.slug, video.youtube_video_id)
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


def add_source_service(
    url: str,
    pastor: str,
    notes: str | None = None,
    base_dir: Path | None = None,
) -> None:
    database = get_database(base_dir)
    try:
        source_type = detect_source_type(url)
    except UnsupportedSourceError as error:
        raise ValueError(str(error)) from error

    pastor_record = database.get_pastor_by_slug(pastor)
    if pastor_record is None:
        raise ValueError(f"Unknown pastor slug: {pastor} (app root: {build_paths(base_dir).root})")

    source = database.add_source(url=url, source_type=source_type, pastor_id=pastor_record.id, notes=notes)
    console.print(
        f"Added source #{source.id}: {source.source_type.value} -> {source.url} (pastor: {pastor_record.slug})"
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
    summary.add_row("Sources", str(counts["sources"]))
    summary.add_row("Pastors", str(counts["pastors"]))
    summary.add_row("Videos", str(counts["videos"]))
    summary.add_row("Transcripts", str(counts["transcript_artifacts"]))
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
    table.add_column("Pastor")
    table.add_column("Type")
    table.add_column("URL")
    for source in sources:
        pastor_name = "-"
        if source.pastor_id is not None:
            pastor_record = database.get_pastor_by_id(source.pastor_id)
            if pastor_record is not None:
                pastor_name = pastor_record.slug
            else:
                pastor_name = str(source.pastor_id)
        table.add_row(str(source.id), pastor_name, source.source_type.value, source.url)
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
    table.add_column("Pastor")
    table.add_column("Type")
    table.add_column("URL")
    for source in sources:
        pastor_name = "-"
        if source.pastor_id is not None:
            pastor_record = database.get_pastor_by_id(source.pastor_id)
            pastor_name = pastor_record.slug if pastor_record is not None else str(source.pastor_id)
        table.add_row(str(source.id), pastor_name, source.source_type.value, source.url)
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
        videos = [video for video in videos if video.pastor_id == pastor_record.id]

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
    table.add_column("Pastor")
    table.add_column("Source", justify="right")
    table.add_column("Status")
    table.add_column("Published")
    table.add_column("Title")
    table.add_column("YouTube ID")

    for video in videos:
        pastor_name = "-"
        if video.pastor_id is not None:
            pastor_record = database.get_pastor_by_id(video.pastor_id)
            pastor_name = pastor_record.slug if pastor_record is not None else str(video.pastor_id)
        published = video.published_at.date().isoformat() if video.published_at is not None else "-"
        table.add_row(
            str(video.id),
            pastor_name,
            str(video.source_id),
            video.status.value,
            published,
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
) -> None:
    database = get_database(base_dir)
    app_paths = build_paths(base_dir)
    tool_config = build_tool_config()
    sources = database.list_sources()
    if source_id is not None:
        sources = [source for source in sources if source.id == source_id]
    if not sources:
        console.print("No sources queued.")
        return

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
    for index, source in enumerate(sources, start=1):
        if source.pastor_id is None:
            console.print(f"[yellow]Skipping[/yellow] source #{source.id}: no pastor linked.")
            continue
        pastor_record = database.get_pastor_by_id(source.pastor_id)
        pastor_slug = pastor_record.slug if pastor_record is not None else str(source.pastor_id)
        console.print(
            f"[{index}/{total_sources}] Discovering source #{source.id} for pastor {pastor_slug}: {source.url}",
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
            continue

        discovered_videos = sort_discovered_videos_by_recency(discovered_videos)
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
            if pastor_record is not None:
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
) -> None:
    database = get_database(base_dir)
    paths = build_paths(base_dir, remember=True)
    tools = build_tool_config()
    videos = database.list_videos()
    if source_id is not None:
        videos = [video for video in videos if video.source_id == source_id]
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
    prep_workers = min(DEFAULT_PREP_WORKERS, total_claimed)
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
) -> None:
    database = get_database(base_dir)
    paths = build_paths(base_dir, remember=True)
    tools = build_tool_config()
    videos = database.list_videos()
    if source_id is not None:
        videos = [video for video in videos if video.source_id == source_id]
    if not videos:
        console.print("No videos queued.")
        return

    processed = 0
    skipped = 0
    unavailable = 0
    failed = 0
    for video in videos:
        if video.pastor_id is None:
            skipped += 1
            continue
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
            event_callback=lambda message: console.print(message, markup=False),
            progress_callback=lambda stage, current, total: console.print(
                f"  {stage} block {current}/{total}"
            ),
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print(f"Extracted {result.processed} video(s); skipped {result.skipped}; failed {result.failed}.")


@app.command(help="Rerun local-LLM classification using existing extraction segments.")
def reclassify(
    video_id: int | None = typer.Option(None, "--video-id", help="Reclassify one database video id."),
    source_id: int | None = typer.Option(None, "--source-id", help="Reclassify extracted videos from one source id."),
    llm_model: str | None = typer.Option(None, "--llm-model", help="Override the configured local Ollama model."),
    force: bool = typer.Option(False, "--force", help="Rerun even when model and prompt versions match."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    if (video_id is None) == (source_id is None):
        raise typer.BadParameter("Pass exactly one of --video-id or --source-id.")
    database = get_database(base_dir)
    paths = build_paths(base_dir, remember=True)
    llm_config = build_llm_config()
    if llm_model is not None:
        from dataclasses import replace

        llm_config = replace(llm_config, model=llm_model)
    client = OllamaClient(llm_config)
    if video_id is not None:
        video = database.get_video_by_id(video_id)
        videos = [video] if video is not None else []
    else:
        assert source_id is not None
        videos = database.list_videos_by_source_id(source_id)
    if not videos:
        raise typer.BadParameter("No matching videos found.")

    processed = 0
    reused = 0
    skipped = 0
    failed = 0
    for video in videos:
        if database.get_latest_extraction_result_for_video(video.id) is None:
            skipped += 1
            continue
        try:
            console.print(f"Reclassifying video #{video.id}: {video.title}")
            result = reclassify_video(
                database,
                paths,
                video.id,
                llm_client=client,
                prompt_version=llm_config.prompt_version,
                force=force,
                progress=lambda stage, current, total: console.print(
                    f"  {stage} block {current}/{total}"
                ),
                model_digest=client.model_digest(),
                context_size=llm_config.context_size,
            )
        except Exception as error:
            console.print(f"[red]Failed to reclassify[/red] video #{video.id}: {error}")
            failed += 1
            continue
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
                f"audit={result.classification_path}"
            )
            processed += 1
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
        import subprocess
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
