from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path
import shutil
import time
from typing import Callable

from pastor_transcript_extractor.application import extract_batch
from pastor_transcript_extractor.inference_defaults import (
    DEFAULT_CLASSIFIER,
    DEFAULT_RECORDING_VERIFIER_BACKEND,
)
from pastor_transcript_extractor.church_database_import import (
    IMPORT_PROVIDER,
    imported_source_ids,
)
from pastor_transcript_extractor.config import AppPaths, build_paths, ensure_directories
from pastor_transcript_extractor.media_archive import (
    archive_source_media,
    media_archive_lock_held,
)
from pastor_transcript_extractor.media_artifacts import backfill_existing_media_artifacts
from pastor_transcript_extractor.storage import Database
from pastor_transcript_extractor.workflows.caption_acquisition import (
    fetch_captions_service,
)
from pastor_transcript_extractor.workflows.source_discovery import (
    discover_sources_service,
)
from pastor_transcript_extractor.workflows.transcript_coordination import (
    TranscriptCoordinationDependencies,
    TranscriptCoordinationRequest,
    coordinate_transcript_acquisition,
)
from pastor_transcript_extractor.workflows.transcription import (
    DEFAULT_PREP_WORKERS,
    DEFAULT_TRANSCRIBE_JOBS,
    recover_stale_transcribing_videos,
    should_transcribe_video,
    transcribe_videos_service,
)


MIN_SYNC_FREE_DISK_FRACTION = 0.20
SYNC_ARCHIVE_WAIT_INITIAL_SECONDS = 1.0
SYNC_ARCHIVE_WAIT_MAX_SECONDS = 30.0
SYNC_AUDIO_RESERVATION_BYTES_PER_SECOND = 250_000
SYNC_UNKNOWN_VIDEO_DURATION_SECONDS = 2 * 60 * 60

SyncProgressCallback = Callable[[str], None]
SyncOperation = Callable[..., object]
DiskUsage = Callable[[Path], object]
Sleeper = Callable[[float], None]


class SourceSyncConfigurationError(ValueError):
    """The requested sync cannot start with the current configuration."""


class SourceSyncDiskReserveError(RuntimeError):
    """Starting another download would violate the local disk reserve."""


@dataclass(frozen=True, slots=True)
class SourceSyncRequest:
    provider: str = IMPORT_PROVIDER
    latest: int = 6
    jobs: int = DEFAULT_TRANSCRIBE_JOBS
    download_jobs: int = DEFAULT_PREP_WORKERS
    all_audio: bool = False
    extract_new: bool = False
    archive_sources: bool = False


@dataclass(frozen=True, slots=True)
class SourceSyncResult:
    source_count: int = 0
    selected_video_count: int = 0
    extracted_count: int = 0
    extraction_skipped_count: int = 0
    extraction_failed_count: int = 0
    registered_artifact_count: int = 0
    missing_path_count: int = 0
    archive_failure_count: int = 0


@dataclass(frozen=True, slots=True)
class SourceSyncDependencies:
    list_imported_sources: SyncOperation = imported_source_ids
    discover: SyncOperation = discover_sources_service
    fetch_captions: SyncOperation = fetch_captions_service
    transcribe: SyncOperation = transcribe_videos_service
    extract: SyncOperation = extract_batch
    register_media: SyncOperation = backfill_existing_media_artifacts
    archive_source: SyncOperation = archive_source_media
    archive_lock_held: Callable[[Path], bool] = media_archive_lock_held
    disk_usage: DiskUsage = shutil.disk_usage
    sleeper: Sleeper = time.sleep
    minimum_free_fraction: float = MIN_SYNC_FREE_DISK_FRACTION
    initial_wait_seconds: float = SYNC_ARCHIVE_WAIT_INITIAL_SECONDS
    maximum_wait_seconds: float = SYNC_ARCHIVE_WAIT_MAX_SECONDS


