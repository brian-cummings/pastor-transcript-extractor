from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Mapping

from pastor_transcript_extractor.reviewed_speaker_evidence import (
    ReviewedSpeakerEvidence,
)
from pastor_transcript_extractor.speaker_registry import normalize_person_name
from pastor_transcript_extractor.storage import Database


REVIEWED_PROFILE_REASON = "reviewed_anonymous_speaker"


@dataclass(frozen=True, slots=True)
class ProfileStatus:
    profile_id: int
    member_count: int
    recording_count: int
    source_count: int
    names: tuple[str, ...]
    configured_identities: tuple[str, ...]
    attributed_frontier_count: int
    state: str
    next_need: str


@dataclass(frozen=True, slots=True)
class ProfilePipelineStatus:
    registry_observation_count: int
    qualification_counts: Mapping[str, int]
    review_event_count: int
    pair_relation_count: int
    same_component_count: int
    evidence_conflict_count: int
    canonical_profile_count: int
    retired_profile_count: int
    profile_member_count: int
    attached_name_claim_count: int
    configured_identity_count: int
    ungrouped_single_count: int
    named_ungrouped_single_count: int
    unnamed_ungrouped_single_count: int
    merge_candidate_count: int
    attribution_conflict_count: int
    pending_qualification_count: int
    pending_same_component_count: int
    pending_difference_count: int
    missing_reviewed_observation_count: int
    profiles: tuple[ProfileStatus, ...]
    next_actions: tuple[str, ...]


