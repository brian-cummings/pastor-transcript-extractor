from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
import math
from pathlib import Path
import time
from typing import Callable

from pastor_transcript_extractor.storage import Database
from pastor_transcript_extractor.workflows.caption_acquisition import (
    CaptionAcquisitionBlockedError,
)


TranscriptCoordinationOperation = Callable[..., object]
TranscriptCoordinationProgress = Callable[[str], None]
CAPTION_BACKGROUND_RETRY_SECONDS = (300.0, 900.0, 1800.0)


@dataclass(frozen=True, slots=True)
class TranscriptCoordinationRequest:
    video_ids: frozenset[int]
    caption_video_ids: frozenset[int]
    captions_only: bool = False
    missing_only: bool = True
    captions_missing_only: bool = True
    jobs: int = 2
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
            dependencies.transcribe(**transcribe_options)
        return False

    futures: list[tuple[Future[object], frozenset[int]]] = []
    queued_for_transcription: set[int] = set()
    ready_for_transcription: set[int] = set()

    def dispatch_transcription(
        executor: ThreadPoolExecutor | None,
        video_ids: set[int],
    ) -> set[int]:
        if executor is None:
            return set()
        batch = set(
            _video_ids_without_transcripts(database, video_ids)
            - queued_for_transcription
        )
        if not batch:
            return set()
        queued_for_transcription.update(batch)
        transcribe_options: dict[str, object] = {
            "missing_only": request.missing_only,
            "captions_missing_only": request.captions_missing_only,
            "jobs": request.jobs,
            "base_dir": request.base_dir,
            "video_ids": batch,
            "allow_network": request.allow_network,
        }
        if request.source_id is not None:
            transcribe_options["source_id"] = request.source_id
        future = executor.submit(dependencies.transcribe, **transcribe_options)
        futures.append((future, frozenset(batch)))
        return batch

    def outstanding_transcription_count() -> int:
        return sum(len(batch) for future, batch in futures if not future.done())

    executor = (
        None
        if request.captions_only
        else ThreadPoolExecutor(max_workers=1)
    )
    captions_blocked = False
    try:
        caption_video_ids = set(request.caption_video_ids)
        known_caption_misses = _known_caption_misses(database, caption_video_ids)
        dispatch_transcription(
            executor,
            (set(request.video_ids) - caption_video_ids) | known_caption_misses,
        )
        pending = _video_ids_without_transcripts(
            database,
            caption_video_ids - known_caption_misses,
        )
        resolved: set[int] = set()

        def caption_outcome(video_id: int, outcome: str) -> None:
            resolved.add(video_id)
            if outcome == "unavailable":
                ready_for_transcription.add(video_id)
                if len(ready_for_transcription) >= request.jobs:
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
                    request_interval_seconds=request.caption_request_interval_seconds,
                    outcome_callback=caption_outcome,
                    **caption_options,
                )
                ready_for_transcription.update(pending - resolved)
                dispatch_transcription(executor, ready_for_transcription)
                ready_for_transcription.clear()
                pending.clear()
            except CaptionAcquisitionBlockedError as error:
                pending -= resolved
                pending = _video_ids_without_transcripts(database, pending)
                resolved.clear()
                authentication_block = "authentication" in str(error).lower()
                if authentication_block or retry_index >= len(
                    CAPTION_BACKGROUND_RETRY_SECONDS
                ):
                    captions_blocked = True
                    report(f"[yellow]Caption acquisition stopped[/yellow]: {error}")
                    ready_for_transcription.update(pending)
                    dispatch_transcription(executor, ready_for_transcription)
                    ready_for_transcription.clear()
                    break
                delay = CAPTION_BACKGROUND_RETRY_SECONDS[retry_index]
                retry_index += 1
                target_work = request.jobs * max(1, math.ceil(delay / 300.0))
                available_capacity = max(
                    0,
                    target_work - outstanding_transcription_count(),
                )
                dispatched: set[int] = set()
                if available_capacity > 0:
                    batch_target = max(request.jobs, available_capacity)
                    needed = max(
                        0,
                        batch_target - len(ready_for_transcription),
                    )
                    spillover = set(sorted(pending)[:needed])
                    pending -= spillover
                    ready_for_transcription.update(spillover)
                    dispatched = dispatch_transcription(
                        executor,
                        ready_for_transcription,
                    )
                    ready_for_transcription.difference_update(dispatched)
                if not pending:
                    dispatched.update(
                        dispatch_transcription(executor, ready_for_transcription)
                    )
                    ready_for_transcription.difference_update(dispatched)
                    report(
                        "Caption acquisition remains rate limited; released the "
                        f"remaining {len(dispatched)} video(s) to Whisper."
                    )
                    break
                if dispatched:
                    activity = f"released {len(dispatched)} video(s) to Whisper"
                else:
                    activity = (
                        f"kept {outstanding_transcription_count()} video(s) "
                        "queued or running in Whisper"
                    )
                report(
                    f"Caption acquisition remains rate limited; {activity} and "
                    f"will retry {len(pending)} caption candidate(s) in "
                    f"{delay / 60:g} minute(s)."
                )
                dependencies.caption_retry_sleeper(delay)
        for future, _batch in futures:
            future.result()
    finally:
        if executor is not None:
            executor.shutdown(wait=True)
    return captions_blocked
