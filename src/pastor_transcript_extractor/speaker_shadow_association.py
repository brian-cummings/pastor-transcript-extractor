from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from pastor_transcript_extractor.models import SpeakerObservation, SpeakerProfile
from pastor_transcript_extractor.reviewed_speaker_evidence import (
    ReviewedSpeakerEvidence,
)
from pastor_transcript_extractor.speaker_pair_diagnostics import (
    DecisionPolicy,
    PairOutcome,
    SpanSpec,
)
from pastor_transcript_extractor.storage import Database


SHADOW_ASSOCIATION_VERSION = "speaker_shadow_association_v7"
SHADOW_ASSOCIATION_FINGERPRINT_VERSION = (
    "speaker_shadow_association_input_v6"
)
SHADOW_ASSOCIATION_ADMISSION_VERSION = (
    "speaker_shadow_association_admission_v1"
)
REVIEWED_PROFILE_REASON = "reviewed_anonymous_speaker"
DISCOVERY_PROFILE_REASON = "shadow_discovery_candidate"


@dataclass(frozen=True, slots=True)
class ShadowPolicySpec:
    policy: DecisionPolicy
    review_status: str
    artifact_sha256: str
    automatic_use_allowed: bool


@dataclass(frozen=True, slots=True)
class ProfileAssociationReadiness:
    profile_id: int
    member_observation_ids: tuple[int, ...]
    member_fingerprints: tuple[str, ...]
    recording_count: int
    source_count: int
    normalized_names: tuple[str, ...]
    shadow_ready: bool
    automatic_profile_ready: bool
    shadow_blockers: tuple[str, ...]
    automatic_blockers: tuple[str, ...]
    review_ready: bool = False
    certified_exemplar_observation_ids: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class ShadowExemplar:
    profile_id: int
    observation: SpeakerObservation
    audio_path: Path
    audio_sha256: str
    span_specs: tuple[SpanSpec, ...] = ()


@dataclass(frozen=True, slots=True)
class StagedAssociationRouting:
    profiles: tuple[
        tuple[ProfileAssociationReadiness, Sequence[ShadowExemplar]], ...
    ]
    exhaustive: bool
    route: str
    priority_profile_ids: tuple[int, ...]
    shortlisted_profile_ids: tuple[int, ...]
    total_routable_profiles: int
    confirmation_priority_profile_ids: tuple[int, ...] = ()
    candidate_funnel: Mapping[str, Any] | None = None


def leave_one_out_profile_readiness(
    readiness: ProfileAssociationReadiness,
    *,
    candidate: SpeakerObservation,
    observations_by_id: Mapping[int, SpeakerObservation],
    source_id_by_video_id: Mapping[int, int],
    normalized_names_by_observation_id: Mapping[int, Sequence[str]],
    minimum_members: int = 3,
) -> ProfileAssociationReadiness:
    """Hide a reviewed candidate from profile inputs before retrospective routing."""
    if candidate.id not in readiness.member_observation_ids:
        return readiness
    member_ids = tuple(
        observation_id
        for observation_id in readiness.member_observation_ids
        if observation_id != candidate.id
    )
    member_observations = [
        observations_by_id[observation_id]
        for observation_id in member_ids
        if observation_id in observations_by_id
    ]
    member_fingerprints = tuple(
        sorted(
            observation.input_fingerprint
            for observation in member_observations
        )
    )
    video_ids = {
        observation.video_id for observation in member_observations
    }
    source_ids = {
        source_id_by_video_id[video_id]
        for video_id in video_ids
        if video_id in source_id_by_video_id
    }
    normalized_names = tuple(
        sorted(
            {
                name.strip()
                for observation_id in member_ids
                for name in normalized_names_by_observation_id.get(
                    observation_id, ()
                )
                if name.strip()
            }
        )
    )
    recomputed_blockers = {
        "fewer_than_three_profile_members",
        "fewer_than_three_distinct_recordings",
        "member_observation_missing",
        "conflicting_explicit_attribution",
    }
    shadow_blockers = [
        blocker
        for blocker in readiness.shadow_blockers
        if blocker not in recomputed_blockers
    ]
    if len(member_ids) < minimum_members:
        shadow_blockers.append("fewer_than_three_profile_members")
    if len(video_ids) < minimum_members:
        shadow_blockers.append("fewer_than_three_distinct_recordings")
    if len(member_observations) != len(member_ids):
        shadow_blockers.append("member_observation_missing")
    if len(normalized_names) > 1:
        shadow_blockers.append("conflicting_explicit_attribution")
    shadow_blockers = list(dict.fromkeys(shadow_blockers))

    automatic_blockers = [
        blocker
        for blocker in readiness.automatic_blockers
        if blocker not in recomputed_blockers
    ]
    automatic_blockers = list(
        dict.fromkeys((*shadow_blockers, *automatic_blockers))
    )
    review_ready = (
        len(member_ids) >= 2
        and len(video_ids) >= 2
        and not any(
            blocker
            not in {
                "fewer_than_three_profile_members",
                "fewer_than_three_distinct_recordings",
            }
            for blocker in shadow_blockers
        )
    )
    return replace(
        readiness,
        member_observation_ids=member_ids,
        member_fingerprints=member_fingerprints,
        recording_count=len(video_ids),
        source_count=len(source_ids),
        normalized_names=normalized_names,
        shadow_ready=not shadow_blockers,
        automatic_profile_ready=not automatic_blockers,
        shadow_blockers=tuple(shadow_blockers),
        automatic_blockers=tuple(automatic_blockers),
        review_ready=review_ready,
        certified_exemplar_observation_ids=tuple(
            observation_id
            for observation_id in readiness.certified_exemplar_observation_ids
            if observation_id != candidate.id
        ),
    )


