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

    futures: list[Future[object]] = []
    queued_for_transcription: set[int] = set()

    def submit_transcription(
        executor: ThreadPoolExecutor | None,
        video_ids: set[int],
    ) -> None:
        if executor is None:
            return
        for video_id in sorted(
            _video_ids_without_transcripts(database, video_ids)
            - queued_for_transcription
        ):
            queued_for_transcription.add(video_id)
            transcribe_options: dict[str, object] = {
                "missing_only": request.missing_only,
                "captions_missing_only": request.captions_missing_only,
                "jobs": 1,
                "base_dir": request.base_dir,
                "video_ids": {video_id},
                "allow_network": request.allow_network,
            }
            if request.source_id is not None:
                transcribe_options["source_id"] = request.source_id
            futures.append(
                executor.submit(dependencies.transcribe, **transcribe_options)
            )

    executor = (
        None
        if request.captions_only
        else ThreadPoolExecutor(max_workers=request.jobs)
    )
    captions_blocked = False
    try:
        caption_video_ids = set(request.caption_video_ids)
        submit_transcription(executor, set(request.video_ids) - caption_video_ids)
        pending = _video_ids_without_transcripts(database, caption_video_ids)
        resolved: set[int] = set()

        def caption_outcome(video_id: int, outcome: str) -> None:
            resolved.add(video_id)
            if outcome == "unavailable":
                submit_transcription(executor, {video_id})

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
                submit_transcription(executor, pending - resolved)
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
                    submit_transcription(executor, pending)
                    break
                delay = CAPTION_BACKGROUND_RETRY_SECONDS[retry_index]
                retry_index += 1
                report(
                    "Caption acquisition remains rate limited; retrying "
                    f"{len(pending)} pending video(s) in {delay / 60:g} minute(s) "
                    "while available Whisper work continues."
                )
                dependencies.caption_retry_sleeper(delay)
        for future in futures:
            future.result()
    finally:
        if executor is not None:
            executor.shutdown(wait=True)
    return captions_blocked
