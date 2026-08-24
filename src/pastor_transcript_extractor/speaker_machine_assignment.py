from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from pastor_transcript_extractor.media_artifacts import MediaVerificationCache
from pastor_transcript_extractor.speaker_pair_eligibility import (
    assess_automatic_speaker_observation,
)
from pastor_transcript_extractor.speaker_profile_discovery import (
    TRANSCRIPT_GROUNDED_SPAN_SELECTION_VERSION,
)
from pastor_transcript_extractor.speaker_shadow_association import (
    ProfileAssociationReadiness,
    SHADOW_ASSOCIATION_VERSION,
)
from pastor_transcript_extractor.storage import Database


MACHINE_ASSIGNMENT_VERSION = "speaker_machine_assignment_v1"
MACHINE_ASSIGNMENT_ACTOR = "system:speaker-machine-assignment-v1"


@dataclass(frozen=True, slots=True)
class MachineAssignmentPolicy:
    version: str
    mode: str
    minimum_same_exemplars: int
    require_unique_profile: bool
    require_automatic_profile_ready: bool
    allow_provisional_activation: bool
    artifact_sha256: str
    maximum_active_assignments: int = 0
    allowed_association_policy_sha256: tuple[str, ...] = ()
    allowed_model_fingerprints: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MachineAssignmentCandidate:
    observation_id: int
    profile_id: int
    candidate_input_fingerprint: str
    association_result_sha256: str
    association_artifact_path: str
    model_fingerprint: str
    policy_fingerprint: str
    profile_snapshot_fingerprint: str
    exemplar_fingerprints: tuple[str, ...]
    same_exemplar_count: int
    different_exemplar_count: int
    evidence_fingerprint: str


@dataclass(frozen=True, slots=True)
class MachineAssignmentPlan:
    policy: MachineAssignmentPolicy
    candidates: tuple[MachineAssignmentCandidate, ...]
    skipped_counts: Mapping[str, int]
    tripped_policy_fingerprints: frozenset[str]


@dataclass(frozen=True, slots=True)
class MachineAssignmentApplyResult:
    evidence_recorded: int
    evidence_reused: int
    assignments_activated: int
    activation_blocked: int


@dataclass(frozen=True, slots=True)
class MachineAssignmentReconciliationResult:
    confirmed: int
    revoked: int
    circuit_breaker_revoked: int
    unchanged: int
    tripped_policy_fingerprints: tuple[str, ...]


def load_machine_assignment_policy(path: Path) -> MachineAssignmentPolicy:
    resolved = path.expanduser().resolve()
    raw = resolved.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("machine-assignment policy must be an object")
    version = payload.get("policy_version")
    mode = payload.get("mode")
    minimum = payload.get("minimum_same_exemplars")
    maximum_active = payload.get("maximum_active_assignments", 0)
    allowed_policy_hashes = payload.get(
        "allowed_association_policy_sha256", []
    )
    allowed_model_fingerprints = payload.get(
        "allowed_model_fingerprints", []
    )
    if (
        not isinstance(version, str)
        or not version
        or mode not in {"shadow", "canary_provisional"}
        or not isinstance(minimum, int)
        or minimum < 2
        or payload.get("require_unique_profile") is not True
        or payload.get("require_automatic_profile_ready") is not True
        or not isinstance(payload.get("allow_provisional_activation"), bool)
        or not isinstance(maximum_active, int)
        or maximum_active < 0
        or not _is_string_list(allowed_policy_hashes)
        or not _is_string_list(allowed_model_fingerprints)
    ):
        raise ValueError("machine-assignment policy contract is invalid")
    if mode == "shadow" and payload["allow_provisional_activation"] is True:
        raise ValueError("shadow policy cannot permit provisional activation")
    if mode == "canary_provisional" and (
        payload["allow_provisional_activation"] is not True
        or maximum_active < 1
        or not allowed_policy_hashes
        or not allowed_model_fingerprints
    ):
        raise ValueError(
            "canary policy must cap assignments and pin approved association "
            "policy and model fingerprints"
        )
    return MachineAssignmentPolicy(
        version=version,
        mode=mode,
        minimum_same_exemplars=minimum,
        require_unique_profile=True,
        require_automatic_profile_ready=True,
        allow_provisional_activation=bool(
            payload["allow_provisional_activation"]
        ),
        artifact_sha256=hashlib.sha256(raw).hexdigest(),
        maximum_active_assignments=maximum_active,
        allowed_association_policy_sha256=tuple(
            sorted(allowed_policy_hashes)
        ),
        allowed_model_fingerprints=tuple(
            sorted(allowed_model_fingerprints)
        ),
    )


