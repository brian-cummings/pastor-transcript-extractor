from __future__ import annotations

from pathlib import Path
import shutil
import sys

import typer
from rich.console import Console
from rich.table import Table

from pastor_transcript_extractor.config import (
    build_paths,
    build_tool_config,
    build_video_artifact_paths,
    ensure_directories,
    remember_base_dir,
)
from pastor_transcript_extractor.discovery import extract_discovered_videos, sort_discovered_videos_by_recency
from pastor_transcript_extractor.extraction import extract_video
from pastor_transcript_extractor.exporting import export_video
from pastor_transcript_extractor.models import TranscriptSourceKind, VideoStatus
from pastor_transcript_extractor.media import NoCaptionsAvailableError, VideoUnavailableError
from pastor_transcript_extractor.sources import UnsupportedSourceError, detect_source_type
from pastor_transcript_extractor.storage import Database
from pastor_transcript_extractor.reviewing import review_video
from pastor_transcript_extractor.transcription import fetch_captions_video, transcribe_video

app = typer.Typer(help="Pastor Transcript Extractor CLI")
pastor_app = typer.Typer(help="Manage pastors.")
source_app = typer.Typer(help="Manage queued sources.")
video_app = typer.Typer(help="Manage discovered videos.")
app.add_typer(pastor_app, name="pastor")
app.add_typer(source_app, name="source")
app.add_typer(video_app, name="video")
console = Console()
DEFAULT_DISCOVER_LIMIT = 26


def get_database(base_dir: Path | None = None) -> Database:
    paths = build_paths(base_dir)
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


def _resolve_pastor_id(database: Database, pastor: str | None) -> int | None:
    if pastor is None:
        return None
    pastor_record = database.get_pastor_by_slug(pastor)
    if pastor_record is None:
        raise typer.BadParameter(f"Unknown pastor slug: {pastor}")
    return pastor_record.id


def _find_next_review_video(database: Database, pastor_id: int | None = None) -> object | None:
    videos = [video for video in database.list_videos() if video.status == VideoStatus.NEEDS_REVIEW]
    if pastor_id is not None:
        videos = [video for video in videos if video.pastor_id == pastor_id]
    return videos[0] if videos else None


