from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import hashlib
import json
from typing import Any, Mapping, Sequence


SELECTOR_VERSION = "speaker_pair_selector_v6"
SAME_SPEAKER_BALANCE_GAP = 2


class SelectionStratum(StrEnum):
    SHARED_ATTRIBUTION = "shared_attribution"
    CONTRADICTING_ATTRIBUTION = "contradicting_attribution"
    PARTIAL_ATTRIBUTION = "partial_attribution"
    UNATTRIBUTED = "unattributed"


class SourceRelation(StrEnum):
    SAME_SOURCE_FAMILY = "same_source_family"
    CROSS_SOURCE_FAMILY = "cross_source_family"
    UNKNOWN = "source_relation_unknown"


STRATUM_ROTATION = (
    SelectionStratum.SHARED_ATTRIBUTION,
    SelectionStratum.CONTRADICTING_ATTRIBUTION,
    SelectionStratum.PARTIAL_ATTRIBUTION,
    SelectionStratum.UNATTRIBUTED,
)

SOURCE_RELATION_ROTATION = (
    SourceRelation.SAME_SOURCE_FAMILY,
    SourceRelation.CROSS_SOURCE_FAMILY,
)


@dataclass(frozen=True, slots=True)
class PairCandidateObservation:
    input_fingerprint: str
    video_id: str
    recording_date: datetime | None
    explicit_attributions: frozenset[str] = frozenset()
    quality_signature: tuple[object, ...] = ()
    source_family_id: str | None = None
    evaluation_partition: str | None = None


@dataclass(frozen=True, slots=True)
class PairSelectionHistory:
    excluded_pairs: frozenset[frozenset[str]] = frozenset()
    excluded_source_pairs: frozenset[frozenset[str]] = frozenset()
    observation_use: Mapping[str, int] | None = None
    source_use: Mapping[str, int] | None = None
    disfavored_observations: Mapping[str, int] | None = None
    disfavored_sources: Mapping[str, int] | None = None
    automatic_selection_count: int = 0
    objective_condition_counts: Mapping[str, int] | None = None
    source_family_use: Mapping[str, int] | None = None
    source_relation_counts: Mapping[str, int] | None = None
    reviewed_pair_outcomes: Mapping[frozenset[str], str] | None = None
    reviewed_pair_partitions: Mapping[frozenset[str], str | None] | None = None


@dataclass(frozen=True, slots=True)
class PairSelection:
    observation_a: PairCandidateObservation
    observation_b: PairCandidateObservation
    manifest: dict[str, object]


