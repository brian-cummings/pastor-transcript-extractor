from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping

from pastor_transcript_extractor.pipeline_diagnostics import (
    load_identity_association_admissions,
    load_identity_association_attempts,
)
from pastor_transcript_extractor.speaker_pair_eligibility import (
    assess_automatic_speaker_observation,
)
from pastor_transcript_extractor.storage import Database


IDENTITY_WORK_STATE_VERSION = "identity_association_work_state_v1"

TECHNICAL_PREREQUISITE_REASONS = frozenset(
    {
        "registered_normalized_media_unavailable",
        "verified_normalized_media_unavailable",
        "archived_media_unavailable",
        "diagnostic_spans_unavailable",
        "extraction_unavailable",
        "extraction_artifact_unreadable",
        "extraction_artifact_malformed",
        "observation_unavailable",
        "observation_not_current_extraction",
        "observation_window_mismatch",
    }
)
POLICY_TERMINAL_REASONS = frozenset(
    {
        "disposition_not_accepted",
        "sermon_window_invalid",
        "disposition_missing_or_malformed",
        "already_profiled",
        "reviewed_exclude",
        "reviewed_ambiguous",
    }
)


@dataclass(frozen=True, slots=True)
class IdentityAssociationWorkItem:
    video_id: int
    youtube_video_id: str
    observation_id: int
    observation_fingerprint: str
    state: str
    stage: str
    reason_code: str
    next_operation: str
    retryable: bool


@dataclass(frozen=True, slots=True)
class IdentityAssociationWorkPlan:
    items: tuple[IdentityAssociationWorkItem, ...]
    attempt_volume: int

    @property
    def counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.items:
            counts[item.state] = counts.get(item.state, 0) + 1
        return dict(sorted(counts.items()))

    def select(self, *states: str, limit: int | None = None):
        allowed = set(states)
        selected = tuple(item for item in self.items if item.state in allowed)
        return selected[:limit] if limit is not None else selected


def classify_association_blocker(stage: str, reason_code: str) -> tuple[str, str, bool]:
    """Classify an exact blocker without weakening identity admission policy."""
    if reason_code in POLICY_TERMINAL_REASONS or stage in {
        "membership_filter",
        "observation_review_filter",
    }:
        return "admission_policy_terminal", "review_policy_terminal", False
    if reason_code in TECHNICAL_PREREQUISITE_REASONS:
        operation = (
            "backfill_existing_normalized_media"
            if reason_code == "registered_normalized_media_unavailable"
            else "rebuild_observation_from_current_extraction"
            if reason_code in {
                "observation_unavailable",
                "observation_not_current_extraction",
                "observation_window_mismatch",
                "diagnostic_spans_unavailable",
            }
            else "retry_when_prerequisite_changes"
        )
        return "prerequisite_blocked", operation, True
    if stage == "technical_failure":
        return "technical_failure", "retry_association", True
    return "admission_blocked", "repair_or_review_admission", False