def plan_machine_assignments(
    database: Database,
    report_paths: Iterable[Path],
    *,
    readiness: Sequence[ProfileAssociationReadiness],
    policy: MachineAssignmentPolicy,
    verification_cache: MediaVerificationCache | None = None,
    excluded_observation_fingerprints: frozenset[str] = frozenset(),
    included_observation_ids: frozenset[int] | None = None,
) -> MachineAssignmentPlan:
    readiness_by_profile = {
        item.profile_id: item
        for item in readiness
        if item.automatic_profile_ready
    }
    evidence_rows = database.list_speaker_machine_evidence()
    evidence_by_fingerprint = {
        str(row["evidence_fingerprint"]): row for row in evidence_rows
    }
    events = database.list_speaker_machine_assignment_events()
    latest_events = _latest_events_by_evidence(events)
    active_observation_ids = {
        int(event["observation_id"])
        for event in latest_events.values()
        if event["action"] == "activate"
    }
    tripped = _tripped_policy_fingerprints(evidence_rows, events)
    skipped: dict[str, int] = {}
    candidates_by_evidence: dict[str, MachineAssignmentCandidate] = {}
    for path in sorted(
        (item.expanduser().resolve() for item in report_paths), key=str
    ):
        try:
            report = _load_verified_association(path)
        except (OSError, ValueError, json.JSONDecodeError):
            _increment(skipped, "invalid_artifact")
            continue
        if report is None:
            _increment(skipped, "stale_or_nonproposal_artifact")
            continue
        candidate_payload = report.get("candidate")
        profile_id = report.get("proposed_profile_id")
        if not isinstance(candidate_payload, Mapping) or not isinstance(
            profile_id, int
        ):
            _increment(skipped, "invalid_proposal_target")
            continue
        try:
            canonical_profile_id = database.resolve_speaker_profile_id(
                profile_id
            )
        except ValueError:
            _increment(skipped, "profile_unavailable")
            continue
        if canonical_profile_id != profile_id:
            _increment(skipped, "profile_redirected_since_association")
            continue
        profile_readiness = readiness_by_profile.get(canonical_profile_id)
        if profile_readiness is None:
            _increment(skipped, "profile_not_automatic_ready")
            continue
        observation_id = candidate_payload.get("observation_id")
        candidate_fingerprint = candidate_payload.get("input_fingerprint")
        if not isinstance(observation_id, int) or not isinstance(
            candidate_fingerprint, str
        ):
            _increment(skipped, "candidate_identity_invalid")
            continue
        observation = database.get_speaker_observation(observation_id)
        if (
            included_observation_ids is not None
            and observation_id not in included_observation_ids
        ):
            _increment(skipped, "candidate_outside_run_scope")
            continue
        if (
            observation is None
            or observation.input_fingerprint != candidate_fingerprint
            or candidate_fingerprint in excluded_observation_fingerprints
        ):
            _increment(skipped, "candidate_stale_or_evaluation_reserved")
            continue
        eligibility = assess_automatic_speaker_observation(
            database,
            observation.video_id,
            verification_cache=verification_cache,
        )
        if (
            not eligibility.eligible
            or eligibility.observation is None
            or eligibility.observation.id != observation_id
        ):
            _increment(skipped, "candidate_not_current_accepted_sermon")
            continue
        candidate_audio_sha256 = candidate_payload.get(
            "normalized_audio_sha256"
        )
        if (
            not isinstance(candidate_audio_sha256, str)
            or eligibility.media_artifact is None
            or eligibility.media_artifact.content_sha256
            != candidate_audio_sha256
        ):
            _increment(skipped, "candidate_media_provenance_stale")
            continue
        if database.list_effective_profile_ids_for_observation(observation_id):
            _increment(skipped, "candidate_already_reviewed_profiled")
            continue
        if observation_id in active_observation_ids:
            _increment(skipped, "candidate_already_machine_assigned")
            continue
        target_member_ids = set(
            database.list_effective_observation_ids_for_profile(
                canonical_profile_id
            )
        )
        target_members = [
            database.get_speaker_observation(member_id)
            for member_id in sorted(target_member_ids)
        ]
        target_fingerprints = {
            member.input_fingerprint
            for member in target_members
            if member is not None
        }
        target_members_by_fingerprint = {
            member.input_fingerprint: member
            for member in target_members
            if member is not None
        }
        different_pairs = set(
            database.list_effective_observation_difference_pairs()
        )
        if any(
            tuple(sorted((observation_id, member_id))) in different_pairs
            for member_id in target_member_ids
        ):
            _increment(skipped, "reviewed_difference_against_profile")
            continue
        matched_profile = _matched_profile_result(report, profile_id)
        if matched_profile is None:
            _increment(skipped, "matched_profile_result_unavailable")
            continue
        comparisons = matched_profile.get("comparisons")
        if not isinstance(comparisons, list):
            _increment(skipped, "comparison_evidence_unavailable")
            continue
        same_fingerprints_set: set[str] = set()
        stale_exemplar = False
        for comparison in comparisons:
            if (
                not isinstance(comparison, Mapping)
                or comparison.get("outcome") != "same_speaker"
                or comparison.get("reason")
                != "approved_policy_same_band"
                or comparison.get("reviewed_constraint") is True
            ):
                continue
            exemplar = target_members_by_fingerprint.get(
                str(comparison.get("exemplar_fingerprint"))
            )
            exemplar_audio_sha256 = comparison.get(
                "exemplar_normalized_audio_sha256"
            )
            exemplar_eligibility = (
                assess_automatic_speaker_observation(
                    database,
                    exemplar.video_id,
                    verification_cache=verification_cache,
                )
                if exemplar is not None
                else None
            )
            if (
                exemplar is None
                or exemplar_eligibility is None
                or not exemplar_eligibility.eligible
                or exemplar_eligibility.observation is None
                or exemplar_eligibility.observation.id != exemplar.id
                or exemplar_eligibility.media_artifact is None
                or not isinstance(exemplar_audio_sha256, str)
                or exemplar_eligibility.media_artifact.content_sha256
                != exemplar_audio_sha256
            ):
                stale_exemplar = True
                break
            same_fingerprints_set.add(exemplar.input_fingerprint)
        if stale_exemplar:
            _increment(skipped, "same_exemplar_provenance_stale")
            continue
        same_fingerprints = tuple(sorted(same_fingerprints_set))
        different_count = sum(
            isinstance(comparison, Mapping)
            and comparison.get("outcome") == "different_speaker"
            for comparison in comparisons
        )
        failure_count = sum(
            isinstance(comparison, Mapping)
            and comparison.get("outcome") == "analysis_failed"
            for comparison in comparisons
        )
        if (
            len(same_fingerprints) < policy.minimum_same_exemplars
            or different_count
            or failure_count
        ):
            _increment(skipped, "multi_exemplar_gate_not_met")
            continue
        candidate_names = {
            claim.normalized_name
            for claim in database.list_speaker_name_claims_for_video(
                observation.video_id
            )
            if claim.observation_id == observation_id
            and claim.explicit_speaker_attribution
            and claim.normalized_name.strip()
        }
        profile_names = set(profile_readiness.normalized_names)
        if candidate_names and profile_names and candidate_names != profile_names:
            _increment(skipped, "current_attribution_conflict")
            continue
        model_fingerprint = report.get("model_fingerprint")
        association_policy = report.get("policy")
        if not isinstance(model_fingerprint, str) or not isinstance(
            association_policy, Mapping
        ):
            _increment(skipped, "model_or_policy_provenance_missing")
            continue
        association_policy_sha256 = association_policy.get("artifact_sha256")
        if policy.allowed_model_fingerprints and (
            model_fingerprint not in policy.allowed_model_fingerprints
        ):
            _increment(skipped, "model_not_allowed_by_machine_policy")
            continue
        if policy.allowed_association_policy_sha256 and (
            not isinstance(association_policy_sha256, str)
            or association_policy_sha256
            not in policy.allowed_association_policy_sha256
        ):
            _increment(
                skipped,
                "association_policy_not_allowed_by_machine_policy",
            )
            continue
        association_policy_fingerprint = _sha256(association_policy)
        profile_snapshot = _sha256(
            {
                "profile_id": canonical_profile_id,
                "member_fingerprints": sorted(target_fingerprints),
            }
        )
        stable = {
            "version": MACHINE_ASSIGNMENT_VERSION,
            "observation_id": observation_id,
            "profile_id": canonical_profile_id,
            "candidate_input_fingerprint": candidate_fingerprint,
            "association_result_sha256": report["result_sha256"],
            "model_fingerprint": model_fingerprint,
            "association_policy_fingerprint": (
                association_policy_fingerprint
            ),
            "machine_policy_artifact_sha256": policy.artifact_sha256,
            "profile_snapshot_fingerprint": profile_snapshot,
            "exemplar_fingerprints": list(same_fingerprints),
        }
        candidate = MachineAssignmentCandidate(
            observation_id=observation_id,
            profile_id=canonical_profile_id,
            candidate_input_fingerprint=candidate_fingerprint,
            association_result_sha256=str(report["result_sha256"]),
            association_artifact_path=str(path),
            model_fingerprint=model_fingerprint,
            policy_fingerprint=_sha256(
                {
                    "association_policy": association_policy_fingerprint,
                    "machine_policy": policy.artifact_sha256,
                }
            ),
            profile_snapshot_fingerprint=profile_snapshot,
            exemplar_fingerprints=same_fingerprints,
            same_exemplar_count=len(same_fingerprints),
            different_exemplar_count=different_count,
            evidence_fingerprint=_sha256(stable),
        )
        persisted = evidence_by_fingerprint.get(candidate.evidence_fingerprint)
        persisted_event = (
            latest_events.get(int(persisted["id"]))
            if persisted is not None
            else None
        )
        if persisted_event is not None and persisted_event["action"] in {
            "confirm",
            "revoke",
        }:
            _increment(skipped, "candidate_evidence_terminal")
            continue
        candidates_by_evidence[candidate.evidence_fingerprint] = candidate
    return MachineAssignmentPlan(
        policy=policy,
        candidates=tuple(
            sorted(
                candidates_by_evidence.values(),
                key=lambda item: (
                    item.profile_id,
                    item.candidate_input_fingerprint,
                    item.evidence_fingerprint,
                ),
            )
        ),
        skipped_counts=dict(sorted(skipped.items())),
        tripped_policy_fingerprints=tripped,
    )


