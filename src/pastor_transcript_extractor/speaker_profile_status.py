from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping

from pastor_transcript_extractor.reviewed_speaker_evidence import (
    ReviewedSpeakerEvidence,
)
from pastor_transcript_extractor.speaker_registry import normalize_person_name
from pastor_transcript_extractor.speaker_shadow_association import (
    assess_profile_association_readiness,
)
from pastor_transcript_extractor.storage import Database


REVIEWED_PROFILE_REASON = "reviewed_anonymous_speaker"
DISCOVERY_PROFILE_REASON = "shadow_discovery_candidate"
IDENTITY_RUN_COVERED_NEED_CODES = frozenset(
    {
        "reviewed_evidence_sync",
        "complete_discovery_confirmation",
        "plan_discovery_promotion",
        "association_validation",
    }
)
PROFILE_ATTRIBUTION_NEED_CODE = "obtain_explicit_attribution"
IDENTITY_RUN_AUTOMATIC_COMMAND = (
    "pte identity run --all --apply-automatic --base-dir BASE_DIR"
)


@dataclass(frozen=True, slots=True)
class StatusNeed:
    code: str
    message: str
    category: str
    command: str | None = None
    actionable: bool = True


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
    shadow_ready: bool
    automatic_profile_ready: bool
    automatic_blockers: tuple[str, ...]
    needs: tuple[StatusNeed, ...]
    next_need: str


@dataclass(frozen=True, slots=True)
class DiscoveredProfileStatus:
    component_id: str
    member_count: int
    recording_count: int
    source_count: int
    names: tuple[str, ...]
    state: str
    promoted_profile_id: int | None
    blockers: tuple[str, ...]
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
    attributed_frontier_observation_count: int
    unmatched_named_ungrouped_single_count: int
    unnamed_ungrouped_single_count: int
    merge_candidate_count: int
    attribution_conflict_count: int
    shadow_ready_profile_count: int
    automatic_profile_ready_count: int
    pending_qualification_count: int
    pending_same_component_count: int
    pending_difference_count: int
    missing_reviewed_observation_count: int
    discovery_report_path: str | None
    discovery_result_sha256: str | None
    shadow_discovery_candidate_count: int
    promoted_discovery_candidate_count: int
    stale_discovery_candidate_count: int
    blocked_discovery_component_count: int
    actionable_discovery_frontier_component_count: int
    immediate_discovery_frontier_component_count: int
    staged_discovery_frontier_component_count: int
    distant_staged_discovery_component_count: int
    discovered_profiles: tuple[DiscoveredProfileStatus, ...]
    profiles: tuple[ProfileStatus, ...]
    actions: tuple[StatusNeed, ...]
    next_actions: tuple[str, ...]


def applicable_status_commands(needs: tuple[StatusNeed, ...]) -> tuple[str, ...]:
    """Collapse automatic pipeline stages into the single identity-run command."""
    run_automatic = any(
        need.actionable and need.code in IDENTITY_RUN_COVERED_NEED_CODES
        for need in needs
    )
    commands = []
    if run_automatic:
        commands.append(IDENTITY_RUN_AUTOMATIC_COMMAND)
    if any(
        need.actionable and need.code == PROFILE_ATTRIBUTION_NEED_CODE
        for need in needs
    ):
        commands.append(
            "pte identity review-profile-attribution --reviewer REVIEWER_ID "
            "--base-dir BASE_DIR"
        )
    commands.extend(
        need.command
        for need in needs
        if (
            need.actionable
            and need.command is not None
            and need.code not in IDENTITY_RUN_COVERED_NEED_CODES
            and need.code != PROFILE_ATTRIBUTION_NEED_CODE
        )
    )
    return tuple(dict.fromkeys(commands))


def status_need_execution_label(need: StatusNeed) -> str:
    if need.code in IDENTITY_RUN_COVERED_NEED_CODES:
        return "identity run"
    if need.actionable:
        return "manual"
    return "informational"