def select_routed_association_profiles(
    profiles: Sequence[
        tuple[ProfileAssociationReadiness, Sequence[ShadowExemplar]]
    ],
    *,
    candidate_source_id: int,
    candidate_normalized_names: Sequence[str],
    source_id_by_video_id: Mapping[int, int],
) -> tuple[
    tuple[ProfileAssociationReadiness, Sequence[ShadowExemplar]], ...
]:
    """Keep confirmed mature profiles global and route review targets safely."""
    names = {
        name.strip() for name in candidate_normalized_names if name.strip()
    }
    return tuple(
        (readiness, exemplars)
        for readiness, exemplars in profiles
        if (
            readiness.shadow_ready
            and "discovery_candidate_unconfirmed"
            not in readiness.automatic_blockers
        )
        or bool(names & set(readiness.normalized_names))
        or any(
            source_id_by_video_id.get(exemplar.observation.video_id)
            == candidate_source_id
            for exemplar in exemplars
        )
    )


def select_staged_association_profiles(
    profiles: Sequence[
        tuple[ProfileAssociationReadiness, Sequence[ShadowExemplar]]
    ],
    *,
    candidate_source_id: int,
    candidate_normalized_names: Sequence[str],
    source_id_by_video_id: Mapping[int, int],
    candidate_centroid: Sequence[float],
    exemplar_centroids: Mapping[int, Sequence[float]],
    maximum_global_profiles: int = 3,
    confirmation_priority_profile_ids: frozenset[int] = frozenset(),
) -> StagedAssociationRouting:
    """Prioritize source/name routes and bound expensive global comparisons."""
    if maximum_global_profiles < 1:
        raise ValueError("global association shortlist must contain a profile")
    routable_by_id = {
        readiness.profile_id: (readiness, exemplars)
        for readiness, exemplars in select_routed_association_profiles(
            profiles,
            candidate_source_id=candidate_source_id,
            candidate_normalized_names=candidate_normalized_names,
            source_id_by_video_id=source_id_by_video_id,
        )
    }
    routable_by_id.update(
        {
            readiness.profile_id: (readiness, exemplars)
            for readiness, exemplars in profiles
            if readiness.profile_id in confirmation_priority_profile_ids
        }
    )
    routable = tuple(routable_by_id.values())
    names = {
        name.strip() for name in candidate_normalized_names if name.strip()
    }

    def priority_reason(
        item: tuple[ProfileAssociationReadiness, Sequence[ShadowExemplar]],
    ) -> tuple[bool, bool, bool]:
        readiness, exemplars = item
        confirmation_match = (
            readiness.profile_id in confirmation_priority_profile_ids
        )
        source_match = any(
            source_id_by_video_id.get(exemplar.observation.video_id)
            == candidate_source_id
            for exemplar in exemplars
        )
        name_match = bool(names & set(readiness.normalized_names))
        return confirmation_match, source_match, name_match

    priority = [item for item in routable if any(priority_reason(item))]
    priority_ids = {item[0].profile_id for item in priority}
    global_candidates = [
        item for item in routable if item[0].profile_id not in priority_ids
    ]

    def profile_similarity(
        item: tuple[ProfileAssociationReadiness, Sequence[ShadowExemplar]],
    ) -> float:
        similarities = [
            _cosine_centroids(
                candidate_centroid,
                exemplar_centroids[exemplar.observation.id],
            )
            for exemplar in item[1]
            if exemplar.observation.id in exemplar_centroids
        ]
        return max(similarities) if similarities else -1.0

    similarity_by_profile_id = {
        item[0].profile_id: profile_similarity(item)
        for item in global_candidates
    }
    evaluation_similarity_by_profile_id = {
        item[0].profile_id: profile_similarity(item)
        for item in routable
    }
    evaluation_ranked_profile_ids = [
        item[0].profile_id
        for item in sorted(
            routable,
            key=lambda item: (-profile_similarity(item), item[0].profile_id),
        )
    ]
    evaluation_rank_by_profile_id = {
        profile_id: rank
        for rank, profile_id in enumerate(
            evaluation_ranked_profile_ids, start=1
        )
    }
    global_candidates.sort(
        key=lambda item: (-profile_similarity(item), item[0].profile_id)
    )
    acoustic_rank_by_profile_id = {
        item[0].profile_id: rank
        for rank, item in enumerate(global_candidates, start=1)
    }
    shortlisted = global_candidates[:maximum_global_profiles]
    selected = sorted(
        (*priority, *shortlisted),
        key=lambda item: (
            0 if priority_reason(item)[0] else 1,
            0 if priority_reason(item)[1] else 1,
            0 if priority_reason(item)[2] else 1,
            -profile_similarity(item),
            item[0].profile_id,
        ),
    )
    exhaustive = len(selected) == len(routable)
    selected_ids = {item[0].profile_id for item in selected}
    routable_ids = set(routable_by_id)
    candidate_funnel_entries = []
    for readiness, exemplars in sorted(
        profiles, key=lambda item: item[0].profile_id
    ):
        confirmation_match, source_match, name_match = priority_reason(
            (readiness, exemplars)
        )
        profile_id = readiness.profile_id
        matched_normalized_names = sorted(
            names & set(readiness.normalized_names)
        )
        matching_source_exemplar_observation_ids = sorted(
            exemplar.observation.id
            for exemplar in exemplars
            if source_id_by_video_id.get(exemplar.observation.video_id)
            == candidate_source_id
        )
        globally_routable = (
            readiness.shadow_ready
            and "discovery_candidate_unconfirmed"
            not in readiness.automatic_blockers
        )
        retrieval_sources = []
        if confirmation_match:
            retrieval_sources.append("pending_confirmation")
        if source_match:
            retrieval_sources.append("source")
        if name_match:
            retrieval_sources.append("name")
        if profile_id in acoustic_rank_by_profile_id:
            retrieval_sources.append("acoustic_global")
        policy_exclusion_reasons = []
        if profile_id not in routable_ids:
            if "discovery_candidate_unconfirmed" in readiness.automatic_blockers:
                policy_exclusion_reasons.append(
                    "discovery_candidate_unconfirmed_without_priority_route"
                )
            if not globally_routable and not policy_exclusion_reasons:
                policy_exclusion_reasons.append(
                    "profile_not_globally_routable_without_local_route"
                )
        candidate_funnel_entries.append(
            {
                "profile_id": profile_id,
                "retrieval_sources": retrieval_sources,
                "source_match": source_match,
                "matching_source_exemplar_observation_ids": (
                    matching_source_exemplar_observation_ids
                ),
                "name_match": name_match,
                "matched_normalized_names": matched_normalized_names,
                "confirmation_priority": confirmation_match,
                "routing_policy_eligible": profile_id in routable_ids,
                "routing_policy_exclusion_reason_codes": (
                    policy_exclusion_reasons
                ),
                "acoustic_similarity": similarity_by_profile_id.get(
                    profile_id
                ),
                "acoustic_rank": acoustic_rank_by_profile_id.get(profile_id),
                "all_eligible_acoustic_similarity": (
                    evaluation_similarity_by_profile_id.get(profile_id)
                ),
                "all_eligible_acoustic_rank": (
                    evaluation_rank_by_profile_id.get(profile_id)
                ),
                "passed_shortlist_cutoff": (
                    profile_id in {item[0].profile_id for item in shortlisted}
                    if profile_id in acoustic_rank_by_profile_id
                    else None
                ),
                "selected_for_comparison": profile_id in selected_ids,
            }
        )
    cutoff_score = (
        similarity_by_profile_id[shortlisted[-1][0].profile_id]
        if shortlisted
        else None
    )
    return StagedAssociationRouting(
        profiles=tuple(selected),
        exhaustive=exhaustive,
        route=(
            "exhaustive"
            if exhaustive
            else (
                "pending_discovery_confirmation_priority_with_global_"
                "centroid_shortlist"
                if confirmation_priority_profile_ids
                else "source_name_priority_with_global_centroid_shortlist"
            )
        ),
        priority_profile_ids=tuple(
            sorted(item[0].profile_id for item in priority)
        ),
        shortlisted_profile_ids=tuple(
            item[0].profile_id for item in shortlisted
        ),
        total_routable_profiles=len(routable),
        confirmation_priority_profile_ids=tuple(
            sorted(
                confirmation_priority_profile_ids
                & set(routable_by_id)
            )
        ),
        candidate_funnel={
            "version": "association_candidate_funnel_v1",
            "retrieval_candidates": candidate_funnel_entries,
            "acoustic_shortlist": {
                "maximum_profiles": maximum_global_profiles,
                "cutoff_score": cutoff_score,
                "ranked_profile_ids": [
                    item[0].profile_id for item in global_candidates
                ],
                "all_eligible_ranked_profile_ids": (
                    evaluation_ranked_profile_ids
                ),
            },
            "profiles_selected_for_comparison": sorted(selected_ids),
        },
    )