def apply_machine_assignment_plan(
    database: Database,
    plan: MachineAssignmentPlan,
    *,
    activate_canary: bool,
) -> MachineAssignmentApplyResult:
    if activate_canary and not plan.policy.allow_provisional_activation:
        raise ValueError(
            "machine-assignment policy does not permit provisional activation"
        )
    existing_fingerprints = {
        str(row["evidence_fingerprint"])
        for row in database.list_speaker_machine_evidence()
    }
    latest_events = _latest_events_by_evidence(
        database.list_speaker_machine_assignment_events()
    )
    active_count = len(active_machine_assignment_evidence(database))
    recorded = reused = activated = blocked = 0
    for candidate in plan.candidates:
        evidence_id = database.add_speaker_machine_evidence(
            observation_id=candidate.observation_id,
            profile_id=candidate.profile_id,
            candidate_input_fingerprint=(
                candidate.candidate_input_fingerprint
            ),
            association_result_sha256=(
                candidate.association_result_sha256
            ),
            association_artifact_path=(
                candidate.association_artifact_path
            ),
            model_fingerprint=candidate.model_fingerprint,
            policy_fingerprint=candidate.policy_fingerprint,
            profile_snapshot_fingerprint=(
                candidate.profile_snapshot_fingerprint
            ),
            exemplar_fingerprints_json=json.dumps(
                candidate.exemplar_fingerprints,
                separators=(",", ":"),
            ),
            same_exemplar_count=candidate.same_exemplar_count,
            different_exemplar_count=candidate.different_exemplar_count,
            decision="proposed_match",
            evidence_fingerprint=candidate.evidence_fingerprint,
        )
        if candidate.evidence_fingerprint in existing_fingerprints:
            reused += 1
        else:
            recorded += 1
        if not activate_canary:
            continue
        latest_event = latest_events.get(evidence_id)
        if latest_event is not None:
            blocked += 1
            continue
        if candidate.policy_fingerprint in plan.tripped_policy_fingerprints:
            blocked += 1
            continue
        if active_count >= plan.policy.maximum_active_assignments:
            blocked += 1
            continue
        event_key = _sha256(
            {
                "version": MACHINE_ASSIGNMENT_VERSION,
                "evidence_fingerprint": candidate.evidence_fingerprint,
                "action": "activate",
            }
        )
        database.add_speaker_machine_assignment_event(
            machine_evidence_id=evidence_id,
            observation_id=candidate.observation_id,
            profile_id=candidate.profile_id,
            action="activate",
            actor=MACHINE_ASSIGNMENT_ACTOR,
            reason=(
                "Policy-gated provisional assignment from a unique "
                "multi-exemplar shadow association"
            ),
            event_fingerprint=event_key,
        )
        activated += 1
        active_count += 1
    return MachineAssignmentApplyResult(
        evidence_recorded=recorded,
        evidence_reused=reused,
        assignments_activated=activated,
        activation_blocked=blocked,
    )


