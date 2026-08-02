from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from pastor_transcript_extractor.speaker_registry import (
    attach_reviewed_observation,
    create_anonymous_profile,
    normalize_person_name,
    record_name_claim_review,
    record_observation_difference,
    record_observation_disposition,
    record_observation_review,
    record_profile_redirect,
)
from pastor_transcript_extractor.speaker_review_invalidation import (
    filter_active_pair_artifacts,
    load_review_revocations,
)
from pastor_transcript_extractor.storage import Database


REVIEWED_EVIDENCE_SYNC_VERSION = "reviewed_speaker_evidence_sync_v1"
ATTRIBUTION_RECONCILIATION_VERSION = "reviewed_profile_attribution_sync_v1"
_DERIVED_QUALIFICATION_REASON_PREFIX = (
    "Derived from consistent speaker-pair qualification review(s): "
)
_DERIVED_MEMBERSHIP_REASON_PREFIX = "Confirmed same-speaker pair review "
_QUALIFICATION_ACTIONS = {
    "qualified_single_speaker": "qualified_single_speaker",
    "multiple_speakers": "multiple_speakers",
    "invalid_audio": "invalid",
    "cannot_determine": "unresolved",
}
_PAIR_OUTCOMES = {"same_speaker", "different_speaker"}
_MERGEABLE_PROFILE_REASONS = {
    "reviewed_anonymous_speaker",
    "shadow_discovery_candidate",
}


@dataclass(frozen=True, slots=True)
class ReviewProvenance:
    review_event_id: str
    pair_id: str
    reviewer: str


@dataclass(frozen=True, slots=True)
class ObservationQualification:
    action: str
    provenance: tuple[ReviewProvenance, ...]


@dataclass(frozen=True, slots=True)
class PairRelation:
    fingerprints: frozenset[str]
    outcome: str
    provenance: tuple[ReviewProvenance, ...]


@dataclass(frozen=True, slots=True)
class ReviewedSpeakerEvidence:
    qualifications: Mapping[str, ObservationQualification]
    qualification_conflicts: Mapping[str, tuple[str, ...]]
    pair_relations: Mapping[frozenset[str], PairRelation]
    pair_conflicts: Mapping[frozenset[str], tuple[str, ...]]
    review_event_count: int

    def same_components(self) -> tuple[frozenset[str], ...]:
        adjacency: dict[str, set[str]] = {}
        for relation in self.pair_relations.values():
            if relation.outcome != "same_speaker":
                continue
            fingerprint_a, fingerprint_b = tuple(relation.fingerprints)
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
        return tuple(sorted(components, key=lambda item: tuple(sorted(item))))


@dataclass(frozen=True, slots=True)
class ReviewedEvidenceSyncResult:
    qualification_events_added: int
    difference_events_added: int
    profiles_added: int
    membership_events_added: int
    name_claim_events_added: int
    profile_redirect_events_added: int
    missing_observations: tuple[str, ...]
    merge_candidates: tuple[str, ...]
    conflicts: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _QualificationRecord:
    fingerprint: str
    action: str
    provenance: ReviewProvenance


@dataclass(frozen=True, slots=True)
class _PairRecord:
    fingerprints: frozenset[str]
    outcome: str
    provenance: ReviewProvenance


@dataclass(frozen=True, slots=True)
class _ProfileAttributionCandidate:
    profile_id: int
    normalized_name: str
    claim_ids: tuple[int, ...]
    provenance: ReviewProvenance


def qualification_conflict_requires_adjudication(
    database: Database,
    evidence: ReviewedSpeakerEvidence,
    *,
    observation_id: int,
    observation_fingerprint: str,
) -> bool:
    if observation_fingerprint not in evidence.qualification_conflicts:
        return False
    effective = database.get_effective_observation_review_event(observation_id)
    if effective is None:
        return True
    reason = effective[2]
    return (
        reason.startswith(_DERIVED_QUALIFICATION_REASON_PREFIX)
        or reason.startswith(_DERIVED_MEMBERSHIP_REASON_PREFIX)
    )


