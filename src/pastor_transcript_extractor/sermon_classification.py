from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from pastor_transcript_extractor.local_llm import LocalLlmClient
from pastor_transcript_extractor.segmentation import SegmentDraft
from pastor_transcript_extractor.sermon_detection import SermonWindowResult


class ContentLabel(StrEnum):
    SERMON = "sermon"
    SERMON_PRAYER = "sermon_prayer"
    SERMON_SCRIPTURE = "sermon_scripture"
    SERVICE_PRAYER = "service_prayer"
    SERVICE_READING = "service_reading"
    MUSIC = "music"
    ANNOUNCEMENTS = "announcements"
    SPEAKER_INTRODUCTION = "speaker_introduction"
    CLOSING_SERVICE = "closing_service"
    UNCERTAIN = "uncertain"


RETAINED_LABELS = {ContentLabel.SERMON, ContentLabel.SERMON_PRAYER, ContentLabel.SERMON_SCRIPTURE}
REASON_CODES = (
    "biblical_exposition",
    "sermon_transition",
    "integrated_prayer",
    "integrated_scripture",
    "service_prayer",
    "service_reading",
    "music_or_lyrics",
    "logistics_or_welcome",
    "speaker_handoff",
    "service_closing",
    "insufficient_context",
)


@dataclass(frozen=True, slots=True)
class TranscriptBlock:
    block_id: int
    segment_indexes: list[int]
    start_seconds: float
    end_seconds: float
    text: str


@dataclass(frozen=True, slots=True)
class BlockClassification:
    block_id: int
    label: ContentLabel
    evidence: str
    raw_response: str


@dataclass(frozen=True, slots=True)
class HybridSermonResult:
    method: str
    model: str | None
    prompt_version: str
    confidence_tier: str
    retained_segment_indexes: list[int]
    excluded_segment_indexes: list[int]
    uncertain_block_ids: list[int]
    warnings: list[str]
    blocks: list[TranscriptBlock]
    classifications: list[BlockClassification]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "method": self.method,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "confidence_tier": self.confidence_tier,
            "retained_segment_indexes": self.retained_segment_indexes,
            "excluded_segment_indexes": self.excluded_segment_indexes,
            "uncertain_block_ids": self.uncertain_block_ids,
            "warnings": self.warnings,
            "blocks": [asdict(block) for block in self.blocks],
            "classifications": [
                {**asdict(item), "label": item.label.value} for item in self.classifications
            ],
        }


class CoarsePhase(StrEnum):
    SERMON = "sermon"
    WORSHIP = "worship"
    ADMINISTRATION = "administration"
    TRANSITION = "transition"
    UNCERTAIN = "uncertain"


def build_transcript_blocks(
    drafts: list[SegmentDraft], *, target_seconds: float = 90.0, max_chars: int = 3200
) -> list[TranscriptBlock]:
    blocks: list[TranscriptBlock] = []
    indexes: list[int] = []
    texts: list[str] = []
    start: float | None = None
    end: float | None = None

    def flush() -> None:
        nonlocal indexes, texts, start, end
        if indexes and start is not None and end is not None:
            blocks.append(TranscriptBlock(len(blocks), indexes, start, end, "\n".join(texts)))
        indexes, texts, start, end = [], [], None, None

    for index, draft in enumerate(drafts):
        if draft.start_seconds is None or draft.end_seconds is None or draft.end_seconds <= draft.start_seconds:
            continue
        if start is not None and ((draft.end_seconds - start) > target_seconds or len("\n".join(texts + [draft.text])) > max_chars):
            flush()
        if start is None:
            start = draft.start_seconds
        end = draft.end_seconds
        indexes.append(index)
        texts.append(draft.text)
    flush()
    return blocks


_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "label": {"type": "string", "enum": [label.value for label in ContentLabel]},
        "reason_code": {"type": "string", "enum": list(REASON_CODES)},
    },
    "required": ["label", "reason_code"],
    "additionalProperties": False,
}

_COARSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "phase": {"type": "string", "enum": [phase.value for phase in CoarsePhase]},
        "reason_code": {"type": "string", "enum": list(REASON_CODES)},
    },
    "required": ["phase", "reason_code"],
    "additionalProperties": False,
}


def _prompt(block: TranscriptBlock, previous: TranscriptBlock | None, following: TranscriptBlock | None) -> str:
    return f"""Classify only the CURRENT transcript block from a Christian worship service.
Keep sermon prayer and scripture when they are part of the preacher's message. Distinguish them from service prayer/readings outside the sermon.
Return the required JSON only. Choose one label and one reason_code from the schema. Do not generate prose.

PREVIOUS CONTEXT:
{previous.text if previous else '(none)'}

CURRENT BLOCK:
{block.text}

FOLLOWING CONTEXT:
{following.text if following else '(none)'}"""