def reconcile_machine_assignments(
    database: Database,
    *,
    verification_cache: MediaVerificationCache | None = None,
) -> MachineAssignmentReconciliationResult:
    evidence_by_id = {
        int(row["id"]): row
        for row in database.list_speaker_machine_evidence()
    }
    events = database.list_speaker_machine_assignment_events()
    latest = _latest_events_by_evidence(events)
    active = [event for event in latest.values() if event["action"] == "activate"]
    confirmed = revoked = unchanged = 0
    newly_tripped: set[str] = set()
    for event in active:
        evidence = evidence_by_id.get(int(event["machine_evidence_id"]))
        if evidence is None:
            continue
        observation_id = int(event["observation_id"])
        profile_id = database.resolve_speaker_profile_id(int(event["profile_id"]))
        memberships = {
            database.resolve_speaker_profile_id(value)
            for value in database.list_effective_profile_ids_for_observation(
                observation_id
            )
        }
        action = None
        reason = None
        if profile_id in memberships:
            action = "confirm"
            reason = "Reviewed evidence confirmed provisional assignment"
            confirmed += 1
        elif memberships:
            action = "revoke"
            reason = "contradiction:reviewed_membership_targets_other_profile"
        else:
            target_members = database.list_effective_observation_ids_for_profile(
                profile_id
            )
            different_pairs = set(
                database.list_effective_observation_difference_pairs()
            )
            if any(
                tuple(sorted((observation_id, member_id))) in different_pairs
                for member_id in target_members
            ):
                action = "revoke"
                reason = "contradiction:reviewed_difference_against_profile"
            else:
                observation = database.get_speaker_observation(observation_id)
                eligibility = (
                    assess_automatic_speaker_observation(
                        database,
                        observation.video_id,
                        verification_cache=verification_cache,
                    )
                    if observation is not None
                    else None
                )
                if (
                    eligibility is None
                    or not eligibility.eligible
                    or eligibility.observation is None
                    or eligibility.observation.id != observation_id
                    or eligibility.observation.input_fingerprint
                    != evidence["candidate_input_fingerprint"]
                    or not _machine_evidence_provenance_current(
                        database,
                        evidence=evidence,
                        profile_id=profile_id,
                        eligibility=eligibility,
                        verification_cache=verification_cache,
                    )
                ):
                    action = "revoke"
                    reason = "stale:candidate_observation_no_longer_current"
        if action is None:
            unchanged += 1
            continue
        if action == "revoke":
            revoked += 1
            if str(reason).startswith("contradiction:"):
                newly_tripped.add(str(evidence["policy_fingerprint"]))
        _append_assignment_event(
            database,
            evidence=evidence,
            action=action,
            reason=str(reason),
        )
    circuit_revoked = 0
    if newly_tripped:
        events = database.list_speaker_machine_assignment_events()
        latest = _latest_events_by_evidence(events)
        for event in latest.values():
            if event["action"] != "activate":
                continue
            evidence = evidence_by_id.get(int(event["machine_evidence_id"]))
            if (
                evidence is None
                or evidence["policy_fingerprint"] not in newly_tripped
            ):
                continue
            _append_assignment_event(
                database,
                evidence=evidence,
                action="revoke",
                reason="circuit_breaker:policy_observed_false_attachment",
            )
            circuit_revoked += 1
    return MachineAssignmentReconciliationResult(
        confirmed=confirmed,
        revoked=revoked,
        circuit_breaker_revoked=circuit_revoked,
        unchanged=unchanged,
        tripped_policy_fingerprints=tuple(sorted(newly_tripped)),
    )


