from __future__ import annotations

import re
from dataclasses import dataclass

from pastor_transcript_extractor.models import TranscriptSegmentLabel, TranscriptSourceKind
from pastor_transcript_extractor.segmentation import SegmentDraft


MIN_WINDOW_DURATION_SECONDS = 12 * 60
MAX_WINDOW_GAP_SECONDS = 90
MAX_BRIDGED_INTERRUPTION_SECONDS = 4 * 60
MAX_BRIDGED_INTERRUPTION_SEGMENTS = 2
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
_STRONG_START_PATTERNS = (
    "turn in your bibles",
    "open your bibles",
    "our text",
    "our scripture",
    "scripture reading",
    "the scripture says",
    "the word of god",
    "today i want to",
    "this passage",
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
_LYRIC_PATTERNS = (
    "[singing]",
    "[music]",
    "my praise",
    "registered in heaven",
    "this is my testimony",
    "everybody smile",
    "praise belongs",
    "living water",
    "peace of the lord go with you",
)
_LEADING_BOUNDARY_PATTERNS = (
    "welcome",
    "happy sabbath",
    "join us",
    "next week",
    "offering",
    "tithe",
    "tithes and offerings",
    "special music",
    "praise team",
    "everybody smile",
    "please stand",
    "call to worship",
    "let us pray",
    "lets pray",
    "amen",
    "thank you",
    "we're going to prepare for our worship service",
)
_TRAILING_BOUNDARY_PATTERNS = (
    "let us pray",
    "lets pray",
    "amen",
    "thank you",
    "round of applause",
    "gift for you",
    "all right, and break",
    "break",
    "have a wonderful sabbath day",
    "until we meet again",
    "jesus' name we pray",
    "in jesus' name",
    "benediction",
    "peace of the lord go with you",
    "thank you so much",
    "you're welcome",
    "go eat",
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
_SELF_INTRO_PATTERNS = (
    "thank you for inviting me",
    "thank you for having me",
    "it is good to be with you",
    "it's good to be with you",
    "i am honored to be here",
    "i'm honored to be here",
    "greetings from",
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
    suspicious_boundary: bool
    suspicious_boundary_reasons: list[str]


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


def _opening_segments(timed: list[_TimedSegment], window_seconds: float = 300.0) -> list[_TimedSegment]:
    opening: list[_TimedSegment] = []
    for segment in timed:
        if segment.start_seconds > window_seconds:
            break
        opening.append(segment)
    return opening


def _looks_like_lyric_fragment(text: str) -> bool:
    lower = _normalize(text)
    if not lower:
        return False
    if _contains_any_pattern(lower, _LYRIC_PATTERNS):
        return True
    words = lower.split()
    return len(words) <= 6


def _opening_repetition_penalty(timed: list[_TimedSegment]) -> dict[int, float]:
    penalties: dict[int, float] = {}
    opening = _opening_segments(timed)
    if not opening:
        return penalties
    text_counts: dict[str, int] = {}
    for segment in opening:
        normalized = _normalize(segment.text)
        if normalized:
            text_counts[normalized] = text_counts.get(normalized, 0) + 1
    for segment in opening:
        normalized = _normalize(segment.text)
        penalty = 0.0
        if _looks_like_lyric_fragment(segment.text):
            penalty += 0.9
        if normalized and text_counts.get(normalized, 0) > 1:
            penalty += 0.7
        if penalty > 0:
            penalties[segment.index] = penalty
    return penalties


def _opening_has_strong_sermon_start(opening: list[_TimedSegment]) -> bool:
    return _first_strong_sermon_start_seconds(opening) is not None


def _first_strong_sermon_start_seconds(opening: list[_TimedSegment]) -> float | None:
    for segment in opening:
        lower = _normalize(segment.text)
        if _contains_any_pattern(lower, _STRONG_START_PATTERNS):
            return segment.start_seconds
        if segment.label == TranscriptSegmentLabel.READING and segment.score > 0.5:
            return segment.start_seconds
    return None


def _contains_any_pattern(text: str, patterns: tuple[str, ...]) -> bool:
    return any(pattern in text for pattern in patterns)


def _is_leading_boundary_segment(segment: _TimedSegment) -> bool:
    lower = _normalize(segment.text)
    if segment.label in {TranscriptSegmentLabel.MUSIC, TranscriptSegmentLabel.ANNOUNCEMENTS}:
        return True
    if segment.label == TranscriptSegmentLabel.PRAYER and _contains_any_pattern(lower, ("let us pray", "lets pray", "amen")):
        return True
    if _contains_any_pattern(lower, _LEADING_BOUNDARY_PATTERNS):
        return True
    return False


def _is_trailing_boundary_segment(segment: _TimedSegment) -> bool:
    lower = _normalize(segment.text)
    if segment.label in {TranscriptSegmentLabel.MUSIC, TranscriptSegmentLabel.ANNOUNCEMENTS}:
        return True
    if segment.label == TranscriptSegmentLabel.PRAYER:
        return True
    if _contains_any_pattern(lower, _TRAILING_BOUNDARY_PATTERNS):
        return True
    return False


def _trim_run_boundaries(run: list[_TimedSegment]) -> tuple[list[_TimedSegment], list[str]]:
    trimmed = list(run)
    reasons: list[str] = []

    while len(trimmed) > 1:
        candidate = trimmed[0]
        next_window_duration = trimmed[-1].end_seconds - trimmed[1].start_seconds
        if next_window_duration < MIN_WINDOW_DURATION_SECONDS or not _is_leading_boundary_segment(candidate):
            break
        trimmed.pop(0)
        if "trimmed leading intro, music, or admin segments from the detected window" not in reasons:
            reasons.append("trimmed leading intro, music, or admin segments from the detected window")

    while len(trimmed) > 1:
        candidate = trimmed[-1]
        next_window_duration = trimmed[-2].end_seconds - trimmed[0].start_seconds
        if next_window_duration < MIN_WINDOW_DURATION_SECONDS or not _is_trailing_boundary_segment(candidate):
            break
        trimmed.pop()
        if "trimmed trailing prayer, music, or closing segments from the detected window" not in reasons:
            reasons.append("trimmed trailing prayer, music, or closing segments from the detected window")

    return trimmed, reasons


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


def _adjusted_score(segment: _TimedSegment, opening_penalties: dict[int, float]) -> float:
    return segment.score - opening_penalties.get(segment.index, 0.0)


def _is_bridgeable_interruption(segment: _TimedSegment) -> bool:
    if segment.label in {TranscriptSegmentLabel.PRAYER, TranscriptSegmentLabel.UNKNOWN, TranscriptSegmentLabel.OTHER, TranscriptSegmentLabel.READING}:
        return True
    lower = _normalize(segment.text)
    if segment.label == TranscriptSegmentLabel.SERMON and not _contains_any_pattern(lower, _TRAILING_BOUNDARY_PATTERNS):
        return True
    return False


def _can_bridge_interruption(
    interruption_segments: list[_TimedSegment],
    gap_seconds: float,
) -> bool:
    if not interruption_segments:
        return gap_seconds <= MAX_WINDOW_GAP_SECONDS
    if len(interruption_segments) > MAX_BRIDGED_INTERRUPTION_SEGMENTS:
        return False
    if gap_seconds > MAX_BRIDGED_INTERRUPTION_SECONDS:
        return False
    return all(_is_bridgeable_interruption(segment) for segment in interruption_segments)


def detect_sermon_window(
    drafts: list[SegmentDraft],
    *,
    transcript_source: TranscriptSourceKind | None = None,
) -> SermonWindowResult:
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
            suspicious_boundary=False,
            suspicious_boundary_reasons=[],
        )

    opening_penalties = _opening_repetition_penalty(timed)
    candidate_positions = [
        position
        for position, segment in enumerate(timed)
        if _adjusted_score(segment, opening_penalties) > 0
    ]
    candidates = [timed[position] for position in candidate_positions]
    if not candidates:
        return SermonWindowResult(
            start_seconds=None,
            end_seconds=None,
            confidence=0.05,
            reasons=["no sermon window detected: no sermon-like segment run met the score threshold"],
            method="rule_based_v1",
            included_segment_indexes=[],
            excluded_segment_indexes=[segment.index for segment in timed],
            suspicious_boundary=False,
            suspicious_boundary_reasons=[],
        )

    merged_runs: list[list[_TimedSegment]] = []
    current_run: list[_TimedSegment] = []
    previous_candidate_position: int | None = None
    for candidate_position in candidate_positions:
        segment = timed[candidate_position]
        if not current_run:
            current_run = [segment]
            previous_candidate_position = candidate_position
            continue
        assert previous_candidate_position is not None
        interruption_segments = timed[previous_candidate_position + 1:candidate_position]
        previous_segment = timed[previous_candidate_position]
        gap = segment.start_seconds - previous_segment.end_seconds
        if _can_bridge_interruption(interruption_segments, gap):
            current_run.extend(interruption_segments)
            current_run.append(segment)
            previous_candidate_position = candidate_position
            continue
        merged_runs.append(current_run)
        current_run = [segment]
        previous_candidate_position = candidate_position
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
            suspicious_boundary=False,
            suspicious_boundary_reasons=[],
        )

    def run_strength(run: list[_TimedSegment]) -> float:
        total = 0.0
        for segment in run:
            duration = segment.end_seconds - segment.start_seconds
            adjusted_score = _adjusted_score(segment, opening_penalties)
            if adjusted_score > 0:
                total += adjusted_score * duration
            elif _is_bridgeable_interruption(segment):
                total -= min(0.2, abs(adjusted_score)) * duration * 0.35
        return total

    best_run = max(valid_runs, key=lambda run: (run_strength(run), run_duration(run), -run[0].start_seconds))
    trimmed_run, trim_reasons = _trim_run_boundaries(best_run)
    opening = _opening_segments(timed)
    first_strong_start_seconds = _first_strong_sermon_start_seconds(opening)
    if (
        transcript_source == TranscriptSourceKind.CAPTIONS
        and first_strong_start_seconds is not None
        and trimmed_run[0].start_seconds < first_strong_start_seconds
    ):
        gated_run = [segment for segment in trimmed_run if segment.start_seconds >= first_strong_start_seconds]
        if gated_run and (gated_run[-1].end_seconds - gated_run[0].start_seconds) >= MIN_WINDOW_DURATION_SECONDS:
            trimmed_run = gated_run
            trim_reasons.append("trimmed weak caption opening until a stronger sermon start appeared")
    included = [
        segment.index
        for segment in timed
        if trimmed_run[0].start_seconds <= segment.start_seconds <= trimmed_run[-1].end_seconds
    ]
    excluded = [segment.index for segment in timed if segment.index not in included]

    reasons = ["contiguous sermon-like block exceeded the 12 minute minimum"]
    reasons.extend(trim_reasons)
    if any(any(pattern in _normalize(segment.text) for pattern in _POSITIVE_PATTERNS) for segment in trimmed_run):
        reasons.append("expository language detected inside the selected window")
    if any(segment.label in {TranscriptSegmentLabel.ANNOUNCEMENTS, TranscriptSegmentLabel.PRAYER, TranscriptSegmentLabel.MUSIC} for segment in timed if segment.index in excluded):
        reasons.append("announcement, prayer, or music segments fell outside the selected window")

    suspicious_boundary_reasons: list[str] = []
    if transcript_source == TranscriptSourceKind.CAPTIONS and trimmed_run[0].start_seconds <= 15.0 and first_strong_start_seconds is None:
        suspicious_boundary_reasons.append("window starts near 00:00 without strong expository cues in caption opening")
    ending_segments = [segment for segment in trimmed_run if segment.end_seconds >= trimmed_run[-1].end_seconds - 180.0]
    if any(_is_trailing_boundary_segment(segment) for segment in ending_segments):
        suspicious_boundary_reasons.append("window ends with possible closing or benediction language")

    positive_segments = sum(1 for segment in trimmed_run if segment.score > 0.5)
    confidence = min(
        0.95,
        0.45 + (run_duration(trimmed_run) / 3600.0) + (positive_segments / max(len(trimmed_run), 1)) * 0.25,
    )
    return SermonWindowResult(
        start_seconds=trimmed_run[0].start_seconds,
        end_seconds=trimmed_run[-1].end_seconds,
        confidence=round(confidence, 2),
        reasons=reasons,
        method="rule_based_v1",
        included_segment_indexes=included,
        excluded_segment_indexes=excluded,
        suspicious_boundary=bool(suspicious_boundary_reasons),
        suspicious_boundary_reasons=suspicious_boundary_reasons,
    )


def detect_guest_speaker_flags(
    *,
    video_title: str,
    drafts: list[SegmentDraft],
    pastor_name: str,
    sermon_window: SermonWindowResult,
) -> GuestSpeakerFlags:
    pastor_lower = _normalize(pastor_name)
    pastor_tokens = {token for token in re.split(r"[^a-z]+", pastor_lower) if token}
    title_candidates: list[str] = []
    reasons: list[str] = []

    def is_not_pastor(candidate: str) -> bool:
        candidate_normalized = _normalize(
            re.sub(r"^(pastor|elder|dr\.?|brother|sister)\s+", "", candidate, flags=re.IGNORECASE)
        )
        if not candidate_normalized or candidate_normalized in pastor_lower:
            return False
        candidate_tokens = {token for token in re.split(r"[^a-z]+", candidate_normalized) if token}
        if candidate_tokens and candidate_tokens.issubset(pastor_tokens):
            return False
        return True

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

    segment_candidates: list[str] = []
    intro_detected = False
    self_intro_detected = False
    named_intro_detected = False
    non_sermon_name_detected = False
    for segment in early_segments:
        lower = _normalize(segment.text)
        segment_intro_detected = any(pattern in lower for pattern in _INTRO_PATTERNS)
        if segment_intro_detected:
            intro_detected = True
        if any(pattern in lower for pattern in _SELF_INTRO_PATTERNS):
            self_intro_detected = True
        matches: list[str] = []
        for match in _HONORIFIC_NAME_RE.finditer(segment.text):
            candidate = match.group(0)
            if is_not_pastor(candidate) and candidate not in segment_candidates:
                segment_candidates.append(candidate)
            if is_not_pastor(candidate):
                matches.append(candidate)
        if matches and segment_intro_detected:
            named_intro_detected = True
        if matches and segment.label != TranscriptSegmentLabel.SERMON:
            non_sermon_name_detected = True

    if intro_detected and named_intro_detected:
        reasons.append("introductory guest-speaker language detected alongside a non-pastor name")
    elif self_intro_detected:
        reasons.append("speaker uses first-person guest-introduction language near the sermon opening")
    elif non_sermon_name_detected:
        reasons.append("early non-sermon transcript names a non-pastor speaker")

    candidates = title_candidates + [candidate for candidate in segment_candidates if candidate not in title_candidates]
    return GuestSpeakerFlags(
        suspected=bool(reasons),
        name_candidates=candidates,
        reasons=reasons,
    )