def build_profile_pipeline_status(
    database: Database,
    evidence: ReviewedSpeakerEvidence,
) -> ProfilePipelineStatus:
    observations = database.list_speaker_observations()
    observations_by_id = {observation.id: observation for observation in observations}
    videos_by_id = {video.id: video for video in database.list_videos()}
    claims = database.list_speaker_name_claims()
    explicit_names_by_observation: dict[int, set[str]] = defaultdict(set)
    explicit_claim_ids_by_observation: dict[int, set[int]] = defaultdict(set)
    for claim in claims:
        normalized_name = claim.normalized_name.strip()
        if (
            claim.observation_id is not None
            and claim.explicit_speaker_attribution
            and normalized_name
        ):
            explicit_names_by_observation[claim.observation_id].add(normalized_name)
            explicit_claim_ids_by_observation[claim.observation_id].add(claim.id)

    review_actions = {
        observation.id: (
            database.get_effective_observation_review_action(observation.id)
            or "unreviewed"
        )
        for observation in observations
    }
    qualification_counts = Counter(review_actions.values())
    all_profiles = database.list_speaker_profiles()
    reviewed_profiles = [
        profile
        for profile in all_profiles
        if profile.created_reason == REVIEWED_PROFILE_REASON
    ]
    canonical_ids = {
        profile.id
        for profile in reviewed_profiles
        if database.resolve_speaker_profile_id(profile.id) == profile.id
    }
    retired_profile_count = len(reviewed_profiles) - len(canonical_ids)

    members_by_profile: dict[int, set[int]] = {
        profile_id: set() for profile_id in canonical_ids
    }
    attached_claim_ids_by_profile: dict[int, set[int]] = {
        profile_id: set() for profile_id in canonical_ids
    }
    for profile in reviewed_profiles:
        canonical_id = database.resolve_speaker_profile_id(profile.id)
        if canonical_id not in canonical_ids:
            continue
        members_by_profile[canonical_id].update(
            database.list_effective_observation_ids_for_profile(profile.id)
        )
        attached_claim_ids_by_profile[canonical_id].update(
            database.list_effective_name_claim_ids_for_profile(profile.id)
        )

    configured_identities_by_profile: dict[int, list[str]] = defaultdict(list)
    configured_profile_ids_by_name: dict[str, list[int]] = defaultdict(list)
    for pastor in database.list_pastors():
        bound_profile_id = database.get_pastor_speaker_profile_id(pastor.id)
        if bound_profile_id is None:
            continue
        normalized_name = normalize_person_name(pastor.display_name)
        if normalized_name:
            configured_profile_ids_by_name[normalized_name].append(
                bound_profile_id
            )
        canonical_id = database.resolve_speaker_profile_id(bound_profile_id)
        if canonical_id in canonical_ids:
            configured_identities_by_profile[canonical_id].append(
                pastor.display_name
            )

    names_by_profile: dict[int, set[str]] = defaultdict(set)
    for profile_id, member_ids in members_by_profile.items():
        for observation_id in member_ids:
            names_by_profile[profile_id].update(
                explicit_names_by_observation.get(observation_id, ())
            )
    profile_ids_by_name: dict[str, set[int]] = defaultdict(set)
    for profile_id, names in names_by_profile.items():
        if len(names) == 1:
            profile_ids_by_name[next(iter(names))].add(profile_id)

    different_pairs = {
        tuple(sorted(pair))
        for pair in database.list_effective_observation_difference_pairs()
    }
    observation_ids_by_fingerprint = {
        observation.input_fingerprint: observation.id
        for observation in observations
    }
    reviewed_fingerprints = set(evidence.qualifications)
    reviewed_fingerprints.update(
        fingerprint
        for relation in evidence.pair_relations.values()
        for fingerprint in relation.fingerprints
    )
    missing_reviewed_fingerprints = (
        reviewed_fingerprints - set(observation_ids_by_fingerprint)
    )
    pending_qualification_count = sum(
        1
        for fingerprint, qualification in evidence.qualifications.items()
        if (
            fingerprint in observation_ids_by_fingerprint
            and review_actions[observation_ids_by_fingerprint[fingerprint]]
            != qualification.action
        )
    )
    pending_difference_count = sum(
        1
        for relation in evidence.pair_relations.values()
        if (
            relation.outcome == "different_speaker"
            and len(relation.fingerprints) == 2
            and all(
                fingerprint in observation_ids_by_fingerprint
                for fingerprint in relation.fingerprints
            )
            and tuple(
                sorted(
                    observation_ids_by_fingerprint[fingerprint]
                    for fingerprint in relation.fingerprints
                )
            )
            not in different_pairs
        )
    )
    owner_by_observation = {
        observation_id: profile_id
        for profile_id, member_ids in members_by_profile.items()
        for observation_id in member_ids
    }
    pending_same_component_count = 0
    for component in evidence.same_components():
        component_observation_ids = [
            observation_ids_by_fingerprint[fingerprint]
            for fingerprint in component
            if fingerprint in observation_ids_by_fingerprint
        ]
        owners = {
            owner_by_observation.get(observation_id)
            for observation_id in component_observation_ids
        }
        if (
            len(component_observation_ids) >= 2
            and (None in owners or len(owners) != 1)
        ):
            pending_same_component_count += 1
    merge_profile_ids: set[int] = set()
    attribution_conflict_profile_ids: set[int] = set()
    for profile_ids in profile_ids_by_name.values():
        if len(profile_ids) < 2:
            continue
        ordered_ids = sorted(profile_ids)
        blocked = any(
            tuple(sorted((member_a, member_b))) in different_pairs
            for index, profile_a in enumerate(ordered_ids)
            for profile_b in ordered_ids[index + 1 :]
            for member_a in members_by_profile[profile_a]
            for member_b in members_by_profile[profile_b]
        )
        target = (
            attribution_conflict_profile_ids if blocked else merge_profile_ids
        )
        target.update(profile_ids)

    attached_observation_ids = {
        observation_id
        for member_ids in members_by_profile.values()
        for observation_id in member_ids
    }
    ungrouped_single_ids = {
        observation.id
        for observation in observations
        if (
            review_actions[observation.id] == "qualified_single_speaker"
            and observation.id not in attached_observation_ids
        )
    }
    named_ungrouped_ids = {
        observation_id
        for observation_id in ungrouped_single_ids
        if len(explicit_names_by_observation.get(observation_id, ())) == 1
    }
    attributed_frontier_by_profile: dict[int, int] = defaultdict(int)
    for observation_id in named_ungrouped_ids:
        normalized_name = next(iter(explicit_names_by_observation[observation_id]))
        for profile_id in profile_ids_by_name.get(normalized_name, ()):
            attributed_frontier_by_profile[profile_id] += 1

    profile_rows: list[ProfileStatus] = []
    claim_review_conflict_profile_ids: set[int] = set()
    for profile_id in sorted(canonical_ids):
        member_ids = members_by_profile[profile_id]
        member_claim_ids = {
            claim_id
            for member_id in member_ids
            for claim_id in explicit_claim_ids_by_observation.get(member_id, ())
        }
        if any(
            review is not None
            and (
                review[0] != "attach"
                or review[1] is None
                or database.resolve_speaker_profile_id(review[1]) != profile_id
            )
            for claim_id in member_claim_ids
            if (review := database.get_effective_name_claim_review(claim_id))
            is not None
        ):
            claim_review_conflict_profile_ids.add(profile_id)
        video_ids = {
            observations_by_id[member_id].video_id
            for member_id in member_ids
            if member_id in observations_by_id
        }
        source_ids = {
            videos_by_id[video_id].source_id
            for video_id in video_ids
            if video_id in videos_by_id
        }
        names = tuple(sorted(names_by_profile.get(profile_id, ())))
        configured = tuple(
            sorted(configured_identities_by_profile.get(profile_id, ()))
        )
        frontier_count = attributed_frontier_by_profile.get(profile_id, 0)
        configured_name_ambiguity = (
            len(names) == 1
            and len(
                configured_profile_ids_by_name.get(next(iter(names)), ())
            )
            > 1
        )
        if len(names) > 1 or configured_name_ambiguity:
            claim_review_conflict_profile_ids.add(profile_id)
        if (
            profile_id in attribution_conflict_profile_ids
            or profile_id in claim_review_conflict_profile_ids
        ):
            state = "attribution-conflict"
            next_need = "adjudicate conflicting attribution evidence"
        elif profile_id in merge_profile_ids:
            state = "merge-candidate"
            next_need = "review a same-name profile bridge"
        elif (
            names
            and (
                not member_claim_ids.issubset(
                    attached_claim_ids_by_profile[profile_id]
                )
                or (
                    next(iter(names)) in configured_profile_ids_by_name
                    and not configured
                )
            )
        ):
            state = "attribution-pending"
            next_need = "run reviewed-evidence sync"
        elif configured:
            state = "linked"
            next_need = (
                f"review {frontier_count} attributed frontier candidate(s)"
                if frontier_count
                else "continue profile-growth review for broader voice evidence"
            )
        elif names:
            state = "attributed"
            next_need = (
                f"review {frontier_count} attributed frontier candidate(s)"
                if frontier_count
                else "link a configured identity when one exists"
            )
        else:
            state = "anonymous"
            next_need = "grow voice evidence and obtain explicit attribution"
        profile_rows.append(
            ProfileStatus(
                profile_id=profile_id,
                member_count=len(member_ids),
                recording_count=len(video_ids),
                source_count=len(source_ids),
                names=names,
                configured_identities=configured,
                attributed_frontier_count=frontier_count,
                state=state,
                next_need=next_need,
            )
        )

    next_actions: list[str] = []
    if (
        pending_qualification_count
        or pending_same_component_count
        or pending_difference_count
    ):
        next_actions.append(
            "Run reviewed-evidence sync to materialize pending reviewed qualifications, "
            "components, or different-speaker constraints."
        )
    if merge_profile_ids:
        next_actions.append(
            "Resolve same-name profile merge candidates with profile-growth pair review."
        )
    if named_ungrouped_ids:
        next_actions.append(
            "Review attributed profile frontiers to attach named single-speaker observations."
        )
    unnamed_ungrouped_count = len(ungrouped_single_ids - named_ungrouped_ids)
    if unnamed_ungrouped_count:
        next_actions.append(
            "Review remaining profile frontiers or seed pairs to grow anonymous profiles."
        )
    if qualification_counts["unreviewed"]:
        next_actions.append(
            "Continue pair review to qualify eligible observations; registry totals include "
            "observations that automatic selection may reject as stale or ineligible."
        )
    if not next_actions:
        next_actions.append("No immediate reviewed-evidence backlog is visible.")

    return ProfilePipelineStatus(
        registry_observation_count=len(observations),
        qualification_counts=dict(qualification_counts),
        review_event_count=evidence.review_event_count,
        pair_relation_count=len(evidence.pair_relations),
        same_component_count=len(evidence.same_components()),
        evidence_conflict_count=(
            len(evidence.qualification_conflicts) + len(evidence.pair_conflicts)
        ),
        canonical_profile_count=len(canonical_ids),
        retired_profile_count=retired_profile_count,
        profile_member_count=len(attached_observation_ids),
        attached_name_claim_count=sum(
            len(claim_ids) for claim_ids in attached_claim_ids_by_profile.values()
        ),
        configured_identity_count=sum(
            len(names) for names in configured_identities_by_profile.values()
        ),
        ungrouped_single_count=len(ungrouped_single_ids),
        named_ungrouped_single_count=len(named_ungrouped_ids),
        unnamed_ungrouped_single_count=unnamed_ungrouped_count,
        merge_candidate_count=len(merge_profile_ids),
        attribution_conflict_count=len(
            attribution_conflict_profile_ids | claim_review_conflict_profile_ids
        ),
        pending_qualification_count=pending_qualification_count,
        pending_same_component_count=pending_same_component_count,
        pending_difference_count=pending_difference_count,
        missing_reviewed_observation_count=len(missing_reviewed_fingerprints),
        profiles=tuple(profile_rows),
        next_actions=tuple(next_actions),
    )