def rollback_machine_assignments(
    database: Database,
    *,
    policy_fingerprint: str,
) -> int:
    evidence_by_id = {
        int(row["id"]): row
        for row in database.list_speaker_machine_evidence()
    }
    latest = _latest_events_by_evidence(
        database.list_speaker_machine_assignment_events()
    )
    count = 0
    for event in latest.values():
        evidence = evidence_by_id.get(int(event["machine_evidence_id"]))
        if (
            event["action"] != "activate"
            or evidence is None
            or evidence["policy_fingerprint"] != policy_fingerprint
        ):
            continue
        _append_assignment_event(
            database,
            evidence=evidence,
            action="revoke",
            reason="manual_rollback:policy_fingerprint",
        )
        count += 1
    return count


def machine_assignment_status(database: Database) -> dict[str, object]:
    evidence = database.list_speaker_machine_evidence()
    events = database.list_speaker_machine_assignment_events()
    latest = _latest_events_by_evidence(events)
    counts = {"active": 0, "confirmed": 0, "revoked": 0, "evidence_only": 0}
    policy_counts: dict[str, dict[str, int]] = {}
    for row in evidence:
        event = latest.get(int(row["id"]))
        state = "evidence_only"
        if event is None:
            counts["evidence_only"] += 1
        elif event["action"] == "activate":
            counts["active"] += 1
            state = "active"
        elif event["action"] == "confirm":
            counts["confirmed"] += 1
            state = "confirmed"
        elif event["action"] == "revoke":
            counts["revoked"] += 1
            state = "revoked"
        policy_fingerprint = str(row["policy_fingerprint"])
        grouped = policy_counts.setdefault(
            policy_fingerprint,
            {"active": 0, "confirmed": 0, "revoked": 0, "evidence_only": 0},
        )
        grouped[state] += 1
    report = machine_assignment_report(database)
    return {
        "evidence_count": len(evidence),
        "event_count": len(events),
        "counts": counts,
        "policies": dict(sorted(policy_counts.items())),
        "tripped_policy_fingerprints": sorted(
            _tripped_policy_fingerprints(evidence, events)
        ),
        "current_counts": report["counts"],
        "profile_counts": report["profile_counts"],
        "assignments": report["assignments"],
        "policy_trips": report["policy_trips"],
    }