def plan_pending_discovery_confirmation_routes(
    profiles: Sequence[
        tuple[ProfileAssociationReadiness, Sequence[ShadowExemplar]]
    ],
    *,
    candidate_centroids: Mapping[int, Sequence[float]],
    candidate_video_ids: Mapping[int, int],
    exemplar_centroids: Mapping[int, Sequence[float]],
    candidates_per_profile: int = 2,
) -> dict[int, tuple[int, ...]]:
    """Assign each pending discovery profile its nearest independent candidates."""
    if candidates_per_profile < 1:
        raise ValueError(
            "pending discovery confirmation requires at least one candidate"
        )
    profile_ids_by_candidate: dict[int, list[int]] = defaultdict(list)
    for readiness, exemplars in profiles:
        if "discovery_candidate_unconfirmed" not in readiness.automatic_blockers:
            continue
        seed_video_ids = {
            exemplar.observation.video_id for exemplar in exemplars
        }
        ranked_candidates: list[tuple[float, int]] = []
        for candidate_id, candidate_centroid in candidate_centroids.items():
            if candidate_video_ids.get(candidate_id) in seed_video_ids:
                continue
            similarity = max(
                (
                    _cosine_centroids(
                        candidate_centroid,
                        exemplar_centroids[exemplar.observation.id],
                    )
                    for exemplar in exemplars
                    if exemplar.observation.id in exemplar_centroids
                ),
                default=-1.0,
            )
            ranked_candidates.append((-similarity, candidate_id))
        for _negative_similarity, candidate_id in sorted(ranked_candidates)[
            :candidates_per_profile
        ]:
            profile_ids_by_candidate[candidate_id].append(
                readiness.profile_id
            )
    return {
        candidate_id: tuple(sorted(profile_ids))
        for candidate_id, profile_ids in sorted(profile_ids_by_candidate.items())
    }


def _cosine_centroids(
    left: Sequence[float], right: Sequence[float]
) -> float:
    if not left or len(left) != len(right):
        return -1.0
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm <= 0.0 or right_norm <= 0.0:
        return -1.0
    similarity = sum(a * b for a, b in zip(left, right, strict=True)) / (
        left_norm * right_norm
    )
    return similarity if math.isfinite(similarity) else -1.0


PairComparer = Callable[
    [SpeakerObservation, SpeakerObservation, Path, Path],
    Mapping[str, Any],
]


def load_shadow_policy(path: Path) -> ShadowPolicySpec:
    resolved = path.expanduser().resolve()
    raw = resolved.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("speaker decision policy must be a JSON object")
    review_status = str(payload.get("review_status", ""))
    if review_status == "approved":
        policy_payload = payload
    elif review_status == "experimental_candidate":
        policy_payload = payload.get("policy")
        if not isinstance(policy_payload, dict):
            raise ValueError("experimental policy artifact requires a policy object")
    else:
        raise ValueError(
            "shadow association policy must be approved or an experimental candidate"
        )
    try:
        policy = DecisionPolicy(
            **{
                key: policy_payload[key]
                for key in DecisionPolicy.__dataclass_fields__
            }
        )
    except KeyError as error:
        raise ValueError(f"speaker decision policy is missing {error.args[0]}") from error
    return ShadowPolicySpec(
        policy=policy,
        review_status=review_status,
        artifact_sha256=hashlib.sha256(raw).hexdigest(),
        automatic_use_allowed=(
            review_status == "approved"
            and payload.get("registry_mutation_allowed") is True
        ),
    )