def _coarse_prompt(block: TranscriptBlock) -> str:
    return f"""Identify the dominant phase of this five-minute excerpt from a complete Christian worship service.
SERMON means sustained preaching or biblical exposition, not merely religious words, prayer, song lyrics, welcomes, or a speaker introduction.
WORSHIP means music, congregational singing, or extended devotional prayer.
ADMINISTRATION means welcomes, announcements, offerings, logistics, or community features.
TRANSITION means a handoff, Scripture introduction, speaker introduction, or movement between phases.
UNCERTAIN means there is not enough coherent evidence.
Return only one phase and one reason_code from the schema. Do not generate prose.

EXCERPT:
{block.text}"""


def _overlaps(block: TranscriptBlock, start: float, end: float) -> bool:
    return block.end_seconds > start and block.start_seconds < end


def _coarse_candidate_ranges(
    blocks: list[TranscriptBlock], phases: list[CoarsePhase]
) -> list[tuple[float, float]]:
    ranges: list[tuple[float, float]] = []
    position = 0
    while position < len(blocks):
        if phases[position] != CoarsePhase.SERMON:
            position += 1
            continue
        start_position = position
        end_position = position
        while end_position + 1 < len(blocks):
            next_phase = phases[end_position + 1]
            if next_phase == CoarsePhase.SERMON:
                end_position += 1
                continue
            if (
                next_phase in {CoarsePhase.WORSHIP, CoarsePhase.TRANSITION, CoarsePhase.UNCERTAIN}
                and end_position + 2 < len(blocks)
                and phases[end_position + 2] == CoarsePhase.SERMON
            ):
                end_position += 2
                continue
            break
        ranges.append((blocks[start_position].start_seconds, blocks[end_position].end_seconds))
        position = end_position + 1
    return ranges


_SERMON_SEED_CUES = (
    "our sermon title",
    "sermon title today",
    "as we open up god's word",
    "as we open god's word",
    "turn in your bibles",
    "open your bibles",
    "today's message",
)


def _candidate_strength(
    candidate: tuple[float, float], blocks: list[TranscriptBlock]
) -> float:
    start, end = candidate
    text = " ".join(block.text.lower() for block in blocks if _overlaps(block, start, end))
    cue_bonus = sum(1800.0 for cue in _SERMON_SEED_CUES if cue in text)
    return (end - start) + cue_bonus


def classify_sermon_content_adaptive(
    drafts: list[SegmentDraft],
    rule_window: SermonWindowResult,
    client: LocalLlmClient,
    *,
    prompt_version: str = "sermon-content-v2",
    progress: Any | None = None,
) -> HybridSermonResult:
    coarse_blocks = build_transcript_blocks(drafts, target_seconds=300.0, max_chars=9000)
    if not coarse_blocks:
        raise ValueError("LLM classification requires timestamped transcript segments")
    phases: list[CoarsePhase] = []
    coarse_audit: list[BlockClassification] = []
    total_estimate = len(coarse_blocks)
    for position, block in enumerate(coarse_blocks):
        if progress is not None:
            progress("coarse", position + 1, total_estimate)
        response = client.generate_json(_coarse_prompt(block), _COARSE_SCHEMA)
        try:
            phase = CoarsePhase(str(response.content["phase"]))
        except (KeyError, ValueError) as error:
            raise ValueError("Local LLM returned an unsupported coarse service phase") from error
        reason = response.content.get("reason_code")
        if not isinstance(reason, str):
            raise ValueError("Local LLM did not return a coarse reason code")
        phases.append(phase)
        mapped_label = {
            CoarsePhase.SERMON: ContentLabel.SERMON,
            CoarsePhase.WORSHIP: ContentLabel.MUSIC,
            CoarsePhase.ADMINISTRATION: ContentLabel.ANNOUNCEMENTS,
            CoarsePhase.TRANSITION: ContentLabel.SPEAKER_INTRODUCTION,
            CoarsePhase.UNCERTAIN: ContentLabel.UNCERTAIN,
        }[phase]
        coarse_audit.append(BlockClassification(block.block_id, mapped_label, f"coarse:{reason}", response.raw_content))

    coarse_candidates = _coarse_candidate_ranges(coarse_blocks, phases)
    candidates: list[tuple[float, float]] = []
    if coarse_candidates:
        candidates.append(max(coarse_candidates, key=lambda item: _candidate_strength(item, coarse_blocks)))
    elif rule_window.start_seconds is not None and rule_window.end_seconds is not None:
        candidates.append((rule_window.start_seconds, rule_window.end_seconds))
    if not candidates:
        return HybridSermonResult(
            "adaptive_llm_v2", client.model, prompt_version, "low", [],
            [index for block in coarse_blocks for index in block.segment_indexes], [],
            ["no plausible sermon region found during coarse scan"], coarse_blocks, coarse_audit,
        )

    expanded_candidates = [(max(0.0, start - 120.0), end + 120.0) for start, end in candidates]
    fine_blocks = [
        block for block in build_transcript_blocks(drafts)
        if any(_overlaps(block, start, end) for start, end in expanded_candidates)
    ]
    fine_audit: list[BlockClassification] = []
    retained: set[int] = set()
    uncertain_ids: list[int] = []
    rule_indexes = set(rule_window.included_segment_indexes)
    for position, block in enumerate(fine_blocks):
        if progress is not None:
            progress("fine", position + 1, len(fine_blocks))
        previous = fine_blocks[position - 1] if position else None
        following = fine_blocks[position + 1] if position + 1 < len(fine_blocks) else None
        response = client.generate_json(_prompt(block, previous, following), _SCHEMA)
        try:
            label = ContentLabel(str(response.content["label"]))
        except (KeyError, ValueError) as error:
            raise ValueError("Local LLM returned an unsupported content label") from error
        reason = response.content.get("reason_code")
        if not isinstance(reason, str):
            raise ValueError("Local LLM did not return a reason code")
        fine_audit.append(BlockClassification(block.block_id, label, f"fine:{reason}", response.raw_content))
        if label in RETAINED_LABELS:
            retained.update(block.segment_indexes)
        elif label == ContentLabel.UNCERTAIN:
            uncertain_ids.append(block.block_id)
            retained.update(index for index in block.segment_indexes if index in rule_indexes)

    all_timed = {index for block in build_transcript_blocks(drafts) for index in block.segment_indexes}
    agreement = len(retained & rule_indexes) / max(len(retained | rule_indexes), 1)
    warnings: list[str] = []
    if agreement < 0.5:
        warnings.append("adaptive LLM and rule-based sermon windows disagree substantially")
    if uncertain_ids:
        warnings.append("one or more refined blocks require boundary review")
    confidence = "high" if agreement >= 0.8 and not uncertain_ids else "medium"
    if agreement < 0.5 or not retained:
        confidence = "low"
    return HybridSermonResult(
        "adaptive_llm_v2", client.model, prompt_version, confidence,
        sorted(retained), sorted(all_timed - retained), uncertain_ids, warnings,
        coarse_blocks + fine_blocks, coarse_audit + fine_audit,
    )


