from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from pastor_transcript_extractor.evaluation_storage import portable_database_artifact_path
from pastor_transcript_extractor.speaker_profile_discovery import (
    SUPPORTED_SHADOW_PROFILE_DISCOVERY_VERSIONS,
    TRANSCRIPT_GROUNDED_SPAN_SELECTION_VERSION,
)
from pastor_transcript_extractor.speaker_registry import (
    attach_reviewed_observation,
)
from pastor_transcript_extractor.speaker_profile_promotion_typesafe import (
    PromotionAssessment,
)
from pastor_transcript_extractor.speaker_shadow_association import (
    SHADOW_ASSOCIATION_VERSION,
)
from pastor_transcript_extractor.storage import Database


DISCOVERY_PROFILE_REASON = "shadow_discovery_candidate"
DISCOVERY_PROMOTION_VERSION = "speaker_profile_discovery_promotion_v1"
DISCOVERY_PROMOTION_ACTOR = "system:profile-discovery-promotion"


@dataclass(frozen=True, slots=True)
class PromotionCandidate:
    component_id: str
    observation_ids: tuple[int, ...]
    observation_fingerprints: tuple[str, ...]
    recording_ids: tuple[int, ...]
    normalized_names: tuple[str, ...]
    existing_profile_id: int | None
    promotion_basis: str = "deterministic_complete_link"
    probability: float | None = None
    expected_utility: float | None = None
    judgment_artifact_path: Path | None = None
    judgment_result_sha256: str | None = None
    probability_policy_version: str | None = None


@dataclass(frozen=True, slots=True)
class DiscoveryPromotionPlan:
    report_path: Path
    report_result_sha256: str
    candidates: tuple[PromotionCandidate, ...]
    skipped: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class ConfirmationCandidate:
    report_path: Path
    report_result_sha256: str
    profile_id: int
    observation_id: int
    observation_fingerprint: str
    video_id: int


@dataclass(frozen=True, slots=True)
class CandidateConfirmationPlan:
    candidates: tuple[ConfirmationCandidate, ...]
    skipped: tuple[dict[str, Any], ...]
    ignored_counts: Mapping[str, int]


def plan_discovery_promotions(
    database: Database,
    report_path: Path,
    *,
    probability_assessments: Sequence[PromotionAssessment] = (),
    probability_policy_version: str | None = None,
) -> DiscoveryPromotionPlan:
    path = report_path.expanduser().resolve()
    report = _load_verified_report(path)
    _validate_discovery_report(report)
    result_sha256 = str(report["result_sha256"])
    candidates: list[PromotionCandidate] = []
    skipped: list[dict[str, Any]] = []
    for component in report["components"]:
        if component.get("outcome") != "provisional_profile_candidate":
            continue
        component_id = str(component.get("component_id", ""))
        try:
            candidate = _validate_component(
                database,
                component,
                component_id=component_id,
            )
        except ValueError as error:
            skipped.append(
                {
                    "component_id": component_id,
                    "reason": str(error),
                }
            )
            continue
        candidates.append(candidate)
    selected_observation_ids = {
        observation_id
        for candidate in candidates
        for observation_id in candidate.observation_ids
    }
    ranked_probability = sorted(
        (
            assessment
            for assessment in probability_assessments
            if assessment.qualifies
            and assessment.probability is not None
            and assessment.expected_utility is not None
        ),
        key=lambda item: (
            -float(item.expected_utility or 0.0),
            -len(item.evidence.grouping.observation_ids),
            item.evidence.grouping.group_id,
        ),
    )
    for assessment in ranked_probability:
        grouping = assessment.evidence.grouping
        if selected_observation_ids & set(grouping.observation_ids):
            skipped.append(
                {
                    "component_id": grouping.group_id,
                    "reason": "overlaps a stronger selected promotion grouping",
                }
            )
            continue
        try:
            candidate = _validate_probability_group(
                database,
                grouping_id=grouping.group_id,
                observation_ids=grouping.observation_ids,
                observation_fingerprints=grouping.observation_fingerprints,
                probability=float(assessment.probability),
                expected_utility=float(assessment.expected_utility),
                judgment_artifact_path=assessment.artifact_path,
                judgment_result_sha256=assessment.result_sha256,
                probability_policy_version=probability_policy_version,
            )
        except ValueError as error:
            skipped.append(
                {"component_id": grouping.group_id, "reason": str(error)}
            )
            continue
        candidates.append(candidate)
        selected_observation_ids.update(candidate.observation_ids)
    return DiscoveryPromotionPlan(
        report_path=path,
        report_result_sha256=result_sha256,
        candidates=tuple(candidates),
        skipped=tuple(skipped),
    )