def assess_profile_association_readiness(
    database: Database,
    evidence: ReviewedSpeakerEvidence,
    *,
    minimum_members: int = 3,
) -> tuple[ProfileAssociationReadiness, ...]:
    if minimum_members < 3:
        raise ValueError("profile readiness requires at least three members")
    observations = {
        observation.id: observation
        for observation in database.list_speaker_observations()
    }
    videos = {video.id: video for video in database.list_videos()}
    names_by_observation: dict[int, set[str]] = defaultdict(set)
    claim_ids_by_observation: dict[int, set[int]] = defaultdict(set)
    for claim in database.list_speaker_name_claims():
        if (
            claim.observation_id is not None
            and claim.explicit_speaker_attribution
            and claim.normalized_name.strip()
        ):
            names_by_observation[claim.observation_id].add(
                claim.normalized_name.strip()
            )
            claim_ids_by_observation[claim.observation_id].add(claim.id)

    profiles = [
        profile
        for profile in database.list_speaker_profiles()
        if profile.created_reason
        in {REVIEWED_PROFILE_REASON, DISCOVERY_PROFILE_REASON}
    ]
    canonical_ids = {
        profile.id
        for profile in profiles
        if database.resolve_speaker_profile_id(profile.id) == profile.id
    }
    members_by_profile: dict[int, set[int]] = {
        profile_id: set() for profile_id in canonical_ids
    }
    constituents_by_profile: dict[int, list[SpeakerProfile]] = {
        profile_id: [] for profile_id in canonical_ids
    }
    for profile in profiles:
        canonical_id = database.resolve_speaker_profile_id(profile.id)
        if canonical_id in canonical_ids:
            constituents_by_profile[canonical_id].append(profile)
            members_by_profile[canonical_id].update(
                database.list_effective_observation_ids_for_profile(profile.id)
            )

    same_edges = {
        frozenset(relation.fingerprints)
        for relation in evidence.pair_relations.values()
        if relation.outcome == "same_speaker" and len(relation.fingerprints) == 2
    }
    different_pairs = {
        tuple(sorted(pair))
        for pair in database.list_effective_observation_difference_pairs()
    }
    readiness: list[ProfileAssociationReadiness] = []
    for profile_id in sorted(canonical_ids):
        member_ids = tuple(sorted(members_by_profile[profile_id]))
        member_observations = [
            observations[member_id]
            for member_id in member_ids
            if member_id in observations
        ]
        fingerprints = tuple(
            sorted(observation.input_fingerprint for observation in member_observations)
        )
        video_ids = {observation.video_id for observation in member_observations}
        source_ids = {
            videos[video_id].source_id
            for video_id in video_ids
            if video_id in videos
        }
        names = tuple(
            sorted(
                {
                    normalized_name
                    for member_id in member_ids
                    for normalized_name in names_by_observation.get(member_id, ())
                }
            )
        )
        shadow_blockers: list[str] = []
        if len(member_ids) < minimum_members:
            shadow_blockers.append("fewer_than_three_profile_members")
        if len(video_ids) < minimum_members:
            shadow_blockers.append("fewer_than_three_distinct_recordings")
        if len(member_observations) != len(member_ids):
            shadow_blockers.append("member_observation_missing")
        if len(names) > 1:
            shadow_blockers.append("conflicting_explicit_attribution")
        if any(
            review[0] != "attach"
            or review[1] is None
            or database.resolve_speaker_profile_id(review[1]) != profile_id
            for member_id in member_ids
            for claim_id in claim_ids_by_observation.get(member_id, ())
            if (
                review := database.get_effective_name_claim_review(claim_id)
            )
            is not None
        ):
            shadow_blockers.append("conflicting_name_claim_review")
        if any(
            tuple(sorted((member_a, member_b))) in different_pairs
            for index, member_a in enumerate(member_ids)
            for member_b in member_ids[index + 1 :]
        ):
            shadow_blockers.append("internal_reviewed_difference")

        profile_edges = {
            edge for edge in same_edges if edge.issubset(fingerprints)
        }
        certified_fingerprints = _review_graph_certified_nodes(
            fingerprints,
            profile_edges,
            minimum_members=minimum_members,
        )
        certified_observation_ids = {
            observation.id
            for observation in member_observations
            if observation.input_fingerprint in certified_fingerprints
        }
        discovery_blockers: list[str] = []
        has_reviewed_constituent = False
        for constituent in constituents_by_profile[profile_id]:
            if constituent.created_reason == REVIEWED_PROFILE_REASON:
                has_reviewed_constituent = True
                continue
            promotion = database.get_speaker_profile_discovery_promotion(
                constituent.id
            )
            confirmations = (
                database.list_speaker_profile_candidate_confirmations(
                    constituent.id
                )
                if promotion is not None
                else []
            )
            if promotion is None:
                discovery_blockers.append(
                    "discovery_promotion_provenance_missing"
                )
                continue
            if not confirmations:
                discovery_blockers.append("discovery_candidate_unconfirmed")
                continue
            certified_observation_ids.update(
                _certified_discovery_observation_ids(
                    promotion,
                    confirmations,
                    member_ids=frozenset(member_ids),
                )
            )

        certified_recording_ids = {
            observations[observation_id].video_id
            for observation_id in certified_observation_ids
            if observation_id in observations
        }
        has_certified_core = (
            len(certified_observation_ids) >= minimum_members
            and len(certified_recording_ids) >= minimum_members
        )
        automatic_blockers = list(shadow_blockers)
        if not has_certified_core:
            automatic_blockers.extend(discovery_blockers)
            if has_reviewed_constituent:
                automatic_blockers.extend(
                    _review_graph_blockers(
                        fingerprints,
                        profile_edges,
                    )
                )
            if (
                discovery_blockers
                and "discovery_promotion_provenance_missing"
                in discovery_blockers
            ):
                shadow_blockers.append(
                    "discovery_promotion_provenance_missing"
                )
        shadow_blockers = list(dict.fromkeys(shadow_blockers))
        automatic_blockers = list(dict.fromkeys(automatic_blockers))
        review_ready = (
            len(member_ids) >= 2
            and len(video_ids) >= 2
            and not any(
                blocker
                not in {
                    "fewer_than_three_profile_members",
                    "fewer_than_three_distinct_recordings",
                }
                for blocker in shadow_blockers
            )
        )
        readiness.append(
            ProfileAssociationReadiness(
                profile_id=profile_id,
                member_observation_ids=member_ids,
                member_fingerprints=fingerprints,
                recording_count=len(video_ids),
                source_count=len(source_ids),
                normalized_names=names,
                shadow_ready=not shadow_blockers,
                automatic_profile_ready=not automatic_blockers,
                shadow_blockers=tuple(shadow_blockers),
                automatic_blockers=tuple(automatic_blockers),
                review_ready=review_ready,
                certified_exemplar_observation_ids=(
                    tuple(sorted(certified_observation_ids))
                    if has_certified_core
                    else ()
                ),
            )
        )
    profile_ids_by_name: dict[str, list[int]] = defaultdict(list)
    for item in readiness:
        if len(item.normalized_names) == 1:
            profile_ids_by_name[item.normalized_names[0]].append(
                item.profile_id
            )
    duplicate_name_profile_ids = {
        profile_id
        for profile_ids in profile_ids_by_name.values()
        if len(profile_ids) > 1
        for profile_id in profile_ids
    }
    readiness = [
        replace(
            item,
            review_ready=False,
            shadow_ready=False,
            automatic_profile_ready=False,
            shadow_blockers=tuple(
                dict.fromkeys(
                    (
                        *item.shadow_blockers,
                        "attribution_spans_multiple_profiles",
                    )
                )
            ),
            automatic_blockers=tuple(
                dict.fromkeys(
                    (
                        *item.automatic_blockers,
                        "attribution_spans_multiple_profiles",
                    )
                )
            ),
        )
        if item.profile_id in duplicate_name_profile_ids
        else item
        for item in readiness
    ]
    return tuple(readiness)


