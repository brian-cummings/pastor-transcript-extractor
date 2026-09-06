from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from pastor_transcript_extractor.caption_normalization import (
    NORMALIZER_VERSION,
    normalize_caption_fragments,
)
from pastor_transcript_extractor.local_llm import LocalLlmClient, LocalLlmResponse
from pastor_transcript_extractor.segmentation import SegmentDraft
from pastor_transcript_extractor.sermon_detection import SermonWindowResult


CONFIDENCE_POLICY_VERSION = "soft_rule_overlap_v2"
BLOCK_BUILDER_VERSION = f"timestamp-blocks-v2+{NORMALIZER_VERSION}"
COARSE_DISCOVERY_VERSION = "phase-primary-evidence-rescue-v3"
FINE_COMPONENT_VERSION = "objective-noise-components+structural-edges-v3"
SEARCH_ALGORITHM_VERSION = "adaptive_llm_v6"
POSITION_PRIOR_VERSION = "service-position-prior-v1"
LONG_EDGE_EXPANSION_SECONDS = 600.0
MAX_PRE_ANCHOR_RECOVERY_SECONDS = 180.0


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
    raw_text: str | None = None
    normalization: dict[str, Any] | None = None


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
    cache_stats: dict[str, int] | None = None
    search: dict[str, Any] | None = None
    confidence_reasons: list[dict[str, Any]] | None = None
    confidence_policy_version: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "method": self.method,
            "block_builder_version": BLOCK_BUILDER_VERSION,
            "coarse_discovery_version": COARSE_DISCOVERY_VERSION,
            "fine_component_version": FINE_COMPONENT_VERSION,
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
            "cache_stats": self.cache_stats or {"hits": 0, "misses": 0},
            "confidence_reasons": self.confidence_reasons or [],
            "confidence_policy_version": self.confidence_policy_version,
            "search": self.search or {
                "schema_version": 1,
                "algorithm_version": self.method,
                "candidates": [],
                "selected_rank": None,
            },
        }


class RawInferenceCache:
    def __init__(
        self,
        root: Path,
        *,
        transcript_hash: str,
        prompt_version: str,
        model_name: str,
        model_digest: str,
        context_size: int,
    ) -> None:
        self.root = root
        self.transcript_hash = transcript_hash
        self.prompt_version = prompt_version
        self.model_name = model_name
        self.model_digest = model_digest
        self.context_size = context_size
        self.hits = 0
        self.misses = 0

    def generate(
        self,
        namespace: str,
        client: LocalLlmClient,
        prompt: str,
        schema: dict[str, Any],
        block: TranscriptBlock,
        previous: TranscriptBlock | None = None,
        following: TranscriptBlock | None = None,
    ) -> LocalLlmResponse:
        def digest(text: str) -> str:
            return hashlib.sha256(text.encode("utf-8")).hexdigest()

        identity = {
            "transcript_hash": self.transcript_hash,
            "block_builder_version": BLOCK_BUILDER_VERSION,
            "block_start_segment": block.segment_indexes[0],
            "block_end_segment": block.segment_indexes[-1],
            "block_text_hash": digest(block.text),
            "context_block_hashes": [
                digest(previous.text) if previous else None,
                digest(following.text) if following else None,
            ],
            "prompt_version": self.prompt_version,
            "schema_version": f"{namespace}-v1",
            "model_name": self.model_name,
            "model_digest": self.model_digest,
            "temperature": 0,
            "context_size": self.context_size,
        }
        key = digest(json.dumps(identity, sort_keys=True, separators=(",", ":")))
        path = self.root / namespace / f"{key}.json"
        if path.exists():
            try:
                cached = json.loads(path.read_text(encoding="utf-8"))
                content = cached["content"]
                raw_content = cached["raw_content"]
                model = cached["model"]
                if isinstance(content, dict) and isinstance(raw_content, str) and isinstance(model, str):
                    self.hits += 1
                    return LocalLlmResponse(content, raw_content, model)
            except (OSError, json.JSONDecodeError, KeyError):
                pass
        response = client.generate_json(prompt, schema)
        self.misses += 1
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"identity": identity, "content": response.content, "raw_content": response.raw_content, "model": response.model},
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        return response


class CoarsePhase(StrEnum):
    SERMON = "sermon"
    WORSHIP = "worship"
    ADMINISTRATION = "administration"
    TRANSITION = "transition"
    UNCERTAIN = "uncertain"


class LikelihoodPhase(StrEnum):
    SERMON_LIKELY = "sermon_likely"
    SERMON_UNLIKELY = "sermon_unlikely"
    UNCERTAIN = "uncertain"


_LIKELIHOOD_DECISIONS: dict[str, tuple[LikelihoodPhase, str, ContentLabel]] = {
    "sermon_biblical_exposition": (
        LikelihoodPhase.SERMON_LIKELY, "biblical_exposition", ContentLabel.SERMON
    ),
    "sermon_sustained_preaching": (
        LikelihoodPhase.SERMON_LIKELY, "biblical_exposition", ContentLabel.SERMON
    ),
    "not_sermon_music_or_lyrics": (
        LikelihoodPhase.SERMON_UNLIKELY, "music_or_lyrics", ContentLabel.MUSIC
    ),
    "not_sermon_extended_prayer": (
        LikelihoodPhase.SERMON_UNLIKELY, "service_prayer", ContentLabel.SERVICE_PRAYER
    ),
    "not_sermon_administration": (
        LikelihoodPhase.SERMON_UNLIKELY, "logistics_or_welcome", ContentLabel.ANNOUNCEMENTS
    ),
    "not_sermon_transition": (
        LikelihoodPhase.SERMON_UNLIKELY, "sermon_transition", ContentLabel.SPEAKER_INTRODUCTION
    ),
    "uncertain": (LikelihoodPhase.UNCERTAIN, "insufficient_context", ContentLabel.UNCERTAIN),
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
            raw_text = "\n".join(texts)
            normalized = normalize_caption_fragments(zip(indexes, texts, strict=True))
            blocks.append(TranscriptBlock(
                len(blocks), list(indexes), start, end, normalized.text,
                raw_text, normalized.diagnostics,
            ))
        indexes, texts, start, end = [], [], None, None

    for index, draft in enumerate(drafts):
        if draft.start_seconds is None or draft.end_seconds is None or draft.end_seconds <= draft.start_seconds:
            continue
        prospective = normalize_caption_fragments(
            zip([*indexes, index], [*texts, draft.text], strict=True)
        ).text
        if start is not None and (
            (draft.end_seconds - start) > target_seconds or len(prospective) > max_chars
        ):
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

_LIKELIHOOD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": list(_LIKELIHOOD_DECISIONS)},
    },
    "required": ["decision"],
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