def machine_assignment_report(database: Database) -> dict[str, object]:
    """Project machine evidence into current sermon/profile associations."""
    evidence_rows = database.list_speaker_machine_evidence()
    events = database.list_speaker_machine_assignment_events()
    latest_events = _latest_events_by_evidence(events)
    tripped_policies = _tripped_policy_fingerprints(evidence_rows, events)
    evidence_by_id = {int(row["id"]): row for row in evidence_rows}
    observations_by_id = {
        observation.id: observation
        for observation in database.list_speaker_observations()
    }
    videos_by_id = {video.id: video for video in database.list_videos()}
    resolved_profiles: dict[int, int] = {}
    assignments: list[dict[str, object]] = []
    for evidence in evidence_rows:
        evidence_id = int(evidence["id"])
        observation_id = int(evidence["observation_id"])
        original_profile_id = int(evidence["profile_id"])
        profile_id = resolved_profiles.get(original_profile_id)
        if profile_id is None:
            try:
                profile_id = database.resolve_speaker_profile_id(
                    original_profile_id
                )
            except ValueError:
                profile_id = original_profile_id
            resolved_profiles[original_profile_id] = profile_id
        observation = observations_by_id.get(observation_id)
        video = (
            videos_by_id.get(observation.video_id)
            if observation is not None
            else None
        )
        event = latest_events.get(evidence_id)
        if event is None:
            if str(evidence["policy_fingerprint"]) in tripped_policies:
                state = "blocked_policy"
                reason = "policy_circuit_breaker_tripped"
            else:
                state = "awaiting_activation"
                reason = "machine_evidence_not_activated"
            event_created_at = None
        else:
            state = {
                "activate": "active",
                "confirm": "confirmed",
                "revoke": "revoked",
            }[str(event["action"])]
            reason = str(event["reason"])
            event_created_at = str(event["created_at"])
        assignments.append(
            {
                "machine_evidence_id": evidence_id,
                "observation_id": observation_id,
                "youtube_video_id": (
                    video.youtube_video_id if video is not None else None
                ),
                "video_title": video.title if video is not None else None,
                "original_profile_id": original_profile_id,
                "profile_id": profile_id,
                "state": state,
                "reason": reason,
                "policy_fingerprint": str(evidence["policy_fingerprint"]),
                "model_fingerprint": str(evidence["model_fingerprint"]),
                "association_artifact_path": str(
                    evidence["association_artifact_path"]
                ),
                "association_result_sha256": str(
                    evidence["association_result_sha256"]
                ),
                "same_exemplar_count": int(
                    evidence["same_exemplar_count"]
                ),
                "evidence_created_at": str(evidence["created_at"]),
                "event_created_at": event_created_at,
            }
        )

    state_precedence = {
        "confirmed": 5,
        "active": 4,
        "blocked_policy": 3,
        "awaiting_activation": 2,
        "revoked": 1,
    }
    current_by_association: dict[
        tuple[int, int], dict[str, object]
    ] = {}
    for assignment in assignments:
        key = (
            int(assignment["observation_id"]),
            int(assignment["profile_id"]),
        )
        persisted = current_by_association.get(key)
        assignment_rank = (
            state_precedence[str(assignment["state"])],
            str(
                assignment["event_created_at"]
                or assignment["evidence_created_at"]
            ),
            int(assignment["machine_evidence_id"]),
        )
        persisted_rank = (
            (
                state_precedence[str(persisted["state"])],
                str(
                    persisted["event_created_at"]
                    or persisted["evidence_created_at"]
                ),
                int(persisted["machine_evidence_id"]),
            )
            if persisted is not None
            else None
        )
        if persisted_rank is None or assignment_rank > persisted_rank:
            current_by_association[key] = assignment
    current = tuple(
        sorted(
            current_by_association.values(),
            key=lambda item: (
                int(item["profile_id"]),
                str(item["state"]),
                str(item["youtube_video_id"] or ""),
                int(item["observation_id"]),
            ),
        )
    )
    states = (
        "active",
        "awaiting_activation",
        "blocked_policy",
        "confirmed",
        "revoked",
    )
    counts = {
        state: sum(item["state"] == state for item in current)
        for state in states
    }
    profile_counts: dict[int, dict[str, int]] = {}
    for assignment in current:
        grouped = profile_counts.setdefault(
            int(assignment["profile_id"]),
            {state: 0 for state in states},
        )
        grouped[str(assignment["state"])] += 1

    policy_trips: list[dict[str, object]] = []
    for policy_fingerprint in sorted(tripped_policies):
        triggering_events = [
            event
            for event in events
            if str(event["reason"]).startswith("contradiction:")
            and (
                evidence := evidence_by_id.get(
                    int(event["machine_evidence_id"])
                )
            )
            is not None
            and str(evidence["policy_fingerprint"])
            == policy_fingerprint
        ]
        if not triggering_events:
            continue
        trigger = min(triggering_events, key=lambda item: int(item["id"]))
        trigger_observation = observations_by_id.get(
            int(trigger["observation_id"])
        )
        trigger_video = (
            videos_by_id.get(trigger_observation.video_id)
            if trigger_observation is not None
            else None
        )
        policy_trips.append(
            {
                "policy_fingerprint": policy_fingerprint,
                "reason": str(trigger["reason"]),
                "created_at": str(trigger["created_at"]),
                "observation_id": int(trigger["observation_id"]),
                "youtube_video_id": (
                    trigger_video.youtube_video_id
                    if trigger_video is not None
                    else None
                ),
                "profile_id": int(trigger["profile_id"]),
            }
        )
    return {
        "evidence_count": len(evidence_rows),
        "current_association_count": len(current),
        "counts": counts,
        "profile_counts": dict(sorted(profile_counts.items())),
        "assignments": current,
        "tripped_policy_fingerprints": tuple(sorted(tripped_policies)),
        "policy_trips": tuple(policy_trips),
    }


