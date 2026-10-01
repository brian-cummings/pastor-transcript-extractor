from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import time
from typing import Callable, Literal

from pastor_transcript_extractor.config import (
    AppPaths,
    ToolConfig,
    build_paths,
    build_tool_config,
    ensure_directories,
)
from pastor_transcript_extractor.media import (
    NoCaptionsAvailableError,
    VideoNotYetAvailableError,
    VideoUnavailableError,
    YtDlpAuthenticationRequiredError,
    YtDlpConfigurationError,
    YtDlpRateLimitError,
)
from pastor_transcript_extractor.models import Video, VideoStatus
from pastor_transcript_extractor.sermon_policy import (
    duration_meets_sermon_minimum,
    duration_within_sermon_maximum,
    maximum_sermon_duration_seconds,
    minimum_sermon_duration_seconds,
    publication_is_not_future,
    video_is_sermon_eligible,
)
from pastor_transcript_extractor.storage import Database
from pastor_transcript_extractor.transcription import fetch_captions_video


CAPTION_RATE_LIMIT_BACKOFF_SECONDS: tuple[float, ...] = ()
CaptionProgressCallback = Callable[[str], None]
CaptionFetcher = Callable[[Database, AppPaths, ToolConfig, int], object]
CaptionOutcomeCallback = Callable[[int, "CaptionOutcome"], None]
CaptionRequestInterval = float | Callable[[], float]
CaptionCandidateFilter = Callable[[int], bool]
CaptionPacingCallback = Callable[[int], None]
CaptionRequestResultCallback = Callable[[bool], None]
Clock = Callable[[], float]
Sleeper = Callable[[float], None]
CaptionOutcome = Literal[
    "processed",
    "unavailable",
    "deferred",
    "failed",
    "retry",
]


class CaptionAcquisitionBlockedError(ValueError):
    """A batch-wide YouTube condition makes further requests unsafe."""


@dataclass(frozen=True, slots=True)
class CaptionAcquisitionRequest:
    source_id: int | None = None
    video_ids: frozenset[int] | None = None
    request_interval_seconds: CaptionRequestInterval = 0.0
    cookies_from_browser: str | None = None
    cookies: Path | None = None


@dataclass(frozen=True, slots=True)
class CaptionAcquisitionResult:
    selected_count: int = 0
    processed_count: int = 0
    skipped_count: int = 0
    unavailable_count: int = 0
    deferred_count: int = 0
    failed_count: int = 0
    below_minimum_count: int = 0
    above_maximum_count: int = 0
    future_count: int = 0


@dataclass(slots=True)
class _CaptionCounts:
    processed: int = 0
    skipped: int = 0
    unavailable: int = 0
    deferred: int = 0
    failed: int = 0


def _selected_videos(
    database: Database,
    request: CaptionAcquisitionRequest,
) -> list[Video]:
    videos = list(database.list_videos())
    if request.source_id is not None:
        videos = [video for video in videos if video.source_id == request.source_id]
    if request.video_ids is not None:
        videos = [video for video in videos if video.id in request.video_ids]
    return videos


def _bypass_counts(
    videos: list[Video],
    *,
    minimum_duration: float,
    maximum_duration: float,
) -> tuple[int, int, int]:
    future_count = sum(
        1 for video in videos if not publication_is_not_future(video.published_at)
    )
    below_minimum_count = sum(
        1
        for video in videos
        if not duration_meets_sermon_minimum(
            video.duration_seconds,
            minimum_seconds=minimum_duration,
        )
        and publication_is_not_future(video.published_at)
    )
    above_maximum_count = sum(
        1
        for video in videos
        if not duration_within_sermon_maximum(
            video.duration_seconds,
            maximum_seconds=maximum_duration,
        )
        and publication_is_not_future(video.published_at)
    )
    return below_minimum_count, above_maximum_count, future_count


