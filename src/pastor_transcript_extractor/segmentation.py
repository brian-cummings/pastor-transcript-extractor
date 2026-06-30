from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from pastor_transcript_extractor.models import TranscriptSegmentLabel


@dataclass(frozen=True, slots=True)
class SegmentDraft:
    start_seconds: float | None
    end_seconds: float | None
    text: str
    speaker_hint: str | None
    label: TranscriptSegmentLabel
    confidence: float | None


_LABEL_PATTERNS: list[tuple[TranscriptSegmentLabel, tuple[str, ...], float]] = [
    (TranscriptSegmentLabel.MUSIC, ("worship", "song", "sing", "music", "praise team", "special music"), 0.8),
    (
        TranscriptSegmentLabel.ANNOUNCEMENTS,
        ("announcements", "welcome", "offering", "tithe", "giving", "join us", "next week", "small group"),
        0.75,
    ),
    (TranscriptSegmentLabel.PRAYER, ("let's pray", "lets pray", "prayer", "amen", "father we"), 0.7),
    (
        TranscriptSegmentLabel.READING,
        ("scripture reading", "reading from", "turn in your bibles", "please stand", "the reading of"),
        0.7,
    ),
]


def _normalize_text(text: str) -> str:
    collapsed = re.sub(r"\s+", " ", text).strip()
    return collapsed


def _label_text(text: str) -> tuple[TranscriptSegmentLabel, float | None]:
    lower = text.lower()
    for label, patterns, confidence in _LABEL_PATTERNS:
        if any(pattern in lower for pattern in patterns):
            return label, confidence
    if len(lower) < 12:
        return TranscriptSegmentLabel.UNKNOWN, None
    return TranscriptSegmentLabel.SERMON, 0.55


def _parse_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _segment_from_entry(entry: dict[str, Any]) -> SegmentDraft | None:
    text = _normalize_text(str(entry.get("text", "")))
    if not text:
        return None
    start_seconds = _parse_float(entry.get("start"))
    end_seconds = _parse_float(entry.get("end"))
    label, confidence = _label_text(text)
    return SegmentDraft(
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        text=text,
        speaker_hint=None,
        label=label,
        confidence=confidence,
    )


def _chunk_plain_text(raw_text: str, max_chars: int = 320) -> list[str]:
    lines = [_normalize_text(line) for line in raw_text.splitlines()]
    paragraphs: list[str] = []
    current: list[str] = []

    for line in lines:
        if not line:
            if current:
                paragraphs.append(" ".join(current))
                current = []
            continue
        current.append(line)
        if len(" ".join(current)) >= max_chars:
            paragraphs.append(" ".join(current))
            current = []

    if current:
        paragraphs.append(" ".join(current))

    if not paragraphs:
        return []

    return paragraphs


def segment_transcript(raw_text: str, raw_json: dict[str, Any] | None = None) -> list[SegmentDraft]:
    if raw_json is not None:
        segments = raw_json.get("segments")
        if isinstance(segments, list):
            drafts = [_segment_from_entry(entry) for entry in segments if isinstance(entry, dict)]
            return [draft for draft in drafts if draft is not None]
        text = raw_json.get("text")
        if isinstance(text, str) and text.strip():
            raw_text = text

    paragraphs = _chunk_plain_text(raw_text)
    drafts: list[SegmentDraft] = []
    for paragraph in paragraphs:
        label, confidence = _label_text(paragraph)
        drafts.append(
            SegmentDraft(
                start_seconds=None,
                end_seconds=None,
                text=paragraph,
                speaker_hint=None,
                label=label,
                confidence=confidence,
            )
        )
    return drafts