def selection_history_from_artifacts(
    *,
    drafts: Sequence[dict[str, Any]],
    reviews: Sequence[dict[str, Any]],
    fixtures: Sequence[dict[str, Any]],
) -> PairSelectionHistory:
    """Derive selector state from append-only review artifacts, without new lifecycle state."""
    drafts_by_pair = {
        str(draft.get("pair_id")): draft for draft in drafts if draft.get("pair_id")
    }
    excluded_pairs: set[frozenset[str]] = set()
    excluded_source_pairs: set[frozenset[str]] = set()
    observation_use: dict[str, int] = {}
    source_use: dict[str, int] = {}
    disfavored: dict[str, int] = {}
    disfavored_sources: dict[str, int] = {}
    objective_counts: dict[str, int] = {}
    source_family_use: dict[str, int] = {}
    source_relation_counts: dict[str, int] = {}
    reviewed_pair_outcomes: dict[frozenset[str], str] = {}
    reviewed_pair_partitions: dict[frozenset[str], str | None] = {}
    source_context_pair_ids: set[str] = set()
    automatic_pair_ids: set[str] = set()
    sources_by_pair: dict[str, list[str]] = {}

    for index, draft in enumerate(drafts):
        fingerprints = _draft_fingerprints(draft)
        if len(fingerprints) == 2:
            excluded_pairs.add(frozenset(fingerprints))
        sources = _draft_sources(draft)
        if len(sources) == 2:
            excluded_source_pairs.add(frozenset(sources))
            sources_by_pair[str(draft.get("pair_id") or f"draft-{index}")] = sources
        _record_automatic_pair(draft, automatic_pair_ids)
        _record_source_context_once(
            draft,
            source_context_pair_ids=source_context_pair_ids,
            source_family_use=source_family_use,
            source_relation_counts=source_relation_counts,
        )

    for index, fixture in enumerate(fixtures):
        fingerprints = _fixture_fingerprints(fixture)
        if len(fingerprints) == 2:
            pair_key = frozenset(fingerprints)
            excluded_pairs.add(pair_key)
            for fingerprint in fingerprints:
                observation_use[fingerprint] = observation_use.get(fingerprint, 0) + 1
            outcome = fixture.get("expected_outcome")
            if outcome in {"same_speaker", "different_speaker"}:
                prior_outcome = reviewed_pair_outcomes.get(pair_key)
                reviewed_pair_outcomes[pair_key] = (
                    str(outcome)
                    if prior_outcome in {None, outcome}
                    else "conflicting"
                )
                reviewed_pair_partitions[pair_key] = _fixture_partition(fixture)
        sources = _fixture_sources(fixture)
        if len(sources) == 2:
            excluded_source_pairs.add(frozenset(sources))
            sources_by_pair.setdefault(
                str(fixture.get("pair_id") or f"fixture-{index}"), sources
            )
        manifest = fixture.get("selection_manifest")
        if isinstance(manifest, dict):
            for reason in manifest.get("reason_codes", []):
                if isinstance(reason, str):
                    objective_counts[reason] = objective_counts.get(reason, 0) + 1
        _record_automatic_pair(fixture, automatic_pair_ids)
        _record_source_context_once(
            fixture,
            source_context_pair_ids=source_context_pair_ids,
            source_family_use=source_family_use,
            source_relation_counts=source_relation_counts,
        )

    for review in reviews:
        pair_id = str(review.get("pair_id", ""))
        draft = drafts_by_pair.get(pair_id)
        if draft is not None:
            fingerprints = _draft_fingerprints(draft)
            if len(fingerprints) == 2:
                excluded_pairs.add(frozenset(fingerprints))
            for label in ("A", "B"):
                qualification = review.get("qualification", {}).get(label)
                if qualification not in {"invalid_audio", "multiple_speakers"}:
                    continue
                source_key = draft.get("presentation", {}).get(label, {}).get("source_key")
                source = draft.get("observations", {}).get(source_key, {})
                fingerprint = source.get("input_fingerprint")
                if isinstance(fingerprint, str):
                    disfavored[fingerprint] = disfavored.get(fingerprint, 0) + 1
                video_id = source.get("youtube_video_id")
                if isinstance(video_id, str) and video_id:
                    disfavored_sources[video_id] = disfavored_sources.get(video_id, 0) + 1
        _record_automatic_pair(review, automatic_pair_ids)

    for sources in sources_by_pair.values():
        for source in sources:
            source_use[source] = source_use.get(source, 0) + 1

    return PairSelectionHistory(
        excluded_pairs=frozenset(excluded_pairs),
        excluded_source_pairs=frozenset(excluded_source_pairs),
        observation_use=observation_use,
        source_use=source_use,
        disfavored_observations=disfavored,
        disfavored_sources=disfavored_sources,
        automatic_selection_count=len(automatic_pair_ids),
        objective_condition_counts=objective_counts,
        source_family_use=source_family_use,
        source_relation_counts=source_relation_counts,
        reviewed_pair_outcomes=reviewed_pair_outcomes,
        reviewed_pair_partitions=reviewed_pair_partitions,
    )