def load_reviewed_speaker_evidence(evaluation_root: Path) -> ReviewedSpeakerEvidence:
    root = evaluation_root.expanduser().resolve()
    revocations = load_review_revocations(root)
    drafts = filter_active_pair_artifacts(
        _load_objects(sorted((root / "drafts").glob("*.json"))), revocations
    )
    reviews = filter_active_pair_artifacts(
        _load_objects(sorted((root / "reviews").glob("*/*.json"))), revocations
    )
    fixtures = filter_active_pair_artifacts(
        _load_objects(sorted((root / "fixtures").glob("*.json"))), revocations
    )
    drafts_by_pair = {
        str(draft["pair_id"]): draft
        for draft in drafts
        if draft.get("review_status") == "draft" and draft.get("pair_id")
    }
    qualification_records: list[_QualificationRecord] = []
    pair_records: list[_PairRecord] = []
    consumed_event_ids: set[str] = set()

    for review in reviews:
        if review.get("event_kind") != "speaker_pair_human_review":
            continue
        pair_id = str(review.get("pair_id", ""))
        draft = drafts_by_pair.get(pair_id)
        if draft is None or review.get("draft_id") != draft.get("draft_id"):
            continue
        label_fingerprints = _draft_label_fingerprints(draft)
        provenance = _provenance(review, pair_id)
        consumed_event_ids.add(provenance.review_event_id)
        _add_qualification_records(
            qualification_records,
            qualifications=review.get("qualification"),
            label_fingerprints=label_fingerprints,
            provenance=provenance,
        )
        identity_evidence_eligible = review.get(
            "identity_evidence_eligible"
        )
        if identity_evidence_eligible is None:
            # Reviews written before evidence-mode separation used fixture
            # eligibility for both acoustic evaluation and identity replay.
            identity_evidence_eligible = (
                review.get("approval_confirmed") is True
                and review.get("fixture_eligible") is True
            )
        if (
            identity_evidence_eligible is True
            and review.get("pair_judgment") in _PAIR_OUTCOMES
            and len(set(label_fingerprints.values())) == 2
        ):
            pair_records.append(
                _PairRecord(
                    fingerprints=frozenset(label_fingerprints.values()),
                    outcome=str(review["pair_judgment"]),
                    provenance=provenance,
                )
            )

    for fixture in fixtures:
        event_id = str(fixture.get("review_event_id", ""))
        if (
            fixture.get("review_status") != "approved"
            or not event_id
            or event_id in consumed_event_ids
        ):
            continue
        observations = fixture.get("observations")
        if not isinstance(observations, dict):
            continue
        label_fingerprints = {
            "A": str(observations.get("a", {}).get("input_fingerprint", "")),
            "B": str(observations.get("b", {}).get("input_fingerprint", "")),
        }
        if not all(label_fingerprints.values()):
            continue
        pair_id = str(fixture.get("pair_id", ""))
        provenance = _provenance(fixture, pair_id)
        consumed_event_ids.add(provenance.review_event_id)
        _add_qualification_records(
            qualification_records,
            qualifications=fixture.get("qualification"),
            label_fingerprints=label_fingerprints,
            provenance=provenance,
        )
        if fixture.get("expected_outcome") in _PAIR_OUTCOMES:
            pair_records.append(
                _PairRecord(
                    fingerprints=frozenset(label_fingerprints.values()),
                    outcome=str(fixture["expected_outcome"]),
                    provenance=provenance,
                )
            )

    qualifications, qualification_conflicts = _derive_qualifications(
        qualification_records
    )
    pair_relations, pair_conflicts = _derive_pair_relations(pair_records)
    return ReviewedSpeakerEvidence(
        qualifications=qualifications,
        qualification_conflicts=qualification_conflicts,
        pair_relations=pair_relations,
        pair_conflicts=pair_conflicts,
        review_event_count=len(consumed_event_ids),
    )


