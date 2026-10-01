from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field, replace
import os
from pathlib import Path
from threading import Lock
from typing import Callable, Iterator

from pastor_transcript_extractor.config import (
    AppPaths,
    ToolConfig,
    build_paths,
    build_tool_config,
    ensure_directories,
)
from pastor_transcript_extractor.models import TranscriptSourceKind, Video, VideoStatus
from pastor_transcript_extractor.sermon_policy import (
    duration_meets_sermon_minimum,
    duration_within_sermon_maximum,
    maximum_sermon_duration_seconds,
    minimum_sermon_duration_seconds,
    publication_is_not_future,
    video_is_sermon_eligible,
)
from pastor_transcript_extractor.storage import Database
from pastor_transcript_extractor.transcription import (
    PreparedTranscriptInput,
    complete_transcription_video,
    prepare_transcription_input,
)
from pastor_transcript_extractor.workflows.transcription_events import (
    STAGE_LABELS,
    STAGE_QUEUED_PREP,
    STAGE_QUEUED_TRANSCRIBE,
    TranscriptionBatchFinished,
    TranscriptionBatchStarted,
    TranscriptionEvent,
    TranscriptionEventCallback,
    TranscriptionMessage,
    TranscriptionProgressed,
    TranscriptionResult,
    TranscriptionRetrying,
    TranscriptionStageChanged,
    TranscriptionTaskSubmitted,
    TranscriptionVideoFinished,
    TranscriptionVideoQueued,
)


DEFAULT_TRANSCRIBE_JOBS = 2
DEFAULT_PREP_WORKERS = 2


@dataclass(frozen=True, slots=True)
class TranscriptionRequest:
    missing_only: bool = False
    captions_missing_only: bool = True
    jobs: int = DEFAULT_TRANSCRIBE_JOBS
    source_id: int | None = None
    prep_jobs: int = DEFAULT_PREP_WORKERS
    video_ids: frozenset[int] | None = None
    allow_network: bool = True
    retry_failed_once: bool = True


StageCallback = Callable[[str], None]
ProgressCallback = Callable[[int], None]
PrepareTranscription = Callable[
    [Database, AppPaths, ToolConfig, int, StageCallback | None, bool],
    PreparedTranscriptInput,
]
CompleteTranscription = Callable[
    [
        Database,
        ToolConfig,
        PreparedTranscriptInput,
        ProgressCallback | None,
        StageCallback | None,
    ],
    None,
]


def default_transcribe_jobs() -> int:
    return min(DEFAULT_TRANSCRIBE_JOBS, max(1, os.cpu_count() or 1))


def _is_terminal_unavailable(
    video_status: VideoStatus,
    failure_reason: str | None,
) -> bool:
    return (
        video_status is VideoStatus.FAILED
        and bool(failure_reason)
        and "video unavailable" in failure_reason.lower()
    )


def _is_retryable_fetch_failure(
    video_status: VideoStatus,
    failure_reason: str | None,
) -> bool:
    if video_status is not VideoStatus.FAILED or not failure_reason:
        return False
    lowered = failure_reason.lower()
    return (
        "has not started yet" in lowered
        or "cannot solve youtube javascript challenges" in lowered
    )


