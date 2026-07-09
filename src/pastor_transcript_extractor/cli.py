from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
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

from pastor_transcript_extractor.config import (
    build_paths,
    build_pastor_paths,
    build_tool_config,
    build_video_artifact_paths,
    ensure_directories,
)
from pastor_transcript_extractor.discovery import extract_discovered_videos, sort_discovered_videos_by_recency
from pastor_transcript_extractor.extraction import extract_video
from pastor_transcript_extractor.exporting import export_pastor_review_markdown
from pastor_transcript_extractor.models import TranscriptSourceKind, VideoStatus
from pastor_transcript_extractor.media import NoCaptionsAvailableError, VideoUnavailableError
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
app.add_typer(pastor_app, name="pastor")
app.add_typer(source_app, name="source")
app.add_typer(video_app, name="video")
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


def get_database(base_dir: Path | None = None) -> Database:
    paths = build_paths(base_dir, remember=True)
    ensure_directories(paths)
    database = Database(paths.database)
    database.initialize()
    return database


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

    def stage_callback(stage: str) -> None:
        label = STAGE_LABELS.get(stage, stage)
        if label not in valid_statuses:
            return
        with lock:
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


def _prepare_review_markdown(database: Database, paths: Path, pastor_slug: str) -> tuple[int, int]:
    pastor = database.get_pastor_by_slug(pastor_slug)
    if pastor is None:
        raise typer.BadParameter(f"Unknown pastor slug: {pastor_slug}")

    processed = 0
    failed = 0
    for video in database.list_videos():
        if video.pastor_id != pastor.id:
            continue
        latest_artifact = database.get_latest_transcript_artifact_for_video(video.id)
        latest_extraction = database.get_latest_extraction_result_for_video(video.id)
        if latest_artifact is None or latest_extraction is not None:
            continue
        try:
            console.print(f"Preparing review markdown for video #{video.id}: {video.title}")
            extract_video(database, paths, video.id)
        except Exception as error:
            database.update_video_status(video.id, VideoStatus.FAILED, str(error))
            console.print(f"[red]Failed to prepare review markdown[/red] video #{video.id}: {error}")
            failed += 1
            continue
        processed += 1
    return processed, failed


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