def sync_reviewed_speaker_evidence(
    database: Database,
    evidence: ReviewedSpeakerEvidence,
) -> ReviewedEvidenceSyncResult:
    before = _event_counts(database)
    missing: set[str] = set()
    merge_candidates: list[str] = []
    conflicts = [
        f"qualification conflict for {fingerprint}: {', '.join(actions)}"
        for fingerprint, actions in sorted(evidence.qualification_conflicts.items())
    ]
    conflicts.extend(
        "pair conflict for "
        + ", ".join(sorted(pair))
        + ": "
        + ", ".join(outcomes)
        for pair, outcomes in sorted(
            evidence.pair_conflicts.items(), key=lambda item: tuple(sorted(item[0]))
        )
    )
    observations = {}
    all_fingerprints = set(evidence.qualifications)
    for pair in evidence.pair_relations:
        all_fingerprints.update(pair)
    for fingerprint in sorted(all_fingerprints):
        observation = database.get_speaker_observation_by_fingerprint(fingerprint)
        if observation is None:
            missing.add(fingerprint)
        else:
            observations[fingerprint] = observation

    for fingerprint, qualification in sorted(evidence.qualifications.items()):
        observation = observations.get(fingerprint)
        if observation is None:
            continue
        effective_event = database.get_effective_observation_review_event(
            observation.id
        )
        if (
            effective_event is not None
            and not effective_event[2].startswith(
                _DERIVED_QUALIFICATION_REASON_PREFIX
            )
        ):
            continue
        provenance = qualification.provenance[0]
        aggregate_key = _sha256(
            [
                item.review_event_id
                for item in qualification.provenance
            ]
        )
        record_observation_disposition(
            database,
            observation_id=observation.id,
            action=qualification.action,
            reviewer=provenance.reviewer,
            reason=(
                _DERIVED_QUALIFICATION_REASON_PREFIX
                + ", ".join(item.review_event_id for item in qualification.provenance)
            ),
            review_event_key=(
                f"{REVIEWED_EVIDENCE_SYNC_VERSION}:qualification:"
                f"{fingerprint}:{aggregate_key}"
            ),
        )

    for pair, relation in sorted(
        evidence.pair_relations.items(), key=lambda item: tuple(sorted(item[0]))
    ):
        if relation.outcome != "different_speaker":
            continue
        fingerprint_a, fingerprint_b = sorted(pair)
        observation_a = observations.get(fingerprint_a)
        observation_b = observations.get(fingerprint_b)
        if observation_a is None or observation_b is None:
            continue
        blocked_fingerprints = [
            fingerprint
            for fingerprint, observation in (
                (fingerprint_a, observation_a),
                (fingerprint_b, observation_b),
            )
            if (
                database.get_effective_observation_review_action(observation.id)
                != "qualified_single_speaker"
                or qualification_conflict_requires_adjudication(
                    database,
                    evidence,
                    observation_id=observation.id,
                    observation_fingerprint=fingerprint,
                )
            )
        ]
        if blocked_fingerprints:
            conflicts.append(
                "different pair lacks effective reviewed single-speaker "
                "qualification: "
                + ", ".join(sorted(blocked_fingerprints))
            )
            continue
        provenance = relation.provenance[0]
        try:
            record_observation_difference(
                database,
                observation_a_id=observation_a.id,
                observation_b_id=observation_b.id,
                different=True,
                reviewer=provenance.reviewer,
                reason=(
                    "Confirmed different-speaker pair review "
                    f"{provenance.review_event_id}"
                ),
                review_event_key=(
                    f"{REVIEWED_EVIDENCE_SYNC_VERSION}:different:"
                    f"{provenance.review_event_id}"
                ),
            )
        except ValueError as error:
            conflicts.append(
                f"different pair {fingerprint_a}, {fingerprint_b}: {error}"
            )

    different_pairs = {
        pair
        for pair, relation in evidence.pair_relations.items()
        if relation.outcome == "different_speaker"
    }
    attribution_candidates: list[_ProfileAttributionCandidate] = []
    for component in evidence.same_components():
        qualification_conflicts = {
            fingerprint
            for fingerprint in component.intersection(
                evidence.qualification_conflicts
            )
            if (
                fingerprint not in observations
                or qualification_conflict_requires_adjudication(
                    database,
                    evidence,
                    observation_id=observations[fingerprint].id,
                    observation_fingerprint=fingerprint,
                )
            )
        }
        if qualification_conflicts:
            conflicts.append(
                "same component contains qualification conflict: "
                + ", ".join(sorted(qualification_conflicts))
            )
            continue
        internal_differences = [
            pair for pair in different_pairs if pair.issubset(component)
        ]
        if internal_differences:
            conflicts.append(
                "same component contains explicit different constraint: "
                + ", ".join(sorted(component))
            )
            continue
        component_observations = [
            observations[fingerprint]
            for fingerprint in sorted(component)
            if fingerprint in observations
        ]
        if len(component_observations) != len(component):
            continue
        unqualified = [
            observation.input_fingerprint
            for observation in component_observations
            if database.get_effective_observation_review_action(observation.id)
            != "qualified_single_speaker"
        ]
        if unqualified:
            conflicts.append(
                "same component contains observation without effective "
                "single-speaker qualification: "
                + ", ".join(sorted(unqualified))
            )
            continue
        profile_ids = {
            profile_id
            for observation in component_observations
            for profile_id in database.list_effective_profile_ids_for_observation(
                observation.id
            )
        }
        component_relations = [
            relation
            for pair, relation in evidence.pair_relations.items()
            if relation.outcome == "same_speaker" and pair.issubset(component)
        ]
        canonical = min(
            (
                provenance
                for relation in component_relations
                for provenance in relation.provenance
            ),
            key=lambda item: item.review_event_id,
        )
        component_key = _sha256(sorted(component))
        if len(profile_ids) > 1:
            profile_id = _merge_reviewed_component_profiles(
                database,
                profile_ids=profile_ids,
                provenance=canonical,
                component_key=component_key,
                conflicts=conflicts,
            )
            if profile_id is None:
                continue
        elif profile_ids:
            profile_id = next(iter(profile_ids))
        else:
            profile = create_anonymous_profile(
                database,
                reviewer=canonical.reviewer,
                reason=(
                    "Created from confirmed same-speaker review component "
                    + ", ".join(sorted(component))
                ),
                review_event_key=(
                    f"{REVIEWED_EVIDENCE_SYNC_VERSION}:profile:{component_key}"
                ),
            )
            profile_id = profile.id
        for observation in component_observations:
            if profile_id in database.list_effective_profile_ids_for_observation(
                observation.id
            ):
                continue
            incident = min(
                (
                    provenance
                    for pair, relation in evidence.pair_relations.items()
                    if relation.outcome == "same_speaker"
                    and observation.input_fingerprint in pair
                    and pair.issubset(component)
                    for provenance in relation.provenance
                ),
                key=lambda item: item.review_event_id,
            )
            try:
                attach_reviewed_observation(
                    database,
                    profile_id=profile_id,
                    observation_id=observation.id,
                    reviewer=incident.reviewer,
                    reason=(
                        "Confirmed same-speaker pair review "
                        f"{incident.review_event_id}"
                    ),
                    review_event_key=(
                        f"{REVIEWED_EVIDENCE_SYNC_VERSION}:membership:"
                        f"{incident.review_event_id}:{observation.input_fingerprint}"
                    ),
                )
            except ValueError as error:
                conflicts.append(
                    f"component membership {observation.input_fingerprint}: {error}"
                )
        profile_observations = [
            observation
            for observation_id in (
                database.list_effective_observation_ids_for_profile(profile_id)
            )
            if (
                observation := database.get_speaker_observation(
                    observation_id
                )
            )
            is not None
        ]
        explicit_claims = []
        for observation in profile_observations:
            explicit_claims.extend(
                claim
                for claim in database.list_speaker_name_claims_for_video(
                    observation.video_id
                )
                if (
                    claim.observation_id == observation.id
                    and claim.explicit_speaker_attribution
                    and claim.normalized_name.strip()
                )
            )
        normalized_names = {
            claim.normalized_name.strip() for claim in explicit_claims
        }
        if len(normalized_names) > 1:
            conflicts.append(
                f"profile {profile_id} has conflicting explicit attributions: "
                + ", ".join(sorted(normalized_names))
            )
        elif len(normalized_names) == 1:
            attribution_candidates.append(
                _ProfileAttributionCandidate(
                    profile_id=profile_id,
                    normalized_name=next(iter(normalized_names)),
                    claim_ids=tuple(
                        sorted({claim.id for claim in explicit_claims})
                    ),
                    provenance=canonical,
                )
            )

    _reconcile_profile_attributions(
        database,
        candidates=attribution_candidates,
        merge_candidates=merge_candidates,
        conflicts=conflicts,
    )

    after = _event_counts(database)
    return ReviewedEvidenceSyncResult(
        qualification_events_added=(
            after["speaker_observation_review_events"]
            - before["speaker_observation_review_events"]
        ),
        difference_events_added=(
            after["speaker_observation_difference_events"]
            - before["speaker_observation_difference_events"]
        ),
        profiles_added=after["speaker_profiles"] - before["speaker_profiles"],
        membership_events_added=(
            after["profile_observation_events"]
            - before["profile_observation_events"]
        ),
        name_claim_events_added=(
            after["profile_name_claim_events"]
            - before["profile_name_claim_events"]
        ),
        profile_redirect_events_added=(
            after["speaker_profile_redirect_events"]
            - before["speaker_profile_redirect_events"]
        ),
        missing_observations=tuple(sorted(missing)),
        merge_candidates=tuple(sorted(set(merge_candidates))),
        conflicts=tuple(sorted(set(conflicts))),
    )


