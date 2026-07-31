from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import hashlib
import json
from typing import Any, Mapping, Sequence


SELECTOR_VERSION = "speaker_pair_selector_v12"
SAME_SPEAKER_BALANCE_GAP = 2


class SelectionGoal(StrEnum):
    EVALUATION = "evaluation"
    PROFILE_GROWTH = "profile-growth"
    AUTOMATION_READINESS = "automation-readiness"


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
    reviewed_profile_ids: frozenset[int] = frozenset()
    explicitly_different_from: frozenset[str] = frozenset()
    observation_consistency_score: float | None = None


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
    reviewed_identity_outcomes: Mapping[frozenset[str], str] | None = None
    profile_growth_selections: tuple[frozenset[str], ...] = ()
    qualified_single_observations: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class PairSelection:
    observation_a: PairCandidateObservation
    observation_b: PairCandidateObservation
    manifest: dict[str, object]


@dataclass(frozen=True, slots=True)
class DiscoveryResolutionPair:
    fingerprint_a: str
    fingerprint_b: str
    component_ids: tuple[str, ...]
    member_fingerprints: tuple[str, ...]
    observations_unlocked: int
    report_result_sha256: str | None = None
    report_path: str | None = None

    @property
    def pair_key(self) -> frozenset[str]:
        return frozenset((self.fingerprint_a, self.fingerprint_b))


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
    reviewed_identity_outcomes: dict[frozenset[str], str] = {}
    source_context_pair_ids: set[str] = set()
    automatic_pair_ids: set[str] = set()
    sources_by_pair: dict[str, list[str]] = {}
    profile_growth_selections_by_pair: dict[str, frozenset[str]] = {}
    qualified_single_observations: set[str] = set()

    for index, draft in enumerate(drafts):
        fingerprints = _draft_fingerprints(draft)
        if len(fingerprints) == 2:
            excluded_pairs.add(frozenset(fingerprints))
        sources = _draft_sources(draft)
        if len(sources) == 2:
            excluded_source_pairs.add(frozenset(sources))
            sources_by_pair[str(draft.get("pair_id") or f"draft-{index}")] = sources
        _record_automatic_pair(draft, automatic_pair_ids)
        _record_profile_growth_selection_once(
            draft,
            profile_growth_selections_by_pair,
        )
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
                identity_outcome = reviewed_identity_outcomes.get(pair_key)
                reviewed_identity_outcomes[pair_key] = (
                    str(outcome)
                    if identity_outcome in {None, outcome}
                    else "conflicting"
                )
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
        qualifications = fixture.get("qualification", {})
        if isinstance(qualifications, Mapping):
            for label, side in (("A", "a"), ("B", "b")):
                if qualifications.get(label) != "qualified_single_speaker":
                    continue
                fingerprint = (
                    fixture.get("observations", {})
                    .get(side, {})
                    .get("input_fingerprint")
                )
                if isinstance(fingerprint, str):
                    qualified_single_observations.add(fingerprint)
        _record_automatic_pair(fixture, automatic_pair_ids)
        _record_profile_growth_selection_once(
            fixture,
            profile_growth_selections_by_pair,
        )
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
                pair_key = frozenset(fingerprints)
                excluded_pairs.add(pair_key)
                judgment = review.get("pair_judgment")
                qualifications = review.get("qualification", {})
                identity_evidence_eligible = review.get(
                    "identity_evidence_eligible"
                )
                if identity_evidence_eligible is None:
                    identity_evidence_eligible = (
                        review.get("approval_confirmed") is True
                        and review.get("fixture_eligible") is True
                    )
                if (
                    identity_evidence_eligible is True
                    and judgment in {"same_speaker", "different_speaker"}
                    and isinstance(qualifications, Mapping)
                    and qualifications.get("A")
                    == "qualified_single_speaker"
                    and qualifications.get("B")
                    == "qualified_single_speaker"
                ):
                    prior_outcome = reviewed_identity_outcomes.get(pair_key)
                    reviewed_identity_outcomes[pair_key] = (
                        str(judgment)
                        if prior_outcome in {None, judgment}
                        else "conflicting"
                    )
            for label in ("A", "B"):
                qualification = review.get("qualification", {}).get(label)
                source_key = draft.get("presentation", {}).get(label, {}).get("source_key")
                source = draft.get("observations", {}).get(source_key, {})
                fingerprint = source.get("input_fingerprint")
                if (
                    qualification == "qualified_single_speaker"
                    and isinstance(fingerprint, str)
                ):
                    qualified_single_observations.add(fingerprint)
                if qualification not in {"invalid_audio", "multiple_speakers"}:
                    continue
                if isinstance(fingerprint, str):
                    disfavored[fingerprint] = disfavored.get(fingerprint, 0) + 1
                video_id = source.get("youtube_video_id")
                if isinstance(video_id, str) and video_id:
                    disfavored_sources[video_id] = disfavored_sources.get(video_id, 0) + 1
        _record_automatic_pair(review, automatic_pair_ids)
        _record_profile_growth_selection_once(
            review,
            profile_growth_selections_by_pair,
        )

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
        reviewed_identity_outcomes=reviewed_identity_outcomes,
        profile_growth_selections=tuple(
            profile_growth_selections_by_pair[pair_id]
            for pair_id in sorted(profile_growth_selections_by_pair)
        ),
        qualified_single_observations=frozenset(
            qualified_single_observations
        ),
    )