def select_next_speaker_pair(
    observations: Sequence[PairCandidateObservation],
    history: PairSelectionHistory,
    *,
    evaluation_partition: str | None = None,
) -> PairSelection:
    """Select the next pair deterministically without assigning identity truth."""
    ordered = sorted(observations, key=lambda item: item.input_fingerprint)
    if len({item.input_fingerprint for item in ordered}) != len(ordered):
        raise ValueError("candidate observation fingerprints must be unique")
    candidates = [
        item
        for item in ordered
        if evaluation_partition is None
        or item.evaluation_partition == evaluation_partition
    ]
    if len(candidates) < 2:
        scope = evaluation_partition or "all partitions"
        raise ValueError(
            f"fewer than two eligible speaker observations remain in {scope}"
        )

    pairs: list[
        tuple[
            PairCandidateObservation,
            PairCandidateObservation,
            SelectionStratum,
            SourceRelation,
        ]
    ] = []
    for index, observation_a in enumerate(candidates):
        for observation_b in candidates[index + 1 :]:
            pair_key = frozenset((observation_a.input_fingerprint, observation_b.input_fingerprint))
            source_pair_key = frozenset((observation_a.video_id, observation_b.video_id))
            if (
                pair_key in history.excluded_pairs
                or source_pair_key in history.excluded_source_pairs
                or _crosses_evaluation_partitions(observation_a, observation_b)
            ):
                continue
            pairs.append(
                (
                    observation_a,
                    observation_b,
                    _pair_stratum(observation_a, observation_b),
                    _source_relation(observation_a, observation_b),
                )
            )
    if not pairs:
        raise ValueError("no unreviewed or undrafted eligible speaker pairs remain")

    observation_use = history.observation_use or {}
    source_use = history.source_use or {}
    source_family_use = history.source_family_use or {}
    disfavored = history.disfavored_observations or {}
    disfavored_sources = history.disfavored_sources or {}
    condition_counts = history.objective_condition_counts or {}
    outcome_counts = _reviewed_outcome_counts(
        history,
        evaluation_partition=evaluation_partition,
    )
    anchor_selection = _select_same_speaker_anchor_expansion(
        pairs,
        history,
        outcome_counts=outcome_counts,
        source_family_use=source_family_use,
        observation_use=observation_use,
        source_use=source_use,
        disfavored=disfavored,
        disfavored_sources=disfavored_sources,
        condition_counts=condition_counts,
    )
    if anchor_selection is not None:
        observation_a, observation_b, chosen_stratum, chosen_relation, anchor_component = (
            anchor_selection
        )
        selection_objective = "same_speaker_anchor_expansion"
    else:
        observation_a, observation_b, chosen_stratum, chosen_relation = (
            _select_rotating_pair(
                pairs,
                history,
                source_family_use=source_family_use,
                observation_use=observation_use,
                source_use=source_use,
                disfavored=disfavored,
                disfavored_sources=disfavored_sources,
                condition_counts=condition_counts,
            )
        )
        anchor_component = None
        selection_objective = "diversity_rotation"

    prior_a = max(
        int(source_use.get(observation_a.video_id, 0)),
        int(observation_use.get(observation_a.input_fingerprint, 0)),
    )
    prior_b = max(
        int(source_use.get(observation_b.video_id, 0)),
        int(observation_use.get(observation_b.input_fingerprint, 0)),
    )
    source_family_prior_a = _source_family_prior_use(
        observation_a,
        source_family_use,
    )
    source_family_prior_b = _source_family_prior_use(
        observation_b,
        source_family_use,
    )
    reason_codes = _reason_codes(
        observation_a,
        observation_b,
        prior_a,
        prior_b,
        chosen_relation,
        source_family_prior_a,
        source_family_prior_b,
    )
    if anchor_component is not None:
        reason_codes.insert(0, "reviewed_same_anchor_expansion")
    elif _same_speaker_balance_needed(outcome_counts):
        reason_codes.insert(0, "same_likely_candidates_exhausted")
    snapshot = [
        {
            "input_fingerprint": item.input_fingerprint,
            "video_id": item.video_id,
            "recording_date": item.recording_date.isoformat() if item.recording_date else None,
            "explicit_attributions": sorted(item.explicit_attributions),
            "quality_signature": item.quality_signature,
            "source_family_id": item.source_family_id,
            "evaluation_partition": item.evaluation_partition,
        }
        for item in candidates
    ]
    manifest: dict[str, object] = {
        "selector_version": SELECTOR_VERSION,
        "selection_origin": "automatic",
        "selection_objective": selection_objective,
        "selection_stratum": chosen_stratum,
        "source_relation": chosen_relation,
        "source_family_ids": {
            "a": observation_a.source_family_id,
            "b": observation_b.source_family_id,
        },
        "source_family_prior_use": {
            "a": source_family_prior_a,
            "b": source_family_prior_b,
        },
        "evaluation_partitions": {
            "a": observation_a.evaluation_partition,
            "b": observation_b.evaluation_partition,
        },
        "evaluation_scope": evaluation_partition or "all_partitions",
        "corpus_snapshot_fingerprint": _sha256_json(snapshot),
        "observation_prior_use": {"a": prior_a, "b": prior_b},
        "reviewed_outcome_counts": outcome_counts,
        "reason_codes": reason_codes,
    }
    if anchor_component is not None:
        manifest["anchor_component_fingerprints"] = sorted(anchor_component)
    return PairSelection(observation_a, observation_b, manifest)