def classify_sermon_content(
    drafts: list[SegmentDraft],
    rule_window: SermonWindowResult,
    client: LocalLlmClient,
    *,
    prompt_version: str = "sermon-content-v1",
) -> HybridSermonResult:
    blocks = build_transcript_blocks(drafts)
    if not blocks:
        raise ValueError("LLM classification requires timestamped transcript segments")
    classifications: list[BlockClassification] = []
    for position, block in enumerate(blocks):
        response = client.generate_json(
            _prompt(block, blocks[position - 1] if position else None, blocks[position + 1] if position + 1 < len(blocks) else None),
            _SCHEMA,
        )
        try:
            label = ContentLabel(str(response.content["label"]))
        except (KeyError, ValueError) as error:
            raise ValueError("Local LLM returned an unsupported content label") from error
        evidence = response.content.get("reason_code")
        if not isinstance(evidence, str):
            raise ValueError("Local LLM did not return a reason code")
        classifications.append(BlockClassification(block.block_id, label, evidence.strip(), response.raw_content))

    retained: set[int] = set()
    uncertain_ids: list[int] = []
    for block, classification in zip(blocks, classifications, strict=True):
        if classification.label in RETAINED_LABELS:
            retained.update(block.segment_indexes)
        elif classification.label == ContentLabel.UNCERTAIN:
            uncertain_ids.append(block.block_id)
            # Favor recall: preserve uncertain content only when rules put it in the sermon.
            retained.update(index for index in block.segment_indexes if index in rule_window.included_segment_indexes)
    all_timed = {index for block in blocks for index in block.segment_indexes}
    rule_set = set(rule_window.included_segment_indexes)
    agreement = len(retained & rule_set) / max(len(retained | rule_set), 1)
    warnings: list[str] = []
    if uncertain_ids:
        warnings.append("one or more transcript blocks require boundary review")
    if agreement < 0.5:
        warnings.append("local LLM and rule-based sermon windows disagree substantially")
    confidence = "high" if agreement >= 0.8 and not uncertain_ids else "medium"
    if agreement < 0.5 or len(uncertain_ids) > 2:
        confidence = "low"
    return HybridSermonResult(
        method="hybrid_llm_v1",
        model=client.model,
        prompt_version=prompt_version,
        confidence_tier=confidence,
        retained_segment_indexes=sorted(retained),
        excluded_segment_indexes=sorted(all_timed - retained),
        uncertain_block_ids=uncertain_ids,
        warnings=warnings,
        blocks=blocks,
        classifications=classifications,
    )
