from __future__ import annotations

import hashlib
import itertools
import json
import math
import os
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from pastor_transcript_extractor.models import utc_now
from pastor_transcript_extractor.speaker_profile_discovery import (
    SHADOW_PROFILE_DISCOVERY_VERSION,
    TRANSCRIPT_GROUNDED_SPAN_SELECTION_VERSION,
)
from pastor_transcript_extractor.speaker_pair_selector import (
    AcousticPairRanking,
    AssociationConfirmationPair,
    DiscoveryResolutionPair,
    EXPLORATORY_MAX_SAME_BOUNDARY_DISTANCE,
)
from pastor_transcript_extractor.speaker_shadow_association import (
    SHADOW_ASSOCIATION_VERSION,
)


IDENTITY_COORDINATION_VERSION = "identity_coordination_shadow_v2"
ASSOCIATION_CONFIRMATION_CACHE_VERSION = (
    "association_confirmation_nomination_cache_v1"
)
SUPPORTED_DISCOVERY_VERSIONS = frozenset(
    {
        "speaker_profile_shadow_discovery_v1",
        "speaker_profile_shadow_discovery_v2",
        "speaker_profile_shadow_discovery_v3",
        "speaker_profile_shadow_discovery_v4",
        "speaker_profile_shadow_discovery_v5",
        "speaker_profile_shadow_discovery_v6",
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
    exploratory_observation_ids = {
        int(observation_id)
        for result in payload.get("pair_results", ())
        if isinstance(result, Mapping)
        and result.get("outcome") == "insufficient_evidence"
        and result.get("reason") == "ambiguous_similarity"
        and result.get("consistency_tier") == "strong_strong"
        and result.get("registry_mutation_allowed") is False
        and result.get("reviewed_constraint") is not True
        and (
            margin := _pair_same_boundary_margin(result)
        ) is not None
        and margin >= -EXPLORATORY_MAX_SAME_BOUNDARY_DISTANCE
        for observation_id in result.get("observation_ids", ())
        if isinstance(observation_id, int)
    }
    for observation_id in exploratory_observation_ids:
        if states.get(observation_id) in {
            "evaluated_unclustered",
            "undersized_component",
        }:
            states[observation_id] = "exploratory_review_candidate"
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
    for frontier in payload.get("staged_review_frontier", ()):
        if not isinstance(frontier, Mapping):
            continue
        selected_review = frontier.get("selected_review")
        companion_review = frontier.get("companion_review")
        component_ids = frontier.get("component_ids")
        seed_fingerprints = frontier.get("seed_observation_fingerprints")
        candidate_fingerprint = frontier.get(
            "candidate_observation_fingerprint"
        )
        if not isinstance(selected_review, Mapping) or not isinstance(
            companion_review, Mapping
        ):
            continue
        fingerprints = selected_review.get("observation_fingerprints")
        companion_fingerprints = companion_review.get(
            "observation_fingerprints"
        )
        distance = selected_review.get("same_boundary_distance")
        required_review_count = frontier.get("required_review_count", 2)
        if (
            not isinstance(fingerprints, list)
            or len(fingerprints) != 2
            or not all(isinstance(value, str) and value for value in fingerprints)
            or not isinstance(companion_fingerprints, list)
            or len(companion_fingerprints) != 2
            or not all(
                isinstance(value, str) and value
                for value in companion_fingerprints
            )
            or not isinstance(component_ids, list)
            or not all(isinstance(value, str) for value in component_ids)
            or not isinstance(seed_fingerprints, list)
            or len(seed_fingerprints) != 2
            or not all(
                isinstance(value, str) and value for value in seed_fingerprints
            )
            or not isinstance(candidate_fingerprint, str)
            or not candidate_fingerprint
            or isinstance(distance, bool)
            or not isinstance(distance, (int, float))
            or not math.isfinite(float(distance))
            or isinstance(required_review_count, bool)
            or not isinstance(required_review_count, int)
            or required_review_count != 2
        ):
            continue
        seed_set = set(seed_fingerprints)
        if (
            candidate_fingerprint in seed_set
            or set(fingerprints)
            not in (
                {candidate_fingerprint, seed_fingerprints[0]},
                {candidate_fingerprint, seed_fingerprints[1]},
            )
            or set(companion_fingerprints)
            != (
                {candidate_fingerprint, seed_fingerprints[1]}
                if seed_fingerprints[0] in fingerprints
                else {candidate_fingerprint, seed_fingerprints[0]}
            )
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
            resolution_kind="staged_near_same_ambiguous_frontier",
            same_boundary_distance=float(distance),
            seed_fingerprints=tuple(sorted(seed_fingerprints)),
            candidate_fingerprint=candidate_fingerprint,
            companion_pair_fingerprints=tuple(
                sorted(companion_fingerprints)
            ),
            required_review_count=required_review_count,
        )
        existing = candidates.get(resolution.pair_key)
        if (
            existing is None
            or _resolution_priority(resolution)
            < _resolution_priority(existing)
        ):
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
                        _resolution_priority(existing) >= 2
                        and resolution.observations_unlocked
                        > existing.observations_unlocked
                    )
                ):
                    candidates[resolution.pair_key] = resolution
    return tuple(
        sorted(
            candidates.values(),
            key=lambda item: (
                _resolution_priority(item),
                item.same_boundary_distance
                if item.same_boundary_distance is not None
                else float("inf"),
                -item.observations_unlocked,
                item.fingerprint_a,
                item.fingerprint_b,
            ),
        )
    )