def _select_same_speaker_anchor_expansion(
    pairs: Sequence[
        tuple[
            PairCandidateObservation,
            PairCandidateObservation,
            SelectionStratum,
            SourceRelation,
        ]
    ],
    history: PairSelectionHistory,
    *,
    outcome_counts: Mapping[str, int],
    source_family_use: Mapping[str, int],
    observation_use: Mapping[str, int],
    source_use: Mapping[str, int],
    disfavored: Mapping[str, int],
    disfavored_sources: Mapping[str, int],
    condition_counts: Mapping[str, int],
) -> tuple[
    PairCandidateObservation,
    PairCandidateObservation,
    SelectionStratum,
    SourceRelation,
    frozenset[str],
] | None:
    if not _same_speaker_balance_needed(outcome_counts):
        return None
    reviewed_outcomes = history.reviewed_pair_outcomes or {}
    same_components = _reviewed_same_speaker_components(reviewed_outcomes)
    if not same_components:
        return None
    different_pairs = {
        pair_key
        for pair_key, outcome in reviewed_outcomes.items()
        if outcome == "different_speaker"
    }
    expansions: list[
        tuple[
            PairCandidateObservation,
            PairCandidateObservation,
            SelectionStratum,
            SourceRelation,
            frozenset[str],
        ]
    ] = []
    for observation_a, observation_b, stratum, relation in pairs:
        fingerprints = {
            observation_a.input_fingerprint,
            observation_b.input_fingerprint,
        }
        for anchor_component in same_components:
            overlap = fingerprints & anchor_component
            if len(overlap) != 1:
                continue
            candidate_fingerprint = next(iter(fingerprints - anchor_component))
            if any(
                frozenset((candidate_fingerprint, anchor_fingerprint))
                in different_pairs
                for anchor_fingerprint in anchor_component
            ):
                continue
            if stratum != SelectionStratum.SHARED_ATTRIBUTION:
                continue
            expansions.append(
                (
                    observation_a,
                    observation_b,
                    stratum,
                    relation,
                    anchor_component,
                )
            )
    if not expansions:
        return None
    return min(
        expansions,
        key=lambda item: (
            0 if item[2] == SelectionStratum.SHARED_ATTRIBUTION else 1,
            _rank_pair(
                item[0],
                item[1],
                source_family_use,
                observation_use,
                source_use,
                disfavored,
                disfavored_sources,
                condition_counts,
            ),
        ),
    )


def _reviewed_same_speaker_components(
    reviewed_outcomes: Mapping[frozenset[str], str],
) -> tuple[frozenset[str], ...]:
    adjacency: dict[str, set[str]] = {}
    for pair_key, outcome in reviewed_outcomes.items():
        if outcome != "same_speaker" or len(pair_key) != 2:
            continue
        fingerprint_a, fingerprint_b = tuple(pair_key)
        adjacency.setdefault(fingerprint_a, set()).add(fingerprint_b)
        adjacency.setdefault(fingerprint_b, set()).add(fingerprint_a)

    components: list[frozenset[str]] = []
    unseen = set(adjacency)
    while unseen:
        pending = [min(unseen)]
        component: set[str] = set()
        while pending:
            fingerprint = pending.pop()
            if fingerprint in component:
                continue
            component.add(fingerprint)
            pending.extend(sorted(adjacency.get(fingerprint, ()), reverse=True))
        unseen.difference_update(component)
        components.append(frozenset(component))
    return tuple(
        sorted(
            components,
            key=lambda component: tuple(sorted(component)),
        )
    )