def _report_bypasses(
    report: CaptionProgressCallback,
    *,
    below_minimum_count: int,
    above_maximum_count: int,
    future_count: int,
    minimum_duration: float,
    maximum_duration: float,
) -> None:
    if below_minimum_count:
        report(
            f"Bypassing {below_minimum_count} video(s) below the configured "
            f"{minimum_duration:g}-second sermon minimum."
        )
    if above_maximum_count:
        report(
            f"Bypassing {above_maximum_count} video(s) above the configured "
            f"{maximum_duration:g}-second sermon-video maximum."
        )
    if future_count:
        report(f"Bypassing {future_count} future event(s).")


def _video_is_eligible(
    video: Video,
    *,
    minimum_duration: float,
    maximum_duration: float,
) -> bool:
    return video_is_sermon_eligible(
        video.duration_seconds,
        video.published_at,
        minimum_seconds=minimum_duration,
        maximum_seconds=maximum_duration,
    )


def _has_acquired_transcript(database: Database, video_id: int) -> bool:
    return bool(database.list_transcript_artifacts_for_video(video_id))


def _failure_is_terminal_unavailable(video: Video) -> bool:
    return (
        video.status is VideoStatus.FAILED
        and bool(video.failure_reason)
        and "video unavailable" in video.failure_reason.lower()
    )


def _failure_is_retryable(video: Video) -> bool:
    if video.status is not VideoStatus.FAILED or not video.failure_reason:
        return False
    lowered = video.failure_reason.lower()
    return (
        "has not started yet" in lowered
        or "cannot solve youtube javascript challenges" in lowered
    )


@dataclass(slots=True)
class _CaptionRequestScheduler:
    database: Database
    app_paths: AppPaths
    tool_config: ToolConfig
    request_interval_seconds: CaptionRequestInterval
    report: CaptionProgressCallback
    fetch_captions: CaptionFetcher
    monotonic: Clock
    sleeper: Sleeper
    pacing_callback: CaptionPacingCallback | None = None
    request_result_callback: CaptionRequestResultCallback | None = None
    last_request_started: float | None = None

    def fetch(self, video: Video) -> object:
        for attempt in range(len(CAPTION_RATE_LIMIT_BACKOFF_SECONDS) + 1):
            if self.pacing_callback is not None:
                self.pacing_callback(video.id)
            request_interval = (
                self.request_interval_seconds()
                if callable(self.request_interval_seconds)
                else self.request_interval_seconds
            )
            if self.last_request_started is not None and request_interval > 0:
                remaining = request_interval - (
                    self.monotonic() - self.last_request_started
                )
                while remaining > 0:
                    interval = min(30.0, remaining)
                    self.sleeper(interval)
                    remaining -= interval
                    if self.pacing_callback is not None:
                        self.pacing_callback(video.id)
            self.last_request_started = self.monotonic()
            try:
                result = self.fetch_captions(
                    self.database,
                    self.app_paths,
                    self.tool_config,
                    video.id,
                )
            except YtDlpRateLimitError:
                if self.request_result_callback is not None:
                    self.request_result_callback(True)
                if attempt >= len(CAPTION_RATE_LIMIT_BACKOFF_SECONDS):
                    raise
                backoff = CAPTION_RATE_LIMIT_BACKOFF_SECONDS[attempt]
                self.report(
                    f"Caption request rate limited for video #{video.id}; "
                    f"retrying in {backoff:g}s."
                )
                self.sleeper(backoff)
            except Exception:
                if self.request_result_callback is not None:
                    self.request_result_callback(False)
                raise
            else:
                if self.request_result_callback is not None:
                    self.request_result_callback(False)
                return result
        raise AssertionError("unreachable caption retry state")