def select_profile_exemplars(
    readiness: ProfileAssociationReadiness,
    eligible_exemplars: Sequence[ShadowExemplar],
    *,
    videos_by_id: Mapping[int, object],
    maximum_exemplars: int = 3,
) -> tuple[ShadowExemplar, ...]:
    if maximum_exemplars < 2:
        raise ValueError("shadow association requires at least two exemplars")
    allowed_observation_ids = (
        readiness.certified_exemplar_observation_ids
        if (
            readiness.automatic_profile_ready
            and readiness.certified_exemplar_observation_ids
        )
        else readiness.member_observation_ids
    )
    candidates = [
        exemplar
        for exemplar in eligible_exemplars
        if (
            exemplar.profile_id == readiness.profile_id
            and exemplar.observation.id in allowed_observation_ids
        )
    ]
    candidates.sort(
        key=lambda exemplar: (
            getattr(
                videos_by_id.get(exemplar.observation.video_id),
                "source_id",
                -1,
            ),
            exemplar.observation.video_id,
            exemplar.observation.id,
        )
    )
    selected: list[ShadowExemplar] = []
    used_sources: set[int] = set()
    for exemplar in candidates:
        source_id = getattr(
            videos_by_id.get(exemplar.observation.video_id),
            "source_id",
            -1,
        )
        if source_id in used_sources:
            continue
        selected.append(exemplar)
        used_sources.add(source_id)
        if len(selected) == maximum_exemplars:
            return tuple(selected)
    for exemplar in candidates:
        if exemplar in selected:
            continue
        selected.append(exemplar)
        if len(selected) == maximum_exemplars:
            break
    return tuple(selected)