def _select_rotating_pair(
    pairs: Sequence[
        tuple[
            PairCandidateObservation,
            PairCandidateObservation,
            SelectionStratum,
            SourceRelation,
        ]
    ],
    history: PairSelectionHistory,
    *,
    source_family_use: Mapping[str, int],
    observation_use: Mapping[str, int],
    source_use: Mapping[str, int],
    disfavored: Mapping[str, int],
    disfavored_sources: Mapping[str, int],
    condition_counts: Mapping[str, int],
) -> tuple[
    PairCandidateObservation,
    PairCandidateObservation,
    SelectionStratum,
    SourceRelation,
]:
    start = history.automatic_selection_count % len(STRATUM_ROTATION)
    rotated = STRATUM_ROTATION[start:] + STRATUM_ROTATION[:start]
    chosen_stratum = next(
        stratum for stratum in rotated if any(pair[2] == stratum for pair in pairs)
    )
    stratum_pairs = [pair for pair in pairs if pair[2] == chosen_stratum]
    relation_counts = history.source_relation_counts or {}
    relation_start = history.automatic_selection_count % len(SOURCE_RELATION_ROTATION)
    relation_rotation = (
        SOURCE_RELATION_ROTATION[relation_start:]
        + SOURCE_RELATION_ROTATION[:relation_start]
    )
    available_relations = {pair[3] for pair in stratum_pairs}
    known_relations = [
        relation for relation in relation_rotation if relation in available_relations
    ]
    if known_relations:
        chosen_relation = min(
            known_relations,
            key=lambda relation: (
                int(relation_counts.get(relation.value, 0)),
                relation_rotation.index(relation),
            ),
        )
    else:
        chosen_relation = SourceRelation.UNKNOWN
    relation_pairs = [pair for pair in stratum_pairs if pair[3] == chosen_relation]
    observation_a, observation_b, _, _ = min(
        relation_pairs,
        key=lambda pair: _rank_pair(
            pair[0],
            pair[1],
            source_family_use,
            observation_use,
            source_use,
            disfavored,
            disfavored_sources,
            condition_counts,
        ),
    )
    return observation_a, observation_b, chosen_stratum, chosen_relation


def _pair_stratum(
    observation_a: PairCandidateObservation,
    observation_b: PairCandidateObservation,
) -> SelectionStratum:
    names_a = observation_a.explicit_attributions
    names_b = observation_b.explicit_attributions
    if bool(names_a) != bool(names_b):
        return SelectionStratum.PARTIAL_ATTRIBUTION
    if not names_a:
        return SelectionStratum.UNATTRIBUTED
    if names_a & names_b:
        return SelectionStratum.SHARED_ATTRIBUTION
    return SelectionStratum.CONTRADICTING_ATTRIBUTION


def _same_speaker_balance_needed(outcome_counts: Mapping[str, int]) -> bool:
    return (
        int(outcome_counts.get("different_speaker", 0))
        - int(outcome_counts.get("same_speaker", 0))
        >= SAME_SPEAKER_BALANCE_GAP
    )


def _source_relation(
    observation_a: PairCandidateObservation,
    observation_b: PairCandidateObservation,
) -> SourceRelation:
    if not observation_a.source_family_id or not observation_b.source_family_id:
        return SourceRelation.UNKNOWN
    if observation_a.source_family_id == observation_b.source_family_id:
        return SourceRelation.SAME_SOURCE_FAMILY
    return SourceRelation.CROSS_SOURCE_FAMILY


