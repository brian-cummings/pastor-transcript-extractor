from __future__ import annotations

import json
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def format_timestamp(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    hours, remainder = divmod(total, 3600)
    minutes, seconds_value = divmod(remainder, 60)
    return f"{hours:d}:{minutes:02d}:{seconds_value:02d}"


def youtube_timestamp_url(url: str, seconds: float) -> str:
    parsed = urlsplit(url)
    query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key not in {"t", "start"}]
    query.append(("t", f"{max(0, int(seconds))}s"))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))


def open_video_url(url: str) -> None:
    opened = webbrowser.open(url, new=2, autoraise=True)
    if not opened:
        raise RuntimeError(f"Could not open video URL: {url}")


def parse_timestamp(value: str, *, current: float | None = None) -> float:
    text = value.strip()
    if current is not None and text[:1] in {"+", "-"}:
        try:
            adjusted = current + float(text)
        except ValueError as error:
            raise ValueError("adjustment must be a number of seconds, such as +5 or -30") from error
        if adjusted < 0:
            raise ValueError("timestamp cannot be negative")
        return adjusted
    parts = text.split(":")
    if not 1 <= len(parts) <= 3:
        raise ValueError("timestamp must be seconds, MM:SS, or HH:MM:SS")
    try:
        numbers = [float(part) for part in parts]
    except ValueError as error:
        raise ValueError("timestamp contains a non-numeric component") from error
    if any(number < 0 for number in numbers):
        raise ValueError("timestamp cannot be negative")
    if len(numbers) == 1:
        return numbers[0]
    if numbers[-1] >= 60 or (len(numbers) == 3 and numbers[-2] >= 60):
        raise ValueError("minutes and seconds components must be less than 60")
    if len(numbers) == 2:
        return numbers[0] * 60 + numbers[1]
    return numbers[0] * 3600 + numbers[1] * 60 + numbers[2]


def parse_interruptions(value: str) -> list[tuple[float, float]]:
    text = value.strip()
    if not text:
        return []
    interruptions: list[tuple[float, float]] = []
    for item in text.split(","):
        parts = item.strip().split("-")
        if len(parts) != 2:
            raise ValueError("interruptions must use start-end pairs separated by commas")
        start = parse_timestamp(parts[0])
        end = parse_timestamp(parts[1])
        if end <= start:
            raise ValueError("interruption end must be after its start")
        interruptions.append((start, end))
    interruptions.sort()
    for previous, current in zip(interruptions, interruptions[1:]):
        if current[0] < previous[1]:
            raise ValueError("interruptions cannot overlap")
    return interruptions


def retained_spans(
    start_seconds: float,
    end_seconds: float,
    interruptions: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    if end_seconds <= start_seconds:
        raise ValueError("sermon end must be after sermon start")
    cursor = start_seconds
    spans: list[tuple[float, float]] = []
    for interruption_start, interruption_end in interruptions:
        if interruption_start < start_seconds or interruption_end > end_seconds:
            raise ValueError("interruptions must fall inside the sermon envelope")
        if interruption_start > cursor:
            spans.append((cursor, interruption_start))
        cursor = interruption_end
    if cursor < end_seconds:
        spans.append((cursor, end_seconds))
    if not spans:
        raise ValueError("interruptions cannot consume the entire sermon envelope")
    return spans


def transcript_context(
    segments: list[dict[str, Any]], timestamp: float, *, radius_seconds: float = 45.0
) -> str:
    lines: list[str] = []
    for segment in segments:
        start = segment.get("start_seconds")
        end = segment.get("end_seconds")
        text = segment.get("text")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or not isinstance(text, str):
            continue
        if float(end) < timestamp - radius_seconds or float(start) > timestamp + radius_seconds:
            continue
        marker = ">" if float(start) <= timestamp < float(end) else " "
        lines.append(f"{marker} [{format_timestamp(float(start))}] {text.strip()}")
    return "\n".join(lines) or "(no timestamped transcript context available)"


def suggested_envelope(
    payload: dict[str, Any], *, fallback_end_seconds: float | None = None
) -> tuple[float, float, str]:
    classification = payload.get("classification")
    segments = payload.get("segments")
    if isinstance(classification, dict) and isinstance(segments, list):
        indexes = classification.get("retained_segment_indexes")
        if isinstance(indexes, list):
            retained = [segments[index] for index in indexes if isinstance(index, int) and 0 <= index < len(segments)]
            starts = [item.get("start_seconds") for item in retained if isinstance(item, dict) and isinstance(item.get("start_seconds"), (int, float))]
            ends = [item.get("end_seconds") for item in retained if isinstance(item, dict) and isinstance(item.get("end_seconds"), (int, float))]
            if starts and ends:
                return float(min(starts)), float(max(ends)), str(classification.get("method", "classification"))
    window = payload.get("sermon_window")
    if isinstance(window, dict) and isinstance(window.get("start_seconds"), (int, float)) and isinstance(window.get("end_seconds"), (int, float)):
        return float(window["start_seconds"]), float(window["end_seconds"]), str(window.get("method", "rule_window"))
    if fallback_end_seconds is not None and fallback_end_seconds > 0:
        return 0.0, fallback_end_seconds, "no_candidate_full_video"
    raise ValueError("extraction has no suggested sermon boundary")


def draft_payload(
    *,
    video_id: str,
    source_url: str,
    start_seconds: float,
    end_seconds: float,
    proposal_source: str,
    selection_manifest: dict[str, object] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "video_id": video_id,
        "source_url": source_url,
        "review_status": "unreviewed",
        "proposal": {
            "source": proposal_source,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "suggested_envelope": {"start_seconds": start_seconds, "end_seconds": end_seconds},
            "suggested_interruptions": [],
        },
    }
    if selection_manifest is not None:
        payload["selection_manifest"] = dict(selection_manifest)
    return payload


def approved_fixture_payload(
    *,
    video_id: str,
    start_seconds: float,
    end_seconds: float,
    interruptions: list[tuple[float, float]],
    reviewer: str,
    failure_mode: str,
    notes: str,
    selection_manifest: dict[str, object] | None = None,
) -> dict[str, Any]:
    spans = retained_spans(start_seconds, end_seconds, interruptions)
    payload: dict[str, Any] = {
        "video_id": video_id,
        "expected_outcome": "sermon",
        "expected_spans": [
            {"start_seconds": start, "end_seconds": end} for start, end in spans
        ],
        "allowed_interruptions": [
            {"start_seconds": start, "end_seconds": end} for start, end in interruptions
        ],
        "ground_truth_version": 1,
        "reviewed_by": reviewer,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "review_method": "video_and_timestamped_transcript",
        "failure_mode": failure_mode,
        "notes": notes,
    }
    if selection_manifest is not None:
        payload["selection_manifest"] = dict(selection_manifest)
    return payload


def approved_negative_fixture_payload(
    *,
    video_id: str,
    reviewer: str,
    failure_mode: str,
    notes: str,
    selection_manifest: dict[str, object] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "video_id": video_id,
        "expected_outcome": "no_sermon",
        "expected_spans": [],
        "allowed_interruptions": [],
        "ground_truth_version": 1,
        "reviewed_by": reviewer,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "review_method": "full_video_and_timestamped_transcript",
        "failure_mode": failure_mode,
        "notes": notes,
    }
    if selection_manifest is not None:
        payload["selection_manifest"] = dict(selection_manifest)
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
