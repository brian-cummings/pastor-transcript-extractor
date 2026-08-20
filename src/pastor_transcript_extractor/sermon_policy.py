from __future__ import annotations

import math
import os
from datetime import datetime, timezone


DEFAULT_MINIMUM_SERMON_DURATION_SECONDS = 12 * 60
MINIMUM_SERMON_DURATION_ENV = "PTE_MIN_SERMON_DURATION_SECONDS"


def minimum_sermon_duration_seconds() -> float:
    raw_value = os.environ.get(MINIMUM_SERMON_DURATION_ENV)
    if raw_value is None or not raw_value.strip():
        return float(DEFAULT_MINIMUM_SERMON_DURATION_SECONDS)
    try:
        value = float(raw_value)
    except ValueError as error:
        raise ValueError(
            f"{MINIMUM_SERMON_DURATION_ENV} must be a positive number of seconds"
        ) from error
    if not math.isfinite(value) or value <= 0:
        raise ValueError(
            f"{MINIMUM_SERMON_DURATION_ENV} must be a positive number of seconds"
        )
    return value


def duration_meets_sermon_minimum(
    duration_seconds: float | int | None,
    *,
    minimum_seconds: float | None = None,
) -> bool:
    """Keep unknown durations eligible until authoritative metadata is available."""
    if duration_seconds is None:
        return True
    threshold = minimum_sermon_duration_seconds() if minimum_seconds is None else minimum_seconds
    return float(duration_seconds) >= threshold


def publication_is_not_future(
    published_at: datetime | str | None,
    *,
    now: datetime | None = None,
) -> bool:
    if published_at is None:
        return True
    if isinstance(published_at, str):
        try:
            resolved = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        except ValueError:
            # Do not discard malformed legacy metadata without stronger evidence.
            return True
    else:
        resolved = published_at
    if resolved.tzinfo is None:
        resolved = resolved.replace(tzinfo=timezone.utc)
    comparison_time = now or datetime.now(timezone.utc)
    if comparison_time.tzinfo is None:
        comparison_time = comparison_time.replace(tzinfo=timezone.utc)
    return resolved <= comparison_time


def video_is_sermon_eligible(
    duration_seconds: float | int | None,
    published_at: datetime | str | None,
    *,
    minimum_seconds: float | None = None,
    now: datetime | None = None,
) -> bool:
    return duration_meets_sermon_minimum(
        duration_seconds,
        minimum_seconds=minimum_seconds,
    ) and publication_is_not_future(published_at, now=now)


def format_minimum_sermon_duration(minimum_seconds: float) -> str:
    minutes = minimum_seconds / 60
    if minutes.is_integer():
        return f"{int(minutes)} minute"
    return f"{minutes:g} minute"