def load_discovery_acoustic_ranking_pairs(
    report_path: Path,
) -> tuple[AcousticPairRanking, ...]:
    """Load strong same and ambiguous results as non-durable review context."""
    payload = _load_verified_discovery_report(report_path)
    rankings: dict[frozenset[str], AcousticPairRanking] = {}
    for result in payload.get("pair_results", ()):
        if not isinstance(result, Mapping):
            continue
        outcome = result.get("outcome")
        reason = result.get("reason")
        if (
            (outcome, reason)
            not in {
                ("same_speaker", "approved_policy_same_band"),
                ("insufficient_evidence", "ambiguous_similarity"),
            }
            or result.get("consistency_tier") != "strong_strong"
            or result.get("registry_mutation_allowed") is not False
            or result.get("reviewed_constraint") is True
        ):
            continue
        fingerprints = result.get("observation_fingerprints")
        if (
            not isinstance(fingerprints, list)
            or len(fingerprints) != 2
            or not all(
                isinstance(value, str) and value for value in fingerprints
            )
        ):
            continue
        margin = _pair_same_boundary_margin(result)
        centroid_similarity = _finite_float(
            result.get("centroid_similarity")
        )
        if margin is None or centroid_similarity is None:
            continue
        if outcome == "same_speaker" and margin < 0.0:
            continue
        if (
            outcome == "insufficient_evidence"
            and margin < -EXPLORATORY_MAX_SAME_BOUNDARY_DISTANCE
        ):
            continue
        ranking = AcousticPairRanking(
            fingerprint_a=fingerprints[0],
            fingerprint_b=fingerprints[1],
            same_boundary_margin=margin,
            centroid_similarity=centroid_similarity,
            report_result_sha256=str(payload["result_sha256"]),
            report_path=str(report_path.expanduser().resolve()),
            outcome=str(outcome),
            reason=str(reason),
            source_local=bool(
                {
                    "source_local_complete_link",
                    "source_local_nearest_neighbor",
                }
                & set(result.get("retrieval_reasons") or ())
            ),
            retrieval_reasons=tuple(
                str(value)
                for value in (result.get("retrieval_reasons") or ())
                if isinstance(value, str) and value
            ),
        )
        existing = rankings.get(ranking.pair_key)
        if existing is None or (
            ranking.same_boundary_margin,
            ranking.centroid_similarity,
        ) > (
            existing.same_boundary_margin,
            existing.centroid_similarity,
        ):
            rankings[ranking.pair_key] = ranking
    return tuple(
        sorted(
            rankings.values(),
            key=lambda item: (
                0 if item.outcome == "same_speaker" else 1,
                -item.same_boundary_margin,
                -item.centroid_similarity,
                item.fingerprint_a,
                item.fingerprint_b,
            ),
        )
    )


