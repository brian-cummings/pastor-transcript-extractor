from __future__ import annotations

import re
from dataclasses import dataclass

from pastor_transcript_extractor.models import TranscriptSegmentLabel
from pastor_transcript_extractor.segmentation import SegmentDraft


MIN_WINDOW_DURATION_SECONDS = 12 * 60
MAX_WINDOW_GAP_SECONDS = 90
EARLY_SEGMENT_LIMIT = 120
EARLY_WINDOW_SECONDS = 12 * 60

_POSITIVE_PATTERNS = (
    "turn in your bibles",
    "our text",
    "today i want to",
    "this passage",
    "the word of god",
    "the scripture says",
    "open your bibles",
    "gospel of",
    "book of",
)
_NEGATIVE_PATTERNS = (
    "welcome",
    "offering",
    "join us",
    "next week",
    "special music",
    "let us pray",
    "amen",
    "potluck",
    "vbs",
    "announcements",
)
_INTRO_PATTERNS = (
    "our speaker today",
    "guest speaker",
    "bring the message",
    "bringing the message",
    "thank you for inviting me",
    "we welcome",
    "welcome to the pulpit",
)
_HONORIFIC_NAME_RE = re.compile(
    r"\b(?P<title>Pastor|Elder|Dr\.?|Brother|Sister)\s+(?P<name>[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})\b"
)


@dataclass(frozen=True, slots=True)
class SermonWindowResult:
    start_seconds: float | None
    end_seconds: float | None
    confidence: float
    reasons: list[str]
    method: str
    included_segment_indexes: list[int]
    excluded_segment_indexes: list[int]


@dataclass(frozen=True, slots=True)
class GuestSpeakerFlags:
    suspected: bool
    name_candidates: list[str]
    reasons: list[str]


@dataclass(frozen=True, slots=True)
class _TimedSegment:
    index: int
    start_seconds: float
    end_seconds: float
    label: TranscriptSegmentLabel
    text: str
    score: float


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _score_segment(draft: SegmentDraft) -> float:
    score_by_label = {
        TranscriptSegmentLabel.SERMON: 1.0,
        TranscriptSegmentLabel.READING: 0.55,
        TranscriptSegmentLabel.UNKNOWN: 0.1,
        TranscriptSegmentLabel.PRAYER: -0.8,
        TranscriptSegmentLabel.ANNOUNCEMENTS: -1.2,
        TranscriptSegmentLabel.MUSIC: -1.4,
        TranscriptSegmentLabel.OTHER: -0.4,
    }
    score = score_by_label.get(draft.label, 0.0)
    lower = _normalize(draft.text)
    if any(pattern in lower for pattern in _POSITIVE_PATTERNS):
        score += 0.8
    if any(pattern in lower for pattern in _NEGATIVE_PATTERNS):
        score -= 1.0
    if len(lower) >= 140:
        score += 0.2
    return score


def _timed_segments(drafts: list[SegmentDraft]) -> list[_TimedSegment]:
    timed: list[_TimedSegment] = []
    for index, draft in enumerate(drafts):
        if draft.start_seconds is None or draft.end_seconds is None:
            continue
        if draft.end_seconds <= draft.start_seconds:
            continue
        timed.append(
            _TimedSegment(
                index=index,
                start_seconds=draft.start_seconds,
                end_seconds=draft.end_seconds,
                label=draft.label,
                text=draft.text,
                score=_score_segment(draft),
            )
        )
    return timed