def _merge_reviewed_component_profiles(
    database: Database,
    *,
    profile_ids: set[int],
    provenance: ReviewProvenance,
    component_key: str,
    conflicts: list[str],
) -> int | None:
    ordered_profile_ids = sorted(profile_ids)
    profiles_by_id = {
        profile_id: database.get_speaker_profile(profile_id)
        for profile_id in ordered_profile_ids
    }
    if any(
        profile is None
        or profile.created_reason not in _MERGEABLE_PROFILE_REASONS
        for profile in profiles_by_id.values()
    ):
        conflicts.append(
            "same component spans profiles that are not all reviewed or "
            "provisional discovery profiles: "
            + ", ".join(str(profile_id) for profile_id in ordered_profile_ids)
        )
        return None
    linked_profile_ids = {
        resolved_profile_id
        for pastor in database.list_pastors()
        if (
            bound_profile_id := database.get_pastor_speaker_profile_id(
                pastor.id
            )
        )
        is not None
        and (
            resolved_profile_id := database.resolve_speaker_profile_id(
                bound_profile_id
            )
        )
        in profile_ids
    }
    if len(linked_profile_ids) > 1:
        conflicts.append(
            "same component spans multiple configured pastor identities: "
            + ", ".join(
                str(profile_id) for profile_id in sorted(linked_profile_ids)
            )
        )
        return None
    reviewed_profile_ids = {
        profile_id
        for profile_id, profile in profiles_by_id.items()
        if profile is not None
        and profile.created_reason == "reviewed_anonymous_speaker"
    }
    canonical_profile_id = (
        next(iter(linked_profile_ids))
        if linked_profile_ids
        else min(reviewed_profile_ids)
        if reviewed_profile_ids
        else ordered_profile_ids[0]
    )
    retired_profile_ids = [
        profile_id
        for profile_id in ordered_profile_ids
        if profile_id != canonical_profile_id
    ]
    if database.get_effective_profile_redirect(canonical_profile_id) is not None:
        conflicts.append(
            f"canonical speaker profile {canonical_profile_id} already "
            "has an effective redirect"
        )
        return None
    for profile_id in retired_profile_ids:
        redirected = database.get_effective_profile_redirect(profile_id)
        if (
            redirected is not None
            and database.resolve_speaker_profile_id(profile_id)
            != canonical_profile_id
        ):
            conflicts.append(
                f"reviewed profile {profile_id} has incompatible redirect "
                f"to profile {redirected}"
            )
            return None

    members_by_profile = {
        profile_id: database.list_effective_observation_ids_for_profile(
            profile_id
        )
        for profile_id in ordered_profile_ids
    }
    different_pairs = set(database.list_effective_observation_difference_pairs())
    member_owner = {
        member_id: profile_id
        for profile_id, member_ids in members_by_profile.items()
        for member_id in member_ids
    }
    cross_profile_differences = [
        pair
        for pair in different_pairs
        if (
            pair[0] in member_owner
            and pair[1] in member_owner
            and member_owner[pair[0]] != member_owner[pair[1]]
        )
    ]
    if cross_profile_differences:
        conflicts.append(
            "reviewed profile merge is blocked by different-speaker "
            "constraint(s): "
            + ", ".join(
                f"{observation_a_id}-{observation_b_id}"
                for observation_a_id, observation_b_id in (
                    cross_profile_differences
                )
            )
        )
        return None

    reason = (
        "Merged reviewed speaker profiles through confirmed same-speaker "
        f"component {component_key}"
    )
    for profile_id in retired_profile_ids:
        for observation_id in members_by_profile[profile_id]:
            record_observation_review(
                database,
                profile_id=profile_id,
                observation_id=observation_id,
                attach=False,
                reviewer=provenance.reviewer,
                reason=reason,
                review_event_key=(
                    f"{REVIEWED_EVIDENCE_SYNC_VERSION}:merge-detach:"
                    f"{component_key}:{profile_id}:{observation_id}"
                ),
            )
            if not database.is_observation_attached(
                canonical_profile_id,
                observation_id,
            ):
                attach_reviewed_observation(
                    database,
                    profile_id=canonical_profile_id,
                    observation_id=observation_id,
                    reviewer=provenance.reviewer,
                    reason=reason,
                    review_event_key=(
                        f"{REVIEWED_EVIDENCE_SYNC_VERSION}:merge-attach:"
                        f"{component_key}:{canonical_profile_id}:"
                        f"{observation_id}"
                    ),
                )
        if database.get_effective_profile_redirect(profile_id) is None:
            record_profile_redirect(
                database,
                from_profile_id=profile_id,
                to_profile_id=canonical_profile_id,
                reviewer=provenance.reviewer,
                reason=reason,
                review_event_key=(
                    f"{REVIEWED_EVIDENCE_SYNC_VERSION}:merge-redirect:"
                    f"{component_key}:{profile_id}:"
                    f"{canonical_profile_id}"
                ),
            )
    return canonical_profile_id