def apply_discovery_promotions(
    database: Database,
    plan: DiscoveryPromotionPlan,
) -> tuple[int, ...]:
    promoted: list[int] = []
    for candidate in plan.candidates:
        stable_key = f"speaker:discovery:{candidate.component_id[:32]}"
        profile = database.ensure_speaker_profile(
            stable_key=stable_key,
            display_label=None,
            lifecycle_state="provisional",
            created_reason=DISCOVERY_PROFILE_REASON,
        )
        if (
            profile.created_reason != DISCOVERY_PROFILE_REASON
            or profile.lifecycle_state != "provisional"
        ):
            raise ValueError(
                f"Stable key {stable_key} belongs to an incompatible profile"
            )
        existing_promotion = database.get_speaker_profile_discovery_promotion(
            profile.id
        )
        if existing_promotion is not None:
            if str(existing_promotion["component_id"]) != candidate.component_id:
                raise ValueError(
                    "Existing discovery promotion belongs to a different "
                    f"component for profile {profile.id}"
                )
            promoted.append(profile.id)
            continue
        event_key = _sha256(
            {
                "promotion_version": DISCOVERY_PROMOTION_VERSION,
                "component_id": candidate.component_id,
                "report_result_sha256": plan.report_result_sha256,
                "promotion_basis": candidate.promotion_basis,
                "judgment_result_sha256": candidate.judgment_result_sha256,
                "probability_policy_version": candidate.probability_policy_version,
            }
        )
        database.add_speaker_profile_creation_event(
            profile_id=profile.id,
            reviewer=DISCOVERY_PROMOTION_ACTOR,
            reason=(
                "Reversible provisional profile promoted from verified "
                f"discovery grouping {candidate.component_id}; "
                f"basis={candidate.promotion_basis}"
            ),
            event_fingerprint=_sha256(
                {"kind": "discovery_profile_creation", "event_key": event_key}
            ),
        )
        database.add_speaker_profile_discovery_promotion(
            profile_id=profile.id,
            component_id=candidate.component_id,
            discovery_result_sha256=plan.report_result_sha256,
            discovery_artifact_path=portable_database_artifact_path(
                plan.report_path, database_path=database.database_path
            ),
            seed_observation_ids_json=json.dumps(
                list(candidate.observation_ids),
                separators=(",", ":"),
            ),
            event_fingerprint=_sha256(
                {"kind": "discovery_profile_promotion", "event_key": event_key}
            ),
            promotion_basis=candidate.promotion_basis,
            promotion_probability=candidate.probability,
            promotion_expected_utility=candidate.expected_utility,
            promotion_judgment_sha256=candidate.judgment_result_sha256,
            promotion_judgment_artifact_path=(
                portable_database_artifact_path(
                    candidate.judgment_artifact_path,
                    database_path=database.database_path,
                )
                if candidate.judgment_artifact_path is not None
                else None
            ),
            probability_policy_version=candidate.probability_policy_version,
        )
        reason = (
            "Seed membership from verified discovery grouping "
            f"{candidate.component_id}; basis={candidate.promotion_basis}; "
            f"report={plan.report_result_sha256}"
        )
        for observation_id in candidate.observation_ids:
            attach_reviewed_observation(
                database,
                profile_id=profile.id,
                observation_id=observation_id,
                reviewer=DISCOVERY_PROMOTION_ACTOR,
                reason=reason,
                review_event_key=f"{event_key}:seed:{observation_id}",
            )
        promoted.append(profile.id)
    # Promotion can rediscover a current component after an older extraction
    # lineage already established the same attributed speaker on this source.
    # Collapse that duplicate before human-on-loop readiness is projected.
    from pastor_transcript_extractor.reviewed_speaker_evidence import (
        consolidate_same_source_attributed_profiles,
    )

    consolidate_same_source_attributed_profiles(database)
    return tuple(
        database.resolve_speaker_profile_id(profile_id)
        for profile_id in promoted
    )