def evaluate_shadow_association(
    *,
    candidate: SpeakerObservation,
    candidate_audio_path: Path,
    candidate_audio_sha256: str,
    candidate_normalized_names: Sequence[str],
    profiles: Sequence[
        tuple[ProfileAssociationReadiness, Sequence[ShadowExemplar]]
    ],
    compare: PairComparer,
    policy_spec: ShadowPolicySpec,
    model_fingerprint: str,
    minimum_same_exemplars: int = 2,
    reviewed_difference_pairs: Sequence[tuple[int, int]] = (),
    span_selection: Mapping[str, Any] | None = None,
    routing: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if minimum_same_exemplars < 2:
        raise ValueError("a shadow match requires at least two same exemplars")
    if not candidate_audio_sha256:
        raise ValueError("candidate normalized audio requires a SHA-256")
    reviewed_differences = {
        tuple(sorted(pair)) for pair in reviewed_difference_pairs
    }
    profile_results: list[dict[str, Any]] = []
    for readiness, exemplars in profiles:
        comparisons: list[dict[str, Any]] = []
        for exemplar in exemplars:
            if exemplar.observation.id == candidate.id:
                continue
            pair = tuple(sorted((candidate.id, exemplar.observation.id)))
            if pair in reviewed_differences:
                comparisons.append(
                    {
                        "exemplar_observation_id": exemplar.observation.id,
                        "exemplar_fingerprint": exemplar.observation.input_fingerprint,
                        "exemplar_normalized_audio_sha256": exemplar.audio_sha256,
                        "outcome": PairOutcome.DIFFERENT_SPEAKER,
                        "reason": "reviewed_different_speaker_constraint",
                        "reviewed_constraint": True,
                    }
                )
                continue
            result = dict(
                compare(
                    candidate,
                    exemplar.observation,
                    candidate_audio_path,
                    exemplar.audio_path,
                )
            )
            comparisons.append(
                {
                    "exemplar_observation_id": exemplar.observation.id,
                    "exemplar_fingerprint": exemplar.observation.input_fingerprint,
                    "exemplar_normalized_audio_sha256": exemplar.audio_sha256,
                    **result,
                }
            )
        counts = {
            outcome.value: sum(
                str(comparison.get("outcome")) == outcome.value
                for comparison in comparisons
            )
            for outcome in PairOutcome
        }
        profile_results.append(
            {
                "profile_id": readiness.profile_id,
                "profile_readiness": {
                    "review_ready": readiness.review_ready,
                    "shadow_ready": readiness.shadow_ready,
                    "automatic_profile_ready": readiness.automatic_profile_ready,
                    "certified_exemplar_observation_ids": list(
                        readiness.certified_exemplar_observation_ids
                    ),
                    "automatic_blockers": list(readiness.automatic_blockers),
                },
                "normalized_names": list(readiness.normalized_names),
                "comparison_counts": counts,
                "comparisons": comparisons,
                "meets_multi_exemplar_match": (
                    counts[PairOutcome.SAME_SPEAKER] >= minimum_same_exemplars
                    and counts[PairOutcome.DIFFERENT_SPEAKER] == 0
                    and counts[PairOutcome.ANALYSIS_FAILED] == 0
                ),
            }
        )

    matching_profiles = [
        result for result in profile_results if result["meets_multi_exemplar_match"]
    ]
    any_failure = any(
        result["comparison_counts"][PairOutcome.ANALYSIS_FAILED] > 0
        for result in profile_results
    )
    candidate_names = {
        normalized_name.strip()
        for normalized_name in candidate_normalized_names
        if normalized_name.strip()
    }
    proposed_profile_id: int | None = None
    reason: str
    if any_failure:
        outcome = "analysis_failed"
        reason = "one_or_more_profile_comparisons_failed"
    elif len(matching_profiles) > 1:
        outcome = "ambiguous"
        reason = "multiple_profiles_meet_multi_exemplar_match"
    elif len(matching_profiles) == 1:
        matched = matching_profiles[0]
        profile_names = set(matched["normalized_names"])
        if candidate_names and profile_names and candidate_names != profile_names:
            outcome = "conflicting_attribution"
            reason = "candidate_name_conflicts_with_acoustic_profile"
        else:
            outcome = "proposed_match"
            reason = "unique_multi_exemplar_same_speaker_match"
            proposed_profile_id = int(matched["profile_id"])
    elif profile_results and all(
        result["comparison_counts"][PairOutcome.DIFFERENT_SPEAKER]
        >= minimum_same_exemplars
        for result in profile_results
    ):
        outcome = "no_match"
        reason = "multiple_different_speaker_results_for_every_profile"
    else:
        outcome = "insufficient_evidence"
        reason = "no_profile_meets_multi_exemplar_match"

    sermon_window_quality_flags: list[dict[str, Any]] = []
    if isinstance(span_selection, Mapping):
        candidate_selection = span_selection.get("candidate_selection")
        if isinstance(candidate_selection, Mapping):
            raw_flags = candidate_selection.get(
                "sermon_window_quality_flags"
            )
            if isinstance(raw_flags, Sequence) and not isinstance(
                raw_flags, (str, bytes)
            ):
                sermon_window_quality_flags = [
                    dict(flag) for flag in raw_flags
                    if isinstance(flag, Mapping)
                ]

    report = {
        "schema_version": 1,
        "association_version": SHADOW_ASSOCIATION_VERSION,
        "input_fingerprint_version": SHADOW_ASSOCIATION_FINGERPRINT_VERSION,
        "artifact_kind": "speaker_profile_shadow_association",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "shadow_mode": True,
        "registry_mutation_allowed": False,
        "automatic_assignment_allowed": False,
        "candidate": {
            "observation_id": candidate.id,
            "video_id": candidate.video_id,
            "input_fingerprint": candidate.input_fingerprint,
            "normalized_audio_sha256": candidate_audio_sha256,
            "normalized_names": sorted(candidate_names),
        },
        "model_fingerprint": model_fingerprint,
        "policy": {
            "version": policy_spec.policy.version,
            "review_status": policy_spec.review_status,
            "artifact_sha256": policy_spec.artifact_sha256,
            "automatic_use_allowed": policy_spec.automatic_use_allowed,
        },
        "minimum_same_exemplars": minimum_same_exemplars,
        "routing": (
            dict(routing)
            if routing is not None
            else {
                "route": "legacy_exhaustive",
                "exhaustive": True,
                "priority_profile_ids": [],
                "shortlisted_profile_ids": [
                    readiness.profile_id for readiness, _ in profiles
                ],
                "total_routable_profiles": len(profiles),
            }
        ),
        "span_selection": dict(span_selection) if span_selection else None,
        "sermon_window_quality_flags": sermon_window_quality_flags,
        "outcome": outcome,
        "reason": reason,
        "proposed_profile_id": proposed_profile_id,
        "profiles": profile_results,
    }
    report["input_fingerprint"] = build_shadow_association_input_fingerprint(
        candidate=candidate,
        candidate_audio_sha256=candidate_audio_sha256,
        candidate_normalized_names=sorted(candidate_names),
        profiles=profiles,
        policy_spec=policy_spec,
        model_fingerprint=model_fingerprint,
        minimum_same_exemplars=minimum_same_exemplars,
        reviewed_difference_pairs=reviewed_difference_pairs,
        span_selection=report["span_selection"],
        routing=report["routing"],
    )
    report["result_sha256"] = _sha256_json(report)
    return report


def build_shadow_association_input_fingerprint(
    *,
    candidate: SpeakerObservation,
    candidate_audio_sha256: str,
    candidate_normalized_names: Sequence[str],
    profiles: Sequence[
        tuple[ProfileAssociationReadiness, Sequence[ShadowExemplar]]
    ],
    policy_spec: ShadowPolicySpec,
    model_fingerprint: str,
    minimum_same_exemplars: int,
    reviewed_difference_pairs: Sequence[tuple[int, int]] = (),
    span_selection: Mapping[str, Any] | None = None,
    routing: Mapping[str, Any] | None = None,
) -> str:
    reviewed_differences = {
        tuple(sorted(pair)) for pair in reviewed_difference_pairs
    }
    candidate_payload = {
        "observation_id": candidate.id,
        "video_id": candidate.video_id,
        "input_fingerprint": candidate.input_fingerprint,
        "normalized_audio_sha256": candidate_audio_sha256,
        "normalized_names": sorted(
            name.strip()
            for name in candidate_normalized_names
            if name.strip()
        ),
    }
    policy_payload = {
        "version": policy_spec.policy.version,
        "review_status": policy_spec.review_status,
        "artifact_sha256": policy_spec.artifact_sha256,
        "automatic_use_allowed": policy_spec.automatic_use_allowed,
    }
    routing_payload = (
        dict(routing)
        if routing is not None
        else {
            "route": "legacy_exhaustive",
            "exhaustive": True,
            "priority_profile_ids": [],
            "shortlisted_profile_ids": [
                readiness.profile_id for readiness, _ in profiles
            ],
            "total_routable_profiles": len(profiles),
        }
    )
    return _sha256_json(
        {
            "association_version": SHADOW_ASSOCIATION_VERSION,
            "input_fingerprint_version": (
                SHADOW_ASSOCIATION_FINGERPRINT_VERSION
            ),
            "candidate": candidate_payload,
            "model_fingerprint": model_fingerprint,
            "policy": policy_payload,
            "minimum_same_exemplars": minimum_same_exemplars,
            "routing": routing_payload,
            "span_selection": dict(span_selection) if span_selection else None,
            "profile_inputs": [
                {
                    "readiness": asdict(readiness),
                    "exemplars": [
                        {
                            "observation_fingerprint": (
                                exemplar.observation.input_fingerprint
                            ),
                            "normalized_audio_sha256": exemplar.audio_sha256,
                            "reviewed_different_speaker_constraint": (
                                tuple(
                                    sorted(
                                        (
                                            candidate.id,
                                            exemplar.observation.id,
                                        )
                                    )
                                )
                                in reviewed_differences
                            ),
                        }
                        for exemplar in exemplars
                    ],
                }
                for readiness, exemplars in profiles
            ],
        }
    )


def load_reusable_shadow_association(
    output_root: Path,
    *,
    candidate_fingerprint: str,
    input_fingerprint: str,
) -> tuple[Path, dict[str, Any]] | None:
    destination = (
        output_root.expanduser().resolve()
        / candidate_fingerprint[:16]
        / f"{input_fingerprint}.json"
    )
    if not destination.exists():
        return None
    payload = json.loads(destination.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("cached shadow association must be an object")
    expected_result = payload.get("result_sha256")
    unhashed = dict(payload)
    unhashed.pop("result_sha256", None)
    if (
        payload.get("input_fingerprint") != input_fingerprint
        or not isinstance(expected_result, str)
        or _sha256_json(unhashed) != expected_result
    ):
        raise ValueError(
            f"cached shadow association failed verification: {destination}"
        )
    return destination, payload


def write_shadow_association(
    output_root: Path,
    report: Mapping[str, Any],
) -> Path:
    candidate = report.get("candidate")
    if not isinstance(candidate, Mapping):
        raise ValueError("shadow association report requires candidate metadata")
    candidate_fingerprint = str(candidate.get("input_fingerprint", ""))
    input_fingerprint = str(report.get("input_fingerprint", ""))
    if not candidate_fingerprint or not input_fingerprint:
        raise ValueError("shadow association report requires stable fingerprints")
    destination = (
        output_root.expanduser().resolve()
        / candidate_fingerprint[:16]
        / f"{input_fingerprint}.json"
    )
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if destination.exists():
        if destination.read_text(encoding="utf-8") != encoded:
            raise ValueError(
                f"shadow association fingerprint collision: {destination}"
            )
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(encoded, encoding="utf-8")
    return destination


def write_shadow_association_admission(
    output_root: Path,
    *,
    observation: SpeakerObservation,
    youtube_video_id: str,
    stage: str,
    reason_code: str,
    evidence: Mapping[str, Any] | None = None,
) -> Path:
    """Persist a fail-closed candidate-admission outcome idempotently."""
    if not stage or not reason_code:
        raise ValueError("association admission requires stage and reason code")
    stable_input = {
        "admission_version": SHADOW_ASSOCIATION_ADMISSION_VERSION,
        "candidate": {
            "video_id": observation.video_id,
            "youtube_video_id": youtube_video_id,
            "observation_id": observation.id,
            "input_fingerprint": observation.input_fingerprint,
            "extraction_result_id": observation.extraction_result_id,
        },
        "stage": stage,
        "reason_code": reason_code,
        "evidence": dict(evidence or {}),
    }
    input_fingerprint = _sha256_json(stable_input)
    destination = (
        output_root.expanduser().resolve()
        / observation.input_fingerprint[:16]
        / f"admission-{input_fingerprint}.json"
    )
    if destination.exists():
        payload = json.loads(destination.read_text(encoding="utf-8"))
        if (
            not isinstance(payload, dict)
            or payload.get("input_fingerprint") != input_fingerprint
            or payload.get("stable_input") != stable_input
        ):
            raise ValueError(
                f"association admission fingerprint collision: {destination}"
            )
        return destination
    payload = {
        "schema_version": 1,
        "artifact_kind": "speaker_profile_shadow_association_admission",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "input_fingerprint": input_fingerprint,
        "stable_input": stable_input,
        **stable_input,
    }
    payload["result_sha256"] = _sha256_json(payload)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return destination


def readiness_payload(
    readiness: Sequence[ProfileAssociationReadiness],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "association_version": SHADOW_ASSOCIATION_VERSION,
        "shadow_mode": True,
        "registry_mutation_allowed": False,
        "profiles": [asdict(item) for item in readiness],
        "counts": {
            "profiles": len(readiness),
            "review_ready": sum(item.review_ready for item in readiness),
            "shadow_ready": sum(item.shadow_ready for item in readiness),
            "automatic_profile_ready": sum(
                item.automatic_profile_ready for item in readiness
            ),
        },
    }


def summarize_shadow_associations(
    database: Database,
    reports: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    outcome_counts: dict[str, int] = {}
    validation_counts = {
        "confirmed_proposal": 0,
        "contradicted_proposal": 0,
        "pending_proposal": 0,
        "resolved_abstention": 0,
        "pending_abstention": 0,
        "invalid_artifact": 0,
    }
    cases: list[dict[str, Any]] = []
    different_pairs = {
        tuple(sorted(pair))
        for pair in database.list_effective_observation_difference_pairs()
    }
    for report in reports:
        candidate = report.get("candidate")
        if (
            report.get("artifact_kind")
            != "speaker_profile_shadow_association"
            or report.get("shadow_mode") is not True
            or report.get("registry_mutation_allowed") is not False
            or not isinstance(candidate, Mapping)
        ):
            validation_counts["invalid_artifact"] += 1
            continue
        outcome = str(report.get("outcome", "unknown"))
        outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1
        observation_id = candidate.get("observation_id")
        fingerprint = candidate.get("input_fingerprint")
        observation = (
            database.get_speaker_observation(int(observation_id))
            if isinstance(observation_id, int)
            else None
        )
        if observation is None or observation.input_fingerprint != fingerprint:
            validation_counts["invalid_artifact"] += 1
            continue
        memberships = {
            database.resolve_speaker_profile_id(profile_id)
            for profile_id in database.list_effective_profile_ids_for_observation(
                observation.id
            )
        }
        proposed_profile_id = report.get("proposed_profile_id")
        validation_status: str
        if outcome == "proposed_match" and isinstance(proposed_profile_id, int):
            try:
                canonical_proposed = database.resolve_speaker_profile_id(
                    proposed_profile_id
                )
            except ValueError:
                canonical_proposed = proposed_profile_id
            proposed_members = database.list_effective_observation_ids_for_profile(
                canonical_proposed
            )
            explicitly_different = any(
                tuple(sorted((observation.id, member_id))) in different_pairs
                for member_id in proposed_members
            )
            if canonical_proposed in memberships:
                validation_status = "confirmed_proposal"
            elif memberships or explicitly_different:
                validation_status = "contradicted_proposal"
            else:
                validation_status = "pending_proposal"
        elif memberships:
            validation_status = "resolved_abstention"
        else:
            validation_status = "pending_abstention"
        validation_counts[validation_status] += 1
        cases.append(
            {
                "candidate_observation_id": observation.id,
                "candidate_fingerprint": observation.input_fingerprint,
                "shadow_outcome": outcome,
                "proposed_profile_id": proposed_profile_id,
                "effective_profile_ids": sorted(memberships),
                "validation_status": validation_status,
            }
        )
    decided_proposals = (
        validation_counts["confirmed_proposal"]
        + validation_counts["contradicted_proposal"]
    )
    return {
        "schema_version": 1,
        "association_version": SHADOW_ASSOCIATION_VERSION,
        "artifact_kind": "speaker_profile_shadow_association_summary",
        "registry_mutation_allowed": False,
        "report_count": len(reports),
        "outcome_counts": outcome_counts,
        "validation_counts": validation_counts,
        "decided_proposal_precision": (
            validation_counts["confirmed_proposal"] / decided_proposals
            if decided_proposals
            else None
        ),
        "cases": cases,
    }


def _review_graph_blockers(
    fingerprints: Sequence[str],
    edges: set[frozenset[str]],
) -> list[str]:
    if len(fingerprints) < 3:
        return ["fewer_than_three_reviewed_members"]
    adjacency = {fingerprint: set() for fingerprint in fingerprints}
    for edge in edges:
        left, right = tuple(edge)
        if left in adjacency and right in adjacency:
            adjacency[left].add(right)
            adjacency[right].add(left)
    visited: set[str] = set()
    pending = [fingerprints[0]]
    while pending:
        current = pending.pop()
        if current in visited:
            continue
        visited.add(current)
        pending.extend(adjacency[current] - visited)
    blockers: list[str] = []
    if visited != set(fingerprints):
        blockers.append("reviewed_same_graph_disconnected")
    elif _has_bridge(adjacency):
        blockers.append("reviewed_same_graph_contains_bridge")
    return blockers


def _review_graph_certified_nodes(
    fingerprints: Sequence[str],
    edges: set[frozenset[str]],
    *,
    minimum_members: int,
) -> frozenset[str]:
    """Return members supported by a redundant reviewed-same core.

    Bridges may connect a certified core to newly reviewed members or another
    certified core, but those bridge edges do not make either core less
    trustworthy. Removing bridges leaves the independently reinforced pieces.
    """
    adjacency = {fingerprint: set() for fingerprint in fingerprints}
    for edge in edges:
        left, right = tuple(edge)
        if left in adjacency and right in adjacency:
            adjacency[left].add(right)
            adjacency[right].add(left)
    bridges = _bridge_edges(adjacency)
    certified: set[str] = set()
    unseen = set(adjacency)
    while unseen:
        start = min(unseen)
        component: set[str] = set()
        pending = [start]
        while pending:
            current = pending.pop()
            if current in component:
                continue
            component.add(current)
            unseen.discard(current)
            pending.extend(
                neighbor
                for neighbor in adjacency[current]
                if frozenset((current, neighbor)) not in bridges
                and neighbor not in component
            )
        if len(component) >= minimum_members:
            certified.update(component)
    return frozenset(certified)


def _certified_discovery_observation_ids(
    promotion: Mapping[str, object],
    confirmations: Sequence[Mapping[str, object]],
    *,
    member_ids: frozenset[int],
) -> frozenset[int]:
    try:
        raw_seed_ids = json.loads(str(promotion["seed_observation_ids_json"]))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        raw_seed_ids = []
    certified = {
        int(observation_id)
        for observation_id in raw_seed_ids
        if isinstance(observation_id, int) and observation_id in member_ids
    }
    certified.update(
        int(confirmation["observation_id"])
        for confirmation in confirmations
        if (
            isinstance(confirmation.get("observation_id"), int)
            and int(confirmation["observation_id"]) in member_ids
        )
    )
    return frozenset(certified)


def _bridge_edges(
    adjacency: Mapping[str, set[str]],
) -> frozenset[frozenset[str]]:
    discovery: dict[str, int] = {}
    low: dict[str, int] = {}
    parent: dict[str, str | None] = {}
    time = 0
    bridges: set[frozenset[str]] = set()

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


def _has_bridge(adjacency: Mapping[str, set[str]]) -> bool:
    return bool(_bridge_edges(adjacency))


def _sha256_json(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
