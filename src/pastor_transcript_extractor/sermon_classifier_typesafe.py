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

from pastor_transcript_extractor.segmentation import SegmentDraft
from pastor_transcript_extractor.sermon_classification import (
    BlockClassification,
    ContentLabel,
    HybridSermonResult,
    TranscriptBlock,
    build_transcript_blocks,
)
from pastor_transcript_extractor.sermon_detection import SermonWindowResult


SEARCH_ALGORITHM_VERSION = "typesafe_first_v1"
QUESTION_SET_VERSION = "sermon-classifier-typesafe-questions-v1"
BLOCK_BUILDER_VERSION = "typesafe-coarse-300s-fine-60s-v1"
COARSE_DISCOVERY_VERSION = "typesafe-batched-role-map-v1"
FINE_COMPONENT_VERSION = "typesafe-local-boundary-map-v1"
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


class TypeSafeBlockClient(Protocol):
    def assess_blocks(
        self,
        title: str,
        blocks: list[TranscriptBlock],
    ) -> Mapping[int, TypeSafeBlockAnswer]: ...


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


def _candidate_components(
    blocks: list[TranscriptBlock],
    answers: Mapping[int, TypeSafeBlockAnswer],
    *,
    threshold: float,
) -> list[list[TranscriptBlock]]:
    components: list[list[TranscriptBlock]] = []
    current: list[TranscriptBlock] = []
    for block in blocks:
        if current and block.start_seconds - current[-1].end_seconds > 1.0:
            components.append(current)
            current = []
        probability = answers[block.block_id].sermon_probability
        if probability >= threshold:
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
            return self._empty_result(drafts, coarse_blocks, coarse_answers, cache)

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
                drafts,
                coarse_blocks + fine_blocks,
                {**coarse_answers, **fine_answers},
                cache,
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
        mean_probability = sum(
            fine_answers[block.block_id].sermon_probability for block in selected
        ) / len(selected)
        duration = last.end_seconds - first.start_seconds
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
                "boundary_seconds": first.start_seconds,
                "inside_probability": round(first_probability, 6),
                "outside_probability": round(previous_probability, 6),
                "transition_strength": round(start_strength, 6),
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
                "boundary_seconds": last.end_seconds,
                "inside_probability": round(last_probability, 6),
                "outside_probability": round(following_probability, 6),
                "transition_strength": round(end_strength, 6),
            },
        }
        candidate = {
            "rank": 1,
            "source": "typesafe_first",
            "start_seconds": first.start_seconds,
            "end_seconds": last.end_seconds,
            "included_segment_indexes": selected_indexes,
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
        return HybridSermonResult(
            method=self.method,
            model=self.model,
            prompt_version=self.prompt_version,
            confidence_tier=confidence,
            retained_segment_indexes=selected_indexes,
            excluded_segment_indexes=sorted(all_timed - set(selected_indexes)),
            uncertain_block_ids=uncertain_ids,
            warnings=warnings,
            blocks=blocks,
            classifications=self._classifications(blocks, answers),
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
        drafts: list[SegmentDraft],
        blocks: list[TranscriptBlock],
        answers: Mapping[int, TypeSafeBlockAnswer],
        cache: TypeSafeBlockCache,
    ) -> HybridSermonResult:
        all_timed = {
            index
            for block in build_transcript_blocks(drafts)
            for index in block.segment_indexes
        }
        return HybridSermonResult(
            self.method,
            self.model,
            self.prompt_version,
            "low",
            [],
            sorted(all_timed),
            [],
            ["TypeSafe found no sufficiently supported principal sermon component"],
            blocks,
            self._classifications(blocks, answers),
            {"hits": cache.hits, "misses": cache.misses},
            {
                "schema_version": 1,
                "algorithm_version": self.method,
                "candidates": [],
                "selected_rank": None,
                "discovery": {"selected_mode": "typesafe_first_no_candidate"},
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