def build_profile_pipeline_status(
    database: Database,
    evidence: ReviewedSpeakerEvidence,
    *,
    discovery_report: Mapping[str, Any] | None = None,
    discovery_report_path: Path | None = None,
) -> ProfilePipelineStatus:
    observations = database.list_speaker_observations()
    observations_by_id = {observation.id: observation for observation in observations}
    videos_by_id = {video.id: video for video in database.list_videos()}
    claims = database.list_speaker_name_claims()
    explicit_names_by_observation: dict[int, set[str]] = defaultdict(set)
    explicit_display_names_by_observation: dict[int, set[str]] = defaultdict(set)
    explicit_claim_ids_by_observation: dict[int, set[int]] = defaultdict(set)
    for claim in claims:
        normalized_name = claim.normalized_name.strip()
        if (
            claim.observation_id is not None
            and claim.explicit_speaker_attribution
            and normalized_name
        ):
            explicit_names_by_observation[claim.observation_id].add(normalized_name)
            explicit_display_names_by_observation[claim.observation_id].add(
                claim.display_name.strip() or normalized_name
            )
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
        if profile.created_reason
        in {REVIEWED_PROFILE_REASON, DISCOVERY_PROFILE_REASON}
    ]
    canonical_ids = {
        profile.id
        for profile in reviewed_profiles
        if database.resolve_speaker_profile_id(profile.id) == profile.id
    }
    retired_profile_count = len(reviewed_profiles) - len(canonical_ids)
    association_readiness = {
        item.profile_id: item
        for item in assess_profile_association_readiness(database, evidence)
    }

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
    normalized_names_by_profile: dict[int, set[str]] = defaultdict(set)
    for profile_id, member_ids in members_by_profile.items():
        for observation_id in member_ids:
            names_by_profile[profile_id].update(
                explicit_display_names_by_observation.get(observation_id, ())
            )
            normalized_names_by_profile[profile_id].update(
                explicit_names_by_observation.get(observation_id, ())
            )
    profile_ids_by_name: dict[str, set[int]] = defaultdict(set)
    for profile_id, names in normalized_names_by_profile.items():
        if len(names) == 1:
            profile_ids_by_name[next(iter(names))].add(profile_id)

    different_pairs = {
        tuple(sorted(pair))
        for pair in database.list_effective_observation_difference_pairs()
    }

    discovery_promotions: dict[str, int] = {}
    for profile in reviewed_profiles:
        if profile.created_reason != DISCOVERY_PROFILE_REASON:
            continue
        promotion = database.get_speaker_profile_discovery_promotion(profile.id)
        if promotion is None:
            continue
        component_id = str(promotion.get("component_id", ""))
        if component_id:
            discovery_promotions[component_id] = (
                database.resolve_speaker_profile_id(profile.id)
            )

    discovered_profiles: list[DiscoveredProfileStatus] = []
    blocked_discovery_component_count = 0
    actionable_discovery_frontier_component_count = 0
    immediate_discovery_frontier_component_count = 0
    staged_discovery_frontier_component_count = 0
    distant_staged_discovery_component_count = 0
    if discovery_report is not None:
        components = discovery_report.get("components", ())
        if not isinstance(components, list):
            raise ValueError("profile discovery artifact components are missing")
        counts = discovery_report.get("counts")
        if isinstance(counts, Mapping):
            actionable_discovery_frontier_component_count = int(
                counts.get(
                    "blocked_components_with_actionable_review_frontier",
                    0,
                )
            )
            immediate_discovery_frontier_component_count = int(
                counts.get(
                    "blocked_components_with_immediate_review_frontier",
                    actionable_discovery_frontier_component_count,
                )
            )
            staged_discovery_frontier_component_count = int(
                counts.get(
                    "blocked_components_with_staged_review_frontier",
                    0,
                )
            )
            distant_staged_discovery_component_count = int(
                counts.get(
                    "blocked_components_with_only_distant_staged_candidates",
                    0,
                )
            )
        for raw_component in components:
            if not isinstance(raw_component, Mapping):
                raise ValueError("profile discovery component must be an object")
            outcome = str(raw_component.get("outcome", ""))
            if outcome == "blocked":
                blocked_discovery_component_count += 1
                continue
            if outcome != "provisional_profile_candidate":
                continue
            component_id = str(raw_component.get("component_id", ""))
            promoted_profile_id = discovery_promotions.get(component_id)
            blockers: list[str] = []
            members = raw_component.get("members")
            if not component_id or not isinstance(members, list):
                blockers.append("invalid_component_metadata")
                members = []
            member_ids: list[int] = []
            if promoted_profile_id is None:
                for member in members:
                    if not isinstance(member, Mapping):
                        blockers.append("invalid_member_metadata")
                        continue
                    observation_id = member.get("observation_id")
                    fingerprint = member.get("input_fingerprint")
                    if not isinstance(observation_id, int):
                        blockers.append("invalid_member_metadata")
                        continue
                    member_ids.append(observation_id)
                    observation = observations_by_id.get(observation_id)
                    if (
                        observation is None
                        or not isinstance(fingerprint, str)
                        or observation.input_fingerprint != fingerprint
                        or observation.video_id != member.get("video_id")
                    ):
                        blockers.append("observation_no_longer_matches_artifact")
                    if database.list_effective_profile_ids_for_observation(
                        observation_id
                    ):
                        blockers.append("member_already_profiled")
                if any(
                    tuple(sorted((left, right))) in different_pairs
                    for index, left in enumerate(member_ids)
                    for right in member_ids[index + 1 :]
                ):
                    blockers.append("reviewed_difference_inside_component")
            blockers = list(dict.fromkeys(blockers))
            if promoted_profile_id is not None:
                state = "promoted"
                next_need = (
                    f"continue maturity work on profile {promoted_profile_id}"
                )
            elif blockers:
                state = "stale"
                next_need = "rerun shadow profile discovery"
            else:
                state = "shadow-candidate"
                next_need = "plan reversible registry promotion"
            discovered_profiles.append(
                DiscoveredProfileStatus(
                    component_id=component_id,
                    member_count=int(raw_component.get("member_count", len(members))),
                    recording_count=int(raw_component.get("recording_count", 0)),
                    source_count=int(raw_component.get("source_count", 0)),
                    names=tuple(
                        sorted(
                            str(name)
                            for name in raw_component.get("normalized_names", ())
                            if str(name).strip()
                        )
                    ),
                    state=state,
                    promoted_profile_id=promoted_profile_id,
                    blockers=tuple(blockers),
                    next_need=next_need,
                )
            )
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
    attributed_frontier_observation_ids: set[int] = set()
    for observation_id in named_ungrouped_ids:
        normalized_name = next(iter(explicit_names_by_observation[observation_id]))
        matching_profile_ids = profile_ids_by_name.get(normalized_name, ())
        if matching_profile_ids:
            attributed_frontier_observation_ids.add(observation_id)
        for profile_id in matching_profile_ids:
            attributed_frontier_by_profile[profile_id] += 1
    unmatched_named_ungrouped_ids = (
        named_ungrouped_ids - attributed_frontier_observation_ids
    )

    profile_rows: list[ProfileStatus] = []
    claim_review_conflict_profile_ids: set[int] = set()
    for profile_id in sorted(canonical_ids):
        registry_profile = next(
            profile for profile in reviewed_profiles if profile.id == profile_id
        )
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
        normalized_names = tuple(
            sorted(normalized_names_by_profile.get(profile_id, ()))
        )
        configured = tuple(
            sorted(configured_identities_by_profile.get(profile_id, ()))
        )
        profile_readiness = association_readiness[profile_id]
        frontier_count = attributed_frontier_by_profile.get(profile_id, 0)
        configured_name_ambiguity = (
            len(normalized_names) == 1
            and len(
                configured_profile_ids_by_name.get(next(iter(normalized_names)), ())
            )
            > 1
        )
        # Display spellings are preserved for reporting, but identity conflict
        # semantics use the normalized person name. Capitalization or other
        # display-only variants must not turn one attribution into two people.
        if len(normalized_names) > 1 or configured_name_ambiguity:
            claim_review_conflict_profile_ids.add(profile_id)
        needs: list[StatusNeed] = []
        if registry_profile.created_reason == DISCOVERY_PROFILE_REASON:
            state = (
                "provisional-confirmed"
                if profile_readiness.automatic_profile_ready
                else "provisional"
            )
            if profile_readiness.automatic_profile_ready:
                needs.append(
                    StatusNeed(
                        "automatic_policy_approval",
                        "profile gate is complete; model/policy approval remains separate",
                        "policy",
                        actionable=False,
                    )
                )
            else:
                needs.append(
                    StatusNeed(
                        "complete_discovery_confirmation",
                        "run the consolidated identity workflow to generate and "
                        "apply an eligible independent confirmation; omit "
                        "--apply-automatic for a non-applying preview",
                        "discovery-confirmation",
                        IDENTITY_RUN_AUTOMATIC_COMMAND,
                    )
                )
        elif (
            profile_id in attribution_conflict_profile_ids
            or profile_id in claim_review_conflict_profile_ids
        ):
            state = "attribution-conflict"
            needs.append(
                StatusNeed(
                    "attribution_conflict",
                    "adjudicate conflicting attribution evidence (no dedicated CLI workflow yet)",
                    "attribution",
                    actionable=False,
                )
            )
        elif profile_id in merge_profile_ids:
            state = "merge-candidate"
            needs.append(
                StatusNeed(
                    "same_name_profile_bridge",
                    "review a same-name profile bridge",
                    "profile-growth",
                    "pte identity review-next-speaker-pair --selection-objective "
                    "profile-growth --reviewer REVIEWER_ID --base-dir BASE_DIR",
                )
            )
        elif (
            names
            and (
                not member_claim_ids.issubset(
                    attached_claim_ids_by_profile[profile_id]
                )
                or (
                    next(iter(normalized_names)) in configured_profile_ids_by_name
                    and not configured
                )
            )
        ):
            state = "attribution-pending"
            needs.append(
                StatusNeed(
                    "reviewed_evidence_sync",
                    "synchronize pending reviewed evidence in the consolidated "
                    "identity workflow",
                    "materialization",
                    IDENTITY_RUN_AUTOMATIC_COMMAND,
                )
            )
        elif configured:
            state = "linked"
        elif names:
            state = "attributed"
        else:
            state = "anonymous"

        if (
            registry_profile.created_reason != DISCOVERY_PROFILE_REASON
            and state in {"linked", "attributed", "anonymous"}
        ):
            if frontier_count:
                needs.append(
                    StatusNeed(
                        "attributed_profile_frontier",
                        f"review {frontier_count} attributed frontier candidate(s); "
                        "selection remains globally prioritized",
                        "profile-growth",
                        "pte identity review-next-speaker-pair --selection-objective "
                        "profile-growth --reviewer REVIEWER_ID --base-dir BASE_DIR",
                    )
                )
            if "reviewed_same_graph_contains_bridge" in (
                profile_readiness.automatic_blockers
            ):
                needs.append(
                    StatusNeed(
                        "reviewed_same_graph_contains_bridge",
                        "review internal reinforcement for automation readiness",
                        "automation-readiness",
                        "pte identity review-next-speaker-pair --selection-objective "
                        "automation-readiness --reviewer REVIEWER_ID "
                        "--base-dir BASE_DIR",
                    )
                )
            if state == "attributed" and not configured:
                needs.append(
                    StatusNeed(
                        "configured_identity_missing",
                        "no configured identity is currently linked for this attributed name",
                        "attribution",
                        actionable=False,
                    )
                )
            if not profile_readiness.shadow_ready:
                needs.append(
                    StatusNeed(
                        "grow_profile_evidence",
                        "continue profile-growth review for broader voice evidence",
                        "profile-growth",
                        "pte identity review-next-speaker-pair --selection-objective "
                        "profile-growth --reviewer REVIEWER_ID --base-dir BASE_DIR",
                    )
                )
            if state == "anonymous":
                needs.append(
                    StatusNeed(
                        "obtain_explicit_attribution",
                        "obtain explicit attribution from the profile's backing videos",
                        "attribution",
                        "pte identity review-profile-attribution --reviewer REVIEWER_ID "
                        f"--profile-id {profile_id} --base-dir BASE_DIR",
                    )
                )
            if profile_readiness.automatic_profile_ready:
                needs.append(
                    StatusNeed(
                        "association_validation",
                        "accumulate shadow-association validation evidence in the "
                        "consolidated identity workflow",
                        "association-validation",
                        IDENTITY_RUN_AUTOMATIC_COMMAND,
                    )
                )
        if not needs:
            needs.append(
                StatusNeed(
                    "no_immediate_profile_work",
                    "no immediate profile-specific work is visible",
                    "status",
                    actionable=False,
                )
            )
        next_need = needs[0].message
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
                shadow_ready=profile_readiness.shadow_ready,
                automatic_profile_ready=(
                    profile_readiness.automatic_profile_ready
                ),
                automatic_blockers=profile_readiness.automatic_blockers,
                needs=tuple(needs),
                next_need=next_need,
            )
        )

    profile_status_by_id = {profile.profile_id: profile for profile in profile_rows}
    discovered_profiles = [
        replace(
            discovered,
            next_need=profile_status_by_id[discovered.promoted_profile_id].next_need,
        )
        if (
            discovered.promoted_profile_id is not None
            and discovered.promoted_profile_id in profile_status_by_id
        )
        else discovered
        for discovered in discovered_profiles
    ]

    actions: list[StatusNeed] = []
    if (
        pending_qualification_count
        or pending_same_component_count
        or pending_difference_count
    ):
        actions.append(
            StatusNeed(
                "reviewed_evidence_sync",
                "Run the consolidated identity workflow to materialize pending "
                "reviewed evidence and recompute profile-specific status; discovery "
                "frontiers already consume review artifacts directly.",
                "materialization",
                IDENTITY_RUN_AUTOMATIC_COMMAND,
            )
        )
    if any(
        profile.state == "shadow-candidate"
        for profile in discovered_profiles
    ):
        actions.append(
            StatusNeed(
                "plan_discovery_promotion",
                "Use the consolidated identity workflow to plan and apply eligible "
                "shadow-discovered profile promotions; omit --apply-automatic for "
                "a non-applying preview.",
                "discovery",
                IDENTITY_RUN_AUTOMATIC_COMMAND,
            )
        )
    if immediate_discovery_frontier_component_count:
        actions.append(
            StatusNeed(
                "immediate_discovery_frontier",
                "Review the near-same ambiguous discovery frontier with the normal "
                "blinded visual-confirmation pair workflow.",
                "automation-readiness",
                "pte identity review-next-speaker-pair --selection-objective "
                "automation-readiness --reviewer REVIEWER_ID --base-dir BASE_DIR",
            )
        )
    if staged_discovery_frontier_component_count:
        actions.append(
            StatusNeed(
                "staged_discovery_frontier",
                "Begin the staged near-same discovery frontier by reviewing each "
                "bundle's weaker bottleneck edge with the normal blinded workflow.",
                "automation-readiness",
                "pte identity review-next-speaker-pair --selection-objective "
                "automation-readiness --reviewer REVIEWER_ID --base-dir BASE_DIR",
            )
        )
    if distant_staged_discovery_component_count:
        actions.append(
            StatusNeed(
                "distant_discovery_frontier_deferred",
                "Do not review distant staged candidates; wait for closer acoustic "
                "retrieval or qualify additional recordings for those components.",
                "discovery",
                actionable=False,
            )
        )
    if merge_profile_ids:
        actions.append(
            StatusNeed(
                "same_name_profile_merges",
                "Resolve same-name profile merge candidates with profile-growth pair review.",
                "profile-growth",
                "pte identity review-next-speaker-pair --selection-objective "
                "profile-growth --reviewer REVIEWER_ID --base-dir BASE_DIR",
            )
        )
    if attributed_frontier_observation_ids:
        actions.append(
            StatusNeed(
                "attributed_profile_frontiers",
                f"Review {len(attributed_frontier_observation_ids)} named "
                "single-speaker observation(s) that match existing profiles.",
                "profile-growth",
                "pte identity review-next-speaker-pair --selection-objective "
                "profile-growth --reviewer REVIEWER_ID --base-dir BASE_DIR",
            )
        )
    if unmatched_named_ungrouped_ids:
        actions.append(
            StatusNeed(
                "unmatched_named_profile_seeds",
                f"Use {len(unmatched_named_ungrouped_ids)} named ungrouped "
                "observation(s) as profile seeds or reconciliation candidates; "
                "they do not match an existing attributed profile.",
                "profile-growth",
                "pte identity review-next-speaker-pair --selection-objective "
                "profile-growth --reviewer REVIEWER_ID --base-dir BASE_DIR",
            )
        )
    unnamed_ungrouped_count = len(ungrouped_single_ids - named_ungrouped_ids)
    if unnamed_ungrouped_count:
        actions.append(
            StatusNeed(
                "unnamed_profile_frontiers",
                "Review remaining profile frontiers or seed pairs to grow anonymous profiles.",
                "profile-growth",
                "pte identity review-next-speaker-pair --selection-objective "
                "profile-growth --reviewer REVIEWER_ID --base-dir BASE_DIR",
            )
        )
    if qualification_counts["unreviewed"]:
        actions.append(
            StatusNeed(
                "unreviewed_observations",
                "Continue pair review to qualify eligible observations; registry totals "
                "include observations that automatic selection may reject as stale or ineligible.",
                "qualification",
                "pte identity review-next-speaker-pair --selection-objective "
                "profile-growth --reviewer REVIEWER_ID --base-dir BASE_DIR",
            )
        )
    if not actions:
        actions.append(
            StatusNeed(
                "no_immediate_backlog",
                "No immediate reviewed-evidence backlog is visible.",
                "status",
                actionable=False,
            )
        )

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
        attributed_frontier_observation_count=len(
            attributed_frontier_observation_ids
        ),
        unmatched_named_ungrouped_single_count=len(
            unmatched_named_ungrouped_ids
        ),
        unnamed_ungrouped_single_count=unnamed_ungrouped_count,
        merge_candidate_count=len(merge_profile_ids),
        attribution_conflict_count=len(
            attribution_conflict_profile_ids | claim_review_conflict_profile_ids
        ),
        shadow_ready_profile_count=sum(
            item.shadow_ready for item in association_readiness.values()
        ),
        automatic_profile_ready_count=sum(
            item.automatic_profile_ready
            for item in association_readiness.values()
        ),
        pending_qualification_count=pending_qualification_count,
        pending_same_component_count=pending_same_component_count,
        pending_difference_count=pending_difference_count,
        missing_reviewed_observation_count=len(missing_reviewed_fingerprints),
        discovery_report_path=(
            str(discovery_report_path) if discovery_report_path is not None else None
        ),
        discovery_result_sha256=(
            str(discovery_report.get("result_sha256", ""))
            if discovery_report is not None
            else None
        ),
        shadow_discovery_candidate_count=sum(
            item.state == "shadow-candidate" for item in discovered_profiles
        ),
        promoted_discovery_candidate_count=sum(
            item.state == "promoted" for item in discovered_profiles
        ),
        stale_discovery_candidate_count=sum(
            item.state == "stale" for item in discovered_profiles
        ),
        blocked_discovery_component_count=blocked_discovery_component_count,
        actionable_discovery_frontier_component_count=(
            actionable_discovery_frontier_component_count
        ),
        immediate_discovery_frontier_component_count=(
            immediate_discovery_frontier_component_count
        ),
        staged_discovery_frontier_component_count=(
            staged_discovery_frontier_component_count
        ),
        distant_staged_discovery_component_count=(
            distant_staged_discovery_component_count
        ),
        discovered_profiles=tuple(discovered_profiles),
        profiles=tuple(profile_rows),
        actions=tuple(actions),
        next_actions=tuple(action.message for action in actions),
    )