def load_unmatched_association_fingerprints(
    report_paths: Iterable[Path],
    *,
    cache_path: Path | None = None,
) -> frozenset[str]:
    """Return candidates that have only current safe no-match/abstention reports."""
    ordered_paths = sorted(
        (path.expanduser().resolve() for path in report_paths),
        key=str,
    )
    if cache_path is not None:
        cached = _load_unmatched_association_cache(
            cache_path,
            report_set_fingerprint=_association_report_set_fingerprint(
                ordered_paths
            ),
            report_count=len(ordered_paths),
        )
        if cached is not None:
            return cached
    outcomes_by_fingerprint: dict[str, set[str]] = {}
    for report_path in ordered_paths:
        payload = _load_verified_association_report(report_path)
        if (
            payload.get("artifact_kind")
            != "speaker_profile_shadow_association"
            or payload.get("association_version")
            != SHADOW_ASSOCIATION_VERSION
        ):
            continue
        span_selection = payload.get("span_selection")
        if (
            payload.get("shadow_mode") is not True
            or payload.get("registry_mutation_allowed") is not False
            or payload.get("automatic_assignment_allowed") is not False
            or not isinstance(span_selection, Mapping)
            or span_selection.get("version")
            != TRANSCRIPT_GROUNDED_SPAN_SELECTION_VERSION
        ):
            continue
        candidate = payload.get("candidate")
        outcome = payload.get("outcome")
        if not isinstance(candidate, Mapping) or not isinstance(outcome, str):
            continue
        fingerprint = candidate.get("input_fingerprint")
        if not isinstance(fingerprint, str) or not fingerprint:
            continue
        outcomes_by_fingerprint.setdefault(fingerprint, set()).add(outcome)
    return frozenset(
        fingerprint
        for fingerprint, outcomes in outcomes_by_fingerprint.items()
        if outcomes
        and outcomes.issubset({"no_match", "insufficient_evidence"})
    )


def _pair_same_boundary_margin(result: Mapping[str, Any]) -> float | None:
    metrics = result.get("metrics")
    cross = metrics.get("cross") if isinstance(metrics, Mapping) else None
    policy = result.get("policy")
    if not isinstance(cross, Mapping) or not isinstance(policy, Mapping):
        return None
    cross_p10 = _finite_float(cross.get("p10"))
    cross_median = _finite_float(cross.get("median"))
    minimum_p10 = _finite_float(policy.get("same_min_cross_p10"))
    minimum_median = _finite_float(policy.get("same_min_cross_median"))
    if None in {
        cross_p10,
        cross_median,
        minimum_p10,
        minimum_median,
    }:
        return None
    assert cross_p10 is not None
    assert cross_median is not None
    assert minimum_p10 is not None
    assert minimum_median is not None
    return min(
        cross_p10 - minimum_p10,
        cross_median - minimum_median,
    )


def count_missing_discovery_reviewed_constraints(
    report_path: Path,
    reviewed_outcomes: Mapping[frozenset[str], str],
) -> int:
    """Count current reviewed edges absent from a discovery artifact."""
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
    report_fingerprints = frozenset(fingerprints_by_observation_id.values())
    constraints = payload.get("reviewed_constraints")
    covered: dict[frozenset[str], str] = {}
    if isinstance(constraints, Mapping):
        for key, outcome in (
            ("same_speaker_observation_pairs", "same_speaker"),
            ("different_speaker_observation_pairs", "different_speaker"),
        ):
            for raw_pair in constraints.get(key, ()):
                if (
                    not isinstance(raw_pair, list)
                    or len(raw_pair) != 2
                    or not all(isinstance(value, int) for value in raw_pair)
                ):
                    continue
                fingerprints = [
                    fingerprints_by_observation_id.get(value)
                    for value in raw_pair
                ]
                if all(fingerprints):
                    covered[frozenset(str(value) for value in fingerprints)] = (
                        outcome
                    )
    return sum(
        1
        for pair, outcome in reviewed_outcomes.items()
        if outcome in {"same_speaker", "different_speaker"}
        and len(pair) == 2
        and pair.issubset(report_fingerprints)
        and covered.get(pair) != outcome
    )