def plan_candidate_confirmations(
    database: Database,
    report_paths: Sequence[Path],
) -> CandidateConfirmationPlan:
    candidates: list[ConfirmationCandidate] = []
    skipped: list[dict[str, Any]] = []
    ignored_counts: dict[str, int] = {}
    seen_observations: set[int] = set()
    seen_recordings: set[int] = set()
    for raw_path in sorted(
        (path.expanduser().resolve() for path in report_paths),
        key=str,
    ):
        try:
            report = _load_verified_report(raw_path)
            if (
                report.get("artifact_kind")
                == "speaker_profile_shadow_association"
                and report.get("association_version")
                != SHADOW_ASSOCIATION_VERSION
            ):
                _increment(ignored_counts, "stale_association_version")
                continue
            candidate = _validate_confirmation(database, raw_path, report)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            skipped.append({"report_path": str(raw_path), "reason": str(error)})
            continue
        if candidate is None:
            if report.get("outcome") != "proposed_match":
                _increment(
                    ignored_counts,
                    f"outcome_{report.get('outcome', 'unknown')}",
                )
            else:
                _increment(
                    ignored_counts,
                    "proposal_not_pending_for_discovery_profile",
                )
            continue
        if candidate.observation_id in seen_observations:
            _increment(ignored_counts, "duplicate_candidate_observation")
            continue
        if candidate.video_id in seen_recordings:
            _increment(ignored_counts, "duplicate_candidate_recording")
            continue
        seen_observations.add(candidate.observation_id)
        seen_recordings.add(candidate.video_id)
        candidates.append(candidate)
    return CandidateConfirmationPlan(
        candidates=tuple(candidates),
        skipped=tuple(skipped),
        ignored_counts=dict(sorted(ignored_counts.items())),
    )


def apply_candidate_confirmations(
    database: Database,
    plan: CandidateConfirmationPlan,
) -> tuple[int, ...]:
    seen_recordings: set[int] = set()
    for candidate in plan.candidates:
        if candidate.video_id in seen_recordings:
            raise ValueError(
                "confirmation plan contains the same recording more than once"
            )
        current_observation = (
            database.get_latest_speaker_observation_for_video(candidate.video_id)
        )
        if (
            current_observation is None
            or current_observation.id != candidate.observation_id
            or current_observation.input_fingerprint
            != candidate.observation_fingerprint
        ):
            raise ValueError(
                "confirmation candidate is no longer the current observation "
                "for its recording"
            )
        seen_recordings.add(candidate.video_id)

    event_ids: list[int] = []
    for candidate in plan.candidates:
        event_key = _sha256(
            {
                "promotion_version": DISCOVERY_PROMOTION_VERSION,
                "profile_id": candidate.profile_id,
                "observation_id": candidate.observation_id,
                "association_result_sha256": candidate.report_result_sha256,
            }
        )
        attach_reviewed_observation(
            database,
            profile_id=candidate.profile_id,
            observation_id=candidate.observation_id,
            reviewer=DISCOVERY_PROMOTION_ACTOR,
            reason=(
                "Independent recording confirmed by current multi-exemplar "
                f"association artifact {candidate.report_result_sha256}"
            ),
            review_event_key=f"{event_key}:confirmation",
        )
        event_ids.append(
            database.add_speaker_profile_candidate_confirmation(
                profile_id=candidate.profile_id,
                observation_id=candidate.observation_id,
                association_result_sha256=candidate.report_result_sha256,
                association_artifact_path=portable_database_artifact_path(
                    candidate.report_path, database_path=database.database_path
                ),
                event_fingerprint=_sha256(
                    {"kind": "discovery_profile_confirmation", "event_key": event_key}
                ),
            )
        )
    return tuple(event_ids)


def _validate_discovery_report(report: Mapping[str, Any]) -> None:
    if (
        report.get("artifact_kind") != "speaker_profile_shadow_discovery"
        or report.get("discovery_version")
        not in SUPPORTED_SHADOW_PROFILE_DISCOVERY_VERSIONS
        or report.get("shadow_mode") is not True
        or report.get("registry_mutation_allowed") is not False
        or report.get("automatic_profile_creation_allowed") is not False
    ):
        raise ValueError("unsupported or unsafe discovery artifact")
    span_selection = report.get("span_selection")
    if (
        not isinstance(span_selection, Mapping)
        or span_selection.get("version")
        != TRANSCRIPT_GROUNDED_SPAN_SELECTION_VERSION
    ):
        raise ValueError("discovery artifact does not use current speech grounding")
    if not isinstance(report.get("components"), list):
        raise ValueError("discovery artifact components are missing")


