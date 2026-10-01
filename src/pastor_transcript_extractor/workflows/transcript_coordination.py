from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
import time
from typing import Callable

from pastor_transcript_extractor.storage import Database
from pastor_transcript_extractor.workflows.caption_acquisition import (
    CaptionAcquisitionBlockedError,
)


TranscriptCoordinationOperation = Callable[..., object]
TranscriptCoordinationProgress = Callable[[str], None]
CAPTION_BACKGROUND_RETRY_SECONDS = (900.0, 1800.0, 3600.0)
CAPTION_REQUEST_INTERVAL_SECONDS = 15.0
CAPTION_MAX_REQUEST_INTERVAL_SECONDS = 900.0
CAPTION_REQUESTS_PER_TRANSCRIPTION = 2.0
WHISPER_REFILL_INTERVAL_SECONDS = 30.0
WHISPER_QUEUE_MULTIPLIER = 2


def _adaptive_caption_request_interval(
    *,
    configured_seconds: float,
    elapsed_seconds: float,
    completed_transcriptions: int,
) -> float:
    adaptive_seconds = CAPTION_REQUEST_INTERVAL_SECONDS
    if completed_transcriptions > 0:
        aggregate_completion_seconds = (
            max(0.0, elapsed_seconds) / completed_transcriptions
        )
        adaptive_seconds = (
            aggregate_completion_seconds / CAPTION_REQUESTS_PER_TRANSCRIPTION
        )
    return max(
        configured_seconds,
        min(
            CAPTION_MAX_REQUEST_INTERVAL_SECONDS,
            max(CAPTION_REQUEST_INTERVAL_SECONDS, adaptive_seconds),
        ),
    )


@dataclass(frozen=True, slots=True)
class TranscriptCoordinationRequest:
    video_ids: frozenset[int]
    caption_video_ids: frozenset[int]
    captions_only: bool = False
    missing_only: bool = True
    captions_missing_only: bool = True
    jobs: int = 2
    prep_jobs: int | None = None
    base_dir: Path | None = None
    allow_network: bool = True
    source_id: int | None = None
    caption_request_interval_seconds: float = 0.0
    cookies_from_browser: str | None = None
    cookies: Path | None = None


@dataclass(frozen=True, slots=True)
class TranscriptCoordinationDependencies:
    fetch_captions: TranscriptCoordinationOperation
    transcribe: TranscriptCoordinationOperation
    caption_retry_sleeper: Callable[[float], None] = time.sleep


def _video_ids_without_transcripts(
    database: Database,
    video_ids: set[int],
) -> set[int]:
    lookup = getattr(database, "get_latest_transcript_artifact_for_video", None)
    if lookup is None:
        return set(video_ids)
    return {video_id for video_id in video_ids if lookup(video_id) is None}


def _known_caption_misses(
    database: Database,
    video_ids: set[int],
) -> set[int]:
    lookup = getattr(database, "known_caption_unavailable_video_ids", None)
    if lookup is None:
        return set()
    return set(lookup(video_ids))