def load_shadow_association_confirmation_pairs(
    report_paths: Iterable[Path],
    *,
    progress_callback: Callable[[int, int, Path], None] | None = None,
    cache_path: Path | None = None,
) -> tuple[AssociationConfirmationPair, ...]:
    """Load exact same edges from safe multi-exemplar profile proposals."""
    ordered_paths = sorted(
        (path.expanduser().resolve() for path in report_paths),
        key=str,
    )
    report_set_fingerprint = _association_report_set_fingerprint(
        ordered_paths
    )
    if cache_path is not None:
        cached = _load_association_confirmation_cache(
            cache_path,
            report_set_fingerprint=report_set_fingerprint,
            report_count=len(ordered_paths),
        )
        if cached is not None:
            return cached

    nominations: dict[frozenset[str], AssociationConfirmationPair] = {}
    outcomes_by_fingerprint: dict[str, set[str]] = {}
    for index, report_path in enumerate(ordered_paths, start=1):
        payload = _load_verified_association_report(report_path)
        if progress_callback is not None:
            progress_callback(index, len(ordered_paths), report_path)
        if (
            payload.get("artifact_kind")
            != "speaker_profile_shadow_association"
            or payload.get("association_version")
            != SHADOW_ASSOCIATION_VERSION
        ):
            continue
        span_selection = payload.get("span_selection")
        if (
            payload.get("shadow_mode") is not True
            or payload.get("registry_mutation_allowed") is not False
            or payload.get("automatic_assignment_allowed") is not False
            or not isinstance(span_selection, Mapping)
            or span_selection.get("version")
            != TRANSCRIPT_GROUNDED_SPAN_SELECTION_VERSION
        ):
            raise ValueError(
                "shadow association artifact uses an unsupported contract"
            )
        candidate = payload.get("candidate")
        profile_id = payload.get("proposed_profile_id")
        outcome = payload.get("outcome")
        if isinstance(candidate, Mapping) and isinstance(outcome, str):
            fingerprint = candidate.get("input_fingerprint")
            if isinstance(fingerprint, str) and fingerprint:
                outcomes_by_fingerprint.setdefault(fingerprint, set()).add(
                    outcome
                )
        if (
            outcome != "proposed_match"
            or not isinstance(candidate, Mapping)
            or not isinstance(profile_id, int)
        ):
            continue
        candidate_fingerprint = candidate.get("input_fingerprint")
        if not isinstance(candidate_fingerprint, str) or not candidate_fingerprint:
            continue
        profile_results = payload.get("profiles")
        if not isinstance(profile_results, list):
            continue
        matched = next(
            (
                result
                for result in profile_results
                if isinstance(result, Mapping)
                and result.get("profile_id") == profile_id
                and result.get("meets_multi_exemplar_match") is True
            ),
            None,
        )
        if not isinstance(matched, Mapping):
            continue
        comparisons = matched.get("comparisons")
        if not isinstance(comparisons, list):
            continue
        same_comparisons = [
            comparison
            for comparison in comparisons
            if isinstance(comparison, Mapping)
            and comparison.get("outcome") == "same_speaker"
            and comparison.get("reason") == "approved_policy_same_band"
            and comparison.get("reviewed_constraint") is not True
        ]
        if len(same_comparisons) < 2:
            continue
        for comparison in same_comparisons:
            exemplar_fingerprint = comparison.get("exemplar_fingerprint")
            metrics = comparison.get("metrics")
            cross = (
                metrics.get("cross")
                if isinstance(metrics, Mapping)
                else None
            )
            policy = comparison.get("policy")
            if (
                not isinstance(exemplar_fingerprint, str)
                or not exemplar_fingerprint
                or not isinstance(cross, Mapping)
                or not isinstance(policy, Mapping)
            ):
                continue
            cross_p10 = _finite_float(cross.get("p10"))
            cross_median = _finite_float(cross.get("median"))
            minimum_p10 = _finite_float(policy.get("same_min_cross_p10"))
            minimum_median = _finite_float(
                policy.get("same_min_cross_median")
            )
            if None in {
                cross_p10,
                cross_median,
                minimum_p10,
                minimum_median,
            }:
                continue
            assert cross_p10 is not None
            assert cross_median is not None
            assert minimum_p10 is not None
            assert minimum_median is not None
            margin = min(
                cross_p10 - minimum_p10,
                cross_median - minimum_median,
            )
            if margin < 0.0:
                continue
            nomination = AssociationConfirmationPair(
                candidate_fingerprint=candidate_fingerprint,
                exemplar_fingerprint=exemplar_fingerprint,
                profile_id=profile_id,
                same_comparison_count=len(same_comparisons),
                same_boundary_margin=margin,
                report_result_sha256=str(payload["result_sha256"]),
                report_path=str(report_path),
            )
            existing = nominations.get(nomination.pair_key)
            if existing is None or (
                nomination.same_comparison_count,
                nomination.same_boundary_margin,
                nomination.report_result_sha256,
            ) > (
                existing.same_comparison_count,
                existing.same_boundary_margin,
                existing.report_result_sha256,
            ):
                nominations[nomination.pair_key] = nomination
    result = tuple(
        sorted(
            nominations.values(),
            key=lambda item: (
                -item.same_comparison_count,
                -item.same_boundary_margin,
                item.candidate_fingerprint,
                item.exemplar_fingerprint,
                item.report_result_sha256,
            ),
        )
    )
    if cache_path is not None:
        _write_association_confirmation_cache(
            cache_path,
            report_set_fingerprint=report_set_fingerprint,
            report_count=len(ordered_paths),
            nominations=result,
            unmatched_fingerprints=frozenset(
                fingerprint
                for fingerprint, outcomes in outcomes_by_fingerprint.items()
                if outcomes
                and outcomes.issubset(
                    {"no_match", "insufficient_evidence"}
                )
            ),
        )
    return result