def select_next_speaker_pair(
    observations: Sequence[PairCandidateObservation],
    history: PairSelectionHistory,
    *,
    evaluation_partition: str | None = None,
    selection_goal: SelectionGoal | str = SelectionGoal.EVALUATION,
    discovery_resolution_pairs: Sequence[DiscoveryResolutionPair] = (),
) -> PairSelection:
    """Select the next pair deterministically without assigning identity truth."""
    try:
        goal = SelectionGoal(selection_goal)
    except ValueError as error:
        raise ValueError(
            "selection goal must be one of: evaluation, profile-growth, "
            "automation-readiness"
        ) from error
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
    discovery_resolution_by_pair = {
        item.pair_key: item for item in discovery_resolution_pairs
    }
    outcome_counts = _reviewed_outcome_counts(
        history,
        evaluation_partition=evaluation_partition,
    )
    objective_selection = (
        _select_profile_growth_pair(
            pairs,
            candidates=candidates,
            history=history,
            source_family_use=source_family_use,
            observation_use=observation_use,
            source_use=source_use,
            disfavored=disfavored,
            disfavored_sources=disfavored_sources,
            condition_counts=condition_counts,
        )
        if goal == SelectionGoal.PROFILE_GROWTH
        else None
    )
    if goal == SelectionGoal.AUTOMATION_READINESS:
        objective_selection = _select_discovery_resolution_pair(
            pairs,
            discovery_resolution_by_pair=discovery_resolution_by_pair,
            source_family_use=source_family_use,
            observation_use=observation_use,
            source_use=source_use,
            disfavored=disfavored,
            disfavored_sources=disfavored_sources,
            condition_counts=condition_counts,
        ) or _select_profile_reinforcement_pair(
            pairs,
            candidates=candidates,
            history=history,
            source_family_use=source_family_use,
            observation_use=observation_use,
            source_use=source_use,
            disfavored=disfavored,
            disfavored_sources=disfavored_sources,
            condition_counts=condition_counts,
        ) or _select_profile_growth_pair(
            pairs,
            candidates=candidates,
            history=history,
            source_family_use=source_family_use,
            observation_use=observation_use,
            source_use=source_use,
            disfavored=disfavored,
            disfavored_sources=disfavored_sources,
            condition_counts=condition_counts,
        )
    if (
        goal in {
            SelectionGoal.PROFILE_GROWTH,
            SelectionGoal.AUTOMATION_READINESS,
        }
        and objective_selection is None
    ):
        raise ValueError(
            f"no unreviewed {goal.value} pair remains after reviewed "
            "same/different and qualification exclusions"
        )
    curated_selection = (
        _select_curated_relation_pair(
            pairs,
            source_family_use=source_family_use,
            observation_use=observation_use,
            source_use=source_use,
            disfavored=disfavored,
            disfavored_sources=disfavored_sources,
            condition_counts=condition_counts,
        )
        if goal == SelectionGoal.EVALUATION
        else None
    )
    anchor_selection = None
    if objective_selection is not None:
        (
            observation_a,
            observation_b,
            chosen_stratum,
            chosen_relation,
            selection_objective,
            growth_components,
        ) = objective_selection
        anchor_component = None
        if selection_objective == "discovery_component_overlap_resolution":
            growth_components = None
    elif curated_selection is not None:
        observation_a, observation_b, chosen_stratum, chosen_relation, curated_relation = (
            curated_selection
        )
        anchor_component = None
        selection_objective = curated_relation
        growth_components = None
    elif goal == SelectionGoal.EVALUATION:
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
    if curated_selection is None and anchor_selection is not None:
        observation_a, observation_b, chosen_stratum, chosen_relation, anchor_component = (
            anchor_selection
        )
        selection_objective = "same_speaker_anchor_expansion"
        growth_components = None
    elif goal == SelectionGoal.EVALUATION and curated_selection is None:
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
        growth_components = None

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
    if objective_selection is not None:
        reason_codes.insert(0, selection_objective)
    elif curated_selection is not None:
        reason_codes.insert(0, selection_objective)
    elif anchor_component is not None:
        reason_codes.insert(0, "reviewed_same_anchor_expansion")
    elif (
        goal == SelectionGoal.EVALUATION
        and _same_speaker_balance_needed(outcome_counts)
    ):
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
            "reviewed_profile_ids": sorted(item.reviewed_profile_ids),
            "explicitly_different_from": sorted(item.explicitly_different_from),
        }
        for item in candidates
    ]
    manifest: dict[str, object] = {
        "selector_version": SELECTOR_VERSION,
        "selection_origin": "automatic",
        "selection_goal": goal.value,
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
    if growth_components is not None:
        manifest["profile_growth_components"] = [
            sorted(component) for component in growth_components
        ]
    selected_resolution = discovery_resolution_by_pair.get(
        frozenset(
            (
                observation_a.input_fingerprint,
                observation_b.input_fingerprint,
            )
        )
    )
    if (
        selection_objective == "discovery_component_overlap_resolution"
        and selected_resolution is not None
    ):
        manifest["discovery_resolution"] = {
            "component_ids": list(selected_resolution.component_ids),
            "member_fingerprints": list(
                selected_resolution.member_fingerprints
            ),
            "observations_unlocked": (
                selected_resolution.observations_unlocked
            ),
        }
        if selected_resolution.report_result_sha256 is not None:
            manifest["discovery_resolution"][
                "report_result_sha256"
            ] = selected_resolution.report_result_sha256
        if selected_resolution.report_path is not None:
            manifest["discovery_resolution"][
                "report_path"
            ] = selected_resolution.report_path
    consistency_scores = {
        side: observation.observation_consistency_score
        for side, observation in (
            ("a", observation_a),
            ("b", observation_b),
        )
        if observation.observation_consistency_score is not None
    }
    if consistency_scores:
        manifest["observation_consistency_scores"] = consistency_scores
    return PairSelection(observation_a, observation_b, manifest)


def _select_discovery_resolution_pair(
    pairs: Sequence[
        tuple[
            PairCandidateObservation,
            PairCandidateObservation,
            SelectionStratum,
            SourceRelation,
        ]
    ],
    *,
    discovery_resolution_by_pair: Mapping[
        frozenset[str], DiscoveryResolutionPair
    ],
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
    str,
    tuple[frozenset[str], frozenset[str]],
] | None:
    candidates = [
        pair
        for pair in pairs
        if frozenset(
            (pair[0].input_fingerprint, pair[1].input_fingerprint)
        )
        in discovery_resolution_by_pair
        and not disfavored.get(pair[0].input_fingerprint, 0)
        and not disfavored.get(pair[1].input_fingerprint, 0)
    ]
    if not candidates:
        return None
    selected = min(
        candidates,
        key=lambda pair: (
            -discovery_resolution_by_pair[
                frozenset(
                    (
                        pair[0].input_fingerprint,
                        pair[1].input_fingerprint,
                    )
                )
            ].observations_unlocked,
            _rank_pair(
                pair[0],
                pair[1],
                source_family_use,
                observation_use,
                source_use,
                disfavored,
                disfavored_sources,
                condition_counts,
            ),
        ),
    )
    return (
        *selected,
        "discovery_component_overlap_resolution",
        (frozenset(), frozenset()),
    )


def _select_profile_growth_pair(
    pairs: Sequence[
        tuple[
            PairCandidateObservation,
            PairCandidateObservation,
            SelectionStratum,
            SourceRelation,
        ]
    ],
    *,
    candidates: Sequence[PairCandidateObservation],
    history: PairSelectionHistory,
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
    str,
    tuple[frozenset[str], frozenset[str]],
] | None:
    components = _profile_growth_components(candidates, history)
    candidate_by_fingerprint = {
        candidate.input_fingerprint: candidate for candidate in candidates
    }
    anchored_components = {
        component
        for component in set(components.values())
        if len(component) > 1
        or any(
            candidate_by_fingerprint[fingerprint].reviewed_profile_ids
            for fingerprint in component
        )
    }
    anchored_attributions = frozenset(
        attribution
        for component in anchored_components
        for fingerprint in component
        for attribution in candidate_by_fingerprint[fingerprint].explicit_attributions
    )
    identity_outcomes = (
        history.reviewed_identity_outcomes
        if history.reviewed_identity_outcomes is not None
        else history.reviewed_pair_outcomes
    ) or {}
    different_pairs = {
        pair_key
        for pair_key, outcome in identity_outcomes.items()
        if outcome == "different_speaker"
    }
    for candidate in candidates:
        different_pairs.update(
            frozenset((candidate.input_fingerprint, other))
            for other in candidate.explicitly_different_from
        )

    growth_pairs: list[
        tuple[
            PairCandidateObservation,
            PairCandidateObservation,
            SelectionStratum,
            SourceRelation,
            str,
            tuple[frozenset[str], frozenset[str]],
        ]
    ] = []
    for observation_a, observation_b, stratum, relation in pairs:
        if (
            disfavored.get(observation_a.input_fingerprint, 0)
            or disfavored.get(observation_b.input_fingerprint, 0)
        ):
            continue
        component_a = components[observation_a.input_fingerprint]
        component_b = components[observation_b.input_fingerprint]
        if component_a == component_b:
            continue
        if any(
            frozenset((fingerprint_a, fingerprint_b)) in different_pairs
            for fingerprint_a in component_a
            for fingerprint_b in component_b
        ):
            continue
        anchored_a = component_a in anchored_components
        anchored_b = component_b in anchored_components
        if anchored_a != anchored_b:
            objective = "profile_growth_frontier"
        elif anchored_a:
            objective = (
                "attribution_reconciliation_bridge"
                if stratum == SelectionStratum.SHARED_ATTRIBUTION
                else "profile_growth_component_bridge"
            )
        else:
            objective = (
                "profile_growth_deferred_frontier_seed"
                if (
                    observation_a.explicit_attributions
                    | observation_b.explicit_attributions
                )
                & anchored_attributions
                else "profile_growth_seed"
            )
        growth_pairs.append(
            (
                observation_a,
                observation_b,
                stratum,
                relation,
                objective,
                (component_a, component_b),
            )
        )
    if not growth_pairs:
        return None
    stratum_rank = {
        SelectionStratum.SHARED_ATTRIBUTION: 0,
        SelectionStratum.PARTIAL_ATTRIBUTION: 1,
        SelectionStratum.UNATTRIBUTED: 2,
        SelectionStratum.CONTRADICTING_ATTRIBUTION: 3,
    }
    return min(
        growth_pairs,
        key=lambda item: (
            0 if item[4] == "attribution_reconciliation_bridge" else 1,
            _profile_growth_consistency_rank(
                observations=(item[0], item[1]),
                components=item[5],
                anchored_components=anchored_components,
                history=history,
            ),
            _profile_growth_marginal_rank(
                objective=item[4],
                components=item[5],
                anchored_components=anchored_components,
                prior_selections=history.profile_growth_selections,
                stratum=item[2],
            ),
            stratum_rank[item[2]],
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


def _profile_growth_consistency_rank(
    *,
    observations: tuple[
        PairCandidateObservation,
        PairCandidateObservation,
    ],
    components: tuple[frozenset[str], frozenset[str]],
    anchored_components: set[frozenset[str]],
    history: PairSelectionHistory,
) -> tuple[int, float]:
    targets = [
        observation
        for observation, component in zip(observations, components)
        if component not in anchored_components
    ] or list(observations)
    known = history.qualified_single_observations
    unknown = [
        observation
        for observation in targets
        if observation.input_fingerprint not in known
    ]
    explore_unknown = len(history.profile_growth_selections) % 3 == 2
    if explore_unknown:
        bucket = 0 if unknown else 1
        scored = [
            observation.observation_consistency_score
            for observation in unknown
            if observation.observation_consistency_score is not None
        ]
    else:
        scored = [
            observation.observation_consistency_score
            for observation in targets
            if observation.observation_consistency_score is not None
        ]
        bucket = 0 if not unknown else (1 if scored else 2)
    # Scores are shadow ranking evidence only. Missing scores remain eligible
    # and are deliberately sampled by the exploration turn.
    return bucket, -max(scored, default=float("-inf"))


def _profile_growth_marginal_rank(
    *,
    objective: str,
    components: tuple[frozenset[str], frozenset[str]],
    anchored_components: set[frozenset[str]],
    prior_selections: Sequence[frozenset[str]],
    stratum: SelectionStratum,
) -> tuple[int, int, int]:
    anchored = [
        component
        for component in components
        if component in anchored_components
    ]
    if objective == "attribution_reconciliation_bridge":
        phase = 0
    elif (
        objective == "profile_growth_frontier"
        and stratum != SelectionStratum.CONTRADICTING_ATTRIBUTION
        and any(len(component) < 3 for component in anchored)
    ):
        # First make blocked two-member profiles large enough to approach
        # automation readiness.
        phase = 1
    elif objective == "profile_growth_seed":
        # Once small existing profiles have a frontier opportunity, create
        # additional anonymous evidence-backed profiles before repeatedly
        # enlarging an already mature component.
        phase = 2
    elif (
        objective == "profile_growth_frontier"
        and stratum != SelectionStratum.CONTRADICTING_ATTRIBUTION
    ):
        phase = 3
    else:
        phase = 4
    target_components = anchored or list(components)
    prior_use = min(
        (
            sum(
                bool(component & selected)
                for selected in prior_selections
            )
            for component in target_components
        ),
        default=0,
    )
    target_size = min(
        (len(component) for component in target_components),
        default=0,
    )
    return phase, prior_use, target_size


def _select_profile_reinforcement_pair(
    pairs: Sequence[
        tuple[
            PairCandidateObservation,
            PairCandidateObservation,
            SelectionStratum,
            SourceRelation,
        ]
    ],
    *,
    candidates: Sequence[PairCandidateObservation],
    history: PairSelectionHistory,
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
    str,
    tuple[frozenset[str], frozenset[str]],
] | None:
    components = _profile_growth_components(candidates, history)
    members_by_profile: dict[int, set[str]] = {}
    for candidate in candidates:
        for profile_id in candidate.reviewed_profile_ids:
            members_by_profile.setdefault(profile_id, set()).add(
                candidate.input_fingerprint
            )
    eligible_profile_ids = {
        profile_id
        for profile_id, fingerprints in members_by_profile.items()
        if len(fingerprints) >= 3
    }
    identity_outcomes = (
        history.reviewed_identity_outcomes
        if history.reviewed_identity_outcomes is not None
        else history.reviewed_pair_outcomes
    ) or {}
    adjacency_by_profile = {
        profile_id: {
            fingerprint: set()
            for fingerprint in members_by_profile[profile_id]
        }
        for profile_id in eligible_profile_ids
    }
    for pair_key, outcome in identity_outcomes.items():
        if outcome != "same_speaker" or len(pair_key) != 2:
            continue
        fingerprint_a, fingerprint_b = tuple(pair_key)
        for adjacency in adjacency_by_profile.values():
            if fingerprint_a in adjacency and fingerprint_b in adjacency:
                adjacency[fingerprint_a].add(fingerprint_b)
                adjacency[fingerprint_b].add(fingerprint_a)
    bridges_by_profile = {
        profile_id: _graph_bridges(adjacency)
        for profile_id, adjacency in adjacency_by_profile.items()
    }
    reinforcement_pairs: list[
        tuple[
            int,
            tuple[
                PairCandidateObservation,
                PairCandidateObservation,
                SelectionStratum,
                SourceRelation,
            ],
        ]
    ] = []
    for pair in pairs:
        if (
            disfavored.get(pair[0].input_fingerprint, 0)
            or disfavored.get(pair[1].input_fingerprint, 0)
        ):
            continue
        shared_profile_ids = (
            pair[0].reviewed_profile_ids
            & pair[1].reviewed_profile_ids
            & eligible_profile_ids
        )
        reinforcement_value = max(
            (
                _bridges_removed_by_edge(
                    adjacency_by_profile[profile_id],
                    bridges_by_profile[profile_id],
                    pair[0].input_fingerprint,
                    pair[1].input_fingerprint,
                )
                for profile_id in shared_profile_ids
            ),
            default=0,
        )
        if reinforcement_value:
            reinforcement_pairs.append((reinforcement_value, pair))
    if not reinforcement_pairs:
        return None
    _, selected = min(
        reinforcement_pairs,
        key=lambda valued_pair: (
            -valued_pair[0],
            _rank_pair(
                valued_pair[1][0],
                valued_pair[1][1],
                source_family_use,
                observation_use,
                source_use,
                disfavored,
                disfavored_sources,
                condition_counts,
            ),
        ),
    )
    component = components[selected[0].input_fingerprint]
    return (
        *selected,
        "profile_reinforcement",
        (component, component),
    )


def _graph_bridges(
    adjacency: Mapping[str, set[str]],
) -> frozenset[frozenset[str]]:
    discovery: dict[str, int] = {}
    low: dict[str, int] = {}
    parent: dict[str, str | None] = {}
    bridges: set[frozenset[str]] = set()
    time = 0

    def visit(node: str) -> None:
        nonlocal time
        time += 1
        discovery[node] = low[node] = time
        for neighbor in adjacency[node]:
            if neighbor not in discovery:
                parent[neighbor] = node
                visit(neighbor)
                low[node] = min(low[node], low[neighbor])
                if low[neighbor] > discovery[node]:
                    bridges.add(frozenset((node, neighbor)))
            elif parent.get(node) != neighbor:
                low[node] = min(low[node], discovery[neighbor])

    for node in adjacency:
        if node not in discovery:
            parent[node] = None
            visit(node)
    return frozenset(bridges)


def _bridges_removed_by_edge(
    adjacency: Mapping[str, set[str]],
    bridges: frozenset[frozenset[str]],
    start: str,
    end: str,
) -> int:
    if start not in adjacency or end not in adjacency or start == end:
        return 0
    parent: dict[str, str | None] = {start: None}
    pending = [start]
    while pending and end not in parent:
        node = pending.pop()
        for neighbor in adjacency[node]:
            if neighbor in parent:
                continue
            parent[neighbor] = node
            pending.append(neighbor)
    if end not in parent:
        # Registry co-membership says these observations are the same reviewed
        # profile, but the loaded review graph cannot replay that connection.
        # A direct comparison repairs the missing support.
        return len(adjacency) + 1
    removed = 0
    node = end
    while parent[node] is not None:
        previous = parent[node]
        if frozenset((node, previous)) in bridges:
            removed += 1
        node = previous
    return removed


def _profile_growth_components(
    candidates: Sequence[PairCandidateObservation],
    history: PairSelectionHistory,
) -> dict[str, frozenset[str]]:
    fingerprints = {
        candidate.input_fingerprint for candidate in candidates
    }
    adjacency = {fingerprint: set() for fingerprint in fingerprints}
    members_by_profile: dict[int, list[str]] = {}
    for candidate in candidates:
        for profile_id in candidate.reviewed_profile_ids:
            members_by_profile.setdefault(profile_id, []).append(
                candidate.input_fingerprint
            )
    for members in members_by_profile.values():
        for member in members:
            adjacency[member].update(
                other for other in members if other != member
            )
    identity_outcomes = (
        history.reviewed_identity_outcomes
        if history.reviewed_identity_outcomes is not None
        else history.reviewed_pair_outcomes
    ) or {}
    for pair_key, outcome in identity_outcomes.items():
        if outcome != "same_speaker" or len(pair_key) != 2:
            continue
        fingerprint_a, fingerprint_b = tuple(pair_key)
        if fingerprint_a not in adjacency or fingerprint_b not in adjacency:
            continue
        adjacency[fingerprint_a].add(fingerprint_b)
        adjacency[fingerprint_b].add(fingerprint_a)

    result: dict[str, frozenset[str]] = {}
    unseen = set(fingerprints)
    while unseen:
        pending = [min(unseen)]
        component: set[str] = set()
        while pending:
            fingerprint = pending.pop()
            if fingerprint in component:
                continue
            component.add(fingerprint)
            pending.extend(adjacency[fingerprint] - component)
        frozen = frozenset(component)
        for fingerprint in component:
            result[fingerprint] = frozen
        unseen.difference_update(component)
    return result


def _select_curated_relation_pair(
    pairs: Sequence[
        tuple[
            PairCandidateObservation,
            PairCandidateObservation,
            SelectionStratum,
            SourceRelation,
        ]
    ],
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
    str,
] | None:
    same_profile = [
        pair
        for pair in pairs
        if pair[0].reviewed_profile_ids & pair[1].reviewed_profile_ids
    ]
    explicitly_different = [
        pair
        for pair in pairs
        if (
            pair[1].input_fingerprint in pair[0].explicitly_different_from
            or pair[0].input_fingerprint in pair[1].explicitly_different_from
        )
    ]
    for candidates, objective in (
        (same_profile, "reviewed_same_profile_nomination"),
        (explicitly_different, "reviewed_different_constraint_nomination"),
    ):
        if candidates:
            selected = min(
                candidates,
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
            return (*selected, objective)
    return None


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
    if (
        isinstance(manifest, dict)
        and manifest.get("selection_origin") == "automatic"
        and pair_id
    ):
        pair_ids.add(str(pair_id))


def _record_profile_growth_selection_once(
    payload: Mapping[str, Any],
    selections_by_pair: dict[str, frozenset[str]],
) -> None:
    pair_id = payload.get("pair_id")
    manifest = payload.get("selection_manifest")
    if (
        not isinstance(pair_id, str)
        or not pair_id
        or pair_id in selections_by_pair
        or not isinstance(manifest, Mapping)
        or manifest.get("selection_goal")
        not in {
            SelectionGoal.PROFILE_GROWTH,
            SelectionGoal.AUTOMATION_READINESS,
        }
    ):
        return
    components = manifest.get("profile_growth_components")
    if not isinstance(components, Sequence) or isinstance(
        components, (str, bytes)
    ):
        return
    fingerprints = frozenset(
        str(fingerprint)
        for component in components
        if isinstance(component, Sequence)
        and not isinstance(component, (str, bytes))
        for fingerprint in component
        if isinstance(fingerprint, str) and fingerprint
    )
    if fingerprints:
        selections_by_pair[pair_id] = fingerprints


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