def coordinate_transcript_acquisition(
    database: Database,
    request: TranscriptCoordinationRequest,
    *,
    progress_callback: TranscriptCoordinationProgress | None = None,
    dependencies: TranscriptCoordinationDependencies,
) -> bool:
    """Retry captions while safely transcribing only resolved caption misses."""

    def report(message: str) -> None:
        if progress_callback is not None:
            progress_callback(message)

    caption_options: dict[str, object] = {}
    if request.cookies_from_browser is not None:
        caption_options["cookies_from_browser"] = request.cookies_from_browser
    if request.cookies is not None:
        caption_options["cookies"] = request.cookies
    if request.source_id is not None:
        caption_options["source_id"] = request.source_id

    if not request.video_ids:
        dependencies.fetch_captions(
            base_dir=request.base_dir,
            video_ids=set(),
            request_interval_seconds=request.caption_request_interval_seconds,
            outcome_callback=lambda _video_id, _outcome: None,
            **caption_options,
        )
        if not request.captions_only:
            transcribe_options: dict[str, object] = {
                "missing_only": request.missing_only,
                "captions_missing_only": request.captions_missing_only,
                "jobs": request.jobs,
                "base_dir": request.base_dir,
                "video_ids": set(),
                "allow_network": request.allow_network,
            }
            if request.source_id is not None:
                transcribe_options["source_id"] = request.source_id
            if request.prep_jobs is not None:
                transcribe_options["prep_jobs"] = request.prep_jobs
            dependencies.transcribe(**transcribe_options)
        return False

    futures: list[tuple[Future[object], frozenset[int]]] = []
    queued_for_transcription: set[int] = set()
    ready_for_transcription: set[int] = set()
    transcription_started = False
    coordination_started_at = time.monotonic()

    def caption_request_interval() -> float:
        return _adaptive_caption_request_interval(
            configured_seconds=request.caption_request_interval_seconds,
            elapsed_seconds=time.monotonic() - coordination_started_at,
            completed_transcriptions=sum(
                1 for future, _batch in futures if future.done()
            ),
        )

    def dispatch_transcription(
        executor: ThreadPoolExecutor | None,
        video_ids: set[int],
    ) -> set[int]:
        nonlocal transcription_started
        if executor is None:
            return set()
        batch = set(
            _video_ids_without_transcripts(database, video_ids)
            - queued_for_transcription
        )
        if not batch:
            return set()
        if not transcription_started:
            report(
                "Whisper queue started; filling up to "
                f"{request.jobs} worker(s) as videos become ready."
            )
            transcription_started = True
        for video_id in sorted(batch):
            queued_for_transcription.add(video_id)
            transcribe_options: dict[str, object] = {
                "missing_only": request.missing_only,
                "captions_missing_only": request.captions_missing_only,
                "jobs": 1,
                "base_dir": request.base_dir,
                "video_ids": {video_id},
                "allow_network": request.allow_network,
                "_coordinated": True,
                "database": database,
            }
            if request.source_id is not None:
                transcribe_options["source_id"] = request.source_id
            if request.prep_jobs is not None:
                transcribe_options["prep_jobs"] = request.prep_jobs
            future = executor.submit(dependencies.transcribe, **transcribe_options)
            futures.append((future, frozenset({video_id})))
        return batch

    def refill_whisper_from_caption_candidates(
        pending_caption_ids: set[int],
    ) -> set[int]:
        active_or_queued = sum(
            len(batch) for future, batch in futures if not future.done()
        )
        target_queue_depth = request.jobs * WHISPER_QUEUE_MULTIPLIER
        available_queue_slots = max(0, target_queue_depth - active_or_queued)
        candidates = set(sorted(pending_caption_ids)[:available_queue_slots])
        dispatched = dispatch_transcription(executor, candidates)
        pending_caption_ids.difference_update(dispatched)
        return dispatched

    executor = (
        None
        if request.captions_only
        else ThreadPoolExecutor(max_workers=request.jobs)
    )
    captions_blocked = False
    try:
        caption_video_ids = set(request.caption_video_ids)
        known_caption_misses = _known_caption_misses(database, caption_video_ids)
        initial_transcription_ids = (
            set(request.video_ids)
            if not request.captions_missing_only
            else (set(request.video_ids) - caption_video_ids) | known_caption_misses
        )
        dispatch_transcription(
            executor,
            initial_transcription_ids,
        )
        pending = _video_ids_without_transcripts(
            database,
            caption_video_ids - known_caption_misses,
        )
        if pending:
            report(
                "Caption requests start 15 seconds apart and will slow with "
                "observed Whisper throughput."
            )
        resolved: set[int] = set()

        def caption_outcome(video_id: int, outcome: str) -> None:
            resolved.add(video_id)
            if outcome == "unavailable":
                ready_for_transcription.add(video_id)
                dispatched = dispatch_transcription(
                    executor,
                    ready_for_transcription,
                )
                ready_for_transcription.difference_update(dispatched)

        retry_index = 0
        while pending:
            try:
                dependencies.fetch_captions(
                    base_dir=request.base_dir,
                    video_ids=set(pending),
                    request_interval_seconds=caption_request_interval,
                    outcome_callback=caption_outcome,
                    **caption_options,
                )
                ready_for_transcription.update(pending - resolved)
                dispatched = dispatch_transcription(
                    executor,
                    ready_for_transcription,
                )
                ready_for_transcription.difference_update(dispatched)
                pending.clear()
            except CaptionAcquisitionBlockedError as error:
                pending -= resolved
                pending = _video_ids_without_transcripts(database, pending)
                resolved.clear()
                authentication_block = "authentication" in str(error).lower()
                if authentication_block:
                    captions_blocked = True
                    report(f"[yellow]Caption acquisition stopped[/yellow]: {error}")
                    ready_for_transcription.update(pending)
                    dispatch_transcription(executor, ready_for_transcription)
                    ready_for_transcription.clear()
                    break
                delay = CAPTION_BACKGROUND_RETRY_SECONDS[
                    min(retry_index, len(CAPTION_BACKGROUND_RETRY_SECONDS) - 1)
                ]
                retry_index += 1
                released_count = len(
                    refill_whisper_from_caption_candidates(pending)
                )
                report(
                    "Caption acquisition remains rate limited; retrying captions "
                    f"in {delay / 60:g} minute(s). Released {released_count} "
                    "unresolved video(s) to fill idle Whisper workers; remaining "
                    f"caption candidates={len(pending)}."
                )
                remaining_delay = delay
                while remaining_delay > 0 and pending:
                    interval = min(
                        WHISPER_REFILL_INTERVAL_SECONDS,
                        remaining_delay,
                    )
                    dependencies.caption_retry_sleeper(interval)
                    remaining_delay -= interval
                    refilled = refill_whisper_from_caption_candidates(pending)
                    if refilled:
                        report(
                            "Caption cooldown refilled "
                            f"{len(refilled)} idle Whisper worker(s); remaining "
                            f"caption candidates={len(pending)}."
                        )
        for future, _batch in futures:
            future.result()
    finally:
        if executor is not None:
            executor.shutdown(wait=True)
    return captions_blocked