def _association_report_set_fingerprint(paths: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        stat = path.stat()
        digest.update(str(path).encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(stat.st_size).encode("ascii"))
        digest.update(b"\0")
        digest.update(str(stat.st_mtime_ns).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _load_association_confirmation_cache(
    path: Path,
    *,
    report_set_fingerprint: str,
    report_count: int,
) -> tuple[AssociationConfirmationPair, ...] | None:
    resolved = path.expanduser().resolve()
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
        raw_nominations = payload["nominations"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        return None
    if (
        not isinstance(payload, Mapping)
        or payload.get("cache_version")
        != ASSOCIATION_CONFIRMATION_CACHE_VERSION
        or payload.get("report_set_fingerprint")
        != report_set_fingerprint
        or payload.get("report_count") != report_count
        or not isinstance(raw_nominations, list)
    ):
        return None
    try:
        return tuple(
            AssociationConfirmationPair(**item)
            for item in raw_nominations
            if isinstance(item, dict)
        )
    except TypeError:
        return None


def _write_association_confirmation_cache(
    path: Path,
    *,
    report_set_fingerprint: str,
    report_count: int,
    nominations: tuple[AssociationConfirmationPair, ...],
    unmatched_fingerprints: frozenset[str],
) -> None:
    resolved = path.expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "cache_version": ASSOCIATION_CONFIRMATION_CACHE_VERSION,
        "report_set_fingerprint": report_set_fingerprint,
        "report_count": report_count,
        "unmatched_fingerprints": sorted(unmatched_fingerprints),
        "nominations": [
            {
                "candidate_fingerprint": item.candidate_fingerprint,
                "exemplar_fingerprint": item.exemplar_fingerprint,
                "profile_id": item.profile_id,
                "same_comparison_count": item.same_comparison_count,
                "same_boundary_margin": item.same_boundary_margin,
                "report_result_sha256": item.report_result_sha256,
                "report_path": item.report_path,
                "provisional_assignment_active": (
                    item.provisional_assignment_active
                ),
            }
            for item in nominations
        ],
    }
    temporary = resolved.with_suffix(resolved.suffix + ".partial")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, resolved)


def _load_unmatched_association_cache(
    path: Path,
    *,
    report_set_fingerprint: str,
    report_count: int,
) -> frozenset[str] | None:
    resolved = path.expanduser().resolve()
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
        values = payload["unmatched_fingerprints"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        return None
    if (
        not isinstance(payload, Mapping)
        or payload.get("cache_version")
        != ASSOCIATION_CONFIRMATION_CACHE_VERSION
        or payload.get("report_set_fingerprint")
        != report_set_fingerprint
        or payload.get("report_count") != report_count
        or not isinstance(values, list)
        or not all(isinstance(value, str) and value for value in values)
    ):
        return None
    return frozenset(values)


def _finite_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    numeric = float(value)
    return numeric if math.isfinite(numeric) else None


def _resolution_priority(resolution: DiscoveryResolutionPair) -> int:
    return {
        "near_same_ambiguous_frontier": 0,
        "staged_near_same_ambiguous_frontier": 1,
        "component_overlap": 2,
    }.get(resolution.resolution_kind, 3)


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


def _load_verified_association_report(report_path: Path) -> dict[str, Any]:
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("shadow association artifact must be an object")
    expected_sha256 = payload.get("result_sha256")
    unhashed = dict(payload)
    unhashed.pop("result_sha256", None)
    if (
        not isinstance(expected_sha256, str)
        or _sha256_json(unhashed) != expected_sha256
    ):
        raise ValueError("shadow association artifact checksum mismatch")
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
        and discovery_state == "exploratory_review_candidate"
    ):
        workflow_state = "identity_human_review_nominatable"
        next_action = "review_exploratory_profile_growth_pair"
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