def _reconcile_profile_attributions(
    database: Database,
    *,
    candidates: Sequence[_ProfileAttributionCandidate],
    merge_candidates: list[str],
    conflicts: list[str],
) -> None:
    candidates_by_name: dict[str, list[_ProfileAttributionCandidate]] = {}
    for candidate in candidates:
        candidates_by_name.setdefault(candidate.normalized_name, []).append(
            candidate
        )

    configured_by_name: dict[str, list[int]] = {}
    for pastor in database.list_pastors():
        profile_id = database.get_pastor_speaker_profile_id(pastor.id)
        if profile_id is None:
            continue
        normalized_name = normalize_person_name(pastor.display_name)
        if normalized_name:
            configured_by_name.setdefault(normalized_name, []).append(
                profile_id
            )

    for normalized_name, named_candidates in sorted(
        candidates_by_name.items()
    ):
        profile_ids = sorted(
            {candidate.profile_id for candidate in named_candidates}
        )
        if len(profile_ids) > 1:
            members_by_profile = {
                profile_id: (
                    database.list_effective_observation_ids_for_profile(
                        profile_id
                    )
                )
                for profile_id in profile_ids
            }
            different_pairs = set(
                database.list_effective_observation_difference_pairs()
            )
            blocked = any(
                tuple(sorted((member_a, member_b))) in different_pairs
                for index, profile_a in enumerate(profile_ids)
                for profile_b in profile_ids[index + 1 :]
                for member_a in members_by_profile[profile_a]
                for member_b in members_by_profile[profile_b]
            )
            message = (
                f"explicit attribution {normalized_name!r} spans reviewed "
                "profiles "
                + ", ".join(str(profile_id) for profile_id in profile_ids)
            )
            if blocked:
                conflicts.append(
                    message
                    + " with an effective different-speaker constraint"
                )
            else:
                merge_candidates.append(message)
            continue
        candidate = named_candidates[0]
        conflicting_claim_reviews = []
        for claim_id in candidate.claim_ids:
            effective = database.get_effective_name_claim_review(claim_id)
            if effective is None:
                continue
            action, attached_profile_id = effective
            if (
                action == "attach"
                and attached_profile_id is not None
                and database.resolve_speaker_profile_id(attached_profile_id)
                == candidate.profile_id
            ):
                continue
            conflicting_claim_reviews.append((claim_id, effective))
        if conflicting_claim_reviews:
            conflicts.append(
                f"profile {candidate.profile_id} attribution "
                f"{normalized_name!r} conflicts with effective claim review(s): "
                + ", ".join(
                    f"{claim_id}:{action}:{profile_id}"
                    for claim_id, (action, profile_id) in conflicting_claim_reviews
                )
            )
            continue

        for claim_id in candidate.claim_ids:
            effective = database.get_effective_name_claim_review(claim_id)
            if effective == ("attach", candidate.profile_id):
                continue
            record_name_claim_review(
                database,
                claim_id=claim_id,
                profile_id=candidate.profile_id,
                attach=True,
                reviewer=candidate.provenance.reviewer,
                reason=(
                    "Consistent explicit attribution across reviewed "
                    f"same-speaker component: {normalized_name}"
                ),
                review_event_key=(
                    f"{ATTRIBUTION_RECONCILIATION_VERSION}:claim:"
                    f"{claim_id}:profile:{candidate.profile_id}"
                ),
            )

        configured_profile_ids = sorted(
            set(configured_by_name.get(normalized_name, ()))
        )
        if not configured_profile_ids:
            continue
        if len(configured_profile_ids) > 1:
            conflicts.append(
                f"explicit attribution {normalized_name!r} matches multiple "
                "configured pastor profiles "
                + ", ".join(
                    str(profile_id)
                    for profile_id in configured_profile_ids
                )
            )
            continue
        configured_profile_id = configured_profile_ids[0]
        if database.list_effective_observation_ids_for_profile(
            configured_profile_id
        ):
            conflicts.append(
                f"configured profile {configured_profile_id} for "
                f"{normalized_name!r} already has direct observation membership"
            )
            continue
        anonymous_redirect = database.get_effective_profile_redirect(
            candidate.profile_id
        )
        if anonymous_redirect is not None:
            conflicts.append(
                f"reviewed profile {candidate.profile_id} for "
                f"{normalized_name!r} already redirects to profile "
                f"{anonymous_redirect}"
            )
            continue
        configured_redirect = database.get_effective_profile_redirect(
            configured_profile_id
        )
        if configured_redirect is not None:
            if (
                database.resolve_speaker_profile_id(configured_profile_id)
                == candidate.profile_id
            ):
                continue
            conflicts.append(
                f"configured profile {configured_profile_id} for "
                f"{normalized_name!r} already redirects to profile "
                f"{configured_redirect}"
            )
            continue
        record_profile_redirect(
            database,
            from_profile_id=configured_profile_id,
            to_profile_id=candidate.profile_id,
            reviewer=candidate.provenance.reviewer,
            reason=(
                "Configured identity reconciled from consistent explicit "
                f"attribution across reviewed voice component: {normalized_name}"
            ),
            review_event_key=(
                f"{ATTRIBUTION_RECONCILIATION_VERSION}:configured:"
                f"{configured_profile_id}:reviewed:{candidate.profile_id}"
            ),
        )