def _validate_component(
    database: Database,
    component: Mapping[str, Any],
    *,
    component_id: str,
) -> PromotionCandidate:
    if not component_id or component.get("blockers") != []:
        raise ValueError("component is not an unblocked candidate")
    members = component.get("members")
    if not isinstance(members, list) or len(members) < 3:
        raise ValueError("component requires at least three members")
    observation_ids: list[int] = []
    fingerprints: list[str] = []
    video_ids: set[int] = set()
    for member in members:
        if not isinstance(member, Mapping):
            raise ValueError("component member metadata is invalid")
        observation_id = member.get("observation_id")
        fingerprint = member.get("input_fingerprint")
        if not isinstance(observation_id, int) or not isinstance(fingerprint, str):
            raise ValueError("component member identity is invalid")
        observation = database.get_speaker_observation(observation_id)
        if observation is None or observation.input_fingerprint != fingerprint:
            raise ValueError(f"observation {observation_id} no longer matches artifact")
        if observation.video_id != member.get("video_id"):
            raise ValueError(f"observation {observation_id} recording changed")
        memberships = database.list_effective_profile_ids_for_observation(
            observation_id
        )
        observation_ids.append(observation_id)
        fingerprints.append(fingerprint)
        video_ids.add(observation.video_id)
        if memberships:
            existing = _existing_discovery_profile(database, component_id)
            if existing is None or any(
                database.resolve_speaker_profile_id(profile_id) != existing
                for profile_id in memberships
            ):
                raise ValueError(
                    f"observation {observation_id} is already profiled elsewhere"
                )
    if len(video_ids) < 3:
        raise ValueError("component requires three distinct recordings")
    expected_component_id = _sha256(sorted(fingerprints))
    if expected_component_id != component_id:
        raise ValueError("component fingerprint does not match its members")
    different_pairs = set(database.list_effective_observation_difference_pairs())
    if any(
        tuple(sorted((left, right))) in different_pairs
        for index, left in enumerate(observation_ids)
        for right in observation_ids[index + 1 :]
    ):
        raise ValueError("component now contains a reviewed difference")
    return PromotionCandidate(
        component_id=component_id,
        observation_ids=tuple(sorted(observation_ids)),
        observation_fingerprints=tuple(sorted(fingerprints)),
        recording_ids=tuple(sorted(video_ids)),
        normalized_names=tuple(
            str(value) for value in component.get("normalized_names", ())
        ),
        existing_profile_id=_existing_discovery_profile(database, component_id),
    )


def _validate_probability_group(
    database: Database,
    *,
    grouping_id: str,
    observation_ids: Sequence[int],
    observation_fingerprints: Sequence[str],
    probability: float,
    expected_utility: float,
    judgment_artifact_path: Path,
    judgment_result_sha256: str,
    probability_policy_version: str | None,
) -> PromotionCandidate:
    if len(observation_ids) < 2:
        raise ValueError("probability-qualified grouping requires two observations")
    if not 0.0 <= probability <= 1.0 or expected_utility <= 0.0:
        raise ValueError("probability-qualified grouping has no positive utility")
    if not judgment_artifact_path.is_file():
        raise ValueError("probability judgment artifact is unavailable")
    expected_grouping_id = _sha256(tuple(sorted(observation_fingerprints)))
    if grouping_id != expected_grouping_id:
        raise ValueError("probability grouping fingerprint does not match its members")
    existing_profile_id = _existing_discovery_profile(database, grouping_id)
    observations = []
    for observation_id in observation_ids:
        observation = database.get_speaker_observation(observation_id)
        if observation is None:
            raise ValueError(f"observation {observation_id} is unavailable")
        observations.append(observation)
    if tuple(sorted(item.input_fingerprint for item in observations)) != tuple(
        sorted(observation_fingerprints)
    ):
        raise ValueError("probability grouping observations no longer match evidence")
    video_ids = {item.video_id for item in observations}
    if len(video_ids) != len(observations):
        raise ValueError("probability grouping repeats a recording")
    for observation in observations:
        current = database.get_latest_speaker_observation_for_video(
            observation.video_id
        )
        if current is None or current.id != observation.id:
            raise ValueError(
                f"observation {observation.id} is no longer current"
            )
        memberships = database.list_effective_profile_ids_for_observation(
            observation.id
        )
        if memberships and (
            existing_profile_id is None
            or any(
                database.resolve_speaker_profile_id(profile_id)
                != database.resolve_speaker_profile_id(existing_profile_id)
                for profile_id in memberships
            )
        ):
            raise ValueError(
                f"observation {observation.id} is already profiled elsewhere"
            )
    different_pairs = set(database.list_effective_observation_difference_pairs())
    if any(
        tuple(sorted((left, right))) in different_pairs
        for index, left in enumerate(observation_ids)
        for right in observation_ids[index + 1 :]
    ):
        raise ValueError("probability grouping now contains a reviewed difference")
    return PromotionCandidate(
        component_id=grouping_id,
        observation_ids=tuple(sorted(observation_ids)),
        observation_fingerprints=tuple(sorted(observation_fingerprints)),
        recording_ids=tuple(sorted(video_ids)),
        normalized_names=(),
        existing_profile_id=existing_profile_id,
        promotion_basis="jev_probability",
        probability=probability,
        expected_utility=expected_utility,
        judgment_artifact_path=judgment_artifact_path,
        judgment_result_sha256=judgment_result_sha256,
        probability_policy_version=probability_policy_version,
    )