@app.command(help="Add a YouTube video, playlist, or channel source for a pastor.")
def add(
    url: str = typer.Argument(..., help="YouTube video, playlist, or channel URL."),
    pastor: str = typer.Option(..., help="Pastor slug to associate with this source."),
    notes: str | None = typer.Option(None, help="Optional notes for this source."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    try:
        source_type = detect_source_type(url)
    except UnsupportedSourceError as error:
        raise typer.BadParameter(str(error)) from error

    pastor_record = database.get_pastor_by_slug(pastor)
    if pastor_record is None:
        raise typer.BadParameter(f"Unknown pastor slug: {pastor}")

    source = database.add_source(url=url, source_type=source_type, pastor_id=pastor_record.id, notes=notes)
    console.print(
        f"Added source #{source.id}: {source.source_type.value} -> {source.url} (pastor: {pastor_record.slug})"
    )


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


@source_app.command("delete", help="Delete a source and optionally all dependent videos and artifacts.")
def source_delete(
    source_id: int = typer.Argument(..., help="Source id to delete."),
    force: bool = typer.Option(False, "--force", help="Delete dependent videos and all related artifacts."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    paths = build_paths(base_dir, remember=True)
    source = database.get_source_by_id(source_id)
    if source is None:
        raise typer.BadParameter(f"Unknown source id: {source_id}")

    videos = database.list_videos_by_source_id(source_id)
    if videos and not force:
        raise typer.BadParameter(
            f"Source #{source_id} has {len(videos)} linked video(s). Use --force to delete them too."
        )

    deleted_videos = _delete_source_tree(database, paths, source_id)
    console.print(
        f"Deleted source #{source_id} ({source.url}); removed {deleted_videos} linked video(s) and artifacts."
    )


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
            raise typer.BadParameter(f"Unknown pastor slug: {pastor}")
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
            raise typer.BadParameter(f"Unknown pastor slug: {pastor}")
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

    table = Table(title="Doctor")
    table.add_column("Check")
    table.add_column("Resolved Path")
    table.add_column("Status")
    for check, resolved, status_value in rows:
        table.add_row(check, resolved, status_value)
    console.print(table)


@app.command(help="Discover videos from queued sources with yt-dlp metadata.")
def discover(
    limit: int | None = typer.Option(
        DEFAULT_DISCOVER_LIMIT,
        "--limit",
        min=1,
        help="Only persist the first N discovered videos per source. Defaults to 26.",
    ),
    all_videos: bool = typer.Option(
        False,
        "--all",
        help="Persist all discovered videos for each source.",
    ),
    source_id: int | None = typer.Option(None, help="Only discover videos for a specific source id."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
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
    for source in sources:
        if source.pastor_id is None:
            console.print(f"[yellow]Skipping[/yellow] source #{source.id}: no pastor linked.")
            continue
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
        if effective_limit is not None:
            discovered_videos = discovered_videos[:effective_limit]

        for discovered in discovered_videos:
            if discovered.youtube_video_id in excluded_ids:
                excluded_count += 1
                continue
            if discovered.youtube_video_id in existing_ids:
                skipped_count += 1
                continue
            database.add_video(
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
            discovered_count += 1
            existing_ids.add(discovered.youtube_video_id)

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


@app.command(help="Download or prepare local ASR transcripts for discovered videos.")
def transcribe(
    missing_only: bool = typer.Option(
        False,
        "--missing-only",
        help="Only transcribe videos without a local ASR artifact.",
    ),
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


@app.command(help="Fetch YouTube captions when available and persist them as transcript artifacts.")
def fetch(
    source_id: int | None = typer.Option(None, help="Only fetch captions for videos from a specific source id."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
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
        latest_artifact = database.get_latest_transcript_artifact_for_video(video.id)
        if latest_artifact is not None and latest_artifact.source_kind == TranscriptSourceKind.CAPTIONS:
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
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    paths = build_paths(base_dir, remember=True)
    videos = database.list_videos()
    if source_id is not None:
        videos = [video for video in videos if video.source_id == source_id]
    if not videos:
        console.print("No videos queued.")
        return

    processed = 0
    skipped = 0
    failed = 0
    for video in videos:
        if video.pastor_id is None:
            skipped += 1
            continue
        latest_artifact = database.get_latest_transcript_artifact_for_video(video.id)
        if latest_artifact is None:
            skipped += 1
            continue
        latest_extraction = database.get_latest_extraction_result_for_video(video.id)
        if missing_only and latest_extraction is not None and not force:
            skipped += 1
            continue
        if (
            not force
            and latest_extraction is not None
            and video.status in {VideoStatus.EXTRACTED, VideoStatus.EXPORTED}
        ):
            skipped += 1
            continue

        try:
            console.print(f"Extracting video #{video.id}: {video.title}")
            extract_video(database, paths, video.id)
        except Exception as error:
            database.update_video_status(video.id, VideoStatus.FAILED, str(error))
            console.print(f"[red]Failed to extract[/red] video #{video.id}: {error}")
            failed += 1
            continue
        console.print(f"Extracted video #{video.id}")
        processed += 1

    console.print(f"Extracted {processed} video(s); skipped {skipped}; failed {failed}.")


@app.command(help="Build or refresh the pastor-scoped Markdown review file from extracted videos.", rich_help_panel="Workflows")
def review(
    pastor: str = typer.Argument(..., help="Pastor slug whose extracted videos should be assembled into review Markdown."),
    edit: bool = typer.Option(False, "--edit", help="Open the generated review Markdown in an editor."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    paths = build_paths(base_dir, remember=True)
    pastor_record = database.get_pastor_by_slug(pastor)
    if pastor_record is None:
        raise typer.BadParameter(f"Unknown pastor slug: {pastor}")
    prepared, failed = _prepare_review_markdown(database, paths, pastor_record.slug)
    pastor_paths = build_pastor_paths(paths, pastor_record.slug)
    result = export_pastor_review_markdown(database, paths, pastor_record.slug)
    if prepared or failed:
        console.print(f"Prepared {prepared} video(s) for review; failed {failed}.")
    console.print(f"Wrote pastor review markdown to {result.export_path}")
    console.print(f"Wrote review manifest to {result.manifest_path}")
    console.print(f"Included {result.video_count} video(s); skipped {result.skipped_count}.")

    if edit:
        editor = shutil.which("code") or shutil.which("nano") or shutil.which("vim")
        if editor is None:
            raise RuntimeError("No editor found on PATH")
        import subprocess
        subprocess.run([editor, str(pastor_paths.exports / "review.md")], check=True)


@app.command(help="Run the intake pipeline from source registration through extraction.", rich_help_panel="Workflows")
def run(
    url: str = typer.Argument(..., help="YouTube video, playlist, or channel URL."),
    pastor: str = typer.Option(..., help="Pastor slug to associate with this source."),
    replace_existing: bool = typer.Option(
        False,
        "--replace-existing",
        help="Delete an existing source with the same URL before re-running the pipeline.",
    ),
    limit: int | None = typer.Option(
        DEFAULT_DISCOVER_LIMIT,
        "--limit",
        min=1,
        help="Only process the first N discovered videos from the source. Defaults to 26.",
    ),
    all_videos: bool = typer.Option(
        False,
        "--all",
        help="Process all discovered videos from the source.",
    ),
    captions_only: bool = typer.Option(
        False,
        "--captions-only",
        help="Stop after caption fetch and extraction; do not run local transcription.",
    ),
    transcribe_missing: bool = typer.Option(
        True,
        "--transcribe-missing/--no-transcribe-missing",
        help="After fetching captions, only run local transcription for videos that still need it.",
    ),
    jobs: int = typer.Option(
        _default_transcribe_jobs(),
        "--jobs",
        min=1,
        help="Number of videos to transcribe concurrently. Defaults to 2.",
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    console.print(
        "Run adds the source, discovers videos, fetches captions, optionally transcribes remaining videos, "
        "and extracts before pastor Markdown review."
    )
    database = get_database(base_dir)
    if replace_existing:
        existing_source = database.get_source_by_url(url)
        if existing_source is not None:
            source_delete(source_id=existing_source.id, force=True, base_dir=base_dir)
            database = get_database(base_dir)
    add(url=url, pastor=pastor, notes=None, base_dir=base_dir)
    source = database.get_source_by_url(url)
    source_id = source.id if source is not None else None
    discover(limit=limit, all_videos=all_videos, source_id=source_id, base_dir=base_dir)
    fetch(source_id=source_id, base_dir=base_dir)
    if not captions_only and transcribe_missing:
        transcribe(
            missing_only=False,
            captions_missing_only=True,
            jobs=jobs,
            source_id=source_id,
            base_dir=base_dir,
        )
    elif not captions_only:
        transcribe(
            missing_only=False,
            captions_missing_only=False,
            jobs=jobs,
            source_id=source_id,
            base_dir=base_dir,
        )
    extract(missing_only=False, source_id=source_id, base_dir=base_dir)


def main() -> int:
    app()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
