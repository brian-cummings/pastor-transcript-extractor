from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, replace
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from pastor_transcript_extractor.models import SpeakerObservation
from pastor_transcript_extractor.reviewed_speaker_evidence import (
    ReviewedSpeakerEvidence,
)
from pastor_transcript_extractor.speaker_pair_diagnostics import (
    DecisionPolicy,
    PairOutcome,
    SpanSpec,
)
from pastor_transcript_extractor.storage import Database


SHADOW_ASSOCIATION_VERSION = "speaker_shadow_association_v2"
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


@dataclass(frozen=True, slots=True)
class ShadowExemplar:
    profile_id: int
    observation: SpeakerObservation
    audio_path: Path
    span_specs: tuple[SpanSpec, ...] = ()


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
    for profile in profiles:
        canonical_id = database.resolve_speaker_profile_id(profile.id)
        if canonical_id in canonical_ids:
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
        automatic_blockers = list(shadow_blockers)
        profile = next(item for item in profiles if item.id == profile_id)
        if profile.created_reason == DISCOVERY_PROFILE_REASON:
            promotion = database.get_speaker_profile_discovery_promotion(
                profile_id
            )
            confirmations = (
                database.list_speaker_profile_candidate_confirmations(
                    profile_id
                )
                if promotion is not None
                else []
            )
            if promotion is None:
                shadow_blockers.append("discovery_promotion_provenance_missing")
                automatic_blockers.append(
                    "discovery_promotion_provenance_missing"
                )
            if not confirmations:
                automatic_blockers.append(
                    "discovery_candidate_unconfirmed"
                )
        else:
            automatic_blockers.extend(
                _review_graph_blockers(
                    fingerprints,
                    profile_edges,
                )
            )
        shadow_blockers = list(dict.fromkeys(shadow_blockers))
        automatic_blockers = list(dict.fromkeys(automatic_blockers))
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
    candidates = [
        exemplar
        for exemplar in eligible_exemplars
        if (
            exemplar.profile_id == readiness.profile_id
            and exemplar.observation.id in readiness.member_observation_ids
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
) -> dict[str, Any]:
    if minimum_same_exemplars < 2:
        raise ValueError("a shadow match requires at least two same exemplars")
    reviewed_differences = {
        tuple(sorted(pair)) for pair in reviewed_difference_pairs
    }
    profile_results: list[dict[str, Any]] = []
    for readiness, exemplars in profiles:
        comparisons: list[dict[str, Any]] = []
        for exemplar in exemplars:
            pair = tuple(sorted((candidate.id, exemplar.observation.id)))
            if pair in reviewed_differences:
                comparisons.append(
                    {
                        "exemplar_observation_id": exemplar.observation.id,
                        "exemplar_fingerprint": exemplar.observation.input_fingerprint,
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
                    "shadow_ready": readiness.shadow_ready,
                    "automatic_profile_ready": readiness.automatic_profile_ready,
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

    report = {
        "schema_version": 1,
        "association_version": SHADOW_ASSOCIATION_VERSION,
        "artifact_kind": "speaker_profile_shadow_association",
        "shadow_mode": True,
        "registry_mutation_allowed": False,
        "automatic_assignment_allowed": False,
        "candidate": {
            "observation_id": candidate.id,
            "video_id": candidate.video_id,
            "input_fingerprint": candidate.input_fingerprint,
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
        "span_selection": dict(span_selection) if span_selection else None,
        "outcome": outcome,
        "reason": reason,
        "proposed_profile_id": proposed_profile_id,
        "profiles": profile_results,
    }
    report["input_fingerprint"] = _sha256_json(
        {
            "association_version": SHADOW_ASSOCIATION_VERSION,
            "candidate": report["candidate"],
            "model_fingerprint": model_fingerprint,
            "policy": report["policy"],
            "minimum_same_exemplars": minimum_same_exemplars,
            "span_selection": report["span_selection"],
            "profile_inputs": [
                {
                    "profile_id": result["profile_id"],
                    "exemplars": [
                        comparison["exemplar_fingerprint"]
                        for comparison in result["comparisons"]
                    ],
                }
                for result in profile_results
            ],
        }
    )
    report["result_sha256"] = _sha256_json(report)
    return report


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


def _has_bridge(adjacency: Mapping[str, set[str]]) -> bool:
    discovery: dict[str, int] = {}
    low: dict[str, int] = {}
    parent: dict[str, str | None] = {}
    time = 0
    found_bridge = False

    def visit(node: str) -> None:
        nonlocal time, found_bridge
        time += 1
        discovery[node] = low[node] = time
        for neighbor in adjacency[node]:
            if neighbor not in discovery:
                parent[neighbor] = node
                visit(neighbor)
                low[node] = min(low[node], low[neighbor])
                if low[neighbor] > discovery[node]:
                    found_bridge = True
            elif parent.get(node) != neighbor:
                low[node] = min(low[node], discovery[neighbor])

    for node in adjacency:
        if node not in discovery:
            parent[node] = None
            visit(node)
    return found_bridge


def _sha256_json(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