def _validate_confirmation(
    database: Database,
    path: Path,
    report: Mapping[str, Any],
) -> ConfirmationCandidate | None:
    if (
        report.get("artifact_kind") != "speaker_profile_shadow_association"
        or report.get("association_version") != SHADOW_ASSOCIATION_VERSION
        or report.get("shadow_mode") is not True
        or report.get("registry_mutation_allowed") is not False
    ):
        raise ValueError("unsupported or unsafe association artifact")
    if report.get("outcome") != "proposed_match":
        return None
    routing = report.get("routing")
    if routing is not None and (
        not isinstance(routing, Mapping)
        or routing.get("exhaustive") is not True
    ):
        return None
    span_selection = report.get("span_selection")
    if (
        not isinstance(span_selection, Mapping)
        or span_selection.get("version")
        != TRANSCRIPT_GROUNDED_SPAN_SELECTION_VERSION
    ):
        raise ValueError("association artifact does not use current speech grounding")
    profile_id = report.get("proposed_profile_id")
    candidate = report.get("candidate")
    if not isinstance(profile_id, int) or not isinstance(candidate, Mapping):
        raise ValueError("association proposal target is invalid")
    profile = database.get_speaker_profile(profile_id)
    promotion = database.get_speaker_profile_discovery_promotion(profile_id)
    if (
        profile is None
        or profile.created_reason != DISCOVERY_PROFILE_REASON
        or promotion is None
    ):
        return None
    observation_id = candidate.get("observation_id")
    fingerprint = candidate.get("input_fingerprint")
    video_id = candidate.get("video_id")
    if (
        not isinstance(observation_id, int)
        or not isinstance(fingerprint, str)
        or not isinstance(video_id, int)
    ):
        raise ValueError("association candidate identity is invalid")
    observation = database.get_speaker_observation(observation_id)
    if (
        observation is None
        or observation.input_fingerprint != fingerprint
        or observation.video_id != video_id
    ):
        raise ValueError("association candidate no longer matches the registry")
    current_observation = database.get_latest_speaker_observation_for_video(video_id)
    if (
        current_observation is None
        or current_observation.id != observation_id
        or current_observation.input_fingerprint != fingerprint
    ):
        raise ValueError(
            "association candidate is not the current observation for its recording"
        )
    memberships = database.list_effective_profile_ids_for_observation(
        observation_id
    )
    if memberships:
        if memberships == [profile_id]:
            already_confirmed = any(
                int(item["observation_id"]) == observation_id
                for item in database.list_speaker_profile_candidate_confirmations(
                    profile_id
                )
            )
            if already_confirmed:
                return None
            # Recover an interrupted apply that persisted membership before
            # its append-only confirmation provenance event.
        else:
            raise ValueError(
                "association candidate is already profiled elsewhere"
            )
    seed_ids = {
        int(value)
        for value in json.loads(str(promotion["seed_observation_ids_json"]))
    }
    seed_video_ids = {
        seed.video_id
        for seed_id in seed_ids
        if (seed := database.get_speaker_observation(seed_id)) is not None
    }
    if video_id in seed_video_ids:
        raise ValueError("confirmation must come from an independent recording")
    matched_profile = next(
        (
            item
            for item in report.get("profiles", ())
            if isinstance(item, Mapping)
            and item.get("profile_id") == profile_id
        ),
        None,
    )
    if (
        not isinstance(matched_profile, Mapping)
        or matched_profile.get("meets_multi_exemplar_match") is not True
    ):
        raise ValueError("association proposal lacks multi-exemplar confirmation")
    return ConfirmationCandidate(
        report_path=path,
        report_result_sha256=str(report["result_sha256"]),
        profile_id=profile_id,
        observation_id=observation_id,
        observation_fingerprint=fingerprint,
        video_id=video_id,
    )


def _existing_discovery_profile(
    database: Database,
    component_id: str,
) -> int | None:
    stable_key = f"speaker:discovery:{component_id[:32]}"
    return next(
        (
            profile.id
            for profile in database.list_speaker_profiles()
            if profile.stable_key == stable_key
        ),
        None,
    )


def _load_verified_report(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("artifact root must be an object")
    expected = payload.get("result_sha256")
    content = dict(payload)
    content.pop("result_sha256", None)
    if not isinstance(expected, str) or expected != _sha256(content):
        raise ValueError("artifact result checksum mismatch")
    return payload


def _sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _increment(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1
