from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
from pathlib import Path
from typing import Any

from pastor_transcript_extractor.local_llm import LocalLlmClient, LocalLlmResponse
from pastor_transcript_extractor.segmentation import SegmentDraft
from pastor_transcript_extractor.sermon_detection import SermonWindowResult


CONFIDENCE_POLICY_VERSION = "soft_rule_overlap_v1"


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
    cache_stats: dict[str, int] | None = None
    search: dict[str, Any] | None = None
    confidence_reasons: list[dict[str, Any]] | None = None
    confidence_policy_version: str | None = None

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
            "block_builder_version": "timestamp-blocks-v1",
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
    return float(_candidate_score_components(candidate, blocks)["total_score"])


def _candidate_score_components(
    candidate: tuple[float, float], blocks: list[TranscriptBlock]
) -> dict[str, Any]:
    start, end = candidate
    text = " ".join(block.text.lower() for block in blocks if _overlaps(block, start, end))
    matched_cues = [cue for cue in _SERMON_SEED_CUES if cue in text]
    duration = end - start
    cue_bonus = len(matched_cues) * 1800.0
    return {
        "duration_seconds": round(duration, 3),
        "matched_sermon_cues": matched_cues,
        "cue_bonus": round(cue_bonus, 3),
        "total_score": round(duration + cue_bonus, 3),
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
    score_components = _candidate_score_components((start, end), blocks)
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
    if (seed is None or preserve_joined_start) and default_pre_roll_start is not None:
        refined = {
            index
            for index in refined
            if drafts[index].end_seconds is None or drafts[index].end_seconds > default_pre_roll_start
        }
    if seed is not None and not preserve_joined_start:
        pre_roll_start = max(0.0, seed - 240.0)
        recovered: set[int] = set()
        stopped_by: str | None = None
        for block in reversed([item for item in fine_blocks if item.start_seconds < seed]):
            if block.end_seconds < pre_roll_start:
                break
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
                draft.start_seconds is not None
                and draft.start_seconds >= pre_roll_start
                and (
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
            }
        else:
            reasons.append("anchored candidate start to an explicit sermon-title or message cue")
            start_refinement = {
                "start_anchor": "explicit_sermon_title",
                "pre_anchor_extension_seconds": 0.0,
                "extension_reason": None,
                "stopped_by": stopped_by or "no_sermon_like_pre_anchor_block",
            }

    retained_blocks = [
        block for block in fine_blocks if any(index in refined for index in block.segment_indexes)
    ]
    retained_start = min((block.start_seconds for block in retained_blocks), default=None)
    for position in range(len(retained_blocks) - 1):
        current = retained_blocks[position]
        following = retained_blocks[position + 1]
        if _noise_ratio(current, drafts) < 0.45 or _noise_ratio(following, drafts) < 0.45:
            continue
        if retained_start is not None and current.start_seconds < retained_start + 600.0:
            continue
        if seed is not None and current.start_seconds < seed + 600.0:
            continue
        cutoff = current.start_seconds
        refined = {
            index
            for index in refined
            if drafts[index].start_seconds is None or drafts[index].start_seconds < cutoff
        }
        reasons.append("trimmed candidate after a sustained music or singing transition")
        break
    return refined, reasons, start_refinement


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
) -> HybridSermonResult:
    coarse_blocks = build_transcript_blocks(drafts, target_seconds=300.0, max_chars=9000)
    if not coarse_blocks:
        raise ValueError("LLM classification requires timestamped transcript segments")
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
    ranked_candidates: list[dict[str, Any]] = []
    for start, end in coarse_candidates:
        score_components = _candidate_score_components((start, end), coarse_blocks)
        supporting_blocks = [
            block.block_id for block in coarse_blocks if _overlaps(block, start, end)
        ]
        ranked_candidates.append(
            {
                "source": "coarse_llm",
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
        if (joined := _joined_candidate(left, right, coarse_blocks, coarse_audit)) is not None
    ]
    ranked_candidates.extend(joined_candidates)
    ranked_candidates.sort(key=lambda candidate: (-float(candidate["score"]), float(candidate["start_seconds"])))
    for rank, candidate in enumerate(ranked_candidates, start=1):
        candidate["rank"] = rank
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
            "algorithm_version": "adaptive_llm_v3",
            "candidates": [],
            "selected_rank": None,
            "rule_baseline": None,
            "model_digest": model_digest,
            "rule_baseline_source": rule_baseline_source,
            "rule_baseline_algorithm_version": rule_baseline_algorithm_version or rule_window.method,
            "manual_override_present": manual_override_present,
        }
        return HybridSermonResult(
            "adaptive_llm_v3", client.model, prompt_version, "low", [],
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
        fine_audit.append(BlockClassification(block.block_id, label, f"fine:{reason}", response.raw_content))
        if label in RETAINED_LABELS:
            retained.update(block.segment_indexes)
        elif label == ContentLabel.UNCERTAIN:
            uncertain_ids.append(block.block_id)
            retained.update(index for index in block.segment_indexes if index in rule_indexes)

    retained, refinement_reasons, start_refinement = _refine_retained_boundaries(
        drafts,
        fine_blocks,
        retained,
        preserve_joined_start=selected_candidate.get("source") == "joined_coarse_llm",
        default_pre_roll_start=max(0.0, selected_range[0] - 120.0),
    )
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
    selected_candidate["fine_support_block_ids"] = [
        block.block_id
        for block in fine_blocks
        if any(index in retained for index in block.segment_indexes)
    ]
    selected_candidate["refinement_reasons"] = list(selected_candidate["refinement_reasons"]) + list(refinement_reasons)
    selected_candidate["start_refinement"] = start_refinement

    all_timed = {index for block in build_transcript_blocks(drafts) for index in block.segment_indexes}
    agreement = len(retained & rule_indexes) / max(len(retained | rule_indexes), 1)
    warnings: list[str] = []
    if agreement < 0.5:
        warnings.append("adaptive LLM and rule-based sermon windows disagree substantially")
    if uncertain_ids:
        warnings.append("one or more refined blocks require boundary review")
    warnings.extend(selected_candidate["refinement_reasons"])
    consistency_warnings = _central_consistency_warnings(
        drafts, retained, fine_blocks, fine_audit, coarse_blocks, phases
    )
    warnings.extend(consistency_warnings)
    confidence = _adaptive_confidence_tier(
        agreement=agreement,
        retained=bool(retained),
        uncertain=bool(uncertain_ids),
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
        "algorithm_version": "adaptive_llm_v3",
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
    }
    return HybridSermonResult(
        "adaptive_llm_v3", client.model, prompt_version, confidence,
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