def _derive_qualifications(
    records: Sequence[_QualificationRecord],
) -> tuple[
    dict[str, ObservationQualification],
    dict[str, tuple[str, ...]],
]:
    by_fingerprint: dict[str, list[_QualificationRecord]] = {}
    for record in records:
        by_fingerprint.setdefault(record.fingerprint, []).append(record)
    qualifications: dict[str, ObservationQualification] = {}
    conflicts: dict[str, tuple[str, ...]] = {}
    for fingerprint, grouped in sorted(by_fingerprint.items()):
        decisive = {
            record.action for record in grouped if record.action != "unresolved"
        }
        if len(decisive) > 1:
            conflicts[fingerprint] = tuple(sorted(decisive))
            continue
        action = next(iter(decisive), "unresolved")
        supporting = [
            record.provenance
            for record in grouped
            if record.action == action
        ]
        qualifications[fingerprint] = ObservationQualification(
            action=action,
            provenance=tuple(
                sorted(
                    {item.review_event_id: item for item in supporting}.values(),
                    key=lambda item: item.review_event_id,
                )
            ),
        )
    return qualifications, conflicts


def _derive_pair_relations(
    records: Sequence[_PairRecord],
) -> tuple[
    dict[frozenset[str], PairRelation],
    dict[frozenset[str], tuple[str, ...]],
]:
    by_pair: dict[frozenset[str], list[_PairRecord]] = {}
    for record in records:
        if len(record.fingerprints) == 2:
            by_pair.setdefault(record.fingerprints, []).append(record)
    relations: dict[frozenset[str], PairRelation] = {}
    conflicts: dict[frozenset[str], tuple[str, ...]] = {}
    for pair, grouped in sorted(
        by_pair.items(), key=lambda item: tuple(sorted(item[0]))
    ):
        outcomes = {record.outcome for record in grouped}
        if len(outcomes) > 1:
            conflicts[pair] = tuple(sorted(outcomes))
            continue
        outcome = next(iter(outcomes))
        relations[pair] = PairRelation(
            fingerprints=pair,
            outcome=outcome,
            provenance=tuple(
                sorted(
                    {
                        record.provenance.review_event_id: record.provenance
                        for record in grouped
                    }.values(),
                    key=lambda item: item.review_event_id,
                )
            ),
        )
    return relations, conflicts