def _acquire_video(
    database: Database,
    video: Video,
    *,
    retrying: bool,
    scheduler: _CaptionRequestScheduler,
    report: CaptionProgressCallback,
) -> CaptionOutcome:
    try:
        action = "Retrying captions" if retrying else "Fetching captions"
        report(f"{action} for video #{video.id}: {video.title}")
        result = scheduler.fetch(video)
    except NoCaptionsAvailableError as error:
        database.mark_captions_unavailable(video.id, detail=str(error))
        if _failure_is_terminal_unavailable(video) or _failure_is_retryable(video):
            database.update_video_status(video.id, VideoStatus.DISCOVERED)
        report(f"No captions for video #{video.id}; leaving it for local transcription.")
        return "unavailable"
    except VideoNotYetAvailableError as error:
        database.update_video_status(video.id, VideoStatus.FAILED, str(error))
        report(f"Video #{video.id} has not started yet; deferring it.")
        return "deferred"
    except YtDlpConfigurationError as error:
        database.update_video_status(video.id, VideoStatus.FAILED, str(error))
        report(f"[red]yt-dlp configuration error[/red] for video #{video.id}: {error}")
        return "failed"
    except YtDlpRateLimitError as error:
        raise CaptionAcquisitionBlockedError(
            "YouTube rate limited caption acquisition."
        ) from error
    except YtDlpAuthenticationRequiredError as error:
        raise CaptionAcquisitionBlockedError(
            "YouTube requested authentication while acquiring captions. Stopped "
            "further caption requests; captions already persisted will be skipped "
            "on retry, and staged audio remains available for local transcription."
        ) from error
    except VideoUnavailableError as error:
        database.update_video_status(video.id, VideoStatus.FAILED, str(error))
        report(f"Video unavailable for video #{video.id}; skipping it.")
        return "failed"
    except Exception as error:
        database.update_video_status(video.id, VideoStatus.FAILED, str(error))
        if not retrying:
            report(
                f"[red]Failed to fetch captions[/red] video #{video.id}: "
                f"{error}; deferred for retry after the first pass"
            )
            return "retry"
        report(f"[red]Failed caption retry[/red] video #{video.id}: {error}")
        return "failed"
    report(f"Fetched captions for video #{video.id}: {result.raw_text_path}")
    return "processed"


def _run_acquisition_queue(
    database: Database,
    videos: list[Video],
    *,
    minimum_duration: float,
    maximum_duration: float,
    initial_skipped: int,
    scheduler: _CaptionRequestScheduler,
    report: CaptionProgressCallback,
    outcome_callback: CaptionOutcomeCallback | None,
    candidate_filter: CaptionCandidateFilter | None,
) -> _CaptionCounts:
    counts = _CaptionCounts(skipped=initial_skipped)
    attempts: dict[int, int] = {}
    for video in videos:
        attempts[video.id] = attempts.get(video.id, 0) + 1
        if not _video_is_eligible(
            video,
            minimum_duration=minimum_duration,
            maximum_duration=maximum_duration,
        ):
            continue
        if _has_acquired_transcript(database, video.id):
            counts.skipped += 1
            continue
        if candidate_filter is not None and not candidate_filter(video.id):
            counts.skipped += 1
            continue
        if database.caption_is_known_unavailable(video.id):
            counts.unavailable += 1
            if outcome_callback is not None:
                outcome_callback(video.id, "unavailable")
            continue

        outcome = _acquire_video(
            database,
            video,
            retrying=attempts[video.id] > 1,
            scheduler=scheduler,
            report=report,
        )
        if outcome != "retry" and outcome_callback is not None:
            outcome_callback(video.id, outcome)
        if outcome == "processed":
            counts.processed += 1
        elif outcome == "unavailable":
            counts.unavailable += 1
        elif outcome == "deferred":
            counts.deferred += 1
        elif outcome == "failed":
            counts.failed += 1
        elif outcome == "retry":
            videos.append(video)
    return counts


