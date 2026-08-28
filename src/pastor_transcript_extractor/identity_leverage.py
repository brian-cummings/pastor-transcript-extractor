from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from pastor_transcript_extractor.storage import Database


SCHEMA_VERSION = 1
AMBIGUOUS_OUTCOMES = {"ambiguous", "ambiguous_match"}
ABSTENTION_OUTCOMES = {*AMBIGUOUS_OUTCOMES, "insufficient_evidence"}
DECISION_KINDS = {
    "duplicate_profile_cleanup",
    "readiness_promotion",
    "exemplar_media_fix",
    "prospective_confirmation",
    "sermon_review",
}


def _load_latest_associations(root: Path) -> dict[int, dict[str, Any]]:
    latest: dict[int, tuple[tuple[str, str], dict[str, Any]]] = {}
    if not root.is_dir():
        return {}
    for path in sorted(root.rglob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict) or payload.get("artifact_kind") != (
            "speaker_profile_shadow_association"
        ):
            continue
        candidate = payload.get("candidate")
        candidate = candidate if isinstance(candidate, dict) else {}
        observation_id = candidate.get("observation_id")
        if not isinstance(observation_id, int):
            continue
        created_at = payload.get("created_at")
        if not isinstance(created_at, str):
            try:
                created_at = datetime.fromtimestamp(
                    path.stat().st_mtime, tz=timezone.utc
                ).isoformat()
            except OSError:
                created_at = ""
        ordering = (created_at, str(path))
        existing = latest.get(observation_id)
        if existing is None or ordering > existing[0]:
            latest[observation_id] = (ordering, {**payload, "artifact_path": str(path)})
    return {observation_id: item[1] for observation_id, item in latest.items()}


