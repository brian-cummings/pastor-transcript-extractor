from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import re
from typing import Any, Iterable


SEMANTIC_VALIDATION_VERSION = "grounded-segment-spans-v1"
_WORD_PATTERN = re.compile(r"\b[\w]+(?:['’][\w]+)?\b", re.UNICODE)


@dataclass(frozen=True, slots=True)
class SemanticSegment:
    index: int
    text: str
    start_seconds: float | None
    end_seconds: float | None

    @property
    def evidence_id(self) -> str:
        return f"S{self.index:06d}"


@dataclass(frozen=True, slots=True)
class SemanticBlock:
    block_id: int
    segments: tuple[SemanticSegment, ...]

    @property
    def start_seconds(self) -> float:
        return float(self.segments[0].start_seconds)

    @property
    def end_seconds(self) -> float:
        return float(self.segments[-1].end_seconds)

    def numbered_text(self) -> str:
        return "\n".join(
            f"[{segment.evidence_id}] {segment.text}" for segment in self.segments
        )


@dataclass(frozen=True, slots=True)
class AcceptedSemanticProposal:
    dimension: str
    start_segment: SemanticSegment
    end_segment: SemanticSegment
    segments: tuple[SemanticSegment, ...]
    excerpt: str
    word_count: int

    @property
    def start_seconds(self) -> float:
        return float(self.start_segment.start_seconds)

    @property
    def end_seconds(self) -> float:
        return float(self.end_segment.end_seconds)


@dataclass(frozen=True, slots=True)
class SemanticValidationResult:
    accepted: tuple[AcceptedSemanticProposal, ...]
    proposed_count: int
    rejection_counts: dict[str, int]


def build_semantic_blocks(
    segments: Iterable[SemanticSegment],
    *,
    target_seconds: float = 75.0,
    max_chars: int = 3600,
) -> list[SemanticBlock]:
    usable = [
        segment
        for segment in segments
        if segment.text.strip()
        and segment.start_seconds is not None
        and segment.end_seconds is not None
        and segment.end_seconds > segment.start_seconds
    ]
    blocks: list[SemanticBlock] = []
    current: list[SemanticSegment] = []
    chars = 0
    for segment in usable:
        would_exceed = bool(current) and (
            float(segment.end_seconds) - float(current[0].start_seconds) > target_seconds
            or chars + len(segment.text) + 1 > max_chars
        )
        if would_exceed:
            blocks.append(SemanticBlock(len(blocks), tuple(current)))
            current = []
            chars = 0
        current.append(segment)
        chars += len(segment.text) + 1
    if current:
        blocks.append(SemanticBlock(len(blocks), tuple(current)))
    return blocks


def semantic_proposal_schema(
    dimensions: Iterable[str], block: SemanticBlock
) -> dict[str, Any]:
    dimension_values = list(dimensions)
    segment_ids = [segment.evidence_id for segment in block.segments]
    return {
        "type": "object",
        "properties": {
            "proposals": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "dimension": {"type": "string", "enum": dimension_values},
                        "start_segment_id": {"type": "string", "enum": segment_ids},
                        "end_segment_id": {"type": "string", "enum": segment_ids},
                    },
                    "required": [
                        "dimension",
                        "start_segment_id",
                        "end_segment_id",
                    ],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["proposals"],
        "additionalProperties": False,
    }


def validate_semantic_proposals(
    content: dict[str, Any],
    block: SemanticBlock,
    dimensions: Iterable[str],
    *,
    minimum_words: int = 10,
    maximum_seconds: float = 120.0,
) -> SemanticValidationResult:
    allowed_dimensions = set(dimensions)
    position_by_id = {
        segment.evidence_id: position
        for position, segment in enumerate(block.segments)
    }
    raw_proposals = content.get("proposals")
    if not isinstance(raw_proposals, list):
        return SemanticValidationResult((), 0, {"invalid_proposals_container": 1})

    accepted: list[AcceptedSemanticProposal] = []
    rejection_counts: Counter[str] = Counter()
    seen: set[tuple[str, str, str]] = set()
    for raw in raw_proposals:
        if not isinstance(raw, dict):
            rejection_counts["invalid_proposal"] += 1
            continue
        dimension = raw.get("dimension")
        start_id = raw.get("start_segment_id")
        end_id = raw.get("end_segment_id")
        if dimension not in allowed_dimensions:
            rejection_counts["invalid_dimension"] += 1
            continue
        if (
            not isinstance(start_id, str)
            or not isinstance(end_id, str)
            or start_id not in position_by_id
            or end_id not in position_by_id
        ):
            rejection_counts["ungrounded_segment_id"] += 1
            continue
        start_position = position_by_id[str(start_id)]
        end_position = position_by_id[str(end_id)]
        if start_position > end_position:
            rejection_counts["reversed_span"] += 1
            continue
        key = (str(dimension), str(start_id), str(end_id))
        if key in seen:
            rejection_counts["duplicate_proposal"] += 1
            continue
        seen.add(key)
        selected = block.segments[start_position : end_position + 1]
        if any(
            segment.start_seconds is None or segment.end_seconds is None
            for segment in selected
        ):
            rejection_counts["missing_source_timestamps"] += 1
            continue
        duration = float(selected[-1].end_seconds) - float(selected[0].start_seconds)
        if duration <= 0 or duration > maximum_seconds:
            rejection_counts["invalid_span_duration"] += 1
            continue
        excerpt = " ".join(segment.text.strip() for segment in selected).strip()
        word_count = len(_WORD_PATTERN.findall(excerpt))
        if word_count < minimum_words:
            rejection_counts["span_too_short"] += 1
            continue
        accepted.append(
            AcceptedSemanticProposal(
                dimension=str(dimension),
                start_segment=selected[0],
                end_segment=selected[-1],
                segments=selected,
                excerpt=excerpt,
                word_count=word_count,
            )
        )
    return SemanticValidationResult(
        accepted=tuple(accepted),
        proposed_count=len(raw_proposals),
        rejection_counts=dict(sorted(rejection_counts.items())),
    )