def _print_review_context(database: Database, video_id: int) -> None:
    video = database.get_video_by_id(video_id)
    if video is None:
        raise typer.BadParameter(f"Unknown video id: {video_id}")

    segments = database.list_transcript_segments(video_id)
    extraction_result = database.get_latest_extraction_result_for_video(video_id)
    if extraction_result is None:
        raise typer.BadParameter(f"Video {video_id} has no extraction result yet")

    console.print(f"Video #{video.id}: {video.title}")
    console.print(f"Status: {video.status.value}")
    console.print(f"Proposed transcript: {extraction_result.proposed_text_path}")
    if segments:
        table = Table(title="Segments")
        table.add_column("#", justify="right")
        table.add_column("Start")
        table.add_column("End")
        table.add_column("Label")
        table.add_column("Text")
        for index, segment in enumerate(segments, start=1):
            start_text = "-" if segment.start_seconds is None else f"{segment.start_seconds:.1f}"
            end_text = "-" if segment.end_seconds is None else f"{segment.end_seconds:.1f}"
            table.add_row(str(index), start_text, end_text, segment.label.value, segment.text)
        console.print(table)
    else:
        console.print("No segments available.")


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
    paths = build_paths(base_dir)
    ensure_directories(paths)
    database = Database(paths.database)
    database.initialize()
    if base_dir is not None:
        remember_base_dir(base_dir)
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
    summary.add_row("Reviews", str(counts["review_results"]))
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
    paths = build_paths(base_dir)
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
    paths = build_paths(base_dir)
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
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    tool_config = build_tool_config()
    sources = database.list_sources()
    if not sources:
        console.print("No sources queued.")
        return

    discovered_count = 0
    skipped_count = 0
    found_count = 0
    effective_limit = None if all_videos else limit
    existing_ids = {
        video.youtube_video_id for video in database.list_videos()
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
        console.print(
            f"Found {found_count} video(s); queued {discovered_count} new video(s) after limit {effective_limit}; "
            f"skipped {skipped_count} duplicate(s)."
        )
    else:
        console.print(
            f"Found {found_count} video(s); queued {discovered_count} new video(s); skipped {skipped_count} duplicate(s)."
        )


@app.command(help="Download or prepare local ASR transcripts for discovered videos.")
def transcribe(
    missing_only: bool = typer.Option(
        False,
        "--missing-only",
        help="Only transcribe videos without a local ASR artifact.",
    ),
    captions_missing_only: bool = typer.Option(
        False,
        "--captions-missing-only",
        help="Only transcribe videos that do not already have a captions artifact.",
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    paths = build_paths(base_dir)
    tools = build_tool_config()
    videos = database.list_videos()
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
        if _is_terminal_unavailable(video.status, video.failure_reason):
            skipped += 1
            continue
        latest_artifact = database.get_latest_transcript_artifact_for_video(video.id)
        if missing_only and latest_artifact is not None:
            skipped += 1
            continue
        if captions_missing_only and latest_artifact is not None and latest_artifact.source_kind == TranscriptSourceKind.CAPTIONS:
            skipped += 1
            continue
        if latest_artifact is not None and latest_artifact.source_kind == TranscriptSourceKind.LOCAL_ASR and video.status in {
            VideoStatus.TRANSCRIBED_LOCAL,
            VideoStatus.EXTRACTED,
            VideoStatus.NEEDS_REVIEW,
            VideoStatus.APPROVED,
            VideoStatus.EXPORTED,
        }:
            skipped += 1
            continue

        try:
            console.print(f"Transcribing video #{video.id}: {video.title}")
            transcribe_video(database, paths, tools, video.id)
        except Exception as error:
            database.update_video_status(video.id, VideoStatus.FAILED, str(error))
            console.print(f"[red]Failed to transcribe[/red] video #{video.id}: {error}")
            failed += 1
            continue
        console.print(f"Transcribed video #{video.id}")
        processed += 1

    console.print(f"Transcribed {processed} video(s); skipped {skipped}; failed {failed}.")


@app.command(help="Fetch YouTube captions when available and persist them as transcript artifacts.")
def fetch(
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    paths = build_paths(base_dir)
    tools = build_tool_config()
    videos = database.list_videos()
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
        help="Only extract videos without a review-ready artifact.",
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    paths = build_paths(base_dir)
    videos = database.list_videos()
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
        if missing_only and latest_extraction is not None:
            skipped += 1
            continue
        if latest_extraction is not None and video.status in {VideoStatus.NEEDS_REVIEW, VideoStatus.APPROVED, VideoStatus.EXPORTED}:
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


@app.command(help="Inspect extracted transcript segments for a video.")
def review(
    video_id: int = typer.Argument(..., help="Video id to review."),
    approve: bool = typer.Option(False, "--approve", help="Mark the extraction as approved after copying it."),
    notes: str | None = typer.Option(None, help="Optional review notes."),
    edit: bool = typer.Option(False, "--edit", help="Open the approved transcript in an editor."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    paths = build_paths(base_dir)
    _print_review_context(database, video_id)

    if not approve:
        console.print("Use --approve to persist a review result.")
        return

    result = review_video(database, paths, video_id, approve=True, review_notes=notes, edit=edit)
    console.print(f"Approved transcript written to {result.approved_text_path}")


@app.command(help="Review the next pending transcript, optionally approve it, export it, and move on.", rich_help_panel="Workflows")
def review_next(
    video_id: int | None = typer.Argument(None, help="Specific video id to review. Defaults to the first unreviewed video."),
    pastor: str | None = typer.Option(None, help="Limit the review queue to a pastor slug."),
    approve: bool = typer.Option(False, "--approve", help="Approve the current video after review."),
    edit: bool = typer.Option(False, "--edit", help="Open the approved transcript in an editor before finalizing."),
    export_after: bool = typer.Option(
        True,
        "--export/--no-export",
        help="Export immediately after approval.",
    ),
    notes: str | None = typer.Option(None, help="Optional review notes."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    paths = build_paths(base_dir)
    pastor_id = _resolve_pastor_id(database, pastor)

    if video_id is None:
        next_video = _find_next_review_video(database, pastor_id)
        if next_video is None:
            console.print("No videos waiting for review.")
            return
        video_id = next_video.id

    _print_review_context(database, video_id)

    if not approve:
        console.print("Use --approve to finalize this item and move to the next one.")
        return

    review_result = review_video(database, paths, video_id, approve=True, review_notes=notes, edit=edit)
    console.print(f"Approved transcript written to {review_result.approved_text_path}")

    if export_after:
        export_result = export_video(database, paths, video_id)
        console.print(f"Exported video #{video_id} to {export_result.export_path}")

    next_video = _find_next_review_video(database, pastor_id)
    if next_video is None:
        console.print("No more videos waiting for review.")
    else:
        console.print(f"Next in review queue: video #{next_video.id} - {next_video.title}")


@app.command("review-queue", help="List videos waiting for review or already approved.")
def review_queue(
    pastor: str | None = typer.Option(None, help="Filter by pastor slug."),
    status: VideoStatus = typer.Option(
        VideoStatus.NEEDS_REVIEW,
        "--status",
        help="Review workflow status to show.",
    ),
    limit: int = typer.Option(50, min=1, help="Maximum number of videos to show."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    videos = [video for video in database.list_videos() if video.status == status]

    if pastor is not None:
        pastor_record = database.get_pastor_by_slug(pastor)
        if pastor_record is None:
            raise typer.BadParameter(f"Unknown pastor slug: {pastor}")
        videos = [video for video in videos if video.pastor_id == pastor_record.id]

    if not videos:
        console.print("No videos matched.")
        return

    table = Table(title="Review Queue")
    table.add_column("ID", justify="right")
    table.add_column("Pastor")
    table.add_column("Status")
    table.add_column("Title")
    table.add_column("Proposed")
    table.add_column("Approved")

    for video in videos[:limit]:
        pastor_name = "-"
        if video.pastor_id is not None:
            pastor_record = database.get_pastor_by_id(video.pastor_id)
            pastor_name = pastor_record.slug if pastor_record is not None else str(video.pastor_id)
        extraction_result = database.get_latest_extraction_result_for_video(video.id)
        review_result = database.get_latest_review_result_for_video(video.id)
        table.add_row(
            str(video.id),
            pastor_name,
            video.status.value,
            video.title,
            extraction_result.proposed_text_path if extraction_result is not None else "-",
            review_result.approved_text_path if review_result is not None else "-",
        )

    console.print(table)


@app.command(help="Approve a reviewed transcript, optionally edit it first, and optionally export it.")
def approve(
    video_id: int = typer.Argument(..., help="Video id to approve."),
    notes: str | None = typer.Option(None, help="Optional review notes."),
    edit: bool = typer.Option(False, "--edit", help="Open the approved transcript in an editor before finalizing."),
    export_after: bool = typer.Option(False, "--export", help="Export immediately after approval."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    paths = build_paths(base_dir)
    result = review_video(database, paths, video_id, approve=True, review_notes=notes, edit=edit)
    console.print(f"Approved transcript written to {result.approved_text_path}")

    if export_after:
        export_result = export_video(database, paths, video_id)
        console.print(f"Exported video #{video_id} to {export_result.export_path}")


@app.command(help="Export approved transcripts to deterministic Markdown files.")
def export(
    video_id: int | None = typer.Argument(None, help="Video id to export. Omit to export all approved videos."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    paths = build_paths(base_dir)

    target_ids = [video_id] if video_id is not None else [video.id for video in database.list_videos()]
    exported = 0
    skipped = 0
    failed = 0
    for target_id in target_ids:
        video = database.get_video_by_id(target_id)
        if video is None:
            skipped += 1
            continue
        if database.get_latest_review_result_for_video(video.id) is None:
            skipped += 1
            continue
        try:
            result = export_video(database, paths, video.id)
        except Exception as error:
            console.print(f"[red]Failed to export[/red] video #{video.id}: {error}")
            failed += 1
            continue
        console.print(f"Exported video #{video.id} to {result.export_path}")
        exported += 1

    console.print(f"Exported {exported} video(s); skipped {skipped}; failed {failed}.")


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
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    console.print(
        "Run adds the source, discovers videos, fetches captions, optionally transcribes remaining videos, "
        "and extracts before review/export."
    )
    database = get_database(base_dir)
    if replace_existing:
        existing_source = database.get_source_by_url(url)
        if existing_source is not None:
            source_delete(source_id=existing_source.id, force=True, base_dir=base_dir)
            database = get_database(base_dir)
    add(url=url, pastor=pastor, notes=None, base_dir=base_dir)
    discover(limit=limit, all_videos=all_videos, base_dir=base_dir)
    fetch(base_dir=base_dir)
    if not captions_only and transcribe_missing:
        transcribe(missing_only=False, captions_missing_only=True, base_dir=base_dir)
    elif not captions_only:
        transcribe(missing_only=False, captions_missing_only=False, base_dir=base_dir)
    extract(missing_only=False, base_dir=base_dir)


def main() -> int:
    app()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