def projected_transcription_disk_bytes(
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
        if not should_transcribe_video(
            database,
            video.id,
            missing_only=captions_missing_only,
            captions_missing_only=captions_missing_only,
        ):
            continue
        duration = video.duration_seconds or SYNC_UNKNOWN_VIDEO_DURATION_SECONDS
        projected += int(duration * SYNC_AUDIO_RESERVATION_BYTES_PER_SECOND)
    return projected


def format_sync_bytes(value: int) -> str:
    amount = float(max(0, value))
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if amount < 1024 or unit == "TiB":
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{amount:.1f} TiB"


@dataclass(slots=True)
class _ArchiveCoordinator:
    database: Database
    app_paths: AppPaths
    enabled: bool
    report: SyncProgressCallback
    archive_source: SyncOperation
    archive_lock_held: Callable[[Path], bool]
    disk_usage: DiskUsage
    sleeper: Sleeper
    minimum_free_fraction: float
    initial_wait_seconds: float
    maximum_wait_seconds: float
    executor: ThreadPoolExecutor | None = field(init=False)
    pending: list[tuple[int, Future[object]]] = field(init=False)
    failure_count: int = field(init=False)

    def __post_init__(self) -> None:
        self.executor = ThreadPoolExecutor(max_workers=1) if self.enabled else None
        self.pending: list[tuple[int, Future[object]]] = []
        self.failure_count = 0

    def _finish(self, source_id: int, future: Future[object]) -> None:
        try:
            archive = future.result()
        except (OSError, RuntimeError, ValueError) as error:
            self.failure_count += 1
            self.report(f"Archive worker failed for source #{source_id}: {error}")
            return
        counts = archive.counts
        self.report(
            f"Archived source #{source_id}: archived={counts['archived']}, "
            f"already_archived={counts['already_archived']}, "
            f"unavailable={counts['destination_unavailable']}, "
            f"failed={counts['failed']}."
        )
        self.failure_count += counts["destination_unavailable"] + counts["failed"]
        if counts["destination_unavailable"] or counts["failed"]:
            self.report(
                "Some source audio remains local and will be retried by the next "
                "archive run; download admission remains governed by disk reserve."
            )

    def reap(self, *, block_one: bool = False) -> None:
        if block_one and self.pending:
            source_id, future = self.pending.pop(0)
            self._finish(source_id, future)
        completed = [item for item in self.pending if item[1].done()]
        for source_id, future in completed:
            self.pending.remove((source_id, future))
            self._finish(source_id, future)

    def require_disk_reserve(self, source_id: int, projected_bytes: int) -> None:
        self.reap()
        wait_seconds = self.initial_wait_seconds
        while True:
            disk = self.disk_usage(self.app_paths.root)
            required_free = int(disk.total * self.minimum_free_fraction)
            projected_free = disk.free - projected_bytes
            if projected_free >= required_free:
                self.report(
                    f"Disk admission for source #{source_id}: "
                    f"{disk.free / disk.total:.1%} free, "
                    f"reserving {format_sync_bytes(projected_bytes)}, "
                    f"projected={projected_free / disk.total:.1%}."
                )
                return
            archive_active = bool(self.pending) or self.archive_lock_held(
                self.app_paths.root
            )
            if archive_active:
                self.report(
                    f"Waiting for archival before source #{source_id}: projected "
                    f"local free space would be {projected_free / disk.total:.1%}; "
                    f"checking again in {wait_seconds:g}s."
                )
                if self.pending:
                    wait(
                        {future for _, future in self.pending},
                        timeout=wait_seconds,
                        return_when=FIRST_COMPLETED,
                    )
                    self.reap()
                else:
                    self.sleeper(wait_seconds)
                wait_seconds = min(
                    wait_seconds * 2,
                    self.maximum_wait_seconds,
                )
                continue
            self.report(
                f"Stopping before audio download for source #{source_id}: "
                f"projected local free space would be "
                f"{projected_free / disk.total:.1%}; synchronization requires at "
                f"least {self.minimum_free_fraction:.1%}."
            )
            raise SourceSyncDiskReserveError(
                f"source #{source_id} would violate the disk reserve"
            )

    def queue(self, source_id: int, video_ids: set[int]) -> None:
        if self.executor is None:
            return
        future = self.executor.submit(
            self.archive_source,
            self.database,
            self.app_paths,
            video_ids=video_ids,
            wait_for_lock=True,
        )
        self.pending.append((source_id, future))
        self.report(
            f"Queued source #{source_id} for archival ({len(self.pending)} pending)."
        )

    def close(self) -> None:
        while self.pending:
            self.reap(block_one=True)
        if self.executor is not None:
            self.executor.shutdown(wait=True)


@dataclass(slots=True)
class _SyncCounts:
    selected: int = 0
    extracted: int = 0
    extraction_skipped: int = 0
    extraction_failed: int = 0
    registered: int = 0
    missing_paths: int = 0


def _acquire_source_videos(
    database: Database,
    request: SourceSyncRequest,
    source_id: int,
    *,
    base_dir: Path | None,
    report: SyncProgressCallback,
    coordinator: _ArchiveCoordinator,
    dependencies: SourceSyncDependencies,
) -> set[int]:
    recover_stale_transcribing_videos(
        database,
        database.list_videos_by_source_id(source_id),
    )
    discovery = dependencies.discover(
        limit=request.latest,
        source_id=source_id,
        base_dir=base_dir,
    )
    selected_video_ids = set(
        discovery.selected_video_ids_by_source.get(source_id, ())
    )
    if not selected_video_ids:
        report(
            f"No videos selected in the current latest-{request.latest} window for "
            f"source #{source_id}; skipping downstream processing."
        )
        return set()
    report(
        f"Selected {len(selected_video_ids)} video(s) for downstream processing "
        f"from source #{source_id}."
    )
    projected_bytes = projected_transcription_disk_bytes(
        database,
        source_id=source_id,
        captions_missing_only=not request.all_audio,
        video_ids=selected_video_ids,
    )
    coordinator.require_disk_reserve(source_id, projected_bytes)
    coordinate_transcript_acquisition(
        database,
        TranscriptCoordinationRequest(
            video_ids=frozenset(selected_video_ids),
            caption_video_ids=frozenset(selected_video_ids),
            missing_only=not request.all_audio,
            captions_missing_only=not request.all_audio,
            jobs=request.jobs,
            prep_jobs=request.download_jobs,
            base_dir=base_dir,
            allow_network=True,
            source_id=source_id,
        ),
        progress_callback=report,
        dependencies=TranscriptCoordinationDependencies(
            fetch_captions=dependencies.fetch_captions,
            transcribe=dependencies.transcribe,
            caption_retry_sleeper=dependencies.sleeper,
        ),
    )
    return selected_video_ids


def _finalize_source(
    database: Database,
    app_paths: AppPaths,
    request: SourceSyncRequest,
    source_id: int,
    selected_video_ids: set[int],
    *,
    report: SyncProgressCallback,
    coordinator: _ArchiveCoordinator,
    dependencies: SourceSyncDependencies,
) -> _SyncCounts:
    counts = _SyncCounts(selected=len(selected_video_ids))
    if request.extract_new:
        extraction = dependencies.extract(
            database,
            app_paths,
            source_id=source_id,
            video_ids=selected_video_ids,
            classifier=DEFAULT_CLASSIFIER,
            llm_model=None,
            recording_verifier_backend=DEFAULT_RECORDING_VERIFIER_BACKEND,
            workers=request.jobs,
            event_callback=lambda message: report(str(message)),
            progress_callback=lambda stage, current, total: report(
                f"  {stage} block {current}/{total}"
            ),
        )
        counts.extracted = extraction.processed
        counts.extraction_skipped = extraction.skipped
        counts.extraction_failed = extraction.failed
        report(
            f"Extracted {extraction.processed} video(s); "
            f"skipped {extraction.skipped}; failed {extraction.failed}."
        )
    source_videos = [
        video
        for video in database.list_videos_by_source_id(source_id)
        if video.id in selected_video_ids
    ]
    registration = [
        dependencies.register_media(
            database,
            app_paths,
            video_id=video.id,
        )
        for video in source_videos
    ]
    counts.registered = sum(item.artifacts_registered for item in registration)
    counts.missing_paths = sum(item.missing_paths for item in registration)
    report(
        f"Registered {counts.registered} media artifact(s) for source #{source_id}; "
        f"missing paths={counts.missing_paths}."
    )
    coordinator.queue(source_id, {video.id for video in source_videos})
    return counts


def _sync_source(
    database: Database,
    app_paths: AppPaths,
    request: SourceSyncRequest,
    source_id: int,
    *,
    base_dir: Path | None,
    report: SyncProgressCallback,
    coordinator: _ArchiveCoordinator,
    dependencies: SourceSyncDependencies,
) -> _SyncCounts:
    selected_video_ids = _acquire_source_videos(
        database,
        request,
        source_id,
        base_dir=base_dir,
        report=report,
        coordinator=coordinator,
        dependencies=dependencies,
    )
    if not selected_video_ids:
        return _SyncCounts()
    return _finalize_source(
        database,
        app_paths,
        request,
        source_id,
        selected_video_ids,
        report=report,
        coordinator=coordinator,
        dependencies=dependencies,
    )
def sync_imported_sources_workflow(
    database: Database,
    app_paths: AppPaths,
    request: SourceSyncRequest,
    *,
    base_dir: Path | None = None,
    progress_callback: SyncProgressCallback | None = None,
    dependencies: SourceSyncDependencies = SourceSyncDependencies(),
) -> SourceSyncResult:
    def report(message: str) -> None:
        if progress_callback is not None:
            progress_callback(message)

    if request.archive_sources and not request.extract_new:
        raise SourceSyncConfigurationError("--archive-sources requires --extract.")
    if (
        request.archive_sources
        and database.get_active_media_archive_destination() is None
    ):
        raise SourceSyncConfigurationError(
            "No media archive destination is configured. Run "
            "'pte media archive-sources --archive-root PATH' first."
        )
    source_ids = dependencies.list_imported_sources(database, request.provider)
    if not source_ids:
        raise SourceSyncConfigurationError(
            f"No imported sources found for provider {request.provider!r}."
        )

    coordinator = _ArchiveCoordinator(
        database=database,
        app_paths=app_paths,
        enabled=request.archive_sources,
        report=report,
        archive_source=dependencies.archive_source,
        archive_lock_held=dependencies.archive_lock_held,
        disk_usage=dependencies.disk_usage,
        sleeper=dependencies.sleeper,
        minimum_free_fraction=dependencies.minimum_free_fraction,
        initial_wait_seconds=dependencies.initial_wait_seconds,
        maximum_wait_seconds=dependencies.maximum_wait_seconds,
    )
    total = _SyncCounts()
    try:
        for index, source_id in enumerate(source_ids, start=1):
            coordinator.reap()
            coordinator.require_disk_reserve(source_id, 0)
            report(
                f"[{index}/{len(source_ids)}] Synchronizing imported source "
                f"#{source_id}"
            )
            counts = _sync_source(
                database,
                app_paths,
                request,
                source_id,
                base_dir=base_dir,
                report=report,
                coordinator=coordinator,
                dependencies=dependencies,
            )
            total.selected += counts.selected
            total.extracted += counts.extracted
            total.extraction_skipped += counts.extraction_skipped
            total.extraction_failed += counts.extraction_failed
            total.registered += counts.registered
            total.missing_paths += counts.missing_paths
    finally:
        coordinator.close()
    report(
        f"Synchronized {len(source_ids)} imported source(s); latest={request.latest}, "
        f"download_jobs={request.download_jobs}, transcription_jobs={request.jobs}, "
        f"extraction_jobs={request.jobs}, all_audio={request.all_audio}, "
        f"extract={request.extract_new}, archive_sources={request.archive_sources}."
    )
    return SourceSyncResult(
        source_count=len(source_ids),
        selected_video_count=total.selected,
        extracted_count=total.extracted,
        extraction_skipped_count=total.extraction_skipped,
        extraction_failed_count=total.extraction_failed,
        registered_artifact_count=total.registered,
        missing_path_count=total.missing_paths,
        archive_failure_count=coordinator.failure_count,
    )


def sync_imported_sources_service(
    request: SourceSyncRequest,
    base_dir: Path | None = None,
    *,
    progress_callback: SyncProgressCallback | None = None,
    dependencies: SourceSyncDependencies = SourceSyncDependencies(),
) -> SourceSyncResult:
    app_paths = build_paths(base_dir, remember=True)
    ensure_directories(app_paths)
    database = Database(app_paths.database)
    database.initialize()
    return sync_imported_sources_workflow(
        database,
        app_paths,
        request,
        base_dir=base_dir,
        progress_callback=progress_callback,
        dependencies=dependencies,
    )