def _crosses_evaluation_partitions(
    observation_a: PairCandidateObservation,
    observation_b: PairCandidateObservation,
) -> bool:
    return (
        bool(observation_a.evaluation_partition)
        and bool(observation_b.evaluation_partition)
        and observation_a.evaluation_partition != observation_b.evaluation_partition
    )


def _draft_fingerprints(payload: Mapping[str, Any]) -> list[str]:
    return [
        str(item["input_fingerprint"])
        for item in payload.get("observations", {}).values()
        if isinstance(item, dict) and item.get("input_fingerprint")
    ]


def _fixture_fingerprints(payload: Mapping[str, Any]) -> list[str]:
    return [
        str(payload.get("observations", {}).get(side, {}).get("input_fingerprint"))
        for side in ("a", "b")
        if payload.get("observations", {}).get(side, {}).get("input_fingerprint")
    ]


def _fixture_partition(payload: Mapping[str, Any]) -> str | None:
    partition = payload.get("evaluation_partition")
    if isinstance(partition, str) and partition:
        return partition
    manifest = payload.get("selection_manifest")
    if isinstance(manifest, Mapping):
        scope = manifest.get("evaluation_scope")
        if scope in {"development", "validation", "held_out"}:
            return str(scope)
    return None


def _reviewed_outcome_counts(
    history: PairSelectionHistory,
    *,
    evaluation_partition: str | None,
) -> dict[str, int]:
    counts = {"same_speaker": 0, "different_speaker": 0}
    outcomes = history.reviewed_pair_outcomes or {}
    partitions = history.reviewed_pair_partitions or {}
    for pair_key, outcome in outcomes.items():
        if outcome not in counts:
            continue
        if (
            evaluation_partition is not None
            and partitions.get(pair_key) != evaluation_partition
        ):
            continue
        counts[outcome] += 1
    return counts


def _draft_sources(payload: Mapping[str, Any]) -> list[str]:
    return [
        str(item["youtube_video_id"])
        for item in payload.get("observations", {}).values()
        if isinstance(item, dict) and item.get("youtube_video_id")
    ]


def _fixture_sources(payload: Mapping[str, Any]) -> list[str]:
    return [
        str(payload.get("observations", {}).get(side, {}).get("youtube_video_id"))
        for side in ("a", "b")
        if payload.get("observations", {}).get(side, {}).get("youtube_video_id")
    ]


def _record_automatic_pair(payload: Mapping[str, Any], pair_ids: set[str]) -> None:
    manifest = payload.get("selection_manifest")
    pair_id = payload.get("pair_id")
    if isinstance(manifest, dict) and manifest.get("selection_origin") == "automatic" and pair_id:
        pair_ids.add(str(pair_id))


def _record_source_context(
    manifest: Mapping[str, Any],
    *,
    source_family_use: dict[str, int],
    source_relation_counts: dict[str, int],
) -> None:
    family_ids = manifest.get("source_family_ids")
    if isinstance(family_ids, Mapping):
        for family_id in family_ids.values():
            if isinstance(family_id, str) and family_id:
                source_family_use[family_id] = source_family_use.get(family_id, 0) + 1
    relation = manifest.get("source_relation")
    if isinstance(relation, str) and relation:
        source_relation_counts[relation] = source_relation_counts.get(relation, 0) + 1


def _record_source_context_once(
    payload: Mapping[str, Any],
    *,
    source_context_pair_ids: set[str],
    source_family_use: dict[str, int],
    source_relation_counts: dict[str, int],
) -> None:
    pair_id = payload.get("pair_id")
    manifest = payload.get("selection_manifest")
    if (
        not isinstance(pair_id, str)
        or not pair_id
        or pair_id in source_context_pair_ids
        or not isinstance(manifest, Mapping)
    ):
        return
    _record_source_context(
        manifest,
        source_family_use=source_family_use,
        source_relation_counts=source_relation_counts,
    )
    source_context_pair_ids.add(pair_id)


