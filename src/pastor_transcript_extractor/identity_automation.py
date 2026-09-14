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


def observation_profile_lineage_exclusion(
    database: Database,
    *,
    video_id: int,
    observation_id: int,
) -> str | None:
    """Classify direct or superseded profile ownership for discovery gates."""
    if database.list_effective_profile_ids_for_observation(observation_id):
        return "already_profiled"
    if database.list_effective_profile_ids_for_observation_lineage(
        video_id=video_id,
        current_observation_id=observation_id,
    ):
        return "superseded_profile_lineage"
    return None


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


@dataclass(frozen=True, slots=True)
class SupersededProfileMemberReviewCandidate:
    profile_id: int
    anchor_observation_id: int
    anchor_youtube_video_id: str
    replacement_observation_id: int
    replacement_youtube_video_id: str
    superseded_observation_id: int
    profile_member_count: int
    current_exemplar_count: int
    selection_kind: str = "restore_unprofiled_replacement"
    successor_profile_id: int | None = None
    shared_normalized_names: tuple[str, ...] = ()
    lineage_overlap_count: int = 0


def select_superseded_profile_member_review(
    database: Database,
    *,
    profile_id: int | None = None,
    excluded_pairs: Iterable[frozenset[str]] = (),
) -> SupersededProfileMemberReviewCandidate | None:
    """Select one guarded review for superseded membership or profile lineage."""
    videos_by_id = {video.id: video for video in database.list_videos()}
    claims = database.list_speaker_name_claims()
    claims_by_id = {claim.id: claim for claim in claims}
    claims_by_observation_id: dict[int, set[str]] = {}
    for claim in claims:
        if (
            claim.observation_id is not None
            and claim.explicit_speaker_attribution
            and claim.normalized_name.strip()
        ):
            claims_by_observation_id.setdefault(
                claim.observation_id, set()
            ).add(claim.normalized_name.strip())

    def profile_names(
        candidate_profile_id: int,
        member_ids: set[int],
    ) -> set[str]:
        names = {
            name
            for observation_id in member_ids
            for name in claims_by_observation_id.get(observation_id, set())
        }
        for claim_id in database.list_effective_name_claim_ids_for_profile(
            candidate_profile_id
        ):
            claim = claims_by_id.get(claim_id)
            if claim is not None and claim.normalized_name.strip():
                names.add(claim.normalized_name.strip())
        return names

    requested_profile_id = (
        database.resolve_speaker_profile_id(profile_id)
        if profile_id is not None
        else None
    )
    excluded_pair_keys = frozenset(excluded_pairs)
    different_pairs = set(
        database.list_effective_observation_difference_pairs()
    )

    def all_members_are_superseded(members: Iterable[Any]) -> bool:
        members = tuple(members)
        return bool(members) and all(
            (
                current := database.get_latest_speaker_observation_for_video(
                    member.video_id
                )
            )
            is not None
            and current.id != member.id
            for member in members
        )

    candidates: list[SupersededProfileMemberReviewCandidate] = []
    for profile in database.list_speaker_profiles():
        if database.resolve_speaker_profile_id(profile.id) != profile.id:
            continue
        if requested_profile_id is not None and profile.id != requested_profile_id:
            continue
        members = [
            observation
            for observation_id in (
                database.list_effective_observation_ids_for_profile(profile.id)
            )
            if (observation := database.get_speaker_observation(observation_id))
            is not None
        ]
        member_recording_count = len({member.video_id for member in members})
        current_members = [
            member
            for member in members
            if (
                current := database.get_latest_speaker_observation_for_video(
                    member.video_id
                )
            )
            is not None
            and current.id == member.id
        ]
        if (
            member_recording_count >= 3
            and len({member.video_id for member in current_members}) == 1
        ):
            anchor = current_members[0]
            anchor_video = videos_by_id.get(anchor.video_id)
            anchor_eligibility = assess_automatic_speaker_observation(
                database, anchor.video_id, verify_media=False
            )
            if anchor_video is not None and anchor_eligibility.eligible:
                for superseded in members:
                    replacement = (
                        database.get_latest_speaker_observation_for_video(
                            superseded.video_id
                        )
                    )
                    if replacement is None or replacement.id == superseded.id:
                        continue
                    replacement_video = videos_by_id.get(
                        replacement.video_id
                    )
                    if replacement_video is None:
                        continue
                    if database.list_effective_profile_ids_for_observation(
                        replacement.id
                    ):
                        continue
                    replacement_eligibility = (
                        assess_automatic_speaker_observation(
                            database,
                            replacement.video_id,
                            verify_media=False,
                        )
                    )
                    if (
                        not replacement_eligibility.eligible
                        or replacement_eligibility.observation is None
                        or replacement_eligibility.observation.id
                        != replacement.id
                        or frozenset(
                            (
                                anchor.input_fingerprint,
                                replacement.input_fingerprint,
                            )
                        )
                        in excluded_pair_keys
                    ):
                        continue
                    candidates.append(
                        SupersededProfileMemberReviewCandidate(
                            profile_id=profile.id,
                            anchor_observation_id=anchor.id,
                            anchor_youtube_video_id=(
                                anchor_video.youtube_video_id
                            ),
                            replacement_observation_id=replacement.id,
                            replacement_youtube_video_id=(
                                replacement_video.youtube_video_id
                            ),
                            superseded_observation_id=superseded.id,
                            profile_member_count=len(members),
                            current_exemplar_count=1,
                        )
                    )

        # If every useful exemplar was superseded and discovery attached a
        # replacement elsewhere, retain the old observation as one side of a
        # blinded bridge.  Lineage and one exact shared name nominate the
        # review; neither is treated as identity proof.
        if requested_profile_id is None or member_recording_count < 2:
            continue
        successor_mappings: dict[
            int, list[tuple[Any, Any]]
        ] = {}
        for superseded in members:
            replacement = database.get_latest_speaker_observation_for_video(
                superseded.video_id
            )
            if replacement is None or replacement.id == superseded.id:
                continue
            replacement_profile_ids = {
                database.resolve_speaker_profile_id(candidate_id)
                for candidate_id in (
                    database.list_effective_profile_ids_for_observation(
                        replacement.id
                    )
                )
            }
            if len(replacement_profile_ids) != 1:
                continue
            successor_profile_id = next(iter(replacement_profile_ids))
            if successor_profile_id == profile.id:
                continue
            successor_mappings.setdefault(successor_profile_id, []).append(
                (superseded, replacement)
            )

        old_member_ids = {member.id for member in members}
        old_names = profile_names(profile.id, old_member_ids)
        if len(old_names) != 1:
            continue
        for successor_profile_id, mappings in sorted(
            successor_mappings.items()
        ):
            successor_profile = database.get_speaker_profile(
                successor_profile_id
            )
            if successor_profile is None:
                continue
            successor_members = [
                observation
                for observation_id in (
                    database.list_effective_observation_ids_for_profile(
                        successor_profile_id
                    )
                )
                if (
                    observation := database.get_speaker_observation(
                        observation_id
                    )
                )
                is not None
            ]
            successor_member_ids = {
                member.id for member in successor_members
            }
            successor_names = profile_names(
                successor_profile_id, successor_member_ids
            )
            if successor_names != old_names:
                continue
            if any(
                tuple(sorted((old_id, successor_id))) in different_pairs
                for old_id in old_member_ids
                for successor_id in successor_member_ids
            ):
                continue
            current_successors = [
                member
                for member in successor_members
                if (
                    current := database.get_latest_speaker_observation_for_video(
                        member.video_id
                    )
                )
                is not None
                and current.id == member.id
            ]
            bridge_options = [
                (old_member, current_successor)
                for old_member in members
                for current_successor in current_successors
                if old_member.video_id != current_successor.video_id
                and tuple(
                    sorted((old_member.id, current_successor.id))
                )
                not in different_pairs
                and frozenset(
                    (
                        old_member.input_fingerprint,
                        current_successor.input_fingerprint,
                    )
                )
                not in excluded_pair_keys
            ]
            if not bridge_options:
                continue
            old_member, current_successor = min(
                bridge_options,
                key=lambda item: (item[0].id, item[1].id),
            )
            old_video = videos_by_id.get(old_member.video_id)
            successor_video = videos_by_id.get(current_successor.video_id)
            if old_video is None or successor_video is None:
                continue
            successor_eligibility = assess_automatic_speaker_observation(
                database,
                current_successor.video_id,
                verify_media=False,
            )
            if (
                not successor_eligibility.eligible
                or successor_eligibility.observation is None
                or successor_eligibility.observation.id
                != current_successor.id
            ):
                continue
            candidates.append(
                SupersededProfileMemberReviewCandidate(
                    profile_id=profile.id,
                    anchor_observation_id=old_member.id,
                    anchor_youtube_video_id=old_video.youtube_video_id,
                    replacement_observation_id=current_successor.id,
                    replacement_youtube_video_id=(
                        successor_video.youtube_video_id
                    ),
                    superseded_observation_id=min(
                        item[0].id for item in mappings
                    ),
                    profile_member_count=len(members),
                    current_exemplar_count=len(current_successors),
                    selection_kind="lineage_profile_consolidation",
                    successor_profile_id=successor_profile_id,
                    shared_normalized_names=tuple(sorted(old_names)),
                    lineage_overlap_count=len(mappings),
                )
            )

    # Targeted review may also recover two named profiles whose members were
    # all superseded before either lineage acquired a current exemplar.  Keep
    # this out of the untargeted queue: an operator must select the profile,
    # and a blinded review remains the only evidence that permits the merge.
    if requested_profile_id is not None and not any(
        item.selection_kind == "lineage_profile_consolidation"
        for item in candidates
    ):
        requested_members = [
            observation
            for observation_id in (
                database.list_effective_observation_ids_for_profile(
                    requested_profile_id
                )
            )
            if (
                observation := database.get_speaker_observation(
                    observation_id
                )
            )
            is not None
        ]
        requested_member_ids = {
            member.id for member in requested_members
        }
        requested_names = profile_names(
            requested_profile_id, requested_member_ids
        )
        requested_current_members = [
            member
            for member in requested_members
            if (
                current := database.get_latest_speaker_observation_for_video(
                    member.video_id
                )
            )
            is not None
            and current.id == member.id
        ]
        requested_fully_superseded = all_members_are_superseded(
            requested_members
        )
        if (
            len({member.video_id for member in requested_members}) >= 2
            and len(requested_names) == 1
        ):
            for other_profile in database.list_speaker_profiles():
                other_profile_id = database.resolve_speaker_profile_id(
                    other_profile.id
                )
                if (
                    other_profile_id != other_profile.id
                    or other_profile_id == requested_profile_id
                ):
                    continue
                other_members = [
                    observation
                    for observation_id in (
                        database.list_effective_observation_ids_for_profile(
                            other_profile_id
                        )
                    )
                    if (
                        observation := database.get_speaker_observation(
                            observation_id
                        )
                    )
                    is not None
                ]
                other_member_ids = {
                    member.id for member in other_members
                }
                if (
                    len({member.video_id for member in other_members}) < 2
                    or not all_members_are_superseded(other_members)
                    or profile_names(
                        other_profile_id, other_member_ids
                    )
                    != requested_names
                ):
                    continue
                if any(
                    tuple(sorted((left_id, right_id))) in different_pairs
                    for left_id in requested_member_ids
                    for right_id in other_member_ids
                ):
                    continue
                reverse_lineage_overlap = []
                for other_member in other_members:
                    replacement = (
                        database.get_latest_speaker_observation_for_video(
                            other_member.video_id
                        )
                    )
                    if replacement is None or replacement.id == other_member.id:
                        continue
                    replacement_profile_ids = {
                        database.resolve_speaker_profile_id(value)
                        for value in (
                            database.list_effective_profile_ids_for_observation(
                                replacement.id
                            )
                        )
                    }
                    if requested_profile_id in replacement_profile_ids:
                        reverse_lineage_overlap.append(
                            (other_member, replacement)
                        )
                if (
                    not requested_fully_superseded
                    and not reverse_lineage_overlap
                ):
                    continue
                requested_bridge_members = (
                    requested_current_members or requested_members
                )
                bridge_options = [
                    (left, right)
                    for left in requested_bridge_members
                    for right in other_members
                    if left.video_id != right.video_id
                    and tuple(sorted((left.id, right.id)))
                    not in different_pairs
                    and frozenset(
                        (left.input_fingerprint, right.input_fingerprint)
                    )
                    not in excluded_pair_keys
                ]
                if not bridge_options:
                    continue
                left, right = min(
                    bridge_options,
                    key=lambda item: (item[0].id, item[1].id),
                )
                left_video = videos_by_id.get(left.video_id)
                right_video = videos_by_id.get(right.video_id)
                if left_video is None or right_video is None:
                    continue
                candidates.append(
                    SupersededProfileMemberReviewCandidate(
                        profile_id=requested_profile_id,
                        anchor_observation_id=left.id,
                        anchor_youtube_video_id=(
                            left_video.youtube_video_id
                        ),
                        replacement_observation_id=right.id,
                        replacement_youtube_video_id=(
                            right_video.youtube_video_id
                        ),
                        superseded_observation_id=left.id,
                        profile_member_count=len(requested_members),
                        current_exemplar_count=0,
                        selection_kind=(
                            "lineage_profile_consolidation"
                            if reverse_lineage_overlap
                            else "superseded_named_profile_consolidation"
                        ),
                        successor_profile_id=other_profile_id,
                        shared_normalized_names=tuple(
                            sorted(requested_names)
                        ),
                        lineage_overlap_count=len(reverse_lineage_overlap),
                    )
                )
    return min(
        candidates,
        key=lambda item: (
            0
            if item.selection_kind == "lineage_profile_consolidation"
            else 1
            if item.selection_kind
            == "superseded_named_profile_consolidation"
            else 2,
            -item.lineage_overlap_count,
            -item.profile_member_count,
            item.profile_id,
            item.replacement_youtube_video_id,
        ),
        default=None,
    )


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
    association_profile_candidate_available = False
    for profile in database.list_speaker_profiles():
        if database.resolve_speaker_profile_id(profile.id) != profile.id:
            continue
        member_observations = [
            observation
            for observation_id in (
                database.list_effective_observation_ids_for_profile(profile.id)
            )
            if (observation := database.get_speaker_observation(observation_id))
            is not None
        ]
        if len({item.video_id for item in member_observations}) < 3:
            continue
        current_member_recordings = {
            observation.video_id
            for observation in member_observations
            if (
                current := database.get_latest_speaker_observation_for_video(
                    observation.video_id
                )
            )
            is not None
            and current.id == observation.id
        }
        if len(current_member_recordings) >= 2:
            association_profile_candidate_available = True
            break
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
            if association_profile_candidate_available:
                state, stage, reason, operation, retryable = (
                    "dispatch_ready",
                    "association_dispatch",
                    "current_result_missing",
                    "run_bounded_association_dispatch",
                    True,
                )
            else:
                state, stage, reason, operation, retryable = (
                    "profile_prerequisite_blocked",
                    "candidate_profile_eligibility",
                    "no_profile_has_two_current_reviewed_acoustic_exemplars",
                    "review_superseded_profile_member_observations",
                    False,
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
