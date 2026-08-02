from __future__ import annotations

import hashlib
import itertools
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from pastor_transcript_extractor.models import utc_now
from pastor_transcript_extractor.speaker_profile_discovery import (
    SHADOW_PROFILE_DISCOVERY_VERSION,
    TRANSCRIPT_GROUNDED_SPAN_SELECTION_VERSION,
)
from pastor_transcript_extractor.speaker_pair_selector import (
    DiscoveryResolutionPair,
)


IDENTITY_COORDINATION_VERSION = "identity_coordination_shadow_v2"
SUPPORTED_DISCOVERY_VERSIONS = frozenset(
    {
        "speaker_profile_shadow_discovery_v1",
        "speaker_profile_shadow_discovery_v2",
        "speaker_profile_shadow_discovery_v3",
        "speaker_profile_shadow_discovery_v4",
        SHADOW_PROFILE_DISCOVERY_VERSION,
    }
)


def build_identity_coordination_report(
    audit_payload: Mapping[str, Any],
    *,
    youtube_video_id: str | None = None,
    confirmation_observation_ids: Iterable[int] = (),
    discovery_observation_states: Mapping[int, str] | None = None,
    promotion_summary: Mapping[str, Any] | None = None,
    execution_summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if audit_payload.get("artifact_kind") != "speaker_association_coverage_audit":
        raise ValueError("identity coordination requires an association audit")
    raw_cases = audit_payload.get("cases")
    if not isinstance(raw_cases, list):
        raise ValueError("association audit cases are missing")
    confirmations = {int(value) for value in confirmation_observation_ids}
    discovery_states = discovery_observation_states or {}
    cases: list[dict[str, Any]] = []
    for raw_case in raw_cases:
        if not isinstance(raw_case, Mapping):
            raise ValueError("association audit case is invalid")
        if (
            youtube_video_id is not None
            and raw_case.get("youtube_video_id") != youtube_video_id
        ):
            continue
        cases.append(
            _coordination_case(
                raw_case,
                confirmation_observation_ids=confirmations,
                discovery_observation_states=discovery_states,
            )
        )
    if youtube_video_id is not None and not cases:
        raise ValueError(
            f"No latest extraction exists for YouTube video {youtube_video_id}"
        )
    state_counts = _counts(case["workflow_state"] for case in cases)
    next_action_counts = _counts(case["next_action"] for case in cases)
    audit_counts = audit_payload.get("counts")
    invalid_artifacts = (
        int(audit_counts.get("invalid_association_artifacts", 0))
        if isinstance(audit_counts, Mapping)
        else 0
    )
    global_blockers = (
        ["invalid_association_artifacts"] if invalid_artifacts else []
    )
    stable = {
        "schema_version": 1,
        "coordination_version": IDENTITY_COORDINATION_VERSION,
        "artifact_kind": "identity_coordination_shadow_report",
        "shadow_mode": True,
        "registry_mutation_allowed": False,
        "automatic_assignment_allowed": False,
        "youtube_video_id_filter": youtube_video_id,
        "association_audit_fingerprint": audit_payload.get(
            "audit_fingerprint"
        ),
        "counts": {
            "extractions": len(cases),
            "terminal": sum(bool(case["terminal"]) for case in cases),
            "waiting_for_evidence": sum(
                bool(case["waiting_for_evidence"]) for case in cases
            ),
            "action_required": sum(
                bool(case["immediate_action_required"]) for case in cases
            ),
            "invalid_association_artifacts": invalid_artifacts,
        },
        "global_blockers": global_blockers,
        "workflow_state_counts": state_counts,
        "next_action_counts": next_action_counts,
        "promotion_summary": (
            dict(promotion_summary) if promotion_summary is not None else None
        ),
        "execution_summary": (
            dict(execution_summary) if execution_summary is not None else None
        ),
        "cases": cases,
    }
    stable["coordination_fingerprint"] = _sha256_json(stable)
    return stable


def write_identity_coordination_report(
    output_root: Path,
    report: Mapping[str, Any],
) -> Path:
    fingerprint = report.get("coordination_fingerprint")
    if not isinstance(fingerprint, str) or not fingerprint:
        raise ValueError("coordination report fingerprint is missing")
    content = dict(report)
    persisted = {
        **content,
        "created_at": utc_now().isoformat(),
    }
    destination = (
        output_root.expanduser().resolve()
        / f"identity-coordination-v2-{fingerprint}.json"
    )
    if destination.exists():
        loaded = json.loads(destination.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError(
                f"identity coordination artifact is invalid: {destination}"
            )
        comparable = dict(loaded)
        comparable.pop("created_at", None)
        if comparable != content:
            raise ValueError(
                f"identity coordination fingerprint collision: {destination}"
            )
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(persisted, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return destination


def load_discovery_observation_states(
    report_path: Path,
) -> dict[int, str]:
    payload = _load_verified_discovery_report(report_path)
    states: dict[int, str] = {}
    for signature in payload.get("observation_signatures", ()):
        if isinstance(signature, Mapping) and isinstance(
            signature.get("observation_id"), int
        ):
            states[int(signature["observation_id"])] = "evaluated_unclustered"
    for failure in payload.get("signature_failures", ()):
        if isinstance(failure, Mapping) and isinstance(
            failure.get("observation_id"), int
        ):
            states[int(failure["observation_id"])] = "signature_failed"
    for component in payload.get("components", ()):
        if not isinstance(component, Mapping):
            continue
        outcome = str(component.get("outcome", "blocked"))
        blockers = {
            str(value) for value in component.get("blockers", ())
        }
        if outcome == "provisional_profile_candidate":
            component_state = "provisional_component"
        elif blockers and blockers.issubset(
            {
                "fewer_than_minimum_members",
                "fewer_than_minimum_distinct_recordings",
            }
        ):
            component_state = "undersized_component"
        else:
            component_state = "blocked_component"
        for member in component.get("members", ()):
            if isinstance(member, Mapping) and isinstance(
                member.get("observation_id"), int
            ):
                states[int(member["observation_id"])] = component_state
    return states


def load_discovery_resolution_pairs(
    report_path: Path,
) -> tuple[DiscoveryResolutionPair, ...]:
    payload = _load_verified_discovery_report(report_path)
    fingerprints_by_observation_id = {
        int(signature["observation_id"]): str(
            signature["observation_fingerprint"]
        )
        for signature in payload.get("observation_signatures", ())
        if isinstance(signature, Mapping)
        and isinstance(signature.get("observation_id"), int)
        and isinstance(signature.get("observation_fingerprint"), str)
    }
    pair_outcomes = {
        tuple(sorted(int(value) for value in result["observation_ids"])): str(
            result.get("outcome", "missing")
        )
        for result in payload.get("pair_results", ())
        if isinstance(result, Mapping)
        and isinstance(result.get("observation_ids"), list)
        and len(result["observation_ids"]) == 2
        and all(isinstance(value, int) for value in result["observation_ids"])
    }
    overlapping = [
        component
        for component in payload.get("components", ())
        if isinstance(component, Mapping)
        and component.get("outcome") == "blocked"
        and "overlapping_complete_link_components"
        in component.get("blockers", ())
    ]
    candidates: dict[frozenset[str], DiscoveryResolutionPair] = {}
    for frontier in payload.get("review_frontier", ()):
        if not isinstance(frontier, Mapping):
            continue
        fingerprints = frontier.get("observation_fingerprints")
        component_ids = frontier.get("component_ids")
        distance = frontier.get("same_boundary_distance")
        if (
            not isinstance(fingerprints, list)
            or len(fingerprints) != 2
            or not all(isinstance(value, str) and value for value in fingerprints)
            or not isinstance(component_ids, list)
            or not all(isinstance(value, str) for value in component_ids)
            or isinstance(distance, bool)
            or not isinstance(distance, (int, float))
        ):
            continue
        resolution = DiscoveryResolutionPair(
            fingerprint_a=fingerprints[0],
            fingerprint_b=fingerprints[1],
            component_ids=tuple(sorted(component_ids)),
            member_fingerprints=tuple(
                sorted(
                    {
                        fingerprints_by_observation_id[observation_id]
                        for component in payload.get("components", ())
                        if isinstance(component, Mapping)
                        and str(component.get("component_id")) in component_ids
                        for observation_id in _component_observation_ids(
                            component
                        )
                        if observation_id in fingerprints_by_observation_id
                    }
                )
            ),
            observations_unlocked=int(frontier.get("observations_unlocked", 0)),
            report_result_sha256=str(payload["result_sha256"]),
            report_path=str(report_path.expanduser().resolve()),
            resolution_kind="near_same_ambiguous_frontier",
            same_boundary_distance=float(distance),
        )
        candidates[resolution.pair_key] = resolution
    for left, right in itertools.combinations(overlapping, 2):
        left_ids = _component_observation_ids(left)
        right_ids = _component_observation_ids(right)
        if not left_ids & right_ids:
            continue
        union_ids = left_ids | right_ids
        component_ids = tuple(
            sorted((str(left["component_id"]), str(right["component_id"])))
        )
        member_fingerprints = tuple(
            sorted(
                fingerprints_by_observation_id[observation_id]
                for observation_id in union_ids
                if observation_id in fingerprints_by_observation_id
            )
        )
        for observation_a_id in sorted(left_ids - right_ids):
            for observation_b_id in sorted(right_ids - left_ids):
                outcome = pair_outcomes.get(
                    tuple(sorted((observation_a_id, observation_b_id)))
                )
                if outcome in {"same_speaker", "different_speaker"}:
                    continue
                fingerprint_a = fingerprints_by_observation_id.get(
                    observation_a_id
                )
                fingerprint_b = fingerprints_by_observation_id.get(
                    observation_b_id
                )
                if fingerprint_a is None or fingerprint_b is None:
                    continue
                resolution = DiscoveryResolutionPair(
                    fingerprint_a=fingerprint_a,
                    fingerprint_b=fingerprint_b,
                    component_ids=component_ids,
                    member_fingerprints=member_fingerprints,
                    observations_unlocked=len(union_ids),
                    report_result_sha256=str(payload["result_sha256"]),
                    report_path=str(report_path.expanduser().resolve()),
                )
                existing = candidates.get(resolution.pair_key)
                if (
                    existing is None
                    or (
                        existing.resolution_kind
                        != "near_same_ambiguous_frontier"
                        and resolution.observations_unlocked
                        > existing.observations_unlocked
                    )
                ):
                    candidates[resolution.pair_key] = resolution
    return tuple(
        sorted(
            candidates.values(),
            key=lambda item: (
                0
                if item.resolution_kind == "near_same_ambiguous_frontier"
                else 1,
                item.same_boundary_distance
                if item.same_boundary_distance is not None
                else float("inf"),
                -item.observations_unlocked,
                item.fingerprint_a,
                item.fingerprint_b,
            ),
        )
    )


def _load_verified_discovery_report(
    report_path: Path,
) -> dict[str, Any]:
    path = report_path.expanduser().resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("profile discovery artifact must be an object")
    expected_sha256 = payload.get("result_sha256")
    unhashed = dict(payload)
    unhashed.pop("result_sha256", None)
    if (
        not isinstance(expected_sha256, str)
        or _sha256_json(unhashed) != expected_sha256
    ):
        raise ValueError("profile discovery artifact checksum mismatch")
    span_selection = payload.get("span_selection")
    if (
        payload.get("artifact_kind")
        != "speaker_profile_shadow_discovery"
        or payload.get("discovery_version")
        not in SUPPORTED_DISCOVERY_VERSIONS
        or not isinstance(span_selection, Mapping)
        or span_selection.get("version")
        != TRANSCRIPT_GROUNDED_SPAN_SELECTION_VERSION
    ):
        raise ValueError("profile discovery artifact uses an unsupported contract")
    return payload


def _component_observation_ids(
    component: Mapping[str, Any],
) -> set[int]:
    return {
        int(member["observation_id"])
        for member in component.get("members", ())
        if isinstance(member, Mapping)
        and isinstance(member.get("observation_id"), int)
    }


def _coordination_case(
    case: Mapping[str, Any],
    *,
    confirmation_observation_ids: set[int],
    discovery_observation_states: Mapping[int, str],
) -> dict[str, Any]:
    coverage_state = str(case.get("coverage_state", "unaccounted"))
    reason_code = str(case.get("reason_code", "unknown"))
    observation_id = case.get("observation_id")
    attempts = [
        attempt
        for attempt in case.get("association_attempts", ())
        if isinstance(attempt, Mapping)
    ]
    outcomes = {str(attempt.get("outcome")) for attempt in attempts}
    proposed_profile_ids = sorted(
        {
            int(attempt["proposed_profile_id"])
            for attempt in attempts
            if isinstance(attempt.get("proposed_profile_id"), int)
            and attempt.get("outcome") == "proposed_match"
        }
    )

    discovery_state = (
        discovery_observation_states.get(observation_id)
        if isinstance(observation_id, int)
        else None
    )

    if coverage_state == "associated":
        workflow_state = "associated"
        next_action = "none"
        terminal = True
    elif (
        coverage_state == "content_terminal"
        and reason_code == "content_review_required"
    ):
        workflow_state = "content_review_required"
        next_action = "review_content"
        terminal = False
    elif coverage_state == "content_terminal":
        workflow_state = "content_terminal"
        next_action = "none"
        terminal = True
    elif coverage_state == "blocked":
        workflow_state = "explicitly_blocked"
        next_action = "none"
        terminal = True
    elif isinstance(observation_id, int) and observation_id in (
        confirmation_observation_ids
    ):
        workflow_state = "provisional_confirmation_proposed"
        next_action = "review_or_apply_provisional_confirmation"
        terminal = False
    elif proposed_profile_ids:
        workflow_state = "profile_match_proposed"
        next_action = "review_or_await_approved_assignment_policy"
        terminal = False
    elif "ambiguous" in outcomes or "conflicting_attribution" in outcomes:
        workflow_state = "identity_review_required"
        next_action = "review_identity_conflict"
        terminal = False
    elif (
        coverage_state == "evaluated"
        and discovery_state == "provisional_component"
    ):
        workflow_state = "profile_promotion_available"
        next_action = "plan_provisional_profile_promotion"
        terminal = False
    elif (
        coverage_state == "evaluated"
        and discovery_state == "blocked_component"
    ):
        workflow_state = "identity_review_required"
        next_action = "review_blocked_discovery_component"
        terminal = False
    elif (
        coverage_state == "evaluated"
        and discovery_state == "signature_failed"
    ):
        workflow_state = "acoustic_evidence_blocked"
        next_action = "repair_acoustic_evidence"
        terminal = False
    elif (
        coverage_state == "evaluated"
        and discovery_state == "undersized_component"
    ):
        workflow_state = "identity_unresolved_waiting_for_evidence"
        next_action = "await_new_evidence"
        terminal = False
    elif (
        coverage_state == "evaluated"
        and discovery_state == "evaluated_unclustered"
    ):
        workflow_state = "identity_unresolved_waiting_for_evidence"
        next_action = "await_new_evidence"
        terminal = False
    elif coverage_state == "evaluated":
        workflow_state = "discovery_batch_candidate"
        next_action = "run_shadow_profile_discovery"
        terminal = False
    elif reason_code in {
        "association_attempt_missing",
        "association_attempt_stale",
        "association_attempt_requires_retry",
    }:
        workflow_state = "association_required"
        next_action = "run_shadow_association"
        terminal = False
    else:
        workflow_state = "identity_reconciliation_required"
        next_action = "repair_identity_prerequisite"
        terminal = False

    return {
        "video_id": case.get("video_id"),
        "youtube_video_id": case.get("youtube_video_id"),
        "extraction_result_id": case.get("extraction_result_id"),
        "observation_id": observation_id,
        "observation_fingerprint": case.get("observation_fingerprint"),
        "content_status": case.get("content_status"),
        "coverage_state": coverage_state,
        "coverage_reason": reason_code,
        "effective_profile_ids": list(
            case.get("effective_profile_ids", ())
        ),
        "association_outcomes": sorted(outcomes),
        "discovery_state": discovery_state,
        "proposed_profile_ids": proposed_profile_ids,
        "workflow_state": workflow_state,
        "next_action": next_action,
        "terminal": terminal,
        "waiting_for_evidence": next_action == "await_new_evidence",
        "immediate_action_required": (
            not terminal and next_action != "await_new_evidence"
        ),
    }


def _counts(values: Iterable[object]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value)
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _sha256_json(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
