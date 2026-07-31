from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from pastor_transcript_extractor.models import utc_now


IDENTITY_COORDINATION_VERSION = "identity_coordination_shadow_v1"


def build_identity_coordination_report(
    audit_payload: Mapping[str, Any],
    *,
    youtube_video_id: str | None = None,
    confirmation_observation_ids: Iterable[int] = (),
    promotion_summary: Mapping[str, Any] | None = None,
    execution_summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if audit_payload.get("artifact_kind") != "speaker_association_coverage_audit":
        raise ValueError("identity coordination requires an association audit")
    raw_cases = audit_payload.get("cases")
    if not isinstance(raw_cases, list):
        raise ValueError("association audit cases are missing")
    confirmations = {int(value) for value in confirmation_observation_ids}
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
            "action_required": sum(
                not bool(case["terminal"]) for case in cases
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
        / f"identity-coordination-v1-{fingerprint}.json"
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


def _coordination_case(
    case: Mapping[str, Any],
    *,
    confirmation_observation_ids: set[int],
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
        "proposed_profile_ids": proposed_profile_ids,
        "workflow_state": workflow_state,
        "next_action": next_action,
        "terminal": terminal,
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
