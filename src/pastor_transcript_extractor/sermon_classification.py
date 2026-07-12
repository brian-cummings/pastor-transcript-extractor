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