def build_identity_association_work_plan(
    database: Database,
    association_root: Path,
) -> IdentityAssociationWorkPlan:
    """Project one current, unique-video state for accepted identity work."""
    videos = database.list_videos()
    video_ids = {video.id for video in videos}
    attempts = load_identity_association_attempts(
        association_root, database_video_ids=video_ids
    )
    admissions = load_identity_association_admissions(
        association_root, database_video_ids=video_ids
    )
    attempt_volume = sum(len(values) for values in attempts.values())
    items: list[IdentityAssociationWorkItem] = []
    for video in sorted(videos, key=lambda item: item.youtube_video_id):
        observation = database.get_latest_speaker_observation_for_video(video.id)
        if observation is None:
            continue
        eligibility = assess_automatic_speaker_observation(
            database, video.id, verify_media=False
        )
        # Only accepted-sermon observations enter this queue. A stale observation
        # is retained as a technical blocker only when eligibility identifies it.
        if eligibility.reason_code == "disposition_not_accepted":
            continue
        if database.list_effective_profile_ids_for_observation(observation.id):
            continue
        current_attempts = [
            attempt
            for attempt in attempts.get(video.id, ())
            if attempt.get("observation_id") == observation.id
            and attempt.get("observation_fingerprint")
            == observation.input_fingerprint
        ]
        if current_attempts:
            state, stage, reason, operation, retryable = (
                "associated",
                "association_result",
                str(current_attempts[-1].get("outcome") or "unknown"),
                "none",
                False,
            )
        elif (
            (admission := admissions.get(observation.id, {})).get(
                "observation_fingerprint"
            )
            == observation.input_fingerprint
            and admission.get("stage") == "technical_failure"
        ):
            stage = "technical_failure"
            reason = str(admission.get("reason_code") or "technical_failure")
            state, operation, retryable = classify_association_blocker(stage, reason)
        elif eligibility.eligible and eligibility.observation is not None:
            state, stage, reason, operation, retryable = (
                "dispatch_ready",
                "association_dispatch",
                "current_result_missing",
                "run_bounded_association_dispatch",
                True,
            )
        else:
            admission = admissions.get(observation.id, {})
            admission_is_current = (
                admission.get("observation_fingerprint")
                == observation.input_fingerprint
            )
            stage = str(
                admission.get("stage")
                if admission_is_current
                else "metadata_eligibility"
            )
            reason = str(
                admission.get("reason_code")
                if admission_is_current
                else eligibility.reason_code
            )
            state, operation, retryable = classify_association_blocker(stage, reason)
        items.append(
            IdentityAssociationWorkItem(
                video_id=video.id,
                youtube_video_id=video.youtube_video_id,
                observation_id=observation.id,
                observation_fingerprint=observation.input_fingerprint,
                state=state,
                stage=stage,
                reason_code=reason,
                next_operation=operation,
                retryable=retryable,
            )
        )
    return IdentityAssociationWorkPlan(tuple(items), attempt_volume)


def write_identity_work_event(
    root: Path,
    item: IdentityAssociationWorkItem,
    *,
    operation: str,
    outcome: str,
    detail: str,
) -> Path:
    stable = {
        "state_version": IDENTITY_WORK_STATE_VERSION,
        "observation_fingerprint": item.observation_fingerprint,
        "operation": operation,
        "input_state": item.state,
        "input_stage": item.stage,
        "input_reason_code": item.reason_code,
        "outcome": outcome,
        "detail": detail,
    }
    fingerprint = hashlib.sha256(
        json.dumps(stable, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    destination = (
        root.expanduser().resolve()
        / "work-events"
        / item.observation_fingerprint[:16]
        / f"{fingerprint}.json"
    )
    if destination.exists():
        return destination
    payload: dict[str, Any] = {
        "schema_version": 1,
        "artifact_kind": "identity_association_work_event",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "video_id": item.video_id,
        "youtube_video_id": item.youtube_video_id,
        "observation_id": item.observation_id,
        **stable,
    }
    unhashed = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["result_sha256"] = hashlib.sha256(unhashed).hexdigest()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".json.partial")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, destination)
    return destination


def latest_association_reports(
    root: Path,
    *,
    outcomes: Iterable[str] | None = None,
) -> tuple[Path, ...]:
    """Return only the newest result for each candidate observation fingerprint."""
    allowed = set(outcomes) if outcomes is not None else None
    latest: dict[str, tuple[str, str, str, Path]] = {}
    for path in sorted(root.expanduser().resolve().glob("*/*.json")):
        if path.name.startswith("admission-"):
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        candidate = payload.get("candidate") if isinstance(payload, dict) else None
        fingerprint = (
            candidate.get("input_fingerprint")
            if isinstance(candidate, Mapping)
            else None
        )
        outcome = payload.get("outcome") if isinstance(payload, dict) else None
        if (
            payload.get("artifact_kind") != "speaker_profile_shadow_association"
            or not isinstance(fingerprint, str)
            or not isinstance(outcome, str)
        ):
            continue
        order = (str(payload.get("created_at") or ""), str(path))
        if fingerprint not in latest or order[:2] > latest[fingerprint][:2]:
            latest[fingerprint] = (order[0], order[1], outcome, path)
    return tuple(
        value[3]
        for _, value in sorted(latest.items())
        if allowed is None or value[2] in allowed
    )
