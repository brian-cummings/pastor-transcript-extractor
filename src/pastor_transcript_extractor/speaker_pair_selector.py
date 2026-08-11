from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import hashlib
import json
import math
from typing import Any, Mapping, Sequence


SELECTOR_VERSION = "speaker_pair_selector_v23"
SAME_SPEAKER_BALANCE_GAP = 2
EXPLORATORY_MAX_SAME_BOUNDARY_DISTANCE = 0.15


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
    automatically_unreviewable_observations: frozenset[str] = frozenset()


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
    resolution_kind: str = "component_overlap"
    same_boundary_distance: float | None = None
    seed_fingerprints: tuple[str, ...] = ()
    candidate_fingerprint: str | None = None
    companion_pair_fingerprints: tuple[str, ...] = ()
    required_review_count: int = 1

    @property
    def pair_key(self) -> frozenset[str]:
        return frozenset((self.fingerprint_a, self.fingerprint_b))


@dataclass(frozen=True, slots=True)
class AcousticPairRanking:
    """Cached acoustic evidence used only to rank a human review pair."""

    fingerprint_a: str
    fingerprint_b: str
    same_boundary_margin: float
    centroid_similarity: float
    report_result_sha256: str
    report_path: str
    outcome: str = "same_speaker"
    reason: str = "approved_policy_same_band"

    @property
    def pair_key(self) -> frozenset[str]:
        return frozenset((self.fingerprint_a, self.fingerprint_b))


@dataclass(frozen=True, slots=True)
class AssociationConfirmationPair:
    """One exact blinded-review edge from a multi-exemplar profile proposal."""

    candidate_fingerprint: str
    exemplar_fingerprint: str
    profile_id: int
    same_comparison_count: int
    same_boundary_margin: float
    report_result_sha256: str
    report_path: str
    provisional_assignment_active: bool = False

    @property
    def pair_key(self) -> frozenset[str]:
        return frozenset(
            (self.candidate_fingerprint, self.exemplar_fingerprint)
        )


def selection_history_from_artifacts(
    *,
    drafts: Sequence[dict[str, Any]],
    reviews: Sequence[dict[str, Any]],
    fixtures: Sequence[dict[str, Any]],
    current_clip_activity_policy_version: str | None = None,
) -> PairSelectionHistory:
    """Derive selector state from append-only review artifacts, without new lifecycle state."""
    drafts_by_pair = {
        str(draft.get("pair_id")): draft for draft in drafts if draft.get("pair_id")
    }
    excluded_pairs: set[frozenset[str]] = set()
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
    automatically_unreviewable_observations: set[str] = set()

    for index, draft in enumerate(drafts):
        is_activity_rejection = (
            draft.get("event_kind")
            == "speaker_pair_automatic_selection_rejection"
            and draft.get("reason") == "insufficient_speech_activity"
        )
        if is_activity_rejection:
            applies_to_current_policy = (
                current_clip_activity_policy_version is None
                or _activity_rejection_policy_version(draft)
                == current_clip_activity_policy_version
            )
            if not applies_to_current_policy:
                continue
            failed_fingerprint = draft.get(
                "failed_observation_fingerprint"
            )
            if isinstance(failed_fingerprint, str) and failed_fingerprint:
                automatically_unreviewable_observations.add(
                    failed_fingerprint
                )
        fingerprints = _draft_fingerprints(draft)
        if len(fingerprints) == 2:
            excluded_pairs.add(frozenset(fingerprints))
        sources = _draft_sources(draft)
        if len(sources) == 2:
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
                # Qualification describes this immutable observation window,
                # not every future observation derived from the recording.
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
        automatically_unreviewable_observations=frozenset(
            automatically_unreviewable_observations
        ),
    )


def _activity_rejection_policy_version(
    rejection: Mapping[str, Any],
) -> str | None:
    failed_fingerprint = rejection.get("failed_observation_fingerprint")
    observations = rejection.get("observations")
    if not isinstance(failed_fingerprint, str) or not isinstance(
        observations, Mapping
    ):
        return None
    for observation in observations.values():
        if (
            not isinstance(observation, Mapping)
            or observation.get("input_fingerprint") != failed_fingerprint
        ):
            continue
        clip_selection = observation.get("clip_selection")
        policy_version = (
            clip_selection.get("policy_version")
            if isinstance(clip_selection, Mapping)
            else None
        )
        return policy_version if isinstance(policy_version, str) else None
    return None


