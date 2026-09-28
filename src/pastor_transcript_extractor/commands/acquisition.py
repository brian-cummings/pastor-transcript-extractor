from __future__ import annotations

from pathlib import Path
import shutil
from threading import Lock
import time

import typer
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    TaskID,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)

from pastor_transcript_extractor import (
    application,
    church_database_import,
    discovery,
    media_archive,
    media_artifacts,
    transcription,
)
from pastor_transcript_extractor.commands.apps import root_app
from pastor_transcript_extractor.config import (
    build_paths,
    build_tool_config,
    ensure_directories,
)
from pastor_transcript_extractor.storage import Database
from pastor_transcript_extractor.workflows.caption_acquisition import (
    CaptionAcquisitionResult,
    fetch_captions_service as _fetch_captions_service,
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
from pastor_transcript_extractor.workflows.transcription import (
    DEFAULT_PREP_WORKERS,
    DEFAULT_TRANSCRIBE_JOBS,
    default_transcribe_jobs,
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


DEFAULT_DISCOVER_LIMIT = 26
MIN_SYNC_FREE_DISK_FRACTION = 0.20
SYNC_ARCHIVE_WAIT_INITIAL_SECONDS = 1.0
SYNC_ARCHIVE_WAIT_MAX_SECONDS = 30.0
console = Console()


def discover_sources_service(
    limit: int | None = DEFAULT_DISCOVER_LIMIT,
    all_videos: bool = False,
    source_id: int | None = None,
    base_dir: Path | None = None,
) -> DiscoveryServiceResult:
    """Adapt source discovery progress and extraction to the command surface."""
    return _discover_sources_service(
        limit,
        all_videos,
        source_id,
        base_dir,
        progress_callback=lambda message: console.print(message, markup=False),
        extract_videos=discovery.extract_discovered_videos,
    )


def fetch_captions_service(
    source_id: int | None = None,
    base_dir: Path | None = None,
    video_ids: set[int] | None = None,
    request_interval_seconds: float = 0.0,
    cookies_from_browser: str | None = None,
    cookies: Path | None = None,
) -> CaptionAcquisitionResult:
    """Adapt caption acquisition progress and scheduling to the command surface."""
    return _fetch_captions_service(
        source_id=source_id,
        base_dir=base_dir,
        video_ids=video_ids,
        request_interval_seconds=request_interval_seconds,
        cookies_from_browser=cookies_from_browser,
        cookies=cookies,
        progress_callback=console.print,
        fetch_captions=transcription.fetch_captions_video,
        monotonic=time.monotonic,
        sleeper=time.sleep,
    )


def get_database(base_dir: Path | None = None) -> Database:
    paths = build_paths(base_dir, remember=True)
    ensure_directories(paths)
    database = Database(paths.database)
    database.initialize()
    return database


def _prepare_transcription_task(
    database,
    paths,
    tools,
    video_id,
    stage_callback=None,
    allow_network=True,
):
    return transcription.prepare_transcription_input(
        database,
        paths,
        tools,
        video_id,
        stage_callback=stage_callback,
        allow_network=allow_network,
    )


def _complete_transcription_task(
    database,
    tools,
    prepared,
    progress_callback=None,
    stage_callback=None,
) -> None:
    transcription.complete_transcription_video(
        database,
        tools,
        prepared,
        progress_callback=progress_callback,
        stage_callback=stage_callback,
    )


class TranscriptionRenderer:
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
            console.print(f"[video #{event.video_id} stage] {event.stage}", markup=False)
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
            completed = None
            if event.stage == STAGE_DONE:
                completed = 100
            elif event.stage == STAGE_TRANSCRIBING:
                completed = 0
            if completed is None:
                self._progress.update(task_id, status=event.stage)
            else:
                self._progress.update(task_id, status=event.stage, completed=completed)

    def _render_progress(self, event: TranscriptionProgressed) -> None:
        if not self._terminal:
            console.print(
                f"[video #{event.video_id} progress] {event.percent}%", markup=False
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
    renderer = TranscriptionRenderer()
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


@root_app.command(help="Discover videos from queued sources with yt-dlp metadata.")
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
    source_id: int | None = typer.Option(
        None,
        help="Only discover videos for a specific source id.",
    ),
    base_dir: Path | None = typer.Option(
        None,
        help="Override app data directory.",
    ),
) -> None:
    discover_sources_service(limit, all_videos, source_id, base_dir)


@root_app.command(
    help="Download or prepare local ASR transcripts for discovered videos."
)
def transcribe(
    missing_only: bool = typer.Option(
        False,
        "--missing-only",
        help="Only transcribe videos without a local ASR artifact.",
    ),
    captions_missing_only: bool = typer.Option(
        True,
        "--captions-missing-only/--all-eligible",
        help=(
            "By default, only transcribe videos that do not already have a "
            "captions artifact. Use --all-eligible to transcribe all eligible videos."
        ),
    ),
    jobs: int = typer.Option(
        default_transcribe_jobs(),
        "--jobs",
        min=1,
        help="Number of videos to transcribe concurrently. Defaults to 2.",
    ),
    source_id: int | None = typer.Option(
        None,
        help="Only transcribe videos from a specific source id.",
    ),
    base_dir: Path | None = typer.Option(
        None,
        help="Override app data directory.",
    ),
) -> None:
    transcribe_videos_service(
        missing_only,
        captions_missing_only,
        jobs,
        source_id,
        base_dir,
    )


@root_app.command(
    help="Fetch YouTube captions when available and persist them as transcript artifacts."
)
def fetch(
    source_id: int | None = typer.Option(
        None,
        help="Only fetch captions for videos from a specific source id.",
    ),
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
    base_dir: Path | None = typer.Option(
        None,
        help="Override app data directory.",
    ),
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


@root_app.command(
    "sync-imported-sources",
    help="Acquire recent transcripts and fallback audio for provenance-imported sources.",
)
def sync_imported_sources(
    provider: str = typer.Option(
        church_database_import.IMPORT_PROVIDER,
        help="Import provider to synchronize.",
    ),
    latest: int = typer.Option(6, min=1, help="Newest videos to retain per imported source."),
    jobs: int = typer.Option(
        default_transcribe_jobs(),
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
                list_imported_sources=church_database_import.imported_source_ids,
                discover=discover_sources_service,
                fetch_captions=fetch_captions_service,
                transcribe=transcribe_videos_service,
                extract=application.extract_batch,
                register_media=media_artifacts.backfill_existing_media_artifacts,
                archive_source=media_archive.archive_source_media,
                archive_lock_held=media_archive.media_archive_lock_held,
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