def detect_sermon_window(drafts: list[SegmentDraft]) -> SermonWindowResult:
    timed = _timed_segments(drafts)
    if not timed:
        return SermonWindowResult(
            start_seconds=None,
            end_seconds=None,
            confidence=0.05,
            reasons=["no sermon window detected: transcript has no timestamped segments"],
            method="rule_based_v1",
            included_segment_indexes=[],
            excluded_segment_indexes=[],
        )

    candidates = [segment for segment in timed if segment.score > 0]
    if not candidates:
        return SermonWindowResult(
            start_seconds=None,
            end_seconds=None,
            confidence=0.05,
            reasons=["no sermon window detected: no sermon-like segment run met the score threshold"],
            method="rule_based_v1",
            included_segment_indexes=[],
            excluded_segment_indexes=[segment.index for segment in timed],
        )

    merged_runs: list[list[_TimedSegment]] = []
    current_run: list[_TimedSegment] = []
    for segment in candidates:
        if not current_run:
            current_run = [segment]
            continue
        gap = segment.start_seconds - current_run[-1].end_seconds
        if gap <= MAX_WINDOW_GAP_SECONDS:
            current_run.append(segment)
            continue
        merged_runs.append(current_run)
        current_run = [segment]
    if current_run:
        merged_runs.append(current_run)

    def run_duration(run: list[_TimedSegment]) -> float:
        return run[-1].end_seconds - run[0].start_seconds

    valid_runs = [run for run in merged_runs if run_duration(run) >= MIN_WINDOW_DURATION_SECONDS]
    if not valid_runs:
        return SermonWindowResult(
            start_seconds=None,
            end_seconds=None,
            confidence=0.15,
            reasons=["no sermon window detected: no sermon-like segment run reached the 12 minute minimum"],
            method="rule_based_v1",
            included_segment_indexes=[],
            excluded_segment_indexes=[segment.index for segment in timed],
        )

    def run_strength(run: list[_TimedSegment]) -> float:
        total = 0.0
        for segment in run:
            duration = segment.end_seconds - segment.start_seconds
            total += max(segment.score, 0.0) * duration
        return total

    best_run = max(valid_runs, key=lambda run: (run_strength(run), run_duration(run), -run[0].start_seconds))
    included = [segment.index for segment in timed if best_run[0].start_seconds <= segment.start_seconds <= best_run[-1].end_seconds]
    excluded = [segment.index for segment in timed if segment.index not in included]

    reasons = ["contiguous sermon-like block exceeded the 12 minute minimum"]
    if any(any(pattern in _normalize(segment.text) for pattern in _POSITIVE_PATTERNS) for segment in best_run):
        reasons.append("expository language detected inside the selected window")
    if any(segment.label in {TranscriptSegmentLabel.ANNOUNCEMENTS, TranscriptSegmentLabel.PRAYER, TranscriptSegmentLabel.MUSIC} for segment in timed if segment.index in excluded):
        reasons.append("announcement, prayer, or music segments fell outside the selected window")

    positive_segments = sum(1 for segment in best_run if segment.score > 0.5)
    confidence = min(0.95, 0.45 + (run_duration(best_run) / 3600.0) + (positive_segments / max(len(best_run), 1)) * 0.25)
    return SermonWindowResult(
        start_seconds=best_run[0].start_seconds,
        end_seconds=best_run[-1].end_seconds,
        confidence=round(confidence, 2),
        reasons=reasons,
        method="rule_based_v1",
        included_segment_indexes=included,
        excluded_segment_indexes=excluded,
    )


def detect_guest_speaker_flags(
    *,
    video_title: str,
    drafts: list[SegmentDraft],
    pastor_name: str,
    sermon_window: SermonWindowResult,
) -> GuestSpeakerFlags:
    pastor_lower = _normalize(pastor_name)
    title_candidates: list[str] = []
    reasons: list[str] = []

    def is_not_pastor(candidate: str) -> bool:
        candidate_normalized = _normalize(re.sub(r"^(pastor|elder|dr\.?|brother|sister)\s+", "", candidate, flags=re.IGNORECASE))
        return bool(candidate_normalized) and candidate_normalized not in pastor_lower

    for match in _HONORIFIC_NAME_RE.finditer(video_title):
        candidate = match.group(0)
        if is_not_pastor(candidate) and candidate not in title_candidates:
            title_candidates.append(candidate)
    if title_candidates:
        reasons.append("video title names a non-pastor speaker")

    timed = _timed_segments(drafts)
    early_segments: list[_TimedSegment] = []
    for segment in timed:
        if len(early_segments) >= EARLY_SEGMENT_LIMIT:
            break
        if segment.start_seconds > EARLY_WINDOW_SECONDS:
            break
        early_segments.append(segment)
    if sermon_window.start_seconds is not None:
        for segment in timed:
            if segment.end_seconds < sermon_window.start_seconds:
                continue
            if segment.start_seconds > sermon_window.start_seconds + 180:
                break
            if segment not in early_segments:
                early_segments.append(segment)

    early_text = " ".join(segment.text for segment in early_segments)
    early_lower = _normalize(early_text)
    if any(pattern in early_lower for pattern in _INTRO_PATTERNS):
        reasons.append("introductory guest-speaker language detected in early transcript segments")

    segment_candidates: list[str] = []
    for match in _HONORIFIC_NAME_RE.finditer(early_text):
        candidate = match.group(0)
        if is_not_pastor(candidate) and candidate not in segment_candidates:
            segment_candidates.append(candidate)
    if segment_candidates and "introductory guest-speaker language detected in early transcript segments" not in reasons:
        reasons.append("early transcript names a non-pastor speaker")

    candidates = title_candidates + [candidate for candidate in segment_candidates if candidate not in title_candidates]
    return GuestSpeakerFlags(
        suspected=bool(reasons),
        name_candidates=candidates,
        reasons=reasons,
    )