def active_machine_assignment_evidence(
    database: Database,
) -> tuple[dict[str, object], ...]:
    evidence_by_id = {
        int(row["id"]): row
        for row in database.list_speaker_machine_evidence()
    }
    latest = _latest_events_by_evidence(
        database.list_speaker_machine_assignment_events()
    )
    return tuple(
        dict(evidence_by_id[evidence_id])
        for evidence_id, event in sorted(latest.items())
        if event["action"] == "activate" and evidence_id in evidence_by_id
    )


def _load_verified_association(path: Path) -> dict[str, Any] | None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("association artifact must be an object")
    expected = payload.get("result_sha256")
    unhashed = dict(payload)
    unhashed.pop("result_sha256", None)
    if not isinstance(expected, str) or _sha256(unhashed) != expected:
        raise ValueError("association artifact checksum mismatch")
    if (
        payload.get("artifact_kind")
        != "speaker_profile_shadow_association"
        or payload.get("association_version") != SHADOW_ASSOCIATION_VERSION
    ):
        return None
    span_selection = payload.get("span_selection")
    if (
        payload.get("shadow_mode") is not True
        or payload.get("registry_mutation_allowed") is not False
        or payload.get("automatic_assignment_allowed") is not False
        or not isinstance(span_selection, Mapping)
        or span_selection.get("version")
        != TRANSCRIPT_GROUNDED_SPAN_SELECTION_VERSION
    ):
        raise ValueError("unsafe association artifact")
    if payload.get("outcome") != "proposed_match":
        return None
    routing = payload.get("routing")
    if routing is not None and (
        not isinstance(routing, Mapping)
        or routing.get("exhaustive") is not True
    ):
        return None
    return payload