def acquire_captions(
    database: Database,
    app_paths: AppPaths,
    tool_config: ToolConfig,
    request: CaptionAcquisitionRequest,
    *,
    progress_callback: CaptionProgressCallback | None = None,
    fetch_captions: CaptionFetcher = fetch_captions_video,
    monotonic: Clock = time.monotonic,
    sleeper: Sleeper = time.sleep,
    outcome_callback: CaptionOutcomeCallback | None = None,
    candidate_filter: CaptionCandidateFilter | None = None,
    pacing_callback: CaptionPacingCallback | None = None,
    request_result_callback: CaptionRequestResultCallback | None = None,
) -> CaptionAcquisitionResult:
    """Acquire captions in sequence, retrying transient per-video failures once."""

    def report(message: str) -> None:
        if progress_callback is not None:
            progress_callback(message)

    videos = _selected_videos(database, request)
    if not videos:
        report("No videos queued.")
        return CaptionAcquisitionResult()

    minimum_duration = minimum_sermon_duration_seconds()
    maximum_duration = maximum_sermon_duration_seconds()
    below_minimum, above_maximum, future = _bypass_counts(
        videos,
        minimum_duration=minimum_duration,
        maximum_duration=maximum_duration,
    )
    _report_bypasses(
        report,
        below_minimum_count=below_minimum,
        above_maximum_count=above_maximum,
        future_count=future,
        minimum_duration=minimum_duration,
        maximum_duration=maximum_duration,
    )

    selected_count = len(videos)
    scheduler = _CaptionRequestScheduler(
        database=database,
        app_paths=app_paths,
        tool_config=tool_config,
        request_interval_seconds=request.request_interval_seconds,
        report=report,
        fetch_captions=fetch_captions,
        monotonic=monotonic,
        sleeper=sleeper,
        pacing_callback=pacing_callback,
        request_result_callback=request_result_callback,
    )
    counts = _run_acquisition_queue(
        database,
        videos,
        minimum_duration=minimum_duration,
        maximum_duration=maximum_duration,
        initial_skipped=below_minimum + above_maximum + future,
        scheduler=scheduler,
        report=report,
        outcome_callback=outcome_callback,
        candidate_filter=candidate_filter,
    )

    report(
        f"Fetched captions for {counts.processed} video(s); "
        f"skipped {counts.skipped}; unavailable {counts.unavailable}; "
        f"deferred {counts.deferred}; failed {counts.failed}."
    )
    return CaptionAcquisitionResult(
        selected_count=selected_count,
        processed_count=counts.processed,
        skipped_count=counts.skipped,
        unavailable_count=counts.unavailable,
        deferred_count=counts.deferred,
        failed_count=counts.failed,
        below_minimum_count=below_minimum,
        above_maximum_count=above_maximum,
        future_count=future,
    )


def fetch_captions_service(
    source_id: int | None = None,
    base_dir: Path | None = None,
    video_ids: set[int] | None = None,
    request_interval_seconds: CaptionRequestInterval = 0.0,
    cookies_from_browser: str | None = None,
    cookies: Path | None = None,
    *,
    progress_callback: CaptionProgressCallback | None = None,
    outcome_callback: CaptionOutcomeCallback | None = None,
    candidate_filter: CaptionCandidateFilter | None = None,
    pacing_callback: CaptionPacingCallback | None = None,
    request_result_callback: CaptionRequestResultCallback | None = None,
    fetch_captions: CaptionFetcher = fetch_captions_video,
    monotonic: Clock = time.monotonic,
    sleeper: Sleeper = time.sleep,
) -> CaptionAcquisitionResult:
    app_paths = build_paths(base_dir, remember=True)
    ensure_directories(app_paths)
    database = Database(app_paths.database)
    database.initialize()
    tool_config = build_tool_config()
    if cookies_from_browser is not None or cookies is not None:
        tool_config = replace(
            tool_config,
            yt_dlp_cookies_from_browser=cookies_from_browser,
            yt_dlp_cookies_path=cookies,
        )
    if (
        tool_config.yt_dlp_cookies_from_browser is not None
        and tool_config.yt_dlp_cookies_path is not None
    ):
        raise ValueError(
            "Use either --cookies-from-browser or --cookies for YouTube, not both."
        )
    return acquire_captions(
        database,
        app_paths,
        tool_config,
        CaptionAcquisitionRequest(
            source_id=source_id,
            video_ids=None if video_ids is None else frozenset(video_ids),
            request_interval_seconds=request_interval_seconds,
            cookies_from_browser=cookies_from_browser,
            cookies=cookies,
        ),
        progress_callback=progress_callback,
        outcome_callback=outcome_callback,
        candidate_filter=candidate_filter,
        pacing_callback=pacing_callback,
        request_result_callback=request_result_callback,
        fetch_captions=fetch_captions,
        monotonic=monotonic,
        sleeper=sleeper,
    )