def _profile_evidence(
    report: Mapping[str, Any], profile_ids: set[int]
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    acoustic_exemplar_excluded = False
    outcome = str(report.get("outcome") or "")
    proposed = report.get("proposed_profile_id")
    if isinstance(proposed, int) and proposed in profile_ids:
        reasons.append("proposed_target")
    for raw in report.get("profiles", []) or []:
        if (
            outcome in AMBIGUOUS_OUTCOMES
            and isinstance(raw, Mapping)
            and raw.get("profile_id") in profile_ids
        ):
            reasons.append("compared_profile")
            break
    routing = report.get("routing")
    routing = routing if isinstance(routing, Mapping) else {}
    funnel = routing.get("candidate_funnel")
    funnel = funnel if isinstance(funnel, Mapping) else {}
    for raw in funnel.get("retrieval_candidates", []) or []:
        if not isinstance(raw, Mapping) or raw.get("profile_id") not in profile_ids:
            continue
        if (
            outcome in AMBIGUOUS_OUTCOMES
            and raw.get("selected_for_comparison") is True
        ):
            reasons.append("selected_retrieval")
        if raw.get("source_match") is True:
            reasons.append("source_retrieval")
        if raw.get("name_match") is True:
            reasons.append("name_retrieval")
        if raw.get("confirmation_priority") is True:
            reasons.append("confirmation_retrieval")
    for raw in funnel.get("excluded_profiles", []) or []:
        if not isinstance(raw, Mapping) or raw.get("profile_id") not in profile_ids:
            continue
        if raw.get("stage") == "acoustic_exemplar_availability":
            acoustic_exemplar_excluded = True
    # Exclusion lists describe global profile state and therefore appear on
    # unrelated candidates. They are diagnostic context, not neighborhood
    # membership. Retain the exclusion only when another persisted route or
    # comparison directly connects this observation to the profile.
    if reasons and acoustic_exemplar_excluded:
        reasons.append("acoustic_exemplar_exclusion")
    return bool(reasons), sorted(set(reasons))


def _target_profile_automatic_ready(
    report: Mapping[str, Any], proposed_profile_id: int | None
) -> bool | None:
    if proposed_profile_id is None:
        return None
    for raw in report.get("profiles", []) or []:
        if not isinstance(raw, Mapping) or raw.get("profile_id") != proposed_profile_id:
            continue
        readiness = raw.get("profile_readiness")
        if not isinstance(readiness, Mapping):
            return None
        value = readiness.get("automatic_profile_ready")
        return value if isinstance(value, bool) else None
    return None


def _legacy_actionable_proposal_ids(state: Mapping[str, Any]) -> set[int]:
    actionable: set[int] = set()
    latest = state.get("latest_observations")
    latest = latest if isinstance(latest, Mapping) else {}
    for raw_id, raw_state in latest.items():
        if not isinstance(raw_state, Mapping):
            continue
        try:
            observation_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        ready = raw_state.get("target_profile_automatic_ready")
        if not isinstance(ready, bool):
            artifact_path = raw_state.get("association_artifact_path")
            if isinstance(artifact_path, str):
                try:
                    report = json.loads(Path(artifact_path).read_text(encoding="utf-8"))
                except (OSError, UnicodeError, json.JSONDecodeError):
                    report = None
                if isinstance(report, Mapping):
                    proposed = report.get("proposed_profile_id")
                    ready = _target_profile_automatic_ready(
                        report, proposed if isinstance(proposed, int) else None
                    )
        if ready is True:
            actionable.add(observation_id)
    return actionable


def build_profile_leverage_snapshot(
    database: Database,
    *,
    association_root: Path,
    profile_ids: Sequence[int],
    decision_kind: str,
    profile_level_decisions: int = 0,
    sermon_level_reviews: int = 0,
    prospective_correct: int = 0,
    prospective_incorrect: int = 0,
) -> dict[str, Any]:
    if decision_kind not in DECISION_KINDS:
        raise ValueError(f"Unsupported decision kind: {decision_kind}")
    if not profile_ids:
        raise ValueError("At least one profile id is required")
    for value in (
        profile_level_decisions,
        sermon_level_reviews,
        prospective_correct,
        prospective_incorrect,
    ):
        if value < 0:
            raise ValueError("Decision and confirmation counts cannot be negative")

    requested_ids = sorted(set(profile_ids))
    for profile_id in requested_ids:
        if database.get_speaker_profile(profile_id) is None:
            raise ValueError(f"Unknown speaker profile: {profile_id}")
    canonical_ids = sorted(
        {database.resolve_speaker_profile_id(profile_id) for profile_id in requested_ids}
    )
    relevant_ids = set(requested_ids) | set(canonical_ids)
    reports = _load_latest_associations(association_root.expanduser().resolve())
    observations = {item.id: item for item in database.list_speaker_observations()}
    videos = {item.id: item for item in database.list_videos()}

    neighborhood: list[dict[str, Any]] = []
    latest_states: dict[str, dict[str, Any]] = {}
    for observation_id, report in sorted(reports.items()):
        relevant, reasons = _profile_evidence(report, relevant_ids)
        if not relevant:
            continue
        observation = observations.get(observation_id)
        if observation is None:
            continue
        video = videos.get(observation.video_id)
        if video is None:
            continue
        effective_ids = sorted(
            {
                database.resolve_speaker_profile_id(profile_id)
                for profile_id in database.list_effective_profile_ids_for_observation(
                    observation_id
                )
            }
        )
        outcome = str(report.get("outcome") or "unknown")
        proposed = report.get("proposed_profile_id")
        proposed_profile_id = proposed if isinstance(proposed, int) else None
        target_profile_automatic_ready = _target_profile_automatic_ready(
            report, proposed_profile_id
        )
        state = {
            "observation_id": observation_id,
            "database_video_id": video.id,
            "youtube_video_id": video.youtube_video_id,
            "effective_profile_ids": effective_ids,
            "association_outcome": outcome,
            "proposed_profile_id": proposed_profile_id,
            "target_profile_automatic_ready": target_profile_automatic_ready,
            "association_artifact_path": report.get("artifact_path"),
            "neighborhood_reason_codes": reasons,
        }
        neighborhood.append(state)
        latest_states[str(observation_id)] = state

    resolved = sorted(
        int(key)
        for key, state in latest_states.items()
        if state["effective_profile_ids"]
    )
    proposed = sorted(
        int(key)
        for key, state in latest_states.items()
        if state["association_outcome"] == "proposed_match"
        and state["proposed_profile_id"] in relevant_ids
        and not state["effective_profile_ids"]
    )
    actionable_proposed = sorted(
        int(key)
        for key, state in latest_states.items()
        if state["association_outcome"] == "proposed_match"
        and state["proposed_profile_id"] in relevant_ids
        and state["target_profile_automatic_ready"] is True
        and not state["effective_profile_ids"]
    )
    abstained = sorted(
        int(key)
        for key, state in latest_states.items()
        if state["association_outcome"] in ABSTENTION_OUTCOMES
    )
    exemplar_excluded = sorted(
        int(key)
        for key, state in latest_states.items()
        if "acoustic_exemplar_exclusion" in state["neighborhood_reason_codes"]
    )
    confirmations = prospective_correct + prospective_incorrect
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": "identity_profile_leverage_snapshot",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "decision_kind": decision_kind,
        "requested_profile_ids": requested_ids,
        "canonical_profile_ids": canonical_ids,
        "human_input_counts": {
            "profile_level_decisions": profile_level_decisions,
            "sermon_level_reviews": sermon_level_reviews,
            "prospective_correct": prospective_correct,
            "prospective_incorrect": prospective_incorrect,
        },
        "state": {
            "neighborhood_observation_count": len(neighborhood),
            "neighborhood_youtube_video_ids": sorted(
                item["youtube_video_id"] for item in neighborhood
            ),
            "resolved_observation_ids": resolved,
            "proposal_observation_ids": proposed,
            "actionable_proposal_observation_ids": actionable_proposed,
            "abstention_observation_ids": abstained,
            "acoustic_exemplar_excluded_observation_ids": exemplar_excluded,
            "latest_observations": latest_states,
        },
        "prospective_confirmation": {
            "confirmation_count": confirmations,
            "correct_count": prospective_correct,
            "incorrect_count": prospective_incorrect,
            "precision": (
                prospective_correct / confirmations if confirmations else None
            ),
            "status": "observed" if confirmations else "not_observed",
        },
    }


