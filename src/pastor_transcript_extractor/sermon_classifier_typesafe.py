"""Fast, cached TypeSafe/Jev-first sermon localization."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json
import math
from pathlib import Path
import re
from threading import Lock
from typing import Any, Mapping, Protocol

from pastor_transcript_extractor.caption_normalization import (
    NORMALIZER_VERSION,
    normalize_caption_fragments,
)
from pastor_transcript_extractor.segmentation import SegmentDraft
from pastor_transcript_extractor.sermon_classification import (
    BlockClassification,
    ContentLabel,
    HybridSermonResult,
    TranscriptBlock,
    build_transcript_blocks,
)
from pastor_transcript_extractor.sermon_detection import SermonWindowResult


SEARCH_ALGORITHM_VERSION = "typesafe_first_v9"
QUESTION_SET_VERSION = "sermon-classifier-typesafe-questions-v1"
BLOCK_BUILDER_VERSION = "typesafe-deduplicated-coarse-300s-fine-60s-v2"
COARSE_DISCOVERY_VERSION = "typesafe-batched-role-map-v1"
FINE_COMPONENT_VERSION = "typesafe-local-boundary-map-v9-temporal-neighborhood"
BOUNDARY_SELECTION_VERSION = "typesafe-segment-boundary-selection-v4-compact"
BOUNDARY_VALIDATION_VERSION = "typesafe-segment-boundary-validation-v4-general"
BOUNDARY_AUTOMATIC_THRESHOLD = 0.72
BOUNDARY_CANDIDATE_MIN_SPACING_SECONDS = 0.75
BOUNDARY_NEIGHBORHOOD_SECONDS = 180.0
BOUNDARY_NEIGHBORHOOD_MAX_BLOCKS = 5
CAPTION_DEDUP_WINDOW_SECONDS = 20.0
CAPTION_DEDUP_MAX_GAP_SECONDS = 2.0
# Coarse blocks can each approach 9,000 characters. Six keeps the worst-case
# shared state near the size exercised by TypeSafe's large-document cookbook.
BATCH_SIZE = 6

ROLE_CHOICES = (
    "principal_sermon",
    "sermon_integrated_prayer_or_scripture",
    "worship_music_or_service_prayer",
    "administration_or_transition",
    "childrens_or_religious_education",
    "unclear",
)
SERMON_ROLES = frozenset(
    {"principal_sermon", "sermon_integrated_prayer_or_scripture"}
)


def role_question() -> dict[str, Any]:
    return {
        "instructions": {
            "task": "Classify the dominant role of the referenced transcript block.",
            "scope": (
                "Judge whether the principal worship-service sermon is underway in "
                "this block. The recording title is supporting context only."
            ),
            "boundary": (
                "A children's feature, lesson study, Bible class, announcements, "
                "music, or a standalone service prayer is not the principal sermon. "
                "Brief prayer, Scripture reading, illustration, or audience response "
                "inside one sustained preacher's message remains part of the sermon."
            ),
        },
        "criteria": {
            "principal_sermon": (
                "One principal preacher is sustaining biblical exposition, a theological "
                "theme, pastoral application, appeal, or sermon conclusion."
            ),
            "sermon_integrated_prayer_or_scripture": (
                "Prayer or Scripture is integrated into and continues the same principal "
                "sermon, rather than being a separate service element."
            ),
            "worship_music_or_service_prayer": (
                "The block is dominated by music, lyrics, congregational worship, or a "
                "standalone service prayer outside the principal sermon."
            ),
            "administration_or_transition": (
                "The block is announcements, welcome, offering, logistics, a speaker "
                "introduction, handoff, or another transition without sustained preaching."
            ),
            "childrens_or_religious_education": (
                "The block is a children's story or feature, object lesson, Sabbath school, "
                "Bible class, curriculum lesson, or facilitated group study rather than "
                "the principal worship-service sermon."
            ),
            "unclear": "The block lacks enough coherent evidence for another role.",
        },
    }


@dataclass(frozen=True, slots=True)
class TypeSafeBlockAnswer:
    choice: str
    probabilities: Mapping[str, float]
    confidence: float | None
    resolved_model_id: str

    @property
    def sermon_probability(self) -> float:
        return sum(float(self.probabilities.get(role, 0.0)) for role in SERMON_ROLES)


@dataclass(frozen=True, slots=True)
class TypeSafeBoundaryCandidate:
    candidate_id: str
    boundary_seconds: float
    before_text: str
    after_text: str
    retained_segment_indexes: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class TypeSafeBoundaryAnswer:
    transition_probability: float
    resolved_model_id: str


@dataclass(frozen=True, slots=True)
class TypeSafeBoundarySelection:
    choice: str
    probabilities: Mapping[str, float]
    confidence: float | None
    resolved_model_id: str


class TypeSafeBlockClient(Protocol):
    def assess_blocks(
        self,
        title: str,
        blocks: list[TranscriptBlock],
    ) -> Mapping[int, TypeSafeBlockAnswer]: ...

    def select_boundary_candidate(
        self,
        title: str,
        edge: str,
        candidates: list[TypeSafeBoundaryCandidate],
    ) -> TypeSafeBoundarySelection: ...

    def validate_boundary_candidate(
        self,
        title: str,
        edge: str,
        candidate: TypeSafeBoundaryCandidate,
    ) -> TypeSafeBoundaryAnswer: ...


def _hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


class TypeSafeBlockCache:
    """Item-level cache: batching changes never invalidate unchanged judgments."""

    def __init__(self, root: Path, *, model: str) -> None:
        self.root = root / "typesafe-first" / re.sub(r"[^A-Za-z0-9_.-]+", "_", model)
        self.model = model
        self.hits = 0
        self.misses = 0

    def _identity(self, title: str, block: TranscriptBlock) -> dict[str, Any]:
        return {
            "model": self.model,
            "question_set_version": QUESTION_SET_VERSION,
            "question": role_question(),
            "recording_title": title,
            "block": {
                "start_seconds": block.start_seconds,
                "end_seconds": block.end_seconds,
                "text": block.text,
            },
        }

    def _path(self, identity: Mapping[str, Any]) -> Path:
        return self.root / f"{_hash(identity)}.json"

    def assess(
        self,
        client: TypeSafeBlockClient,
        title: str,
        blocks: list[TranscriptBlock],
    ) -> dict[int, TypeSafeBlockAnswer]:
        answers: dict[int, TypeSafeBlockAnswer] = {}
        missing: list[tuple[TranscriptBlock, dict[str, Any], Path]] = []
        for block in blocks:
            identity = self._identity(title, block)
            path = self._path(identity)
            if path.exists():
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    answers[block.block_id] = TypeSafeBlockAnswer(**payload["answer"])
                    self.hits += 1
                    continue
                except (OSError, ValueError, KeyError, TypeError):
                    pass
            missing.append((block, identity, path))

        for offset in range(0, len(missing), BATCH_SIZE):
            batch = missing[offset : offset + BATCH_SIZE]
            assessed = client.assess_blocks(title, [item[0] for item in batch])
            for block, identity, path in batch:
                answer = assessed.get(block.block_id)
                if answer is None:
                    raise ValueError(
                        f"TypeSafe omitted block judgment {block.block_id}"
                    )
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    json.dumps(
                        {"identity": identity, "answer": asdict(answer)},
                        indent=2,
                        sort_keys=True,
                    ),
                    encoding="utf-8",
                )
                answers[block.block_id] = answer
                self.misses += 1
        return answers

    def _boundary_selection_identity(
        self,
        title: str,
        edge: str,
        candidates: list[TypeSafeBoundaryCandidate],
    ) -> dict[str, Any]:
        return {
            "model": self.model,
            "question_version": BOUNDARY_SELECTION_VERSION,
            "recording_title": title,
            "edge": edge,
            "candidates": [
                {
                    "candidate_id": candidate.candidate_id,
                    "boundary_seconds": candidate.boundary_seconds,
                    "before_text": candidate.before_text,
                    "after_text": candidate.after_text,
                }
                for candidate in candidates
            ],
        }

    def select_boundary(
        self,
        client: TypeSafeBlockClient,
        title: str,
        edge: str,
        candidates: list[TypeSafeBoundaryCandidate],
    ) -> TypeSafeBoundarySelection:
        identity = self._boundary_selection_identity(title, edge, candidates)
        path = self.root / "boundaries" / "selections" / f"{_hash(identity)}.json"
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                self.hits += 1
                return TypeSafeBoundarySelection(**payload["answer"])
            except (OSError, ValueError, KeyError, TypeError):
                pass
        answer = client.select_boundary_candidate(title, edge, candidates)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"identity": identity, "answer": asdict(answer)},
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        self.misses += 1
        return answer

    def validate_boundary(
        self,
        client: TypeSafeBlockClient,
        title: str,
        edge: str,
        candidate: TypeSafeBoundaryCandidate,
    ) -> TypeSafeBoundaryAnswer:
        identity = {
            "model": self.model,
            "question_version": BOUNDARY_VALIDATION_VERSION,
            "recording_title": title,
            "edge": edge,
            "candidate": {
                "boundary_seconds": candidate.boundary_seconds,
                "before_text": candidate.before_text,
                "after_text": candidate.after_text,
            },
        }
        path = self.root / "boundaries" / "validations" / f"{_hash(identity)}.json"
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                self.hits += 1
                return TypeSafeBoundaryAnswer(**payload["answer"])
            except (OSError, ValueError, KeyError, TypeError):
                pass
        answer = client.validate_boundary_candidate(title, edge, candidate)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"identity": identity, "answer": asdict(answer)},
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        self.misses += 1
        return answer


def _context_text(drafts: list[SegmentDraft], indexes: list[int], *, tail: bool) -> str:
    text = "\n".join(drafts[index].text for index in indexes)
    return text[-700:] if tail else text[:700]


def _deduplicated_drafts(
    drafts: list[SegmentDraft],
) -> tuple[list[SegmentDraft], tuple[tuple[int, ...], ...], dict[str, Any]]:
    timed_indexes = [
        index
        for index, draft in enumerate(drafts)
        if draft.start_seconds is not None
        and draft.end_seconds is not None
        and draft.end_seconds > draft.start_seconds
    ]
    semantic_drafts: list[SegmentDraft] = []
    source_groups: list[tuple[int, ...]] = []
    raw_token_count = 0
    normalized_token_count = 0

    def flush(chunk: list[int]) -> None:
        nonlocal raw_token_count, normalized_token_count
        if not chunk:
            return
        normalized = normalize_caption_fragments(
            (index, drafts[index].text) for index in chunk
        )
        raw_token_count += int(normalized.diagnostics["raw_token_count"])
        normalized_token_count += int(
            normalized.diagnostics["normalized_token_count"]
        )
        for unit in normalized.units:
            source_indexes = unit.source_segment_indexes
            if not source_indexes:
                continue
            sources = [drafts[index] for index in source_indexes]
            starts = [
                item.start_seconds for item in sources if item.start_seconds is not None
            ]
            ends = [
                item.end_seconds for item in sources if item.end_seconds is not None
            ]
            if not starts or not ends:
                continue
            source_groups.append(source_indexes)
            semantic_drafts.append(
                SegmentDraft(
                    start_seconds=min(starts),
                    end_seconds=max(ends),
                    text=unit.text,
                    speaker_hint=next(
                        (item.speaker_hint for item in sources if item.speaker_hint),
                        None,
                    ),
                    label=sources[0].label,
                    confidence=sources[0].confidence,
                )
            )

    chunk: list[int] = []
    for index in timed_indexes:
        draft = drafts[index]
        if chunk:
            first = drafts[chunk[0]]
            previous = drafts[chunk[-1]]
            assert first.start_seconds is not None
            assert previous.end_seconds is not None
            assert draft.start_seconds is not None
            assert draft.end_seconds is not None
            if (
                draft.end_seconds - first.start_seconds
                > CAPTION_DEDUP_WINDOW_SECONDS
                or draft.start_seconds - previous.end_seconds
                > CAPTION_DEDUP_MAX_GAP_SECONDS
            ):
                flush(chunk)
                chunk = []
        chunk.append(index)
    flush(chunk)

    diagnostics = {
        "normalizer_version": NORMALIZER_VERSION,
        "window_seconds": CAPTION_DEDUP_WINDOW_SECONDS,
        "source_segment_count": len(timed_indexes),
        "semantic_segment_count": len(semantic_drafts),
        "raw_token_count": raw_token_count,
        "normalized_token_count": normalized_token_count,
        "deduplication_ratio": round(
            1.0 - (normalized_token_count / raw_token_count), 6
        )
        if raw_token_count
        else 0.0,
    }
    return semantic_drafts, tuple(source_groups), diagnostics


def _source_indexes(
    semantic_indexes: list[int] | set[int],
    source_groups: tuple[tuple[int, ...], ...],
) -> list[int]:
    return sorted(
        {
            source_index
            for semantic_index in semantic_indexes
            for source_index in source_groups[semantic_index]
        }
    )


def _source_blocks(
    blocks: list[TranscriptBlock],
    source_groups: tuple[tuple[int, ...], ...],
) -> list[TranscriptBlock]:
    return [
        replace(
            block,
            segment_indexes=_source_indexes(block.segment_indexes, source_groups),
        )
        for block in blocks
    ]


def _boundary_candidates(
    drafts: list[SegmentDraft],
    *,
    edge: str,
    selected_indexes: list[int],
    neighborhood_blocks: list[TranscriptBlock],
) -> list[TypeSafeBoundaryCandidate]:
    neighborhood = [
        index for block in neighborhood_blocks for index in block.segment_indexes
    ]
    if len(neighborhood) < 2:
        return []
    neighborhood_set = set(neighborhood)
    selected_outside_neighborhood = set(selected_indexes) - neighborhood_set
    candidates: list[TypeSafeBoundaryCandidate] = []
    if edge == "end":
        for split in range(1, len(neighborhood)):
            before_indexes = neighborhood[:split]
            after_indexes = neighborhood[split:]
            boundary = drafts[before_indexes[-1]].end_seconds
            if boundary is None:
                continue
            candidates.append(
                TypeSafeBoundaryCandidate(
                    candidate_id=f"end:{boundary:.3f}",
                    boundary_seconds=boundary,
                    before_text=_context_text(drafts, before_indexes, tail=True),
                    after_text=_context_text(drafts, after_indexes, tail=False),
                    retained_segment_indexes=tuple(
                        sorted(selected_outside_neighborhood | set(before_indexes))
                    ),
                )
            )
    else:
        for split in range(1, len(neighborhood)):
            before_indexes = neighborhood[:split]
            after_indexes = neighborhood[split:]
            boundary = drafts[after_indexes[0]].start_seconds
            if boundary is None:
                continue
            candidates.append(
                TypeSafeBoundaryCandidate(
                    candidate_id=f"start:{boundary:.3f}",
                    boundary_seconds=boundary,
                    before_text=_context_text(drafts, before_indexes, tail=True),
                    after_text=_context_text(drafts, after_indexes, tail=False),
                    retained_segment_indexes=tuple(
                        sorted(selected_outside_neighborhood | set(after_indexes))
                    ),
                )
            )
    compact: list[TypeSafeBoundaryCandidate] = []
    for candidate in candidates:
        if (
            compact
            and candidate.boundary_seconds - compact[-1].boundary_seconds
            < BOUNDARY_CANDIDATE_MIN_SPACING_SECONDS
        ):
            continue
        compact.append(candidate)
    return compact


def _edge_neighborhood(
    blocks: list[TranscriptBlock], position: int, *, edge: str
) -> list[TranscriptBlock]:
    """Return contiguous edge context within a bounded temporal neighborhood."""
    result = [blocks[position]]
    step = -1 if edge == "start" else 1
    cursor = position
    anchor = (
        blocks[position].start_seconds
        if edge == "start"
        else blocks[position].end_seconds
    )
    while len(result) < BOUNDARY_NEIGHBORHOOD_MAX_BLOCKS:
        next_position = cursor + step
        if next_position < 0 or next_position >= len(blocks):
            break
        inner = blocks[cursor]
        outer = blocks[next_position]
        gap = (
            inner.start_seconds - outer.end_seconds
            if edge == "start"
            else outer.start_seconds - inner.end_seconds
        )
        if gap > 1.0:
            break
        distance = (
            anchor - outer.end_seconds
            if edge == "start"
            else outer.start_seconds - anchor
        )
        if distance > BOUNDARY_NEIGHBORHOOD_SECONDS:
            break
        if edge == "start":
            result.insert(0, outer)
        else:
            result.append(outer)
        cursor = next_position
    return result


def _candidate_components(
    blocks: list[TranscriptBlock],
    answers: Mapping[int, TypeSafeBlockAnswer],
    *,
    threshold: float,
) -> list[list[TranscriptBlock]]:
    components: list[list[TranscriptBlock]] = []
    current: list[TranscriptBlock] = []
    supported = [
        answers[block.block_id].sermon_probability >= threshold for block in blocks
    ]
    for position in range(1, len(blocks) - 1):
        if (
            supported[position]
            or not supported[position - 1]
            or not supported[position + 1]
        ):
            continue
        previous = blocks[position - 1]
        block = blocks[position]
        following = blocks[position + 1]
        if (
            block.start_seconds - previous.end_seconds <= 1.0
            and following.start_seconds - block.end_seconds <= 1.0
            and (
                answers[block.block_id].sermon_probability >= 0.4
                or answers[block.block_id].choice == "unclear"
            )
        ):
            supported[position] = True

    for position, block in enumerate(blocks):
        if current and block.start_seconds - current[-1].end_seconds > 1.0:
            components.append(current)
            current = []
        if supported[position]:
            current.append(block)
            continue
        if current:
            components.append(current)
            current = []
    if current:
        components.append(current)
    return components


def _component_score(
    component: list[TranscriptBlock],
    answers: Mapping[int, TypeSafeBlockAnswer],
) -> float:
    duration = component[-1].end_seconds - component[0].start_seconds
    mean_probability = sum(
        answers[block.block_id].sermon_probability for block in component
    ) / len(component)
    return mean_probability * math.log2(max(duration, 1.0) + 1.0)


def _mapped_label(answer: TypeSafeBlockAnswer) -> ContentLabel:
    if answer.choice == "principal_sermon":
        return ContentLabel.SERMON
    if answer.choice == "sermon_integrated_prayer_or_scripture":
        return ContentLabel.SERMON_SCRIPTURE
    if answer.choice == "worship_music_or_service_prayer":
        return ContentLabel.MUSIC
    if answer.choice == "administration_or_transition":
        return ContentLabel.SPEAKER_INTRODUCTION
    if answer.choice == "childrens_or_religious_education":
        return ContentLabel.ANNOUNCEMENTS
    return ContentLabel.UNCERTAIN


class TypeSafeFirstPassSermonClassifier:
    """Map the recording first, then refine only plausible sermon regions."""

    method = SEARCH_ALGORITHM_VERSION
    prompt_version = QUESTION_SET_VERSION
    block_builder_version = BLOCK_BUILDER_VERSION
    coarse_discovery_version = COARSE_DISCOVERY_VERSION
    fine_component_version = FINE_COMPONENT_VERSION

    def __init__(
        self,
        *,
        model: str,
        client: TypeSafeBlockClient,
        lock: Lock | None = None,
    ) -> None:
        self.model = model
        self.client = client
        self._lock = lock or Lock()

    def classify_sermon(
        self,
        drafts: list[SegmentDraft],
        rule_window: SermonWindowResult,
        *,
        title: str,
        cache_dir: Path,
        progress: Any | None = None,
    ) -> HybridSermonResult:
        del rule_window  # independent baseline; arbitration compares it downstream.
        drafts, source_groups, caption_normalization = _deduplicated_drafts(drafts)
        coarse_blocks = build_transcript_blocks(
            drafts, target_seconds=300.0, max_chars=9000
        )
        if not coarse_blocks:
            raise ValueError("TypeSafe classification requires timestamped segments")
        cache = TypeSafeBlockCache(cache_dir, model=self.model)
        if progress is not None:
            progress("typesafe-coarse", 0, len(coarse_blocks))
        with self._lock:
            coarse_answers = cache.assess(self.client, title, coarse_blocks)
        if progress is not None:
            progress("typesafe-coarse", len(coarse_blocks), len(coarse_blocks))
        coarse_components = _candidate_components(
            coarse_blocks, coarse_answers, threshold=0.62
        )
        if not coarse_components:
            return self._empty_result(
                coarse_blocks,
                coarse_answers,
                cache,
                source_groups,
                caption_normalization,
            )

        plausible_ranges = [
            (
                max(0.0, component[0].start_seconds - 300.0),
                component[-1].end_seconds + 300.0,
            )
            for component in coarse_components
        ]
        raw_fine_blocks = build_transcript_blocks(
            drafts, target_seconds=60.0, max_chars=3200
        )
        fine_blocks = [
            replace(block, block_id=len(coarse_blocks) + block.block_id)
            for block in raw_fine_blocks
            if any(
                block.end_seconds > start and block.start_seconds < end
                for start, end in plausible_ranges
            )
        ]
        if progress is not None:
            progress("typesafe-boundary", 0, len(fine_blocks))
        with self._lock:
            fine_answers = cache.assess(self.client, title, fine_blocks)
        if progress is not None:
            progress("typesafe-boundary", len(fine_blocks), len(fine_blocks))

        fine_components = _candidate_components(
            fine_blocks, fine_answers, threshold=0.66
        )
        if not fine_components:
            return self._empty_result(
                coarse_blocks + fine_blocks,
                {**coarse_answers, **fine_answers},
                cache,
                source_groups,
                caption_normalization,
            )
        ranked_components = sorted(
            fine_components,
            key=lambda component: _component_score(component, fine_answers),
            reverse=True,
        )
        selected = ranked_components[0]
        selected_component_score = _component_score(selected, fine_answers)
        competing_component_ratio = (
            _component_score(ranked_components[1], fine_answers)
            / max(selected_component_score, 1e-9)
            if len(ranked_components) > 1
            else 0.0
        )
        selected_ids = {block.block_id for block in selected}
        selected_indexes = sorted(
            {index for block in selected for index in block.segment_indexes}
        )
        all_timed = {
            index
            for block in raw_fine_blocks
            for index in block.segment_indexes
        }
        first = selected[0]
        last = selected[-1]
        fine_positions = {block.block_id: position for position, block in enumerate(fine_blocks)}
        start_position = fine_positions[first.block_id]
        end_position = fine_positions[last.block_id]
        previous_probability = (
            fine_answers[fine_blocks[start_position - 1].block_id].sermon_probability
            if start_position > 0
            and first.start_seconds - fine_blocks[start_position - 1].end_seconds <= 1.0
            else 0.0
        )
        following_probability = (
            fine_answers[fine_blocks[end_position + 1].block_id].sermon_probability
            if end_position + 1 < len(fine_blocks)
            and fine_blocks[end_position + 1].start_seconds - last.end_seconds <= 1.0
            else 0.0
        )
        first_probability = fine_answers[first.block_id].sermon_probability
        last_probability = fine_answers[last.block_id].sermon_probability
        recording_start = raw_fine_blocks[0].start_seconds
        recording_end = raw_fine_blocks[-1].end_seconds
        start_strength = min(first_probability, 1.0 - previous_probability)
        end_strength = min(last_probability, 1.0 - following_probability)
        refined_edges: dict[str, dict[str, Any]] = {}
        boundary_selector = getattr(self.client, "select_boundary_candidate", None)
        boundary_validator = getattr(self.client, "validate_boundary_candidate", None)
        boundary_work: list[tuple[str, list[TypeSafeBoundaryCandidate]]] = []
        if callable(boundary_selector) and callable(boundary_validator):
            if (
                start_strength < BOUNDARY_AUTOMATIC_THRESHOLD
                and start_position > 0
                and first.start_seconds
                - fine_blocks[start_position - 1].end_seconds
                <= 1.0
            ):
                boundary_work.append(
                    (
                        "start",
                        _boundary_candidates(
                            drafts,
                            edge="start",
                            selected_indexes=selected_indexes,
                            neighborhood_blocks=_edge_neighborhood(
                                fine_blocks, start_position, edge="start"
                            ),
                        ),
                    )
                )
            if (
                end_strength < BOUNDARY_AUTOMATIC_THRESHOLD
                and end_position + 1 < len(fine_blocks)
                and fine_blocks[end_position + 1].start_seconds
                - last.end_seconds
                <= 1.0
            ):
                boundary_work.append(
                    (
                        "end",
                        _boundary_candidates(
                            drafts,
                            edge="end",
                            selected_indexes=selected_indexes,
                            neighborhood_blocks=_edge_neighborhood(
                                fine_blocks, end_position, edge="end"
                            ),
                        ),
                    )
                )
        boundary_candidate_count = sum(len(items) for _, items in boundary_work)
        if progress is not None and boundary_candidate_count:
            progress("typesafe-segment-boundary", 0, boundary_candidate_count)
        for edge, candidates in boundary_work:
            if not candidates:
                continue
            try:
                with self._lock:
                    selection = cache.select_boundary(
                        self.client, title, edge, candidates
                    )
                    selected_boundary = next(
                        (
                            candidate
                            for candidate in candidates
                            if candidate.candidate_id == selection.choice
                        ),
                        None,
                    )
                    validation = (
                        cache.validate_boundary(
                            self.client, title, edge, selected_boundary
                        )
                        if selected_boundary is not None
                        else None
                    )
            except Exception as error:
                refined_edges[edge] = {
                    "algorithm_version": BOUNDARY_SELECTION_VERSION,
                    "candidate_count": len(candidates),
                    "accepted": False,
                    "error": f"{type(error).__name__}: {error}",
                }
                continue
            selection_probability = float(
                selection.probabilities.get(selection.choice, 0.0)
            )
            probability = (
                validation.transition_probability if validation is not None else 0.0
            )
            refinement = {
                "algorithm_version": BOUNDARY_SELECTION_VERSION,
                "validation_version": BOUNDARY_VALIDATION_VERSION,
                "candidate_count": len(candidates),
                "selected_candidate_id": selection.choice,
                "selection_probability": round(selection_probability, 6),
                "selection_confidence": selection.confidence,
                "transition_probability": round(probability, 6),
                "automatic_threshold": BOUNDARY_AUTOMATIC_THRESHOLD,
                "accepted": (
                    selected_boundary is not None
                    and probability >= BOUNDARY_AUTOMATIC_THRESHOLD
                ),
            }
            if selected_boundary is not None:
                refinement["boundary_seconds"] = selected_boundary.boundary_seconds
            refined_edges[edge] = refinement
            if not refinement["accepted"]:
                continue
            assert selected_boundary is not None
            selected_indexes = list(selected_boundary.retained_segment_indexes)
            if edge == "start":
                start_strength = probability
            else:
                end_strength = probability
        if progress is not None and boundary_candidate_count:
            progress(
                "typesafe-segment-boundary",
                boundary_candidate_count,
                boundary_candidate_count,
            )
        mean_probability = sum(
            fine_answers[block.block_id].sermon_probability for block in selected
        ) / len(selected)
        selected_start = (
            float(refined_edges["start"]["boundary_seconds"])
            if refined_edges.get("start", {}).get("accepted")
            else first.start_seconds
        )
        selected_end = (
            float(refined_edges["end"]["boundary_seconds"])
            if refined_edges.get("end", {}).get("accepted")
            else last.end_seconds
        )
        duration = selected_end - selected_start
        confidence = (
            "high"
            if mean_probability >= 0.82
            and start_strength >= 0.72
            and end_strength >= 0.72
            and duration >= 600.0
            else "medium"
            if mean_probability >= 0.72 and duration >= 300.0
            else "low"
        )
        if competing_component_ratio >= 0.75:
            confidence = "low"
        elif competing_component_ratio >= 0.45 and confidence == "high":
            confidence = "medium"
        boundary_recovery = {
            "algorithm_version": FINE_COMPONENT_VERSION,
            "mode": "typesafe_first",
            "anchored_component_block_ids": sorted(selected_ids),
            "discarded_component_block_ids": [
                [block.block_id for block in component]
                for component in fine_components
                if component is not selected
            ],
            "objective_separator_block_ids": [],
            "objective_segment_precision": [],
            "start": {
                "status": (
                    "semantic_transition"
                    if start_position > 0
                    and first.start_seconds
                    - fine_blocks[start_position - 1].end_seconds
                    <= 1.0
                    else "search_edge"
                    if first.start_seconds > recording_start + 1.0
                    else "recording_edge"
                ),
                "boundary_seconds": selected_start,
                "inside_probability": round(first_probability, 6),
                "outside_probability": round(previous_probability, 6),
                "transition_strength": round(start_strength, 6),
                **(
                    {"segment_refinement": refined_edges["start"]}
                    if "start" in refined_edges
                    else {}
                ),
            },
            "end": {
                "status": (
                    "semantic_transition"
                    if end_position + 1 < len(fine_blocks)
                    and fine_blocks[end_position + 1].start_seconds
                    - last.end_seconds
                    <= 1.0
                    else "search_edge"
                    if last.end_seconds < recording_end - 1.0
                    else "recording_edge"
                ),
                "boundary_seconds": selected_end,
                "inside_probability": round(last_probability, 6),
                "outside_probability": round(following_probability, 6),
                "transition_strength": round(end_strength, 6),
                **(
                    {"segment_refinement": refined_edges["end"]}
                    if "end" in refined_edges
                    else {}
                ),
            },
        }
        source_selected_indexes = _source_indexes(selected_indexes, source_groups)
        source_all_timed = set(_source_indexes(all_timed, source_groups))
        candidate = {
            "rank": 1,
            "source": "typesafe_first",
            "start_seconds": selected_start,
            "end_seconds": selected_end,
            "included_segment_indexes": source_selected_indexes,
            "coarse_support_block_ids": [
                block.block_id
                for block in coarse_blocks
                if block.end_seconds > first.start_seconds
                and block.start_seconds < last.end_seconds
            ],
            "fine_support_block_ids": sorted(selected_ids),
            "score": round(selected_component_score, 6),
            "score_components": {
                "mean_sermon_probability": round(mean_probability, 6),
                "start_transition_strength": round(start_strength, 6),
                "end_transition_strength": round(end_strength, 6),
                "competing_component_ratio": round(competing_component_ratio, 6),
                "sermon_specific_support_ratio": round(mean_probability, 6),
                "matched_sermon_cues": [],
            },
            "boundary_recovery": boundary_recovery,
            "boundary_precision": {
                "objective_version": FINE_COMPONENT_VERSION,
                "contamination_risk": "low" if confidence == "high" else "medium",
                "recall_guard": "typesafe_transition_probabilities",
            },
            "refinement_reasons": ["typesafe_local_boundary_map"],
        }
        answers = {**coarse_answers, **fine_answers}
        blocks = coarse_blocks + fine_blocks
        source_mapped_blocks = _source_blocks(blocks, source_groups)
        uncertain_ids = [
            block.block_id
            for block in fine_blocks
            if 0.4 <= answers[block.block_id].sermon_probability < 0.66
            or answers[block.block_id].choice == "unclear"
        ]
        warnings = []
        if confidence != "high":
            warnings.append("TypeSafe boundary map did not meet the automatic threshold")
        if len(fine_components) > 1:
            warnings.append("multiple TypeSafe sermon-like components were found")
        if any("error" in refinement for refinement in refined_edges.values()):
            warnings.append(
                "TypeSafe segment boundary refinement failed; retained block boundary"
            )
        return HybridSermonResult(
            method=self.method,
            model=self.model,
            prompt_version=self.prompt_version,
            confidence_tier=confidence,
            retained_segment_indexes=source_selected_indexes,
            excluded_segment_indexes=sorted(
                source_all_timed - set(source_selected_indexes)
            ),
            uncertain_block_ids=uncertain_ids,
            warnings=warnings,
            blocks=source_mapped_blocks,
            classifications=self._classifications(source_mapped_blocks, answers),
            cache_stats={"hits": cache.hits, "misses": cache.misses},
            search={
                "schema_version": 1,
                "algorithm_version": self.method,
                "candidates": [candidate],
                "selected_rank": 1,
                "model_digest": self.model,
                "rule_baseline_source": "recomputed_rules",
                "rule_baseline_algorithm_version": "rule_based_v1",
                "manual_override_present": False,
                "discovery": {
                    "selected_mode": "typesafe_first",
                    "coarse_component_count": len(coarse_components),
                    "fine_component_count": len(fine_components),
                    "competing_component_ratio": round(
                        competing_component_ratio, 6
                    ),
                    "cache_identity": "per_block_question_state",
                    "segment_boundary_refinement": bool(boundary_candidate_count),
                    "caption_normalization": caption_normalization,
                },
            },
            confidence_reasons=[
                {
                    "code": "typesafe_probability_map",
                    "mean_sermon_probability": round(mean_probability, 6),
                    "start_transition_strength": round(start_strength, 6),
                    "end_transition_strength": round(end_strength, 6),
                    "competing_component_ratio": round(
                        competing_component_ratio, 6
                    ),
                    "tier": confidence,
                }
            ],
            confidence_policy_version="typesafe-boundary-confidence-v1",
            block_builder_version=self.block_builder_version,
            coarse_discovery_version=self.coarse_discovery_version,
            fine_component_version=self.fine_component_version,
        )

    def _empty_result(
        self,
        blocks: list[TranscriptBlock],
        answers: Mapping[int, TypeSafeBlockAnswer],
        cache: TypeSafeBlockCache,
        source_groups: tuple[tuple[int, ...], ...],
        caption_normalization: Mapping[str, Any],
    ) -> HybridSermonResult:
        all_timed = _source_indexes(
            {index for block in blocks for index in block.segment_indexes},
            source_groups,
        )
        source_mapped_blocks = _source_blocks(blocks, source_groups)
        return HybridSermonResult(
            self.method,
            self.model,
            self.prompt_version,
            "low",
            [],
            sorted(all_timed),
            [],
            ["TypeSafe found no sufficiently supported principal sermon component"],
            source_mapped_blocks,
            self._classifications(source_mapped_blocks, answers),
            {"hits": cache.hits, "misses": cache.misses},
            {
                "schema_version": 1,
                "algorithm_version": self.method,
                "candidates": [],
                "selected_rank": None,
                "discovery": {
                    "selected_mode": "typesafe_first_no_candidate",
                    "caption_normalization": dict(caption_normalization),
                },
            },
            [{"code": "typesafe_probability_map", "tier": "low"}],
            "typesafe-boundary-confidence-v1",
            self.block_builder_version,
            self.coarse_discovery_version,
            self.fine_component_version,
        )

    @staticmethod
    def _classifications(
        blocks: list[TranscriptBlock],
        answers: Mapping[int, TypeSafeBlockAnswer],
    ) -> list[BlockClassification]:
        return [
            BlockClassification(
                block.block_id,
                _mapped_label(answers[block.block_id]),
                (
                    f"typesafe:{answers[block.block_id].choice}:"
                    f"{answers[block.block_id].sermon_probability:.6f}"
                ),
                json.dumps(asdict(answers[block.block_id]), sort_keys=True),
            )
            for block in blocks
            if block.block_id in answers
        ]