def _rank_pair(
    observation_a: PairCandidateObservation,
    observation_b: PairCandidateObservation,
    source_family_use: Mapping[str, int],
    observation_use: Mapping[str, int],
    source_use: Mapping[str, int],
    disfavored: Mapping[str, int],
    disfavored_sources: Mapping[str, int],
    condition_counts: Mapping[str, int],
) -> tuple[object, ...]:
    family_ids = {
        family_id
        for family_id in (
            observation_a.source_family_id,
            observation_b.source_family_id,
        )
        if family_id
    }
    family_uses = [int(source_family_use.get(family_id, 0)) for family_id in family_ids]
    source_use_a = int(source_use.get(observation_a.video_id, 0))
    source_use_b = int(source_use.get(observation_b.video_id, 0))
    observation_use_a = int(observation_use.get(observation_a.input_fingerprint, 0))
    observation_use_b = int(observation_use.get(observation_b.input_fingerprint, 0))
    dates_differ = (
        observation_a.recording_date is not None
        and observation_b.recording_date is not None
        and observation_a.recording_date.date() != observation_b.recording_date.date()
    )
    separation = _date_separation_days(observation_a, observation_b)
    quality_differs = (
        bool(observation_a.quality_signature)
        and bool(observation_b.quality_signature)
        and observation_a.quality_signature != observation_b.quality_signature
    )
    objective_count = condition_counts.get("varied_audio_quality", 0) if quality_differs else 10**9
    pair_hash = _sha256_json(
        sorted((observation_a.input_fingerprint, observation_b.input_fingerprint))
    )
    disfavored_count = (
        int(disfavored.get(observation_a.input_fingerprint, 0))
        + int(disfavored.get(observation_b.input_fingerprint, 0))
        + int(disfavored_sources.get(observation_a.video_id, 0))
        + int(disfavored_sources.get(observation_b.video_id, 0))
    )
    return (
        # Known review failures are a safety constraint, not a coverage
        # objective. Never select one merely to represent a new source family.
        disfavored_count,
        sum(use > 0 for use in family_uses),
        sum(family_uses),
        max(family_uses, default=0),
        int(source_use_a > 0) + int(source_use_b > 0),
        source_use_a + source_use_b,
        max(source_use_a, source_use_b),
        int(observation_use_a > 0) + int(observation_use_b > 0),
        observation_use_a + observation_use_b,
        0 if dates_differ else 1,
        -separation,
        objective_count,
        pair_hash,
    )


def _date_separation_days(
    observation_a: PairCandidateObservation,
    observation_b: PairCandidateObservation,
) -> int:
    if observation_a.recording_date is None or observation_b.recording_date is None:
        return -1
    return abs((observation_a.recording_date.date() - observation_b.recording_date.date()).days)


def _reason_codes(
    observation_a: PairCandidateObservation,
    observation_b: PairCandidateObservation,
    prior_a: int,
    prior_b: int,
    source_relation: SourceRelation,
    source_family_prior_a: int,
    source_family_prior_b: int,
) -> list[str]:
    reasons: list[str] = []
    if prior_a == 0 and prior_b == 0:
        reasons.append("both_observations_unused")
    elif prior_a == 0 or prior_b == 0:
        reasons.append("one_observation_unused")
    else:
        reasons.append("least_used_observations")
    reasons.append(source_relation.value)
    if source_relation == SourceRelation.UNKNOWN:
        reasons.append("source_family_context_unavailable")
    elif source_family_prior_a == 0 and source_family_prior_b == 0:
        reasons.append("source_families_unrepresented")
    elif source_family_prior_a == 0 or source_family_prior_b == 0:
        reasons.append("one_source_family_unrepresented")
    else:
        reasons.append("least_used_source_families")
    if _date_separation_days(observation_a, observation_b) > 0:
        reasons.append("different_date")
    if (
        observation_a.quality_signature
        and observation_b.quality_signature
        and observation_a.quality_signature != observation_b.quality_signature
    ):
        reasons.append("varied_audio_quality")
    return reasons


def _source_family_prior_use(
    observation: PairCandidateObservation,
    source_family_use: Mapping[str, int],
) -> int:
    if not observation.source_family_id:
        return 0
    return int(source_family_use.get(observation.source_family_id, 0))


def _sha256_json(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