def select_next_speaker_pair(
    observations: Sequence[PairCandidateObservation],
    history: PairSelectionHistory,
    *,
    evaluation_partition: str | None = None,
    selection_goal: SelectionGoal | str = SelectionGoal.EVALUATION,
    discovery_resolution_pairs: Sequence[DiscoveryResolutionPair] = (),
    profile_growth_acoustic_pairs: Sequence[AcousticPairRanking] = (),
    association_confirmation_pairs: Sequence[
        AssociationConfirmationPair
    ] = (),
    automatic_profile_ready_ids: frozenset[int] = frozenset(),
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
    if any(
        ranking.outcome not in {"same_speaker", "insufficient_evidence"}
        or ranking.fingerprint_a == ranking.fingerprint_b
        or (
            ranking.outcome == "same_speaker"
            and (
                ranking.reason != "approved_policy_same_band"
                or ranking.same_boundary_margin < 0.0
            )
        )
        or (
            ranking.outcome == "insufficient_evidence"
            and (
                ranking.reason != "ambiguous_similarity"
                or ranking.same_boundary_margin
                < -EXPLORATORY_MAX_SAME_BOUNDARY_DISTANCE
            )
        )
        or not math.isfinite(ranking.same_boundary_margin)
        or not math.isfinite(ranking.centroid_similarity)
        or not ranking.report_result_sha256
        or not ranking.report_path
        for ranking in profile_growth_acoustic_pairs
    ):
        raise ValueError(
            "profile-growth acoustic rankings require finite, provenance-bound "
            "same-speaker or ambiguous-similarity nomination context"
        )
    if any(
        nomination.candidate_fingerprint
        == nomination.exemplar_fingerprint
        or nomination.profile_id < 1
        or nomination.same_comparison_count < 2
        or nomination.same_boundary_margin < 0.0
        or not math.isfinite(nomination.same_boundary_margin)
        or not nomination.report_result_sha256
        or not nomination.report_path
        for nomination in association_confirmation_pairs
    ):
        raise ValueError(
            "association confirmations require finite, provenance-bound "
            "multi-exemplar same-speaker context"
        )
    candidates = [
        item
        for item in ordered
        if (
            item.input_fingerprint
            not in history.automatically_unreviewable_observations
            and (
                evaluation_partition is None
                or item.evaluation_partition == evaluation_partition
            )
        )
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
            if (
                pair_key in history.excluded_pairs
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
    profile_growth_acoustic_by_pair = {
        item.pair_key: item for item in profile_growth_acoustic_pairs
    }
    if len(profile_growth_acoustic_by_pair) != len(
        profile_growth_acoustic_pairs
    ):
        raise ValueError("profile-growth acoustic ranking pairs must be unique")
    association_confirmation_by_pair = {
        item.pair_key: item for item in association_confirmation_pairs
    }
    if len(association_confirmation_by_pair) != len(
        association_confirmation_pairs
    ):
        raise ValueError("association confirmation pairs must be unique")
    outcome_counts = _reviewed_outcome_counts(
        history,
        evaluation_partition=evaluation_partition,
    )
    objective_selection = (
        _select_association_confirmation_pair(
            pairs,
            association_confirmation_by_pair=(
                association_confirmation_by_pair
            ),
            observation_use=observation_use,
            source_use=source_use,
            source_family_use=source_family_use,
            disfavored=disfavored,
            disfavored_sources=disfavored_sources,
            condition_counts=condition_counts,
        )
        or _select_profile_growth_pair(
            pairs,
            candidates=candidates,
            history=history,
            source_family_use=source_family_use,
            observation_use=observation_use,
            source_use=source_use,
            disfavored=disfavored,
            disfavored_sources=disfavored_sources,
            condition_counts=condition_counts,
            acoustic_ranking_by_pair=profile_growth_acoustic_by_pair,
            automatic_profile_ready_ids=automatic_profile_ready_ids,
            allow_exploratory=True,
        )
        if goal == SelectionGoal.PROFILE_GROWTH
        else None
    )
    if goal == SelectionGoal.AUTOMATION_READINESS:
        objective_selection = _select_association_confirmation_pair(
            pairs,
            association_confirmation_by_pair=(
                association_confirmation_by_pair
            ),
            observation_use=observation_use,
            source_use=source_use,
            source_family_use=source_family_use,
            disfavored=disfavored,
            disfavored_sources=disfavored_sources,
            condition_counts=condition_counts,
        ) or _select_discovery_resolution_pair(
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
            automatic_profile_ready_ids=automatic_profile_ready_ids,
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
            acoustic_ranking_by_pair=profile_growth_acoustic_by_pair,
            automatic_profile_ready_ids=automatic_profile_ready_ids,
            allow_exploratory=False,
        )
    if (
        goal in {
            SelectionGoal.PROFILE_GROWTH,
            SelectionGoal.AUTOMATION_READINESS,
        }
        and objective_selection is None
    ):
        raise ValueError(
            f"no actionable {goal.value} pair remains: discovery and "
            "same-speaker nomination signals are exhausted or excluded; "
            "generic unsupported pairs were withheld"
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
        if selection_objective in {
            "discovery_component_overlap_resolution",
            "discovery_near_same_frontier_review",
            "discovery_staged_near_same_frontier_review",
        }:
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
        "selected_observation_fingerprints": {
            "a": observation_a.input_fingerprint,
            "b": observation_b.input_fingerprint,
        },
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
    if goal == SelectionGoal.AUTOMATION_READINESS:
        manifest[
            "automatic_profile_ready_ids_excluded_from_reinforcement"
        ] = sorted(
            automatic_profile_ready_ids
        )
    selected_association = association_confirmation_by_pair.get(
        frozenset(
            (
                observation_a.input_fingerprint,
                observation_b.input_fingerprint,
            )
        )
    )
    if (
        selection_objective
        in {
            "shadow_association_confirmation",
            "machine_assignment_validation",
        }
        and selected_association is not None
    ):
        manifest["shadow_association_confirmation"] = {
            "candidate_fingerprint": (
                selected_association.candidate_fingerprint
            ),
            "exemplar_fingerprint": (
                selected_association.exemplar_fingerprint
            ),
            "profile_id": selected_association.profile_id,
            "same_comparison_count": (
                selected_association.same_comparison_count
            ),
            "report_result_sha256": (
                selected_association.report_result_sha256
            ),
            "report_path": selected_association.report_path,
            "role": "review_nomination_only",
            "identity_evidence": False,
            "provisional_assignment_active": (
                selected_association.provisional_assignment_active
            ),
            "durable_evidence_source": "approved_blinded_pair_review_only",
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
        selection_objective
        in {
            "discovery_component_overlap_resolution",
            "discovery_near_same_frontier_review",
            "discovery_staged_near_same_frontier_review",
        }
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
        if selected_resolution.resolution_kind != "component_overlap":
            manifest["discovery_resolution"]["resolution_kind"] = (
                selected_resolution.resolution_kind
            )
        if selected_resolution.same_boundary_distance is not None:
            manifest["discovery_resolution"]["same_boundary_distance"] = (
                selected_resolution.same_boundary_distance
            )
        if selected_resolution.seed_fingerprints:
            manifest["discovery_resolution"]["seed_fingerprints"] = list(
                selected_resolution.seed_fingerprints
            )
        if selected_resolution.candidate_fingerprint is not None:
            manifest["discovery_resolution"]["candidate_fingerprint"] = (
                selected_resolution.candidate_fingerprint
            )
        if selected_resolution.companion_pair_fingerprints:
            manifest["discovery_resolution"][
                "companion_pair_fingerprints"
            ] = list(selected_resolution.companion_pair_fingerprints)
        if selected_resolution.required_review_count > 1:
            manifest["discovery_resolution"]["required_review_count"] = (
                selected_resolution.required_review_count
            )
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
    selected_acoustic_ranking = profile_growth_acoustic_by_pair.get(
        frozenset(
            (
                observation_a.input_fingerprint,
                observation_b.input_fingerprint,
            )
        )
    )
    if (
        growth_components is not None
        and selected_acoustic_ranking is not None
    ):
        manifest["profile_growth_acoustic_ranking"] = {
            "outcome": selected_acoustic_ranking.outcome,
            "reason": selected_acoustic_ranking.reason,
            "same_boundary_margin": (
                selected_acoustic_ranking.same_boundary_margin
            ),
            "centroid_similarity": (
                selected_acoustic_ranking.centroid_similarity
            ),
            "report_result_sha256": (
                selected_acoustic_ranking.report_result_sha256
            ),
            "report_path": selected_acoustic_ranking.report_path,
            "role": "review_ranking_only",
            "identity_evidence": False,
            "durable_evidence_source": "approved_blinded_pair_review_only",
        }
        reason_codes.insert(
            1,
            (
                "cached_acoustic_same_ranking"
                if selected_acoustic_ranking.outcome == "same_speaker"
                else "cached_acoustic_uncertain_nomination"
            ),
        )
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

    def resolution_for(
        pair: tuple[
            PairCandidateObservation,
            PairCandidateObservation,
            SelectionStratum,
            SourceRelation,
        ],
    ) -> DiscoveryResolutionPair:
        return discovery_resolution_by_pair[
            frozenset(
                (pair[0].input_fingerprint, pair[1].input_fingerprint)
            )
        ]

    selected = min(
        candidates,
        key=lambda pair: (
            _discovery_resolution_priority(resolution_for(pair)),
            resolution_for(pair).same_boundary_distance
            if resolution_for(pair).same_boundary_distance is not None
            else float("inf"),
            -resolution_for(pair).observations_unlocked,
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
        (
            "discovery_near_same_frontier_review"
            if resolution_for(selected).resolution_kind
            == "near_same_ambiguous_frontier"
            else "discovery_staged_near_same_frontier_review"
            if resolution_for(selected).resolution_kind
            == "staged_near_same_ambiguous_frontier"
            else "discovery_component_overlap_resolution"
        ),
        (frozenset(), frozenset()),
    )


def _discovery_resolution_priority(
    resolution: DiscoveryResolutionPair,
) -> int:
    return {
        "near_same_ambiguous_frontier": 0,
        "staged_near_same_ambiguous_frontier": 1,
        "component_overlap": 2,
    }.get(resolution.resolution_kind, 3)


def _select_association_confirmation_pair(
    pairs: Sequence[
        tuple[
            PairCandidateObservation,
            PairCandidateObservation,
            SelectionStratum,
            SourceRelation,
        ]
    ],
    *,
    association_confirmation_by_pair: Mapping[
        frozenset[str], AssociationConfirmationPair
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
    eligible = []
    for pair in pairs:
        observation_a, observation_b, _stratum, _relation = pair
        nomination = association_confirmation_by_pair.get(
            frozenset(
                (
                    observation_a.input_fingerprint,
                    observation_b.input_fingerprint,
                )
            )
        )
        if nomination is None:
            continue
        candidate = (
            observation_a
            if observation_a.input_fingerprint
            == nomination.candidate_fingerprint
            else observation_b
        )
        exemplar = (
            observation_a
            if observation_a.input_fingerprint
            == nomination.exemplar_fingerprint
            else observation_b
        )
        if (
            candidate.input_fingerprint
            != nomination.candidate_fingerprint
            or exemplar.input_fingerprint
            != nomination.exemplar_fingerprint
            or candidate.reviewed_profile_ids
            or nomination.profile_id not in exemplar.reviewed_profile_ids
            or disfavored.get(candidate.input_fingerprint, 0)
            or disfavored.get(exemplar.input_fingerprint, 0)
        ):
            continue
        eligible.append((pair, nomination))
    if not eligible:
        return None
    pair, selected_nomination = min(
        eligible,
        key=lambda item: (
            0 if item[1].provisional_assignment_active else 1,
            -item[1].same_comparison_count,
            -item[1].same_boundary_margin,
            _rank_pair(
                item[0][0],
                item[0][1],
                source_family_use,
                observation_use,
                source_use,
                disfavored,
                disfavored_sources,
                condition_counts,
            ),
            item[1].report_result_sha256,
        ),
    )
    observation_a, observation_b, stratum, relation = pair
    return (
        observation_a,
        observation_b,
        stratum,
        relation,
        (
            "machine_assignment_validation"
            if selected_nomination.provisional_assignment_active
            else "shadow_association_confirmation"
        ),
        (
            frozenset((observation_a.input_fingerprint,)),
            frozenset((observation_b.input_fingerprint,)),
        ),
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
    acoustic_ranking_by_pair: Mapping[
        frozenset[str], AcousticPairRanking
    ],
    automatic_profile_ready_ids: frozenset[int],
    allow_exploratory: bool,
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
    component_attributions = {
        component: frozenset(
            attribution
            for fingerprint in component
            for attribution in candidate_by_fingerprint[
                fingerprint
            ].explicit_attributions
        )
        for component in set(components.values())
    }
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
    exploratory_pairs: list[
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
        pair_key = frozenset(
            (
                observation_a.input_fingerprint,
                observation_b.input_fingerprint,
            )
        )
        acoustic_ranking = acoustic_ranking_by_pair.get(pair_key)
        has_acoustic_same_signal = (
            acoustic_ranking is not None
            and acoustic_ranking.outcome == "same_speaker"
        )
        has_acoustic_exploration_signal = (
            allow_exploratory
            and acoustic_ranking is not None
            and acoustic_ranking.outcome == "insufficient_evidence"
        )
        has_component_attribution_overlap = bool(
            component_attributions[component_a]
            & component_attributions[component_b]
        )
        # Profile growth is a positive-evidence workflow. The absence of a
        # known difference is not evidence that two voices may match.
        if not (
            has_acoustic_same_signal
            or has_component_attribution_overlap
            or has_acoustic_exploration_signal
        ):
            continue
        # Conflicting claims need direct acoustic support before spending a
        # blinded review on reconciliation. Attribution remains a nomination
        # hint and never becomes identity truth.
        if (
            stratum == SelectionStratum.CONTRADICTING_ATTRIBUTION
            and not has_acoustic_same_signal
        ):
            continue
        anchored_a = component_a in anchored_components
        anchored_b = component_b in anchored_components
        touches_automatic_ready_profile = any(
            candidate_by_fingerprint[fingerprint].reviewed_profile_ids
            & automatic_profile_ready_ids
            for fingerprint in component_a | component_b
        )
        if (
            touches_automatic_ready_profile
            and not has_acoustic_same_signal
            and not (
                anchored_a
                and anchored_b
                and has_component_attribution_overlap
            )
        ):
            continue
        if anchored_a != anchored_b:
            objective = "profile_growth_frontier"
        elif anchored_a:
            objective = (
                "attribution_reconciliation_bridge"
                if has_component_attribution_overlap
                and stratum != SelectionStratum.CONTRADICTING_ATTRIBUTION
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
        selected_pair = (
            observation_a,
            observation_b,
            stratum,
            relation,
            objective,
            (component_a, component_b),
        )
        if has_acoustic_exploration_signal and not (
            has_acoustic_same_signal or has_component_attribution_overlap
        ):
            exploratory_pairs.append(
                (
                    *selected_pair[:4],
                    "profile_growth_exploratory_frontier"
                    if anchored_a or anchored_b
                    else "profile_growth_exploratory_seed",
                    selected_pair[5],
                )
            )
        else:
            growth_pairs.append(selected_pair)
    selectable_pairs = growth_pairs or exploratory_pairs
    if not selectable_pairs:
        return None
    stratum_rank = {
        SelectionStratum.SHARED_ATTRIBUTION: 0,
        SelectionStratum.PARTIAL_ATTRIBUTION: 1,
        SelectionStratum.UNATTRIBUTED: 2,
        SelectionStratum.CONTRADICTING_ATTRIBUTION: 3,
    }
    return min(
        selectable_pairs,
        key=lambda item: (
            *_profile_growth_acoustic_rank(
                item[0], item[1], acoustic_ranking_by_pair
            ),
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


def _profile_growth_acoustic_rank(
    observation_a: PairCandidateObservation,
    observation_b: PairCandidateObservation,
    ranking_by_pair: Mapping[frozenset[str], AcousticPairRanking],
) -> tuple[int, float, float]:
    ranking = ranking_by_pair.get(
        frozenset(
            (observation_a.input_fingerprint, observation_b.input_fingerprint)
        )
    )
    if ranking is None:
        return 1, 0.0, 0.0
    return 0, -ranking.same_boundary_margin, -ranking.centroid_similarity


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
    automatic_profile_ready_ids: frozenset[int],
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
        and profile_id not in automatic_profile_ready_ids
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