def _likelihood_prompt(block: TranscriptBlock) -> str:
    return f"""Decide whether this five-minute transcript excerpt contains sustained sermon preaching.
Choose sermon_biblical_exposition or sermon_sustained_preaching when a preacher develops a message, explains Scripture, applies a biblical theme, or continues a sermon. A sermon may include an integrated prayer, illustration, or Communion teaching.
Choose a not_sermon decision only when the excerpt is dominated by music or lyrics, a standalone extended prayer, administration or logistics, or a transition without sustained preaching.
Do not use not_sermon merely because the excerpt comes from a worship service. Religious education and other sustained biblical teaching still count as sermon-likely during discovery; program-type verification happens later.
Choose uncertain only when the text is too fragmentary to decide.
Return exactly one decision from the schema and no prose.

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


def _likelihood_candidate_ranges(
    blocks: list[TranscriptBlock], phases: list[LikelihoodPhase]
) -> list[tuple[float, float]]:
    ranges: list[tuple[float, float]] = []
    position = 0
    while position < len(blocks):
        if phases[position] != LikelihoodPhase.SERMON_LIKELY:
            position += 1
            continue
        start_position = position
        end_position = position
        while end_position + 1 < len(blocks):
            next_phase = phases[end_position + 1]
            if next_phase == LikelihoodPhase.SERMON_LIKELY:
                end_position += 1
                continue
            if (
                next_phase == LikelihoodPhase.UNCERTAIN
                and end_position + 2 < len(blocks)
                and phases[end_position + 2] == LikelihoodPhase.SERMON_LIKELY
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
    "our title today",
    "as we open up god's word",
    "as we open god's word",
    "turn in your bibles",
    "open your bibles",
    "today's message",
    "message that i've entitled",
    "message i have entitled",
)

_EXPLICIT_CLOSING_TRANSITION = re.compile(
    r"\b(?:as we (?:sing|close)|closing (?:song|hymn)|invite you to sing|"
    r"time for questions|any questions|praise team can come)\b",
    re.IGNORECASE,
)
_STRUCTURAL_SERVICE_TRANSITION = re.compile(
    r"(?:♪|\[(?:music|singing)[^]]*\])|\b(?:special music|praise team|"
    r"announcements?|open (?:our|your) hymnals?|song number \d+|"
    r"in jesus(?:'|’) name(?:,)? (?:we )?pray|amen\.?$)\b",
    re.IGNORECASE,
)


def _draft_interval_coverage(
    drafts: list[SegmentDraft], start: float, end: float, labels: set[str]
) -> float:
    intervals = sorted(
        (max(start, float(draft.start_seconds)), min(end, float(draft.end_seconds)))
        for draft in drafts
        if draft.start_seconds is not None
        and draft.end_seconds is not None
        and draft.end_seconds > start
        and draft.start_seconds < end
        and draft.label.value in labels
        and not _STRUCTURAL_SERVICE_TRANSITION.search(draft.text)
    )
    coverage = 0.0
    cursor: float | None = None
    for left, right in intervals:
        if right <= left:
            continue
        if cursor is None or left > cursor:
            coverage += right - left
            cursor = right
        elif right > cursor:
            coverage += right - cursor
            cursor = right
    return coverage


def _service_interval_coverage(
    drafts: list[SegmentDraft], start: float, end: float
) -> float:
    intervals = sorted(
        (max(start, float(draft.start_seconds)), min(end, float(draft.end_seconds)))
        for draft in drafts
        if draft.start_seconds is not None
        and draft.end_seconds is not None
        and draft.end_seconds > start
        and draft.start_seconds < end
        and (
            draft.label.value in {"music", "prayer", "announcements"}
            or bool(_STRUCTURAL_SERVICE_TRANSITION.search(draft.text))
        )
    )
    coverage = 0.0
    cursor: float | None = None
    for left, right in intervals:
        if right <= left:
            continue
        if cursor is None or left > cursor:
            coverage += right - left
            cursor = right
        elif right > cursor:
            coverage += right - cursor
            cursor = right
    return coverage


def _candidate_strength(
    candidate: tuple[float, float], blocks: list[TranscriptBlock]
) -> float:
    return float(_candidate_score_components(candidate, blocks)["total_score"])


def recording_structure_prior(video_title: str | None) -> dict[str, Any]:
    """Return a soft, title-derived prior for where a service sermon is likely to occur.

    Position affects candidate discovery and ranking only.  It is never evidence that
    a candidate is a sermon and therefore cannot make a candidate acceptable by itself.
    """
    normalized = " ".join((video_title or "").casefold().replace("’", "'").split())
    combined = "sabbath school" in normalized and any(
        marker in normalized
        for marker in ("church", "worship", "divine service", "divine worship")
    )
    if combined:
        return {
            "version": POSITION_PRIOR_VERSION,
            "kind": "combined_sabbath_school_and_church",
            "preferred_region_start_fraction": 0.75,
            "preferred_region_end_fraction": 0.98,
            "comparison_region_start_fraction": 0.75,
            "maximum_bonus": 1600.0,
            "evidence_role": "search_and_ranking_only",
        }
    service_markers = (
        "church service",
        "worship service",
        "divine service",
        "divine worship",
        "sabbath service",
        "morning worship",
        "evening worship",
    )
    if any(marker in normalized for marker in service_markers):
        return {
            "version": POSITION_PRIOR_VERSION,
            "kind": "worship_service",
            "preferred_region_start_fraction": 0.50,
            "preferred_region_end_fraction": 0.95,
            "comparison_region_start_fraction": 0.50,
            "maximum_bonus": 900.0,
            "evidence_role": "search_and_ranking_only",
        }
    return {
        "version": POSITION_PRIOR_VERSION,
        "kind": "unknown_or_sermon_only",
        "preferred_region_start_fraction": None,
        "preferred_region_end_fraction": None,
        "comparison_region_start_fraction": None,
        "maximum_bonus": 0.0,
        "evidence_role": "none",
    }


def _candidate_score_components(
    candidate: tuple[float, float],
    blocks: list[TranscriptBlock],
    *,
    audit: list[BlockClassification] | None = None,
    rule_window: SermonWindowResult | None = None,
    recording_duration_seconds: float | None = None,
    position_prior: dict[str, Any] | None = None,
) -> dict[str, Any]:
    start, end = candidate
    supporting_positions = [
        position for position, block in enumerate(blocks) if _overlaps(block, start, end)
    ]
    text = " ".join(blocks[position].text.lower() for position in supporting_positions)
    matched_cues = [cue for cue in _SERMON_SEED_CUES if cue in text]
    duration = end - start
    # Duration is useful evidence of continuity, but it is deliberately capped so
    # a long religious program cannot outrank a more sermon-specific candidate by
    # length alone.
    duration_score = min(duration, 1200.0)
    cue_bonus = len(matched_cues) * 1800.0
    sermon_specific_reasons = []
    if audit is not None:
        sermon_specific_reasons = [
            item.evidence.partition(":")[2]
            for position in supporting_positions
            if position < len(audit)
            and (item := audit[position]).evidence.partition(":")[2]
            in {"biblical_exposition", "integrated_scripture"}
        ]
    semantic_ratio = len(sermon_specific_reasons) / max(len(supporting_positions), 1)
    semantic_bonus = semantic_ratio * 900.0
    cohesion_ratio = (
        sum(
            1
            for position in supporting_positions
            if audit is None
            or (
                position < len(audit)
                and (
                    getattr(audit[position], "label", None) == ContentLabel.SERMON
                    or getattr(audit[position], "evidence", "").partition(":")[2]
                    in {"biblical_exposition", "integrated_scripture"}
                )
            )
        )
        / max(len(supporting_positions), 1)
    )
    cohesion_bonus = cohesion_ratio * 450.0
    rule_overlap_seconds = 0.0
    rule_coverage = 0.0
    rule_bonus = 0.0
    if (
        rule_window is not None
        and rule_window.start_seconds is not None
        and rule_window.end_seconds is not None
        and rule_window.end_seconds > rule_window.start_seconds
        and rule_window.method != "manual_override_v1"
    ):
        rule_overlap_seconds = max(
            0.0,
            min(end, rule_window.end_seconds) - max(start, rule_window.start_seconds),
        )
        rule_coverage = rule_overlap_seconds / (
            rule_window.end_seconds - rule_window.start_seconds
        )
        rule_bonus = rule_coverage * max(0.0, min(rule_window.confidence, 1.0)) * 1200.0
    candidate_start_fraction = None
    candidate_end_fraction = None
    preferred_region_coverage = 0.0
    position_prior_bonus = 0.0
    prior_start = position_prior.get("preferred_region_start_fraction") if position_prior else None
    prior_end = position_prior.get("preferred_region_end_fraction") if position_prior else None
    maximum_bonus = position_prior.get("maximum_bonus", 0.0) if position_prior else 0.0
    if (
        isinstance(recording_duration_seconds, (int, float))
        and recording_duration_seconds > 0
        and isinstance(prior_start, (int, float))
        and isinstance(prior_end, (int, float))
    ):
        candidate_start_fraction = max(0.0, min(1.0, start / recording_duration_seconds))
        candidate_end_fraction = max(0.0, min(1.0, end / recording_duration_seconds))
        preferred_start = recording_duration_seconds * float(prior_start)
        preferred_end = recording_duration_seconds * float(prior_end)
        preferred_overlap = max(0.0, min(end, preferred_end) - max(start, preferred_start))
        preferred_region_coverage = preferred_overlap / max(duration, 1.0)
        # Reward overlap plus a start near the expected service phase.  Keeping this
        # separate from semantic evidence makes the soft prior inspectable.
        start_alignment = max(
            0.0,
            min(1.0, (candidate_start_fraction - max(0.0, float(prior_start) - 0.20)) / 0.20),
        )
        position_prior_bonus = float(maximum_bonus) * (
            0.65 * preferred_region_coverage + 0.35 * start_alignment
        )
    return {
        "duration_seconds": round(duration, 3),
        "duration_score": round(duration_score, 3),
        "matched_sermon_cues": matched_cues,
        "cue_bonus": round(cue_bonus, 3),
        "sermon_specific_support_count": len(sermon_specific_reasons),
        "sermon_specific_support_ratio": round(semantic_ratio, 6),
        "semantic_bonus": round(semantic_bonus, 3),
        "cohesion_ratio": round(cohesion_ratio, 6),
        "cohesion_bonus": round(cohesion_bonus, 3),
        "independent_rule_overlap_seconds": round(rule_overlap_seconds, 3),
        "independent_rule_coverage": round(rule_coverage, 6),
        "independent_rule_bonus": round(rule_bonus, 3),
        "recording_structure": position_prior.get("kind") if position_prior else None,
        "candidate_start_fraction": (
            round(candidate_start_fraction, 6) if candidate_start_fraction is not None else None
        ),
        "candidate_end_fraction": (
            round(candidate_end_fraction, 6) if candidate_end_fraction is not None else None
        ),
        "preferred_region_coverage": round(preferred_region_coverage, 6),
        "position_prior_bonus": round(position_prior_bonus, 3),
        "total_score": round(
            duration_score
            + cue_bonus
            + semantic_bonus
            + cohesion_bonus
            + rule_bonus
            + position_prior_bonus,
            3,
        ),
    }


_ALLOWED_JOIN_REASON_CODES = {
    "sermon_transition",
    "integrated_prayer",
    "integrated_scripture",
    "service_prayer",
    "service_reading",
    "speaker_handoff",
}


def _joined_candidate(
    left: dict[str, Any],
    right: dict[str, Any],
    blocks: list[TranscriptBlock],
    audit: list[BlockClassification],
    rule_window: SermonWindowResult | None = None,
    recording_duration_seconds: float | None = None,
    position_prior: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    left_end = float(left["end_seconds"])
    right_start = float(right["start_seconds"])
    gap_duration = right_start - left_end
    if gap_duration <= 0.0 or gap_duration > 360.0:
        return None
    gap_evidence = [
        (block, item.evidence.partition(":")[2])
        for block, item in zip(blocks, audit, strict=True)
        if block.end_seconds > left_end and block.start_seconds < right_start
    ]
    if not gap_evidence or any(reason not in _ALLOWED_JOIN_REASON_CODES for _, reason in gap_evidence):
        return None
    start = float(left["start_seconds"])
    end = float(right["end_seconds"])
    resumed_text = " ".join(
        block.text.lower()
        for block in blocks
        if _overlaps(block, right_start, float(right["end_seconds"]))
    )
    continuity_cues = [cue for cue in _SERMON_SEED_CUES if cue in resumed_text]
    if not continuity_cues:
        return None
    score_components = _candidate_score_components(
        (start, end),
        blocks,
        audit=audit,
        rule_window=rule_window,
        recording_duration_seconds=recording_duration_seconds,
        position_prior=position_prior,
    )
    reasons = sorted({reason for _, reason in gap_evidence})
    score_components["join_gap_duration_seconds"] = round(gap_duration, 3)
    score_components["join_reason_codes"] = reasons
    return {
        "source": "joined_coarse_llm",
        "start_seconds": start,
        "end_seconds": end,
        "score": score_components["total_score"],
        "score_components": score_components,
        "coarse_support_block_ids": list(dict.fromkeys(
            list(left["coarse_support_block_ids"]) + list(right["coarse_support_block_ids"])
        )),
        "fine_support_block_ids": [],
        "refinement_reasons": [
            f"joined sermon candidates across {gap_duration:.1f}s interruption classified as {', '.join(reasons)}"
        ],
        "join": {
            "gap_start_seconds": left_end,
            "gap_end_seconds": right_start,
            "gap_duration_seconds": round(gap_duration, 3),
            "reason_codes": reasons,
            "continuity_cues": continuity_cues,
        },
    }


def _explicit_sermon_seed_seconds(
    drafts: list[SegmentDraft], retained_indexes: set[int]
) -> float | None:
    for index in sorted(retained_indexes):
        draft = drafts[index]
        lower = draft.text.lower()
        if any(cue in lower for cue in _SERMON_SEED_CUES):
            return draft.start_seconds
    return None


def _noise_ratio(block: TranscriptBlock, drafts: list[SegmentDraft]) -> float:
    if not block.segment_indexes:
        return 0.0
    noisy = 0
    for index in block.segment_indexes:
        lower = drafts[index].text.lower()
        if "[music" in lower or "[singing" in lower or lower.strip() in {"music", "singing"}:
            noisy += 1
    return noisy / len(block.segment_indexes)


def _strong_pre_anchor_negative(block: TranscriptBlock, drafts: list[SegmentDraft]) -> str | None:
    if _noise_ratio(block, drafts) >= 0.35:
        return "music"
    text = " ".join(drafts[index].text.lower() for index in block.segment_indexes)
    negative_markers = {
        "announcements": (
            "announcement",
            "register for",
            "registration",
            "next week",
            "offering",
            "camp meeting",
            "vbs",
            "pastor will be away",
        ),
        "children_story": ("children's story", "children's corner", "children come forward"),
        "service_transition": ("our speaker today", "welcome to the pulpit", "special music", "please stand"),
    }
    for reason, markers in negative_markers.items():
        if any(marker in text for marker in markers):
            return reason
    return None


def _refine_retained_boundaries(
    drafts: list[SegmentDraft],
    fine_blocks: list[TranscriptBlock],
    retained: set[int],
    *,
    preserve_joined_start: bool = False,
    default_pre_roll_start: float | None = None,
) -> tuple[set[int], list[str], dict[str, Any] | None]:
    refined = set(retained)
    reasons: list[str] = []
    start_refinement: dict[str, Any] | None = None
    seed = _explicit_sermon_seed_seconds(drafts, refined)
    if seed is not None and not preserve_joined_start:
        recovered: set[int] = set()
        stopped_by: str | None = None
        default_floor = (
            default_pre_roll_start
            if default_pre_roll_start is not None and default_pre_roll_start < seed
            else 0.0
        )
        recovery_floor = max(0.0, seed - MAX_PRE_ANCHOR_RECOVERY_SECONDS, default_floor)
        for block in reversed(
            [
                item
                for item in fine_blocks
                if item.start_seconds < seed and item.end_seconds > recovery_floor
            ]
        ):
            negative = _strong_pre_anchor_negative(block, drafts)
            if negative is not None:
                stopped_by = negative
                break
            retained_ratio = len(set(block.segment_indexes) & refined) / max(len(block.segment_indexes), 1)
            if retained_ratio < 0.75:
                stopped_by = "non_sermon_fine_label"
                break
            recovered.update(block.segment_indexes)
        recovered_starts = [
            drafts[index].start_seconds
            for index in recovered
            if drafts[index].start_seconds is not None and drafts[index].start_seconds < seed
        ]
        for index in list(refined):
            draft = drafts[index]
            if draft.end_seconds is None or draft.end_seconds > seed:
                continue
            lower = draft.text.lower()
            integral_pre_roll = (
                draft.start_seconds is not None and (
                    draft.label.value in {"prayer", "reading"}
                    or "scripture reading" in lower
                    or "our speaker" in lower
                    or "welcome to the pulpit" in lower
                )
            )
            if index not in recovered and not integral_pre_roll:
                refined.discard(index)
        if recovered_starts:
            extension = seed - min(recovered_starts)
            reasons.append("extended explicit sermon anchor backward through contiguous sermon-like exposition")
            start_refinement = {
                "start_anchor": "explicit_sermon_title",
                "pre_anchor_extension_seconds": round(extension, 3),
                "extension_reason": "contiguous_sermon_like_exposition",
                "stopped_by": stopped_by or "inspection_limit",
                "recall_guard_floor_seconds": round(recovery_floor, 3),
            }
        else:
            reasons.append("anchored candidate start to an explicit sermon-title or message cue")
            start_refinement = {
                "start_anchor": "explicit_sermon_title",
                "pre_anchor_extension_seconds": 0.0,
                "extension_reason": None,
                "stopped_by": stopped_by or "no_sermon_like_pre_anchor_block",
            }

    return refined, reasons, start_refinement


def _rule_supported_structural_precision(
    drafts: list[SegmentDraft],
    retained: set[int],
    rule_window: SermonWindowResult,
    *,
    allow_unbaselined_transition: bool = False,
) -> tuple[set[int], list[dict[str, Any]]]:
    """Trim only explicit internal transitions supported by rule direction."""
    timed = [
        (index, drafts[index])
        for index in sorted(retained)
        if drafts[index].start_seconds is not None
        and drafts[index].end_seconds is not None
    ]
    if not timed:
        return retained, []
    start = min(float(draft.start_seconds) for _, draft in timed)
    end = max(float(draft.end_seconds) for _, draft in timed)
    duration = end - start
    if duration < 600.0:
        return retained, []
    refined = set(retained)
    decisions: list[dict[str, Any]] = []
    seed = _explicit_sermon_seed_seconds(drafts, retained)
    if (
        seed is not None
        and rule_window.start_seconds is not None
        and rule_window.start_seconds > start
        and start + 15.0 <= seed <= start + duration * 0.45
    ):
        refined = {
            index
            for index in refined
            if drafts[index].end_seconds is None or drafts[index].end_seconds > seed
        }
        decisions.append({
            "edge": "start",
            "decision": "explicit_sermon_anchor_selected",
            "boundary_seconds": round(float(seed), 3),
            "rule_direction": "inward",
        })
        start = float(seed)
    rule_supports_inward_start = (
        rule_window.start_seconds is not None and rule_window.start_seconds > start
    )
    if not any(item.get("edge") == "start" for item in decisions) and (
        rule_supports_inward_start or allow_unbaselined_transition
    ):
        transition_candidates: list[tuple[float, float]] = []
        for _, draft in timed:
            boundary = float(draft.start_seconds)
            if not start + 15.0 <= boundary <= start + duration * 0.45:
                continue
            prior_service = _service_interval_coverage(
                drafts, max(start, boundary - 120.0), boundary
            )
            following_sermon = _draft_interval_coverage(
                drafts,
                boundary,
                min(end, boundary + 120.0),
                {"sermon", "reading"},
            )
            if prior_service >= 10.0 and following_sermon >= 60.0:
                transition_candidates.append((boundary, prior_service))
        if transition_candidates:
            eligible_transitions = (
                [
                    item
                    for item in transition_candidates
                    if rule_window.start_seconds is not None
                    and item[0] <= rule_window.start_seconds
                ]
                if rule_supports_inward_start
                else transition_candidates
            )
            pool = eligible_transitions or transition_candidates
            boundary, prior_service = max(
                pool, key=lambda item: (item[1], -item[0])
            )
            refined = {
                index
                for index in refined
                if drafts[index].end_seconds is None
                or drafts[index].end_seconds > boundary
            }
            decisions.append({
                "edge": "start",
                "decision": "service_to_sermon_transition_selected",
                "boundary_seconds": round(boundary, 3),
                "prior_service_seconds": round(prior_service, 3),
                "rule_direction": (
                    "inward" if rule_supports_inward_start else "unavailable"
                ),
            })
            start = boundary
    if (
        not any(item.get("edge") == "start" for item in decisions)
        and rule_window.start_seconds is not None
        and start < rule_window.start_seconds < end
        and (rule_window.start_seconds - start) / duration <= 0.15
    ):
        boundary = float(rule_window.start_seconds)
        refined = {
            index
            for index in refined
            if drafts[index].end_seconds is None or drafts[index].end_seconds > boundary
        }
        decisions.append({
            "edge": "start",
            "decision": "bounded_rule_edge_selected",
            "boundary_seconds": round(boundary, 3),
            "trim_fraction": round((boundary - start) / duration, 6),
        })
        start = boundary
    closing_candidates: list[tuple[float, int, str, float]] = []
    for _, draft in timed:
        boundary = float(draft.start_seconds)
        if not start + (end - start) * 0.55 <= boundary <= end - 15.0:
            continue
        explicit = bool(
            _EXPLICIT_CLOSING_TRANSITION.search(draft.text)
            or re.search(r"\bsong number \d+\b", draft.text, re.IGNORECASE)
        )
        service_after = _service_interval_coverage(
            drafts, boundary, min(end, boundary + 120.0)
        )
        late_service_transition = (
            boundary >= start + (end - start) * 0.70
            and draft.label.value in {"music", "prayer"}
            and service_after >= 10.0
        )
        if explicit or late_service_transition:
            closing_candidates.append((
                boundary,
                100 if explicit else 90 if draft.label.value == "prayer" else 80,
                (
                    "explicit_closing_transition"
                    if explicit
                    else "late_service_transition"
                ),
                service_after,
            ))
    if (
        closing_candidates
        and (
            (
                rule_window.end_seconds is not None
                and rule_window.end_seconds < end
            )
            or allow_unbaselined_transition
        )
    ):
        boundary, _, transition_kind, service_after = sorted(
            closing_candidates, key=lambda item: (-item[1], item[0])
        )[0]
        refined = {
            index
            for index in refined
            if drafts[index].start_seconds is None
            or drafts[index].start_seconds < boundary
        }
        decisions.append({
            "edge": "end",
            "decision": "explicit_closing_transition_selected",
            "boundary_seconds": round(boundary, 3),
            "transition_kind": transition_kind,
            "following_service_seconds": round(service_after, 3),
            "rule_direction": (
                "inward"
                if rule_window.end_seconds is not None
                and rule_window.end_seconds < end
                else "unavailable"
            ),
        })
    remaining = [
        drafts[index]
        for index in refined
        if drafts[index].start_seconds is not None
        and drafts[index].end_seconds is not None
    ]
    if not remaining or (
        max(float(draft.end_seconds) for draft in remaining)
        - min(float(draft.start_seconds) for draft in remaining)
        < 600.0
    ):
        return retained, [{
            "decision": "rejected",
            "reason": "minimum_remaining_sermon_not_satisfied",
            "proposed_edges": decisions,
        }]
    return refined, decisions


def _apply_refinement_retention_safety(
    proposed: set[int],
    pre_refinement: set[int],
    *,
    objective_separator_block_ids: list[int],
) -> tuple[set[int], dict[str, Any]]:
    retention = len(proposed & pre_refinement) / max(len(pre_refinement), 1)
    triggered = (
        bool(pre_refinement)
        and retention < 0.5
        and not objective_separator_block_ids
    )
    evidence = {
        "contract_version": "fine-retention-v1",
        "triggered": triggered,
        "pre_refinement_segment_count": len(pre_refinement),
        "proposed_segment_count": len(proposed),
        "proposed_retention_ratio": round(retention, 6),
        "objective_separator_present": bool(objective_separator_block_ids),
        "decision": (
            "restore_pre_refinement_component"
            if triggered
            else "accept_boundary_refinement"
        ),
        "reason": (
            "catastrophic_trim_without_independent_boundary_evidence"
            if triggered
            else "retention_within_contract_or_objective_separator_present"
        ),
    }
    return (set(pre_refinement) if triggered else set(proposed)), evidence


def _sustained_noise_separator_positions(
    positions: list[int], blocks: list[TranscriptBlock], drafts: list[SegmentDraft]
) -> set[int]:
    position_set = set(positions)
    noisy = {
        position for position in positions if _noise_ratio(blocks[position], drafts) >= 0.45
    }
    separators: set[int] = set()
    for position in noisy:
        if position + 1 in noisy and position + 1 in position_set:
            separators.update({position, position + 1})
    return separators


def _central_consistency_warnings(
    drafts: list[SegmentDraft],
    retained: set[int],
    fine_blocks: list[TranscriptBlock],
    fine_audit: list[BlockClassification],
    coarse_blocks: list[TranscriptBlock],
    phases: list[CoarsePhase],
) -> list[str]:
    timed = [drafts[index] for index in retained if drafts[index].start_seconds is not None and drafts[index].end_seconds is not None]
    if not timed:
        return ["candidate has no timestamped retained content"]
    start = min(draft.start_seconds for draft in timed if draft.start_seconds is not None)
    end = max(draft.end_seconds for draft in timed if draft.end_seconds is not None)
    central_start = start + (end - start) * 0.1
    central_end = end - (end - start) * 0.1
    warnings: list[str] = []
    central_fine = [
        classification
        for block, classification in zip(fine_blocks, fine_audit, strict=True)
        if _overlaps(block, central_start, central_end)
    ]
    fine_support = sum(1 for item in central_fine if item.label in RETAINED_LABELS)
    if not central_fine or fine_support / len(central_fine) < 0.75:
        warnings.append("fine labels do not show sustained exposition across the candidate center")
    central_coarse = [
        phase
        for block, phase in zip(coarse_blocks, phases, strict=True)
        if _overlaps(block, central_start, central_end)
    ]
    coarse_support = sum(1 for phase in central_coarse if phase == CoarsePhase.SERMON)
    if not central_coarse or coarse_support / len(central_coarse) < 0.6:
        warnings.append("coarse and fine labels disagree across the candidate center")
    return warnings


def _adaptive_confidence_tier(
    *,
    agreement: float,
    retained: bool,
    uncertain: bool,
    consistency_failed: bool,
) -> str:
    if not retained or consistency_failed:
        return "low"
    if uncertain:
        return "medium"
    return "medium" if agreement < 0.5 else "high"


def _long_recording_edge_expansion(
    probe_outcomes: dict[str, dict[str, Any]], blocks: list[TranscriptBlock]
) -> dict[str, Any] | None:
    blocks_by_id = {block.block_id: block for block in blocks}
    expansions: list[dict[str, Any]] = []
    for direction in ("start", "end"):
        outcome = probe_outcomes.get(direction, {})
        if outcome.get("status") != "recording_edge":
            continue
        block_ids = [
            block_id
            for block_id in outcome.get("probed_block_ids", [])
            if isinstance(block_id, int) and block_id in blocks_by_id
        ]
        duration = sum(
            blocks_by_id[block_id].end_seconds - blocks_by_id[block_id].start_seconds
            for block_id in block_ids
        )
        if duration > LONG_EDGE_EXPANSION_SECONDS:
            expansions.append({
                "direction": direction,
                "duration_seconds": round(duration, 3),
                "block_ids": block_ids,
            })
    if not expansions:
        return None
    return {
        "threshold_seconds": LONG_EDGE_EXPANSION_SECONDS,
        "expansions": expansions,
    }


def classify_sermon_content_adaptive(
    drafts: list[SegmentDraft],
    rule_window: SermonWindowResult,
    client: LocalLlmClient,
    *,
    prompt_version: str = "sermon-content-v2",
    progress: Any | None = None,
    cache_dir: Path | None = None,
    model_digest: str | None = None,
    context_size: int = 4096,
    rule_baseline_source: str = "recomputed_rules",
    rule_baseline_algorithm_version: str | None = None,
    manual_override_present: bool = False,
    video_title: str | None = None,
) -> HybridSermonResult:
    if rule_window.method == "manual_override_v1" or rule_baseline_source == "manual_override":
        raise ValueError(
            "manual content overrides cannot be used as independent rule-baseline evidence"
        )
    coarse_blocks = build_transcript_blocks(drafts, target_seconds=300.0, max_chars=9000)
    if not coarse_blocks:
        raise ValueError("LLM classification requires timestamped transcript segments")
    recording_duration_seconds = max(block.end_seconds for block in coarse_blocks)
    position_prior = recording_structure_prior(video_title)
    transcript_identity = json.dumps(
        [(draft.start_seconds, draft.end_seconds, draft.text) for draft in drafts],
        separators=(",", ":"),
    )
    cache = None
    if cache_dir is not None and model_digest is not None:
        cache = RawInferenceCache(
            cache_dir,
            transcript_hash=hashlib.sha256(transcript_identity.encode("utf-8")).hexdigest(),
            prompt_version=prompt_version,
            model_name=client.model,
            model_digest=model_digest,
            context_size=context_size,
        )
    phases: list[CoarsePhase] = []
    coarse_audit: list[BlockClassification] = []
    total_estimate = len(coarse_blocks)
    for position, block in enumerate(coarse_blocks):
        if progress is not None:
            progress("coarse", position + 1, total_estimate)
        prompt = _coarse_prompt(block)
        response = (
            cache.generate("coarse", client, prompt, _COARSE_SCHEMA, block)
            if cache is not None
            else client.generate_json(prompt, _COARSE_SCHEMA)
        )
        try:
            phase = CoarsePhase(str(response.content["phase"]))
        except (KeyError, ValueError) as error:
            raise ValueError("Local LLM returned an unsupported coarse worship-service phase") from error
        reason = response.content.get("reason_code")
        if not isinstance(reason, str) or reason not in REASON_CODES:
            raise ValueError("Local LLM did not return a supported coarse reason code")
        mapped_label = {
            CoarsePhase.SERMON: ContentLabel.SERMON,
            CoarsePhase.WORSHIP: ContentLabel.MUSIC,
            CoarsePhase.ADMINISTRATION: ContentLabel.ANNOUNCEMENTS,
            CoarsePhase.TRANSITION: ContentLabel.SPEAKER_INTRODUCTION,
            CoarsePhase.UNCERTAIN: ContentLabel.UNCERTAIN,
        }[phase]
        phases.append(phase)
        coarse_audit.append(BlockClassification(block.block_id, mapped_label, f"coarse:{reason}", response.raw_content))

    coarse_candidates = _coarse_candidate_ranges(coarse_blocks, phases)
    primary_candidates = list(coarse_candidates)
    primary_score_components = [
        _candidate_score_components(
            candidate,
            coarse_blocks,
            audit=coarse_audit,
            rule_window=rule_window,
            recording_duration_seconds=recording_duration_seconds,
            position_prior=position_prior,
        )
        for candidate in primary_candidates
    ]
    primary_top = max(
        zip(primary_candidates, primary_score_components, strict=True),
        key=lambda item: (float(item[1]["total_score"]), item[0][0]),
        default=None,
    )
    rescue_reasons: list[str] = []
    if not coarse_candidates:
        rescue_reasons.append("primary_found_no_candidate")
    elif primary_top is not None:
        top_range, top_score = primary_top
        if (
            not top_score["matched_sermon_cues"]
            and float(top_score["sermon_specific_support_ratio"]) < 0.75
        ):
            rescue_reasons.append("top_candidate_lacks_strong_sermon_specific_cues")
        if (
            len(primary_candidates) > 1
            and any(candidate[0] > top_range[1] for candidate in primary_candidates)
        ):
            rescue_reasons.append("disjoint_later_candidate_requires_comparison")
        comparison_start = position_prior.get("comparison_region_start_fraction")
        if (
            isinstance(comparison_start, (int, float))
            and not any(
                candidate[1] >= recording_duration_seconds * float(comparison_start)
                for candidate in primary_candidates
            )
        ):
            rescue_reasons.append("expected_late_service_region_requires_comparison")
        if (
            rule_window.start_seconds is not None
            and rule_window.end_seconds is not None
            and float(top_score["independent_rule_coverage"]) < 0.35
        ):
            rescue_reasons.append("rule_adaptive_evidence_disagrees_substantially")
    rescue_triggered = bool(rescue_reasons)
    selected_discovery_mode = "primary"
    candidate_source = "coarse_llm"
    rescue_audit: list[BlockClassification] = []
    if rescue_triggered:
        likelihood_phases: list[LikelihoodPhase] = []
        for position, block in enumerate(coarse_blocks):
            if progress is not None:
                progress("coarse-rescue", position + 1, total_estimate)
            prompt = _likelihood_prompt(block)
            response = (
                cache.generate("coarse-likelihood", client, prompt, _LIKELIHOOD_SCHEMA, block)
                if cache is not None
                else client.generate_json(prompt, _LIKELIHOOD_SCHEMA)
            )
            try:
                phase, reason, mapped_label = _LIKELIHOOD_DECISIONS[
                    str(response.content["decision"])
                ]
            except (KeyError, ValueError) as error:
                raise ValueError("Local LLM returned an unsupported sermon-likelihood decision") from error
            likelihood_phases.append(phase)
            rescue_audit.append(BlockClassification(
                block.block_id,
                mapped_label,
                f"coarse-rescue:{reason}",
                response.raw_content,
            ))
        rescue_candidates = _likelihood_candidate_ranges(coarse_blocks, likelihood_phases)
        rescue_phases = [
            CoarsePhase.SERMON
            if phase == LikelihoodPhase.SERMON_LIKELY
            else CoarsePhase.UNCERTAIN
            if phase == LikelihoodPhase.UNCERTAIN
            else CoarsePhase.WORSHIP
            for phase in likelihood_phases
        ]
        if not primary_candidates:
            coarse_candidates = rescue_candidates
            phases = rescue_phases
            coarse_audit = rescue_audit
            selected_discovery_mode = "likelihood_rescue"
            candidate_source = "coarse_likelihood_rescue"
        else:
            # Preserve independent primary evidence and add genuinely new rescue
            # envelopes for ranking.  This avoids making rescue an all-or-nothing
            # replacement of a useful primary scan.
            coarse_candidates = list(primary_candidates)
            for candidate in rescue_candidates:
                if candidate not in coarse_candidates:
                    coarse_candidates.append(candidate)
            selected_discovery_mode = "primary_plus_likelihood_rescue"
    discovery = {
        "primary_version": "multiclass-phase-v1",
        "rescue_version": "sermon-likelihood-v1",
        "rescue_triggered": rescue_triggered,
        "rescue_reasons": rescue_reasons,
        "rescue_outcome": (
            "added_or_reranked_candidates"
            if rescue_triggered and coarse_candidates
            else "no_candidate_found"
            if rescue_triggered
            else "not_triggered"
        ),
        "selected_mode": selected_discovery_mode,
        "recording_structure": position_prior,
    }
    ranked_candidates: list[dict[str, Any]] = []
    for start, end in coarse_candidates:
        candidate_is_primary = (start, end) in primary_candidates
        scoring_audit = (
            coarse_audit if candidate_is_primary or not rescue_audit else rescue_audit
        )
        score_components = _candidate_score_components(
            (start, end),
            coarse_blocks,
            audit=scoring_audit,
            rule_window=rule_window,
            recording_duration_seconds=recording_duration_seconds,
            position_prior=position_prior,
        )
        supporting_blocks = [
            block.block_id for block in coarse_blocks if _overlaps(block, start, end)
        ]
        ranked_candidates.append(
            {
                "source": (
                    candidate_source
                    if candidate_is_primary or not primary_candidates
                    else "coarse_likelihood_rescue"
                ),
                "start_seconds": start,
                "end_seconds": end,
                "score": score_components["total_score"],
                "score_components": score_components,
                "coarse_support_block_ids": supporting_blocks,
                "fine_support_block_ids": [],
                "refinement_reasons": [],
            }
        )
    chronological_candidates = sorted(ranked_candidates, key=lambda candidate: float(candidate["start_seconds"]))
    joined_candidates = [
        joined
        for left, right in zip(chronological_candidates, chronological_candidates[1:], strict=False)
        if (
            joined := _joined_candidate(
                left,
                right,
                coarse_blocks,
                coarse_audit,
                rule_window,
                recording_duration_seconds,
                position_prior,
            )
        )
        is not None
    ]
    ranked_candidates.extend(joined_candidates)
    ranked_candidates.sort(key=lambda candidate: (-float(candidate["score"]), float(candidate["start_seconds"])))
    for rank, candidate in enumerate(ranked_candidates, start=1):
        candidate["rank"] = rank
        candidate["selection_state"] = "selected" if rank == 1 else "alternative"
    if ranked_candidates:
        selected_candidate = ranked_candidates[0]
    elif rule_window.start_seconds is not None and rule_window.end_seconds is not None:
        selected_candidate = {
            "rank": 1,
            "source": "rule_fallback",
            "start_seconds": rule_window.start_seconds,
            "end_seconds": rule_window.end_seconds,
            "score": 0.0,
            "score_components": {
                "duration_seconds": round(rule_window.end_seconds - rule_window.start_seconds, 3),
                "matched_sermon_cues": [],
                "cue_bonus": 0.0,
                "total_score": 0.0,
                "source_note": "rule fallback candidates are not coarse-ranked",
            },
            "coarse_support_block_ids": [],
            "fine_support_block_ids": [],
            "refinement_reasons": ["no coarse LLM candidate; refined the rule-based fallback"],
        }
        ranked_candidates = [selected_candidate]
    else:
        search = {
            "schema_version": 1,
            "algorithm_version": SEARCH_ALGORITHM_VERSION,
            "candidates": [],
            "selected_rank": None,
            "rule_baseline": None,
            "model_digest": model_digest,
            "rule_baseline_source": rule_baseline_source,
            "rule_baseline_algorithm_version": rule_baseline_algorithm_version or rule_window.method,
            "manual_override_present": manual_override_present,
            "discovery": discovery,
            "recording_structure": position_prior,
        }
        return HybridSermonResult(
            SEARCH_ALGORITHM_VERSION, client.model, prompt_version, "low", [],
            [index for block in coarse_blocks for index in block.segment_indexes], [],
            ["no plausible sermon region found during coarse scan"], coarse_blocks, coarse_audit,
            {"hits": cache.hits, "misses": cache.misses} if cache is not None else None,
            search,
            [{
                "code": "no_plausible_candidate",
                "effect": "low_confidence",
                "message": "No plausible sermon region was found during coarse scan.",
            }],
        )

    selected_range = (
        float(selected_candidate["start_seconds"]),
        float(selected_candidate["end_seconds"]),
    )
    expanded_candidates = [(max(0.0, selected_range[0] - 360.0), selected_range[1] + 120.0)]
    all_fine_blocks = build_transcript_blocks(drafts)
    initial_positions = [
        position
        for position, block in enumerate(all_fine_blocks)
        if any(_overlaps(block, start, end) for start, end in expanded_candidates)
    ]
    inspected_positions = set(initial_positions)
    fine_audit_by_position: dict[int, BlockClassification] = {}
    retained: set[int] = set()
    uncertain_ids: list[int] = []
    rule_indexes = set(rule_window.included_segment_indexes)

    def classify_fine_position(position: int) -> None:
        if position in fine_audit_by_position:
            return
        block = all_fine_blocks[position]
        if progress is not None:
            progress("fine", len(fine_audit_by_position) + 1, len(all_fine_blocks))
        previous = all_fine_blocks[position - 1] if position else None
        following = all_fine_blocks[position + 1] if position + 1 < len(all_fine_blocks) else None
        prompt = _prompt(block, previous, following)
        response = (
            cache.generate("fine", client, prompt, _SCHEMA, block, previous, following)
            if cache is not None
            else client.generate_json(prompt, _SCHEMA)
        )
        try:
            label = ContentLabel(str(response.content["label"]))
        except (KeyError, ValueError) as error:
            raise ValueError("Local LLM returned an unsupported content label") from error
        reason = response.content.get("reason_code")
        if not isinstance(reason, str):
            raise ValueError("Local LLM did not return a reason code")
        fine_audit_by_position[position] = BlockClassification(
            block.block_id, label, f"fine:{reason}", response.raw_content
        )
        if label in RETAINED_LABELS:
            retained.update(block.segment_indexes)
        elif label == ContentLabel.UNCERTAIN:
            uncertain_ids.append(block.block_id)
            retained.update(index for index in block.segment_indexes if index in rule_indexes)

    for position in initial_positions:
        classify_fine_position(position)

    def component_overlap(component: list[int]) -> float:
        return sum(
            max(
                0.0,
                min(all_fine_blocks[position].end_seconds, selected_range[1])
                - max(all_fine_blocks[position].start_seconds, selected_range[0]),
            )
            for position in component
        )

    def retained_components(
        positions: set[int],
    ) -> tuple[set[int], list[list[int]], list[int]]:
        raw_positions = [
            position
            for position in sorted(positions)
            if any(index in retained for index in all_fine_blocks[position].segment_indexes)
        ]
        separators = _sustained_noise_separator_positions(
            raw_positions, all_fine_blocks, drafts
        )
        component_positions = [
            position for position in raw_positions if position not in separators
        ]
        found: list[list[int]] = []
        for position in component_positions:
            if found and position == found[-1][-1] + 1:
                found[-1].append(position)
            else:
                found.append([position])
        overlapping = [
            component for component in found if component_overlap(component) > 0.0
        ]
        anchored = max(
            overlapping,
            key=lambda component: (
                component_overlap(component),
                sum(
                    all_fine_blocks[position].end_seconds
                    - all_fine_blocks[position].start_seconds
                    for position in component
                ),
                -component[0],
            ),
            default=[],
        )
        return separators, found, anchored

    separator_positions, components, anchored_component = retained_components(
        inspected_positions
    )
    probe_outcomes: dict[str, dict[str, Any]] = {}
    for direction, step in (("start", -1), ("end", 1)):
        component_edge = (
            anchored_component[0]
            if direction == "start" and anchored_component
            else anchored_component[-1]
            if anchored_component
            else None
        )
        inspection_edge = (
            min(initial_positions)
            if direction == "start" and initial_positions
            else max(initial_positions)
            if initial_positions
            else None
        )
        initially_saturated = (
            component_edge is not None and component_edge == inspection_edge
        )
        probed_block_ids: list[int] = []
        stopping_block_id: int | None = None
        stopping_label: str | None = None
        status = "no_anchored_component" if not anchored_component else "semantic_transition"
        adjacent = component_edge + step if component_edge is not None else None
        if initially_saturated and adjacent is not None:
            while 0 <= adjacent < len(all_fine_blocks):
                inspected_positions.add(adjacent)
                classify_fine_position(adjacent)
                block = all_fine_blocks[adjacent]
                classification = fine_audit_by_position[adjacent]
                probed_block_ids.append(block.block_id)
                if _noise_ratio(block, drafts) >= 0.45:
                    retained.difference_update(block.segment_indexes)
                    stopping_block_id = block.block_id
                    stopping_label = "objective_noise"
                    status = "objective_noise"
                    break
                if classification.label not in RETAINED_LABELS:
                    stopping_block_id = block.block_id
                    stopping_label = classification.label.value
                    status = "semantic_transition"
                    break
                if direction == "start":
                    anchored_component.insert(0, adjacent)
                else:
                    anchored_component.append(adjacent)
                adjacent += step
            else:
                status = "recording_edge"
        probe_outcomes[direction] = {
            "initially_saturated": initially_saturated,
            "probe_performed": bool(probed_block_ids),
            "probed_block_ids": probed_block_ids,
            "stopping_block_id": stopping_block_id,
            "stopping_label": stopping_label,
            "status": status,
        }

    long_edge_expansion = _long_recording_edge_expansion(
        probe_outcomes, all_fine_blocks
    )

    separator_positions, components, anchored_component = retained_components(
        inspected_positions
    )
    anchored_indexes = {
        index
        for position in anchored_component
        for index in all_fine_blocks[position].segment_indexes
    }
    discarded_component_block_ids = [
        [all_fine_blocks[position].block_id for position in component]
        for component in components
        if component != anchored_component
    ]
    retained.intersection_update(anchored_indexes)

    boundary_recovery: dict[str, Any] = {
        "algorithm_version": "fine-continuity-probe-v1",
        "mode": "active",
        "anchored_component_block_ids": [
            all_fine_blocks[position].block_id for position in anchored_component
        ],
        "discarded_component_block_ids": discarded_component_block_ids,
        "objective_separator_block_ids": [
            all_fine_blocks[position].block_id for position in sorted(separator_positions)
        ],
    }
    boundary_probe_required = False
    boundary_recovery.update(probe_outcomes)

    fine_positions = sorted(inspected_positions)
    fine_blocks = [all_fine_blocks[position] for position in fine_positions]
    fine_audit = [fine_audit_by_position[position] for position in fine_positions]

    pre_boundary_refinement_retained = set(retained)
    retained, refinement_reasons, start_refinement = _refine_retained_boundaries(
        drafts,
        fine_blocks,
        retained,
        preserve_joined_start=selected_candidate.get("source") == "joined_coarse_llm",
        default_pre_roll_start=max(0.0, selected_range[0] - 120.0),
    )
    objective_separator_ids = boundary_recovery["objective_separator_block_ids"]
    retained, refinement_safety = _apply_refinement_retention_safety(
        retained,
        pre_boundary_refinement_retained,
        objective_separator_block_ids=objective_separator_ids,
    )
    if refinement_safety["triggered"]:
        refinement_reasons.append(
            "rejected boundary trim that removed most coherent fine-supported content"
        )
    selected_score = selected_candidate.get("score_components")
    selected_score = selected_score if isinstance(selected_score, dict) else {}
    retained, structural_precision = _rule_supported_structural_precision(
        drafts,
        retained,
        rule_window,
        allow_unbaselined_transition=(
            selected_candidate.get("source") == "coarse_likelihood_rescue"
            and (
                bool(selected_score.get("matched_sermon_cues"))
                or float(selected_score.get("sermon_specific_support_ratio", 0.0))
                >= 0.9
            )
        ),
    )
    if any(item.get("edge") for item in structural_precision):
        refinement_reasons.append(
            "applied rule-direction-supported explicit structural boundary precision"
        )
    boundary_recovery["refinement_safety"] = refinement_safety
    boundary_recovery["structural_precision"] = structural_precision
    retained_timed = [
        drafts[index]
        for index in retained
        if drafts[index].start_seconds is not None and drafts[index].end_seconds is not None
    ]
    if retained_timed:
        selected_candidate["start_seconds"] = min(
            draft.start_seconds for draft in retained_timed if draft.start_seconds is not None
        )
        selected_candidate["end_seconds"] = max(
            draft.end_seconds for draft in retained_timed if draft.end_seconds is not None
        )
    refined_start = selected_candidate.get("start_seconds")
    refined_end = selected_candidate.get("end_seconds")
    start_expansion = (
        selected_range[0] - float(refined_start)
        if isinstance(refined_start, (int, float))
        else 0.0
    )
    end_expansion = (
        float(refined_end) - selected_range[1]
        if isinstance(refined_end, (int, float))
        else 0.0
    )
    selected_candidate["boundary_precision"] = {
        "objective_version": "recall_guarded_precision_v1",
        "start_expansion_seconds": round(max(0.0, start_expansion), 3),
        "end_expansion_seconds": round(max(0.0, end_expansion), 3),
        "start_transition": boundary_recovery["start"],
        "end_transition": boundary_recovery["end"],
        "contamination_risk": (
            "high"
            if max(start_expansion, end_expansion) > 300.0
            else "medium"
            if max(start_expansion, end_expansion) > 120.0
            else "low"
        ),
        "recall_guard": "boundaries_not_trimmed_without_independent_transition_evidence",
    }
    selected_candidate["fine_support_block_ids"] = [
        block.block_id
        for block in fine_blocks
        if any(index in retained for index in block.segment_indexes)
    ]
    selected_candidate["refinement_reasons"] = (
        list(selected_candidate["refinement_reasons"])
        + list(refinement_reasons)
    )
    selected_candidate["start_refinement"] = start_refinement
    selected_candidate["boundary_recovery"] = boundary_recovery

    all_timed = {index for block in build_transcript_blocks(drafts) for index in block.segment_indexes}
    agreement = len(retained & rule_indexes) / max(len(retained | rule_indexes), 1)
    warnings: list[str] = []
    if agreement < 0.5:
        warnings.append("adaptive LLM and rule-based sermon windows disagree substantially")
    if uncertain_ids:
        warnings.append("one or more refined blocks require boundary review")
    if boundary_probe_required:
        warnings.append("a saturated fine boundary requires a continuity probe before expansion")
    if long_edge_expansion is not None:
        warnings.append(
            "fine classification expanded more than ten minutes to a recording edge"
        )
    warnings.extend(selected_candidate["refinement_reasons"])
    consistency_warnings = _central_consistency_warnings(
        drafts, retained, fine_blocks, fine_audit, coarse_blocks, phases
    )
    if (
        boundary_recovery["start"].get("status") == "recording_edge"
        and boundary_recovery["end"].get("status") == "recording_edge"
        and not selected_candidate["score_components"].get("matched_sermon_cues")
    ):
        consistency_warnings.append(
            "candidate spans both recording edges without an explicit sermon boundary cue"
        )
    warnings.extend(consistency_warnings)
    post_refinement_rescue_reasons: list[str] = []
    if consistency_warnings:
        post_refinement_rescue_reasons.append("coarse_fine_classification_disagrees")
    selected_end = float(selected_candidate["end_seconds"])
    if any(
        candidate is not selected_candidate
        and float(candidate["start_seconds"]) > selected_end
        and float(candidate["score_components"].get("sermon_specific_support_ratio", 0.0))
        >= float(selected_candidate["score_components"].get("sermon_specific_support_ratio", 0.0))
        for candidate in ranked_candidates
    ):
        post_refinement_rescue_reasons.append("alternative_indicates_uncovered_continuation")
    discovery["post_refinement_rescue_reasons"] = post_refinement_rescue_reasons
    discovery["refinement_strategy"] = {
        "refined_ranks": [int(selected_candidate["rank"])],
        "reranked_candidate_count": len(ranked_candidates),
        "additional_refinement_required": bool(post_refinement_rescue_reasons),
        "reason": (
            "review_required_before_selecting_an_unrefined_alternative"
            if post_refinement_rescue_reasons
            else "top_evidence_candidate_was_coherent"
        ),
    }
    confidence = _adaptive_confidence_tier(
        agreement=agreement,
        retained=bool(retained),
        uncertain=(
            bool(uncertain_ids)
            or boundary_probe_required
            or long_edge_expansion is not None
        ),
        consistency_failed=bool(consistency_warnings),
    )
    confidence_reasons = [
        {
            "code": "rule_llm_agreement",
            "value": round(agreement, 6),
            "strong_support_threshold": 0.8,
            "soft_penalty_threshold": 0.5,
            "effect": "small_positive" if agreement >= 0.8 else "downgrades_high_to_medium" if agreement < 0.5 else "neutral",
        },
        {
            "code": "uncertain_blocks",
            "count": len(uncertain_ids),
            "block_ids": list(uncertain_ids),
            "effect": "caps_medium" if uncertain_ids else "no_cap",
        },
        {
            "code": "boundary_saturation",
            "probe_required": boundary_probe_required,
            "start": boundary_recovery["start"],
            "end": boundary_recovery["end"],
            "effect": "caps_medium" if boundary_probe_required else "no_cap",
        },
        {
            "code": "long_recording_edge_expansion",
            "details": long_edge_expansion,
            "effect": "caps_medium" if long_edge_expansion is not None else "no_cap",
        },
        {
            "code": "retained_content",
            "segment_count": len(retained),
            "effect": "forces_low" if not retained else "present",
        },
        {
            "code": "central_consistency",
            "warnings": list(consistency_warnings),
            "effect": "forces_low" if consistency_warnings else "passed",
        },
        {
            "code": "confidence_decision",
            "tier": confidence,
            "message": "Persisted explanation of the soft-rule-overlap confidence policy.",
        },
    ]
    search = {
        "schema_version": 1,
        "algorithm_version": SEARCH_ALGORITHM_VERSION,
        "candidates": ranked_candidates,
        "selected_rank": int(selected_candidate["rank"]),
        "rule_baseline": {
            "start_seconds": rule_window.start_seconds,
            "end_seconds": rule_window.end_seconds,
            "confidence": rule_window.confidence,
        },
        "model_digest": model_digest,
        "rule_baseline_source": rule_baseline_source,
        "rule_baseline_algorithm_version": rule_baseline_algorithm_version or rule_window.method,
        "manual_override_present": manual_override_present,
        "discovery": discovery,
        "recording_structure": position_prior,
    }
    return HybridSermonResult(
        SEARCH_ALGORITHM_VERSION, client.model, prompt_version, confidence,
        sorted(retained), sorted(all_timed - retained), uncertain_ids, warnings,
        coarse_blocks + fine_blocks, coarse_audit + fine_audit,
        {"hits": cache.hits, "misses": cache.misses} if cache is not None else None,
        search,
        confidence_reasons,
        CONFIDENCE_POLICY_VERSION,
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