def _machine_evidence_provenance_current(
    database: Database,
    *,
    evidence: Mapping[str, object],
    profile_id: int,
    eligibility: object,
    verification_cache: MediaVerificationCache | None,
) -> bool:
    try:
        report = _load_verified_association(
            Path(str(evidence["association_artifact_path"]))
        )
        exemplar_fingerprints = tuple(
            json.loads(str(evidence["exemplar_fingerprints_json"]))
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False
    if (
        report is None
        or report.get("result_sha256")
        != evidence["association_result_sha256"]
        or not all(
            isinstance(fingerprint, str)
            for fingerprint in exemplar_fingerprints
        )
    ):
        return False
    candidate = report.get("candidate")
    media_artifact = getattr(eligibility, "media_artifact", None)
    if (
        not isinstance(candidate, Mapping)
        or media_artifact is None
        or candidate.get("normalized_audio_sha256")
        != media_artifact.content_sha256
    ):
        return False
    member_ids = database.list_effective_observation_ids_for_profile(profile_id)
    members = [
        database.get_speaker_observation(member_id) for member_id in member_ids
    ]
    members_by_fingerprint = {
        member.input_fingerprint: member
        for member in members
        if member is not None
    }
    current_snapshot = _sha256(
        {
            "profile_id": profile_id,
            "member_fingerprints": sorted(members_by_fingerprint),
        }
    )
    if current_snapshot != evidence["profile_snapshot_fingerprint"]:
        return False
    matched = _matched_profile_result(report, int(evidence["profile_id"]))
    comparisons = matched.get("comparisons") if matched is not None else None
    if not isinstance(comparisons, list):
        return False
    comparisons_by_fingerprint = {
        comparison.get("exemplar_fingerprint"): comparison
        for comparison in comparisons
        if isinstance(comparison, Mapping)
    }
    for fingerprint in exemplar_fingerprints:
        member = members_by_fingerprint.get(fingerprint)
        comparison = comparisons_by_fingerprint.get(fingerprint)
        if member is None or not isinstance(comparison, Mapping):
            return False
        member_eligibility = assess_automatic_speaker_observation(
            database,
            member.video_id,
            verification_cache=verification_cache,
        )
        if (
            not member_eligibility.eligible
            or member_eligibility.observation is None
            or member_eligibility.observation.id != member.id
            or member_eligibility.media_artifact is None
            or comparison.get("exemplar_normalized_audio_sha256")
            != member_eligibility.media_artifact.content_sha256
        ):
            return False
    return True


def _matched_profile_result(
    report: Mapping[str, Any], profile_id: int
) -> Mapping[str, Any] | None:
    profiles = report.get("profiles")
    if not isinstance(profiles, list):
        return None
    return next(
        (
            item
            for item in profiles
            if isinstance(item, Mapping)
            and item.get("profile_id") == profile_id
            and item.get("meets_multi_exemplar_match") is True
        ),
        None,
    )


def _latest_events_by_evidence(
    events: Sequence[Mapping[str, object]],
) -> dict[int, Mapping[str, object]]:
    latest: dict[int, Mapping[str, object]] = {}
    for event in events:
        latest[int(event["machine_evidence_id"])] = event
    return latest


def _tripped_policy_fingerprints(
    evidence_rows: Sequence[Mapping[str, object]],
    events: Sequence[Mapping[str, object]],
) -> frozenset[str]:
    evidence_by_id = {int(row["id"]): row for row in evidence_rows}
    return frozenset(
        str(evidence_by_id[int(event["machine_evidence_id"])]["policy_fingerprint"])
        for event in events
        if str(event["reason"]).startswith("contradiction:")
        and int(event["machine_evidence_id"]) in evidence_by_id
    )


def _append_assignment_event(
    database: Database,
    *,
    evidence: Mapping[str, object],
    action: str,
    reason: str,
) -> int:
    fingerprint = _sha256(
        {
            "version": MACHINE_ASSIGNMENT_VERSION,
            "evidence_fingerprint": evidence["evidence_fingerprint"],
            "action": action,
            "reason": reason,
        }
    )
    return database.add_speaker_machine_assignment_event(
        machine_evidence_id=int(evidence["id"]),
        observation_id=int(evidence["observation_id"]),
        profile_id=int(evidence["profile_id"]),
        action=action,
        actor=MACHINE_ASSIGNMENT_ACTOR,
        reason=reason,
        event_fingerprint=fingerprint,
    )


def _increment(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _is_string_list(value: object) -> bool:
    return isinstance(value, list) and all(
        isinstance(item, str) and item for item in value
    )


def _sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