def profile_neighborhood_video_ids(
    database: Database,
    *,
    association_root: Path,
    profile_ids: Sequence[int],
) -> list[int]:
    """Return the bounded historical evidence neighborhood for profile replay."""
    relevant_ids = set(profile_ids)
    relevant_ids.update(
        database.resolve_speaker_profile_id(profile_id) for profile_id in profile_ids
    )
    reports = _load_latest_associations(association_root.expanduser().resolve())
    observations = {item.id: item for item in database.list_speaker_observations()}
    return sorted(
        {
            observation.video_id
            for observation_id, report in reports.items()
            if (observation := observations.get(observation_id)) is not None
            and _profile_evidence(report, relevant_ids)[0]
        }
    )


def compare_profile_leverage_snapshots(
    before: Mapping[str, Any], after: Mapping[str, Any]
) -> dict[str, Any]:
    if before.get("artifact_kind") != "identity_profile_leverage_snapshot":
        raise ValueError("Baseline is not an identity profile leverage snapshot")
    if after.get("artifact_kind") != "identity_profile_leverage_snapshot":
        raise ValueError("Current artifact is not an identity profile leverage snapshot")
    if before.get("requested_profile_ids") != after.get("requested_profile_ids"):
        raise ValueError("Baseline and current snapshot profile ids differ")
    before_state = before.get("state") if isinstance(before.get("state"), Mapping) else {}
    after_state = after.get("state") if isinstance(after.get("state"), Mapping) else {}

    def ids(state: Mapping[str, Any], key: str) -> set[int]:
        return {value for value in state.get(key, []) if isinstance(value, int)}

    newly_resolved = ids(after_state, "resolved_observation_ids") - ids(
        before_state, "resolved_observation_ids"
    )
    new_proposals = ids(after_state, "proposal_observation_ids") - ids(
        before_state, "proposal_observation_ids"
    )
    before_actionable = (
        ids(before_state, "actionable_proposal_observation_ids")
        if "actionable_proposal_observation_ids" in before_state
        else _legacy_actionable_proposal_ids(before_state)
    )
    after_actionable = (
        ids(after_state, "actionable_proposal_observation_ids")
        if "actionable_proposal_observation_ids" in after_state
        else _legacy_actionable_proposal_ids(after_state)
    )
    proposals_made_actionable = after_actionable - before_actionable
    enabled_proposals = new_proposals | proposals_made_actionable
    after_observations = {
        int(value)
        for value in (after_state.get("latest_observations") or {})
        if str(value).isdigit()
    }
    before_abstentions = ids(before_state, "abstention_observation_ids")
    after_abstentions = ids(after_state, "abstention_observation_ids")
    eliminated_abstentions = (
        before_abstentions & after_observations
    ) - after_abstentions
    repaired_exemplars = (
        ids(before_state, "acoustic_exemplar_excluded_observation_ids")
        & before_abstentions
        & after_observations
    ) - (
        ids(after_state, "acoustic_exemplar_excluded_observation_ids")
        | after_abstentions
    )
    inputs = after.get("human_input_counts")
    inputs = inputs if isinstance(inputs, Mapping) else {}
    profile_decisions = int(inputs.get("profile_level_decisions") or 0)
    sermon_reviews = int(inputs.get("sermon_level_reviews") or 0)
    prospective = after.get("prospective_confirmation")
    prospective = prospective if isinstance(prospective, Mapping) else {}
    confirmation_count = int(prospective.get("confirmation_count") or 0)
    prospective_correct = int(prospective.get("correct_count") or 0)
    baseline_proposals = ids(before_state, "proposal_observation_ids")
    if confirmation_count > len(baseline_proposals):
        raise ValueError(
            "Prospective confirmations exceed unresolved baseline proposals"
        )
    if prospective_correct > len(newly_resolved):
        raise ValueError(
            "Prospective correct confirmations exceed newly resolved sermons"
        )
    result = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": "identity_profile_leverage_result",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "decision_kind": after.get("decision_kind"),
        "requested_profile_ids": after.get("requested_profile_ids"),
        "observed": {
            "newly_resolved_observation_ids": sorted(newly_resolved),
            "newly_resolved_sermon_count": len(newly_resolved),
            "downstream_proposal_observation_ids": sorted(enabled_proposals),
            "downstream_proposals_enabled": len(enabled_proposals),
            "new_proposal_observation_ids": sorted(new_proposals),
            "proposals_made_actionable_observation_ids": sorted(
                proposals_made_actionable
            ),
            "proposals_made_actionable": len(proposals_made_actionable),
            "abstention_observation_ids_eliminated": sorted(eliminated_abstentions),
            "abstentions_eliminated": len(eliminated_abstentions),
            "exemplar_exclusion_observation_ids_repaired": sorted(repaired_exemplars),
            "unresolved_cases_repaired_through_exemplar_media_fixes": len(
                repaired_exemplars
            ),
            "sermons_resolved_per_profile_level_human_decision": (
                len(newly_resolved) / profile_decisions if profile_decisions else None
            ),
            "sermons_resolved_per_sermon_level_review": (
                len(newly_resolved) / sermon_reviews if sermon_reviews else None
            ),
            "prospective_confirmation_precision": prospective.get("precision"),
            "prospective_confirmation_count": confirmation_count,
        },
        "interpretation": {
            "unit": "speaker_observations backed by sermon recordings",
            "predicted_unlocks_used": False,
            "membership_firewall_changed": False,
            "zero_is_observed": True,
        },
    }
    normalized = json.dumps(result, sort_keys=True, separators=(",", ":"))
    result["result_sha256"] = hashlib.sha256(normalized.encode()).hexdigest()
    return result