def should_transcribe_video(
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
    if _is_terminal_unavailable(
        video.status,
        video.failure_reason,
    ) or _is_retryable_fetch_failure(video.status, video.failure_reason):
        return False

    latest_artifact = database.get_latest_transcript_artifact_for_video(video.id)
    if missing_only and latest_artifact is not None:
        return False
    if (
        captions_missing_only
        and latest_artifact is not None
        and latest_artifact.source_kind == TranscriptSourceKind.CAPTIONS
    ):
        return False
    return not (
        latest_artifact is not None
        and latest_artifact.source_kind == TranscriptSourceKind.LOCAL_ASR
        and video.status
        in {
            VideoStatus.TRANSCRIBING_LOCAL,
            VideoStatus.TRANSCRIBED_LOCAL,
            VideoStatus.EXTRACTED,
            VideoStatus.EXPORTED,
        }
    )


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


def recover_stale_transcribing_videos(
    database: Database,
    videos: list[Video],
) -> None:
    for video in videos:
        if video.status != VideoStatus.TRANSCRIBING_LOCAL:
            continue
        latest_artifact = database.get_latest_transcript_artifact_for_video(video.id)
        if (
            latest_artifact is not None
            and latest_artifact.source_kind == TranscriptSourceKind.LOCAL_ASR
        ):
            database.update_video_status(video.id, VideoStatus.TRANSCRIBED_LOCAL)
            continue
        marker = video.failure_reason or ""
        if marker.startswith("transcription_previous_status:"):
            previous_value = marker.partition(":")[2]
            try:
                previous_status = VideoStatus(previous_value)
            except ValueError:
                previous_status = None
            if (
                previous_status is not None
                and previous_status is not VideoStatus.TRANSCRIBING_LOCAL
            ):
                database.update_video_status(video.id, previous_status)
                continue
        if database.get_latest_extraction_result_for_video(video.id) is not None:
            database.update_video_status(video.id, VideoStatus.EXTRACTED)
            continue
        if (
            latest_artifact is not None
            and latest_artifact.source_kind == TranscriptSourceKind.CAPTIONS
        ):
            database.update_video_status(video.id, VideoStatus.TRANSCRIPT_FETCHED)
            continue
        database.update_video_status(video.id, VideoStatus.DISCOVERED)


def _selected_videos(
    database: Database,
    request: TranscriptionRequest,
) -> list[Video]:
    videos = list(database.list_videos())
    if request.source_id is not None:
        videos = [video for video in videos if video.source_id == request.source_id]
    if request.video_ids is not None:
        videos = [video for video in videos if video.id in request.video_ids]
    return videos


def _bypass_counts(videos: list[Video]) -> tuple[int, int, int, float, float]:
    minimum_duration = minimum_sermon_duration_seconds()
    maximum_duration = maximum_sermon_duration_seconds()
    future = sum(
        1 for video in videos if not publication_is_not_future(video.published_at)
    )
    below_minimum = sum(
        1
        for video in videos
        if not duration_meets_sermon_minimum(
            video.duration_seconds,
            minimum_seconds=minimum_duration,
        )
        and publication_is_not_future(video.published_at)
    )
    above_maximum = sum(
        1
        for video in videos
        if not duration_within_sermon_maximum(
            video.duration_seconds,
            maximum_seconds=maximum_duration,
        )
        and publication_is_not_future(video.published_at)
    )
    return below_minimum, above_maximum, future, minimum_duration, maximum_duration


def _stage_callback(
    video_id: int,
    emit: TranscriptionEventCallback,
) -> StageCallback:
    lock = Lock()
    state = {"last_stage": STAGE_QUEUED_PREP}

    def callback(stage: str) -> None:
        label = STAGE_LABELS.get(stage, stage)
        with lock:
            if label == state["last_stage"]:
                return
            state["last_stage"] = label
        emit(TranscriptionStageChanged(video_id, label))

    return callback


def _progress_callback(
    video_id: int,
    emit: TranscriptionEventCallback,
) -> ProgressCallback:
    lock = Lock()
    state = {"last_percent": -1}

    def callback(percent: int) -> None:
        bounded = max(0, min(percent, 100))
        with lock:
            if bounded <= state["last_percent"]:
                return
            state["last_percent"] = bounded
        emit(TranscriptionProgressed(video_id, bounded))

    return callback


@dataclass(slots=True)
class _PassState:
    processed: int = 0
    failed: int = 0
    failed_video_ids: set[int] = field(default_factory=set)


@dataclass(slots=True)
class _TranscriptionPipeline:
    database: Database
    app_paths: AppPaths
    tool_config: ToolConfig
    request: TranscriptionRequest
    claimed_videos: list[Video]
    emit: TranscriptionEventCallback
    prepare: PrepareTranscription
    complete: CompleteTranscription
    state: _PassState = field(default_factory=_PassState)
    prep_futures: dict[Future[PreparedTranscriptInput], Video] = field(
        default_factory=dict
    )
    transcribe_futures: dict[Future[None], Video] = field(default_factory=dict)
    pending: Iterator[Video] = field(init=False)

    def __post_init__(self) -> None:
        self.pending = iter(self.claimed_videos)

    @property
    def total(self) -> int:
        return len(self.claimed_videos)

    def submit_prep(self, executor: ThreadPoolExecutor) -> bool:
        video = next(self.pending, None)
        if video is None:
            return False
        self.emit(TranscriptionTaskSubmitted(video.id, video.title))
        future = executor.submit(
            self.prepare,
            self.database,
            self.app_paths,
            self.tool_config,
            video.id,
            _stage_callback(video.id, self.emit),
            self.request.allow_network,
        )
        self.prep_futures[future] = video
        return True

    def handle_prepared(
        self,
        done: set[Future[PreparedTranscriptInput]],
        transcribe_executor: ThreadPoolExecutor,
    ) -> None:
        for future in done:
            video = self.prep_futures.pop(future)
            try:
                prepared = future.result()
            except Exception as error:
                self._record_failure(video, error)
                continue
            self.emit(
                TranscriptionStageChanged(video.id, STAGE_QUEUED_TRANSCRIBE)
            )
            future = transcribe_executor.submit(
                self.complete,
                self.database,
                self.tool_config,
                prepared,
                _progress_callback(video.id, self.emit),
                _stage_callback(video.id, self.emit),
            )
            self.transcribe_futures[future] = video

    def handle_completed(self, done: set[Future[None]]) -> None:
        for future in done:
            video = self.transcribe_futures.pop(future)
            try:
                future.result()
            except Exception as error:
                self._record_failure(video, error)
                continue
            self.state.processed += 1
            self.emit(
                TranscriptionVideoFinished(
                    self.state.processed + self.state.failed,
                    self.total,
                    video.id,
                    video.title,
                )
            )

    def _record_failure(self, video: Video, error: Exception) -> None:
        self.database.update_video_status(
            video.id,
            VideoStatus.FAILED,
            str(error),
        )
        self.state.failed += 1
        self.state.failed_video_ids.add(video.id)
        self.emit(
            TranscriptionVideoFinished(
                self.state.processed + self.state.failed,
                self.total,
                video.id,
                video.title,
                str(error),
            )
        )

    def run(self) -> _PassState:
        prep_workers = min(self.request.prep_jobs, self.total)
        transcribe_workers = min(self.request.jobs, self.total)
        with (
            ThreadPoolExecutor(max_workers=prep_workers) as prep_executor,
            ThreadPoolExecutor(max_workers=transcribe_workers) as transcribe_executor,
        ):
            for _ in range(prep_workers):
                if not self.submit_prep(prep_executor):
                    break
            while self.prep_futures or self.transcribe_futures:
                if self.prep_futures:
                    done, _ = wait(
                        set(self.prep_futures),
                        timeout=0.05,
                        return_when=FIRST_COMPLETED,
                    )
                    self.handle_prepared(done, transcribe_executor)
                if self.transcribe_futures:
                    done, _ = wait(
                        set(self.transcribe_futures),
                        timeout=0.05,
                        return_when=FIRST_COMPLETED,
                    )
                    self.handle_completed(done)
                while (
                    len(self.prep_futures) < prep_workers
                    and len(self.prep_futures) + len(self.transcribe_futures)
                    < prep_workers + transcribe_workers
                ):
                    if not self.submit_prep(prep_executor):
                        break
        return self.state


def _run_claimed_videos(
    database: Database,
    app_paths: AppPaths,
    tool_config: ToolConfig,
    request: TranscriptionRequest,
    claimed_videos: list[Video],
    *,
    emit: TranscriptionEventCallback,
    prepare: PrepareTranscription,
    complete: CompleteTranscription,
) -> _PassState:
    return _TranscriptionPipeline(
        database=database,
        app_paths=app_paths,
        tool_config=tool_config,
        request=request,
        claimed_videos=claimed_videos,
        emit=emit,
        prepare=prepare,
        complete=complete,
    ).run()
@dataclass(frozen=True, slots=True)
class _PreparedBatch:
    selected_count: int
    claimed_videos: tuple[Video, ...]
    skipped_count: int
    below_minimum_count: int
    above_maximum_count: int
    future_count: int


def _prepare_batch(
    database: Database,
    videos: list[Video],
    request: TranscriptionRequest,
    emit: TranscriptionEventCallback,
) -> _PreparedBatch:
    below, above, future, minimum_duration, maximum_duration = _bypass_counts(videos)
    if below:
        emit(
            TranscriptionMessage(
                f"Bypassing {below} video(s) below the configured "
                f"{minimum_duration:g}-second sermon minimum."
            )
        )
    if above:
        emit(
            TranscriptionMessage(
                f"Bypassing {above} video(s) above the configured "
                f"{maximum_duration:g}-second sermon-video maximum."
            )
        )
    if future:
        emit(TranscriptionMessage(f"Bypassing {future} future event(s)."))

    eligible = [
        video
        for video in videos
        if video_is_sermon_eligible(
            video.duration_seconds,
            video.published_at,
            minimum_seconds=minimum_duration,
            maximum_seconds=maximum_duration,
        )
    ]
    recover_stale_transcribing_videos(database, eligible)
    eligible = [database.get_video_by_id(video.id) or video for video in eligible]

    skipped = below + above + future
    claimed: list[Video] = []
    for video in eligible:
        if not should_transcribe_video(
            database,
            video.id,
            missing_only=request.missing_only,
            captions_missing_only=request.captions_missing_only,
        ) or not _claim_video_for_transcription(database, video.id):
            skipped += 1
            continue
        claimed.append(video)
    return _PreparedBatch(
        selected_count=len(videos),
        claimed_videos=tuple(claimed),
        skipped_count=skipped,
        below_minimum_count=below,
        above_maximum_count=above,
        future_count=future,
    )


def _pass_result(
    batch: _PreparedBatch,
    state: _PassState | None = None,
) -> TranscriptionResult:
    state = state or _PassState()
    return TranscriptionResult(
        selected_count=batch.selected_count,
        claimed_count=len(batch.claimed_videos),
        processed_count=state.processed,
        skipped_count=batch.skipped_count,
        failed_count=state.failed,
        failed_video_ids=frozenset(state.failed_video_ids),
        below_minimum_count=batch.below_minimum_count,
        above_maximum_count=batch.above_maximum_count,
        future_count=batch.future_count,
    )


def _run_transcription_pass(
    database: Database,
    app_paths: AppPaths,
    tool_config: ToolConfig,
    request: TranscriptionRequest,
    *,
    emit: TranscriptionEventCallback,
    prepare: PrepareTranscription,
    complete: CompleteTranscription,
) -> TranscriptionResult:
    videos = _selected_videos(database, request)
    if not videos:
        emit(TranscriptionMessage("No videos queued."))
        return TranscriptionResult()

    batch = _prepare_batch(database, videos, request, emit)
    if not batch.claimed_videos:
        result = _pass_result(batch)
        emit(TranscriptionBatchFinished(result))
        return result

    workers = min(request.jobs, len(batch.claimed_videos))
    emit(TranscriptionBatchStarted(len(batch.claimed_videos), workers))
    for index, video in enumerate(batch.claimed_videos, start=1):
        emit(
            TranscriptionVideoQueued(
                index,
                len(batch.claimed_videos),
                video.id,
                video.title,
            )
        )
    state = _run_claimed_videos(
        database,
        app_paths,
        tool_config,
        request,
        list(batch.claimed_videos),
        emit=emit,
        prepare=prepare,
        complete=complete,
    )
    result = _pass_result(batch, state)
    emit(TranscriptionBatchFinished(result))
    return result
def transcribe_videos(
    database: Database,
    app_paths: AppPaths,
    tool_config: ToolConfig,
    request: TranscriptionRequest,
    *,
    event_callback: TranscriptionEventCallback | None = None,
    prepare: PrepareTranscription = prepare_transcription_input,
    complete: CompleteTranscription = complete_transcription_video,
) -> TranscriptionResult:
    """Run bounded download/normalization and ASR stages with one failure retry."""

    def emit(event: TranscriptionEvent) -> None:
        if event_callback is not None:
            event_callback(event)

    first = _run_transcription_pass(
        database,
        app_paths,
        tool_config,
        request,
        emit=emit,
        prepare=prepare,
        complete=complete,
    )
    if not first.failed_video_ids or not request.retry_failed_once:
        return first

    emit(TranscriptionRetrying(len(first.failed_video_ids)))
    retry = _run_transcription_pass(
        database,
        app_paths,
        tool_config,
        replace(
            request,
            video_ids=first.failed_video_ids,
            retry_failed_once=False,
        ),
        emit=emit,
        prepare=prepare,
        complete=complete,
    )
    return TranscriptionResult(
        selected_count=first.selected_count,
        claimed_count=first.claimed_count + retry.claimed_count,
        processed_count=first.processed_count + retry.processed_count,
        skipped_count=first.skipped_count,
        failed_count=retry.failed_count,
        failed_video_ids=retry.failed_video_ids,
        below_minimum_count=first.below_minimum_count,
        above_maximum_count=first.above_maximum_count,
        future_count=first.future_count,
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
    _coordinated: bool = False,
    *,
    event_callback: TranscriptionEventCallback | None = None,
    database: Database | None = None,
    app_paths: AppPaths | None = None,
    tool_config: ToolConfig | None = None,
    prepare: PrepareTranscription = prepare_transcription_input,
    complete: CompleteTranscription = complete_transcription_video,
) -> TranscriptionResult:
    del _coordinated
    if app_paths is None:
        app_paths = build_paths(base_dir, remember=True)
    ensure_directories(app_paths)
    if database is None:
        database = Database(app_paths.database)
        database.initialize()
    if tool_config is None:
        tool_config = build_tool_config()
    return transcribe_videos(
        database,
        app_paths,
        tool_config,
        TranscriptionRequest(
            missing_only=missing_only,
            captions_missing_only=captions_missing_only,
            jobs=jobs,
            source_id=source_id,
            prep_jobs=prep_jobs,
            video_ids=None if video_ids is None else frozenset(video_ids),
            allow_network=allow_network,
            retry_failed_once=_retry_failed_once,
        ),
        event_callback=event_callback,
        prepare=prepare,
        complete=complete,
    )