def _draft_label_fingerprints(draft: Mapping[str, Any]) -> dict[str, str]:
    presentation = draft.get("presentation")
    observations = draft.get("observations")
    if not isinstance(presentation, dict) or not isinstance(observations, dict):
        return {}
    result: dict[str, str] = {}
    for label in ("A", "B"):
        side = presentation.get(label)
        if not isinstance(side, dict):
            continue
        source = observations.get(side.get("source_key"))
        if isinstance(source, dict) and source.get("input_fingerprint"):
            result[label] = str(source["input_fingerprint"])
    return result


def _add_qualification_records(
    records: list[_QualificationRecord],
    *,
    qualifications: object,
    label_fingerprints: Mapping[str, str],
    provenance: ReviewProvenance,
) -> None:
    if not isinstance(qualifications, dict):
        return
    for label in ("A", "B"):
        action = _QUALIFICATION_ACTIONS.get(str(qualifications.get(label, "")))
        fingerprint = label_fingerprints.get(label)
        if action and fingerprint:
            records.append(
                _QualificationRecord(fingerprint, action, provenance)
            )


def _provenance(payload: Mapping[str, Any], pair_id: str) -> ReviewProvenance:
    event_id = str(payload.get("review_event_id", "")).strip()
    reviewer = str(payload.get("reviewer", "")).strip()
    if not event_id or not pair_id or not reviewer:
        raise ValueError("review evidence requires event id, pair id, and reviewer")
    return ReviewProvenance(event_id, pair_id, reviewer)


def _load_objects(paths: Sequence[Path]) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            payloads.append(payload)
    return payloads


def _event_counts(database: Database) -> dict[str, int]:
    tables = (
        "speaker_profiles",
        "speaker_observation_review_events",
        "speaker_observation_difference_events",
        "profile_observation_events",
        "profile_name_claim_events",
        "speaker_profile_redirect_events",
    )
    with database.connect() as connection:
        return {
            table: int(
                connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            )
            for table in tables
        }


def _sha256(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
