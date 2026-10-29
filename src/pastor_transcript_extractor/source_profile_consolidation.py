from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
import hashlib
import html
import itertools
import json
import math
import shlex
from pathlib import Path
from typing import Any, Mapping, Sequence

from pastor_transcript_extractor.reviewed_speaker_evidence import (
    ReviewedSpeakerEvidence,
    merge_reviewed_source_profile_cohort,
)
from pastor_transcript_extractor.models import SpeakerObservation, Video
from pastor_transcript_extractor.speaker_shadow_association import (
    ProfileAssociationReadiness,
    assess_profile_association_readiness,
)
from pastor_transcript_extractor.storage import Database
from pastor_transcript_extractor.speaker_pair_diagnostics import (
    ANALYZER_VERSION,
    DecisionPolicy,
    apply_decision_policy,
)
from pastor_transcript_extractor.speaker_pair_eligibility import assess_automatic_speaker_observation


SOURCE_PROFILE_CONSOLIDATION_VERSION = "source_profile_consolidation_v2"


@dataclass(frozen=True, slots=True)
class SourceProfileCandidate:
    profile_id: int
    member_observation_ids: tuple[int, ...]
    exemplar_observation_ids: tuple[int, ...]
    recording_count: int
    normalized_names: tuple[str, ...]
    identity_warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SourceProfilePairEvidence:
    profile_ids: tuple[int, int]
    comparison_count: int
    same_count: int
    different_count: int
    insufficient_count: int
    weakest_observation_pair: tuple[int, int] | None
    weakest_score: float | None
    eligible: bool
    blockers: tuple[str, ...]
    identity_warnings: tuple[str, ...] = ()
    reviewed_same_pairs: tuple[tuple[int, int], ...] = ()
    review_event_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SourceProfileConsolidationProposal:
    profile_ids: tuple[int, ...]
    profile_pair_count: int
    comparison_count: int
    weakest_observation_pair: tuple[int, int]
    weakest_score: float | None


@dataclass(frozen=True, slots=True)
class SourceProfileConsolidationPlan:
    source_id: int
    candidates: tuple[SourceProfileCandidate, ...]
    pair_evidence: tuple[SourceProfilePairEvidence, ...]
    proposals: tuple[SourceProfileConsolidationProposal, ...]
    excluded_profiles: tuple[tuple[int, str], ...]


@dataclass(frozen=True, slots=True)
class SourceProfileCohortSummary:
    source_id: int
    source_reference: str
    profile_count: int
    member_count: int
    exemplar_count: int
    comparison_upper_bound: int
    excluded_profile_count: int


@dataclass(frozen=True, slots=True)
class _SourceProfileCandidateContext:
    videos_by_id: Mapping[int, Video]
    observations_by_id: Mapping[int, SpeakerObservation]
    readiness_by_id: Mapping[int, ProfileAssociationReadiness]
    identity_warnings_by_id: Mapping[int, tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class SavedSourceProfileComparisons:
    comparisons: Mapping[tuple[int, int], Mapping[str, Any]]
    inspected_artifact_count: int
    rejection_counts: Mapping[str, int]


def load_saved_source_profile_comparisons(
    database: Database,
    candidates: Sequence[SourceProfileCandidate],
    *,
    association_root: Path,
    model: Mapping[str, Any],
    policy: DecisionPolicy,
    policy_fingerprint: str,
) -> SavedSourceProfileComparisons:
    """Reuse exact diagnostic leaves from hash-verified association snapshots.

    A changed association pack or profile snapshot does not invalidate a leaf.
    Its observation, registered parent audio, model and policy must still match.
    No audio is consumed here; archive availability is not evidence validity.
    """
    rejected: Counter[str] = Counter()
    eligible = {}
    owners: dict[int, set[int]] = defaultdict(set)
    for candidate in candidates:
        for observation_id in candidate.member_observation_ids:
            owners[observation_id].add(candidate.profile_id)
    for observation_id in sorted(owners):
        observation = database.get_speaker_observation(observation_id)
        if observation is None:
            rejected["observation_missing"] += 1
            continue
        eligibility = assess_automatic_speaker_observation(
            database, observation.video_id, observation_id=observation_id,
            verify_media=False,
        )
        if not eligibility.eligible or eligibility.media_artifact is None:
            rejected[eligibility.reason_code] += 1
            continue
        eligible[observation.input_fingerprint] = (observation, eligibility.media_artifact)

    accepted: dict[tuple[int, int], list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    inspected = 0
    expected_policy = asdict(policy)
    for fingerprint, (candidate_observation, candidate_media) in sorted(eligible.items()):
        directory = association_root.expanduser().resolve() / fingerprint[:16]
        for path in sorted(directory.glob("*.json")):
            inspected += 1
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                unhashed = dict(payload)
                receipt = unhashed.pop("result_sha256", None)
                if (payload.get("artifact_kind") != "speaker_profile_shadow_association"
                    or payload.get("schema_version") != 1
                    or payload.get("shadow_mode") is not True
                    or payload.get("registry_mutation_allowed") is not False
                    or receipt != _sha256(unhashed)):
                    rejected["invalid_artifact_receipt"] += 1
                    continue
                candidate = payload.get("candidate", {})
                if (candidate.get("input_fingerprint") != fingerprint
                    or candidate.get("observation_id") != candidate_observation.id
                    or candidate.get("normalized_audio_sha256") != candidate_media.content_sha256):
                    rejected["candidate_media_or_observation_mismatch"] += 1
                    continue
                if (payload.get("model_fingerprint") != _sha256(model)
                    or payload.get("policy", {}).get("artifact_sha256") != policy_fingerprint):
                    rejected["model_or_policy_artifact_mismatch"] += 1
                    continue
                for profile in payload.get("profiles", []):
                    for comparison in profile.get("comparisons", []):
                        try:
                            other_fingerprint = comparison.get("exemplar_fingerprint")
                            other = eligible.get(other_fingerprint)
                            if other is None or other_fingerprint == fingerprint:
                                continue
                            observation, media = other
                            if not any(a != b for a in owners[candidate_observation.id] for b in owners[observation.id]):
                                continue
                            if (comparison.get("reviewed_constraint") is True
                                or comparison.get("schema_version") != 1
                                or comparison.get("registry_mutation_allowed") is not False
                                or comparison.get("exemplar_observation_id") != observation.id
                                or comparison.get("exemplar_normalized_audio_sha256") != media.content_sha256
                                or comparison.get("observations") != {"a": fingerprint, "b": other_fingerprint}
                                or comparison.get("analyzer_version") != ANALYZER_VERSION
                                or comparison.get("model") != dict(model)
                                or comparison.get("policy") != expected_policy
                                or comparison.get("policy_version") != policy.version):
                                rejected["incompatible_comparison"] += 1
                                continue
                            result = {key: value for key, value in comparison.items()
                                      if key not in {"exemplar_fingerprint", "exemplar_observation_id", "exemplar_normalized_audio_sha256"}}
                            if not _saved_comparison_spans_match(result, candidate_observation, observation, policy.min_valid_spans):
                                rejected["incompatible_saved_spans"] += 1
                                continue
                            metrics = result["metrics"]
                            values = [metrics["within_a"]["median"], metrics["within_b"]["median"],
                                      *(metrics["cross"][name] for name in ("p10", "median", "p90"))]
                            if not all(isinstance(value, (int, float)) and not isinstance(value, bool)
                                       and math.isfinite(value) for value in values):
                                rejected["invalid_saved_metrics"] += 1
                                continue
                            outcome, _ = apply_decision_policy(result["metrics"], policy)
                            if result.get("outcome") != outcome:
                                rejected["saved_outcome_policy_mismatch"] += 1
                                continue
                            pair = tuple(sorted((candidate_observation.id, observation.id)))
                            accepted[pair].append((result, {
                                "artifact_path": str(path), "artifact_sha256": receipt,
                                "comparison_sha256": _sha256(comparison),
                                "outcome": result["outcome"],
                                "association_version": payload.get("association_version"),
                                "span_selection": payload.get("span_selection"),
                                "reuse_scope": "exact_recorded_diagnostic; no_new_audio_consumed_or_spans_reselected",
                                "normalized_audio_sha256": {"a": candidate_media.content_sha256, "b": media.content_sha256},
                            }))
                        except (ValueError, TypeError, KeyError, AttributeError):
                            rejected["malformed_saved_comparison"] += 1
            except (OSError, UnicodeError, ValueError, TypeError, KeyError, AttributeError):
                rejected["malformed_saved_artifact"] += 1
    comparisons = {}
    for pair, records in sorted(accepted.items()):
        # Never cherry-pick the strongest diagnostic or hide a conflicting run.
        outcomes = {result["outcome"] for result, _ in records}
        result = dict(records[0][0]) if len(outcomes) == 1 else {
            "outcome": "insufficient_evidence", "reason": "conflicting_saved_comparisons",
        }
        result["saved_evidence"] = [receipt for _, receipt in records]
        comparisons[pair] = result
    return SavedSourceProfileComparisons(comparisons, inspected, dict(sorted(rejected.items())))


def _saved_comparison_spans_match(
    result: Mapping[str, Any], a: SpeakerObservation, b: SpeakerObservation, minimum: int,
) -> bool:
    for label, observation in (("a", a), ("b", b)):
        spans = result.get("spans", {}).get(label, [])
        if not isinstance(spans, list) or len(spans) < minimum:
            return False
        for span in spans:
            start, end = float(span["start_seconds"]), float(span["end_seconds"])
            digest = span.get("wav_sha256", "")
            if (span.get("observation_fingerprint") != observation.input_fingerprint
                or not math.isfinite(start) or not math.isfinite(end)
                or not observation.start_seconds <= start < end <= observation.end_seconds
                or not isinstance(digest, str) or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)):
                return False
    return True


def source_profile_candidates(
    database: Database,
    evidence: ReviewedSpeakerEvidence,
    *,
    source_id: int,
    exemplars_per_profile: int = 3,
) -> tuple[tuple[SourceProfileCandidate, ...], tuple[tuple[int, str], ...]]:
    """Select bounded, independent exemplars for canonical profiles on a source.

    Source membership is only a cohort-retrieval condition. Every selected
    exemplar remains an independently recorded observation and must later pass
    the normal acoustic decision policy.
    """
    if exemplars_per_profile < 2:
        raise ValueError("source-profile consolidation requires at least two exemplars")
    context = _source_profile_candidate_context(database, evidence)
    return _source_profile_candidates_from_context(
        database,
        context,
        source_id=source_id,
        exemplars_per_profile=exemplars_per_profile,
    )


def list_source_profile_cohorts(
    database: Database,
    evidence: ReviewedSpeakerEvidence,
    *,
    exemplars_per_profile: int = 3,
    minimum_profiles: int = 2,
) -> tuple[SourceProfileCohortSummary, ...]:
    if minimum_profiles < 1:
        raise ValueError("minimum source profile count must be positive")
    if exemplars_per_profile < 2:
        raise ValueError("source-profile consolidation requires at least two exemplars")
    context = _source_profile_candidate_context(database, evidence)
    summaries: list[SourceProfileCohortSummary] = []
    for source in database.list_sources():
        candidates, excluded = _source_profile_candidates_from_context(
            database,
            context,
            source_id=source.id,
            exemplars_per_profile=exemplars_per_profile,
        )
        if len(candidates) < minimum_profiles:
            continue
        summaries.append(
            SourceProfileCohortSummary(
                source_id=source.id,
                source_reference=source.source_identity_key or source.url,
                profile_count=len(candidates),
                member_count=sum(
                    len(candidate.member_observation_ids)
                    for candidate in candidates
                ),
                exemplar_count=sum(
                    len(candidate.exemplar_observation_ids)
                    for candidate in candidates
                ),
                comparison_upper_bound=sum(
                    len(left.exemplar_observation_ids)
                    * len(right.exemplar_observation_ids)
                    for index, left in enumerate(candidates)
                    for right in candidates[index + 1 :]
                ),
                excluded_profile_count=len(excluded),
            )
        )
    return tuple(
        sorted(
            summaries,
            key=lambda item: (-item.profile_count, item.source_id),
        )
    )


def _source_profile_candidate_context(
    database: Database,
    evidence: ReviewedSpeakerEvidence,
) -> _SourceProfileCandidateContext:
    videos_by_id = {video.id: video for video in database.list_videos()}
    observations_by_id = {
        observation.id: observation
        for observation in database.list_speaker_observations()
    }
    readiness_by_id = {
        item.profile_id: item
        for item in assess_profile_association_readiness(
            database, evidence, include_configured_profiles=True
        )
    }
    linked_profile_ids = {
        database.resolve_speaker_profile_id(profile_id)
        for pastor in database.list_pastors()
        if (profile_id := database.get_pastor_speaker_profile_id(pastor.id))
        is not None
    }
    warnings_by_id = {}
    for profile_id in readiness_by_id:
        warnings = []
        if profile_id in linked_profile_ids:
            warnings.append("configured_pastor_identity")
        if (database.list_effective_name_claim_ids_for_profile(profile_id)
            or readiness_by_id[profile_id].normalized_names):
            warnings.append("confirmed_name_claim")
        if len(readiness_by_id[profile_id].normalized_names) > 1:
            warnings.append("conflicting_explicit_attribution")
        warnings_by_id[profile_id] = tuple(warnings)
    return _SourceProfileCandidateContext(
        videos_by_id=videos_by_id,
        observations_by_id=observations_by_id,
        readiness_by_id=readiness_by_id,
        identity_warnings_by_id=warnings_by_id,
    )


def _source_profile_candidates_from_context(
    database: Database,
    context: _SourceProfileCandidateContext,
    *,
    source_id: int,
    exemplars_per_profile: int,
) -> tuple[tuple[SourceProfileCandidate, ...], tuple[tuple[int, str], ...]]:
    candidates: list[SourceProfileCandidate] = []
    excluded: list[tuple[int, str]] = []
    for profile_id, readiness in sorted(context.readiness_by_id.items()):
        member_ids = tuple(readiness.member_observation_ids)
        source_member_ids = tuple(
            observation_id
            for observation_id in member_ids
            if (
                (observation := context.observations_by_id.get(observation_id))
                is not None
                and observation.video_id in context.videos_by_id
                and context.videos_by_id[observation.video_id].source_id
                == source_id
            )
        )
        if not source_member_ids:
            continue
        unsafe_blockers = tuple(
            blocker
            for blocker in readiness.shadow_blockers
            if blocker
            not in {
                "fewer_than_three_profile_members",
                "fewer_than_three_distinct_recordings",
                "conflicting_explicit_attribution",
            }
        )
        if unsafe_blockers:
            excluded.append((profile_id, unsafe_blockers[0]))
            continue

        preferred_ids = list(readiness.certified_exemplar_observation_ids)
        if not preferred_ids:
            promotion = database.get_speaker_profile_discovery_promotion(profile_id)
            raw_seed_ids = promotion.get("seed_observation_ids_json") if promotion else None
            try:
                parsed_seed_ids = json.loads(str(raw_seed_ids)) if raw_seed_ids else []
            except json.JSONDecodeError:
                parsed_seed_ids = []
            preferred_ids = [
                int(value)
                for value in parsed_seed_ids
                if isinstance(value, int) and value in member_ids
            ]
        ordered_ids = tuple(dict.fromkeys((*preferred_ids, *source_member_ids, *member_ids)))
        selected: list[int] = []
        selected_video_ids: set[int] = set()
        for observation_id in ordered_ids:
            observation = context.observations_by_id.get(observation_id)
            if observation is None or observation.video_id in selected_video_ids:
                continue
            selected.append(observation_id)
            selected_video_ids.add(observation.video_id)
            if len(selected) >= exemplars_per_profile:
                break
        if len(selected) < 2:
            excluded.append((profile_id, "fewer_than_two_independent_exemplars"))
            continue
        candidates.append(
            SourceProfileCandidate(
                profile_id=profile_id,
                member_observation_ids=member_ids,
                exemplar_observation_ids=tuple(selected),
                recording_count=readiness.recording_count,
                normalized_names=readiness.normalized_names,
                identity_warnings=context.identity_warnings_by_id.get(profile_id, ()),
            )
        )
    return tuple(candidates), tuple(excluded)


def build_source_profile_consolidation_plan(
    database: Database,
    *,
    source_id: int,
    candidates: Sequence[SourceProfileCandidate],
    comparisons: Mapping[tuple[int, int], Mapping[str, Any]],
    minimum_same_comparisons: int = 2,
    reviewed_evidence: ReviewedSpeakerEvidence | None = None,
) -> SourceProfileConsolidationPlan:
    """Build non-overlapping complete-link profile cohorts.

    Every cross-profile exemplar comparison must say ``same_speaker`` or have
    its abstention resolved by a qualified, exact human same-speaker judgment.
    Every profile pair in a cohort must have such an edge. Reviewed differences
    and conflicting human reviews remain blockers, including unsampled members.
    """
    if minimum_same_comparisons < 2:
        raise ValueError("at least two same-speaker comparisons are required")
    different_pairs = {
        tuple(sorted(pair))
        for pair in database.list_effective_observation_difference_pairs()
    }
    pair_evidence: list[SourceProfilePairEvidence] = []
    review_actions = database.list_effective_observation_review_actions()
    observations_by_id = {
        observation.id: observation for observation in database.list_speaker_observations()
    } if reviewed_evidence is not None else {}
    eligible_profile_pairs: set[tuple[int, int]] = set()
    pair_by_profiles: dict[tuple[int, int], SourceProfilePairEvidence] = {}
    ordered_candidates = sorted(candidates, key=lambda item: item.profile_id)
    for left, right in itertools.combinations(ordered_candidates, 2):
        blockers: list[str] = []
        member_ids = set(left.member_observation_ids) | set(right.member_observation_ids)
        if any(review_actions.get(value) not in (None, "qualified_single_speaker") for value in member_ids):
            blockers.append("reviewed_unqualified_profile_member")
        if reviewed_evidence is not None:
            for value in member_ids:
                observation = observations_by_id.get(value)
                if observation is None:
                    continue
                fingerprint = observation.input_fingerprint
                qualification = reviewed_evidence.qualifications.get(fingerprint)
                if (fingerprint in reviewed_evidence.qualification_conflicts
                    or (qualification is not None and qualification.action != "qualified_single_speaker")):
                    blockers.append("reviewed_unqualified_profile_member")
        names = set(left.normalized_names) | set(right.normalized_names)
        identity_warnings = list(dict.fromkeys((*left.identity_warnings, *right.identity_warnings)))
        if len(names) > 1:
            identity_warnings.append("conflicting_explicit_attribution")
        cross_pairs = [
            tuple(sorted((left_id, right_id)))
            for left_id in left.exemplar_observation_ids
            for right_id in right.exemplar_observation_ids
        ]
        if any(
            (a in left.member_observation_ids and b in right.member_observation_ids)
            or (b in left.member_observation_ids and a in right.member_observation_ids)
            for a, b in different_pairs
        ):
            blockers.append("reviewed_different_speaker_constraint")
        if reviewed_evidence is not None:
            left_fingerprints = {
                observations_by_id[value].input_fingerprint
                for value in left.member_observation_ids if value in observations_by_id
            }
            right_fingerprints = {
                observations_by_id[value].input_fingerprint
                for value in right.member_observation_ids if value in observations_by_id
            }
            for relation in reviewed_evidence.pair_relations.values():
                if (relation.outcome == "different_speaker"
                    and relation.fingerprints & left_fingerprints
                    and relation.fingerprints & right_fingerprints):
                    blockers.append("reviewed_different_speaker_constraint")
            if any(pair & left_fingerprints and pair & right_fingerprints
                   for pair in reviewed_evidence.pair_conflicts):
                blockers.append("conflicting_human_pair_reviews")
        results = [comparisons.get(pair) for pair in cross_pairs]
        reviewed_same_pairs = []
        review_event_ids: set[str] = set()
        for index, pair in enumerate(cross_pairs):
            if reviewed_evidence is None:
                break
            observations = [observations_by_id.get(value) for value in pair]
            if any(observation is None for observation in observations):
                continue
            fingerprints = frozenset(observation.input_fingerprint for observation in observations)
            if fingerprints in reviewed_evidence.pair_conflicts:
                blockers.append("conflicting_human_pair_reviews")
                continue
            relation = reviewed_evidence.pair_relations.get(fingerprints)
            if relation is None:
                continue
            if relation.outcome == "different_speaker":
                blockers.append("reviewed_different_speaker_constraint")
                continue
            qualified = all(
                fingerprint not in reviewed_evidence.qualification_conflicts
                and (qualification := reviewed_evidence.qualifications.get(fingerprint)) is not None
                and qualification.action == "qualified_single_speaker"
                for fingerprint in fingerprints
            )
            result = results[index]
            if qualified and relation.outcome == "same_speaker" and (
                result is None or result.get("outcome") == "insufficient_evidence"
            ):
                results[index] = {**(result or {}), "outcome": "same_speaker"}
                reviewed_same_pairs.append(pair)
                review_event_ids.update(item.review_event_id for item in relation.provenance)
        same_count = sum(
            result is not None and result.get("outcome") == "same_speaker"
            for result in results
        )
        different_count = sum(
            result is not None and result.get("outcome") == "different_speaker"
            for result in results
        )
        insufficient_count = len(results) - same_count - different_count
        if different_count:
            blockers.append("acoustic_different_speaker_result")
        if insufficient_count:
            blockers.append("incomplete_or_ambiguous_complete_link")
        if same_count < minimum_same_comparisons:
            blockers.append("too_few_same_speaker_comparisons")
        scored = [
            (_comparison_score(result), pair)
            for pair, result in zip(cross_pairs, results, strict=True)
            if result is not None and _comparison_score(result) is not None
        ]
        weakest_score: float | None = None
        weakest_pair: tuple[int, int] | None = None
        if scored:
            weakest_score, weakest_pair = min(scored, key=lambda item: (item[0], item[1]))
        elif cross_pairs:
            weakest_pair = min(cross_pairs)
        eligible = not blockers
        profile_pair = (left.profile_id, right.profile_id)
        item = SourceProfilePairEvidence(
            profile_ids=profile_pair,
            comparison_count=len(results),
            same_count=same_count,
            different_count=different_count,
            insufficient_count=insufficient_count,
            weakest_observation_pair=weakest_pair,
            weakest_score=weakest_score,
            eligible=eligible,
            blockers=tuple(dict.fromkeys(blockers)),
            identity_warnings=tuple(dict.fromkeys(identity_warnings)),
            reviewed_same_pairs=tuple(reviewed_same_pairs),
            review_event_ids=tuple(sorted(review_event_ids)),
        )
        pair_evidence.append(item)
        pair_by_profiles[profile_pair] = item
        if eligible:
            eligible_profile_pairs.add(profile_pair)

    remaining = [candidate.profile_id for candidate in ordered_candidates]
    proposal_ids: list[tuple[int, ...]] = []
    while remaining:
        seed = remaining.pop(0)
        component = [seed]
        for profile_id in tuple(remaining):
            if all(
                tuple(sorted((profile_id, member))) in eligible_profile_pairs
                for member in component
            ):
                component.append(profile_id)
                remaining.remove(profile_id)
        if len(component) >= 2:
            proposal_ids.append(tuple(component))

    proposals: list[SourceProfileConsolidationProposal] = []
    for profile_ids in proposal_ids:
        evidence_items = [
            pair_by_profiles[tuple(sorted(pair))]
            for pair in itertools.combinations(profile_ids, 2)
        ]
        weakest = min(
            (item for item in evidence_items if item.weakest_observation_pair is not None),
            key=lambda item: (
                item.weakest_score if item.weakest_score is not None else float("-inf"),
                item.profile_ids,
            ),
        )
        assert weakest.weakest_observation_pair is not None
        proposals.append(
            SourceProfileConsolidationProposal(
                profile_ids=profile_ids,
                profile_pair_count=len(evidence_items),
                comparison_count=sum(item.comparison_count for item in evidence_items),
                weakest_observation_pair=weakest.weakest_observation_pair,
                weakest_score=weakest.weakest_score,
            )
        )
    return SourceProfileConsolidationPlan(
        source_id=source_id,
        candidates=tuple(candidates),
        pair_evidence=tuple(pair_evidence),
        proposals=tuple(proposals),
        excluded_profiles=(),
    )


def apply_source_profile_consolidation(
    database: Database,
    *,
    plan: SourceProfileConsolidationPlan,
    proposal: SourceProfileConsolidationProposal,
    reviewer: str,
    artifact_sha256: str,
    conflicts: list[str] | None = None,
    allow_confirmed_names: bool = False,
    canonical_profile_id: int | None = None,
) -> int | None:
    if proposal not in plan.proposals:
        raise ValueError("Only a supported proposal from this plan may be approved")
    return merge_reviewed_source_profile_cohort(
        database,
        source_id=plan.source_id,
        profile_ids=set(proposal.profile_ids),
        reviewer=reviewer,
        evidence_sha256=artifact_sha256,
        conflicts=conflicts,
        allow_confirmed_names=allow_confirmed_names,
        canonical_profile_id=canonical_profile_id,
    )


def source_profile_consolidation_payload(
    plan: SourceProfileConsolidationPlan,
    *,
    comparisons: Mapping[tuple[int, int], Mapping[str, Any]],
    model_fingerprint: str,
    policy_fingerprint: str,
    preparation_failures: Sequence[tuple[int, str]] = (),
    review_suggestions: Sequence[Mapping[str, Any]] = (),
    saved_evidence_reuse: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "artifact_kind": "source_profile_consolidation",
        "version": SOURCE_PROFILE_CONSOLIDATION_VERSION,
        "source_id": plan.source_id,
        "source_role": "retrieval_only",
        "source_is_identity_evidence": False,
        "model_fingerprint": model_fingerprint,
        "policy_fingerprint": policy_fingerprint,
        "candidates": [
            {
                "profile_id": item.profile_id,
                "member_observation_ids": list(item.member_observation_ids),
                "exemplar_observation_ids": list(item.exemplar_observation_ids),
                "recording_count": item.recording_count,
                "normalized_names": list(item.normalized_names),
                "identity_warnings": list(item.identity_warnings),
            }
            for item in plan.candidates
        ],
        "pair_evidence": [
            {
                "profile_ids": list(item.profile_ids),
                "comparison_count": item.comparison_count,
                "same_count": item.same_count,
                "different_count": item.different_count,
                "insufficient_count": item.insufficient_count,
                "weakest_observation_pair": (
                    list(item.weakest_observation_pair)
                    if item.weakest_observation_pair
                    else None
                ),
                "weakest_score": item.weakest_score,
                "eligible": item.eligible,
                "blockers": list(item.blockers),
                "identity_warnings": list(item.identity_warnings),
                "reviewed_same_pairs": [list(pair) for pair in item.reviewed_same_pairs],
                "review_event_ids": list(item.review_event_ids),
            }
            for item in plan.pair_evidence
        ],
        "proposals": [
            {
                "profile_ids": list(item.profile_ids),
                "profile_pair_count": item.profile_pair_count,
                "comparison_count": item.comparison_count,
                "weakest_observation_pair": list(item.weakest_observation_pair),
                "weakest_score": item.weakest_score,
            }
            for item in plan.proposals
        ],
        "excluded_profiles": [
            {"profile_id": profile_id, "reason": reason}
            for profile_id, reason in plan.excluded_profiles
        ],
        "comparisons": [
            {"observation_ids": list(pair), **dict(result)}
            for pair, result in sorted(comparisons.items())
        ],
        "preparation_failures": [
            {"observation_id": observation_id, "reason": reason}
            for observation_id, reason in preparation_failures
        ],
        "registry_mutation_allowed": False,
        "human_cohort_approval_required": True,
        "review_suggestions": [dict(item) for item in review_suggestions],
        "saved_evidence_reuse": dict(saved_evidence_reuse or {}),
    }
    payload["result_sha256"] = _sha256(payload)
    return payload


def source_profile_review_suggestions(
    database: Database,
    plan: SourceProfileConsolidationPlan,
    *,
    comparisons: Mapping[tuple[int, int], Mapping[str, Any]],
    base_dir: Path,
    evaluation_root: Path,
    cache_dir: Path,
) -> list[dict[str, Any]]:
    """Nominate the exact abstaining windows, without widening merge authority."""
    candidates = {item.profile_id: item for item in plan.candidates}
    suggestions = []
    for evidence in plan.pair_evidence:
        left, right = (candidates[value] for value in evidence.profile_ids)
        resolved = set(evidence.reviewed_same_pairs)
        for a, b in itertools.product(left.exemplar_observation_ids, right.exemplar_observation_ids):
            pair = tuple(sorted((a, b)))
            result = comparisons.get(pair)
            if pair in resolved or (result is not None and result.get("outcome") != "insufficient_evidence"):
                continue
            observations = [database.get_speaker_observation(value) for value in pair]
            if any(item is None for item in observations):
                continue
            videos = [database.get_video_by_id(item.video_id) for item in observations]
            if any(item is None for item in videos):
                continue
            command = shlex.join([
                "pte", "identity", "review-speaker-pair",
                "--observation-fingerprint-a", observations[0].input_fingerprint,
                "--observation-fingerprint-b", observations[1].input_fingerprint,
                "--evaluation-root", str(evaluation_root.expanduser().resolve()),
                "--cache-dir", str(cache_dir.expanduser().resolve()),
                "--base-dir", str(base_dir.expanduser().resolve()),
                "--", videos[0].youtube_video_id, videos[1].youtube_video_id,
            ])
            suggestions.append({
                "profile_ids": list(evidence.profile_ids),
                "observation_ids": list(pair),
                "observation_fingerprints": [item.input_fingerprint for item in observations],
                "windows": [{"start_seconds": item.start_seconds, "end_seconds": item.end_seconds} for item in observations],
                "youtube_video_ids": [item.youtube_video_id for item in videos],
                "reason": result.get("reason", "insufficient_evidence") if result else "comparison_missing",
                "review_command": command,
                "prepare_command": command.replace("review-speaker-pair", "review-speaker-pair --prepare-only", 1),
            })
    return suggestions


def write_source_profile_consolidation_review_report(
    destination: Path, payload: Mapping[str, Any]
) -> Path:
    lines = ["# Source-profile consolidation review", "",
             "Shared source is retrieval context. Names warn; identity merges require human approval.", ""]
    if payload.get("saved_evidence_reuse"):
        lines.extend(["## Saved comparison reuse", "",
                      "```json", json.dumps(payload["saved_evidence_reuse"], indent=2), "```", ""])
    if payload["preparation_failures"]:
        lines.extend(["## Unavailable acoustic inputs", "",
                      "Profiles remain in the review. Missing comparisons stay unknown; these failures do not invalidate saved compatible evidence.", ""])
        for item in payload["preparation_failures"]:
            lines.append(f"- Observation {item['observation_id']}: {item['reason']}")
        lines.append("")
    for item in payload["pair_evidence"]:
        lines.extend([
            "## Profiles " + " / ".join(map(str, item["profile_ids"])), "",
            f"Same: {item['same_count']}; different: {item['different_count']}; unresolved: {item['insufficient_count']}.",
            "Identity warnings: " + (", ".join(item["identity_warnings"]) or "none") + ".",
            "Blockers: " + (", ".join(item["blockers"]) or "none") + ".", "",
        ])
    lines.extend(["## Exact ambiguous comparisons", "",
                  "Review each pinned window pair. A same-speaker judgment resolves that exact abstention on the next plan; it does not approve a whole cohort or bypass different-speaker constraints.", ""])
    for item in payload["review_suggestions"]:
        lines.extend([
            "### Observations " + " / ".join(map(str, item["observation_ids"])), "",
            "Profiles " + " / ".join(map(str, item["profile_ids"])) + "; reason: " + item["reason"], "",
            "```console", item["review_command"], "```", "",
        ])
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return destination


def write_source_profile_consolidation_artifact(
    destination: Path,
    payload: Mapping[str, Any],
) -> Path:
    path = destination.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(dict(payload), indent=2, sort_keys=True) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") != encoded:
        raise ValueError(f"source-profile consolidation artifact collision: {path}")
    path.write_text(encoded, encoding="utf-8")
    return path


def write_source_profile_consolidation_packet(
    database: Database,
    proposal: SourceProfileConsolidationProposal,
    destination: Path,
) -> Path:
    cards: list[str] = []
    for label, observation_id in zip(("A", "B"), proposal.weakest_observation_pair, strict=True):
        observation = database.get_speaker_observation(observation_id)
        video = database.get_video_by_id(observation.video_id) if observation else None
        if observation is None or video is None:
            continue
        timestamp = max(0, int((observation.start_seconds + observation.end_seconds) / 2))
        joiner = "&" if "?" in video.url else "?"
        url = f"{video.url}{joiner}t={timestamp}s"
        cards.append(
            f"<section><h2>Weakest-edge recording {label}</h2>"
            f"<p>Observation {observation_id}; {html.escape(video.title)}</p>"
            f'<p><a target="_blank" rel="noopener" href="{html.escape(url, quote=True)}">'
            "Open identity timestamp</a></p></section>"
        )
    score = "unavailable" if proposal.weakest_score is None else f"{proposal.weakest_score:.4f}"
    profile_labels = html.escape(
        ", ".join(str(value) for value in proposal.profile_ids)
    )
    document = f"""<!doctype html><html><head><meta charset="utf-8">
<title>Source profile consolidation</title>
<style>
body{{font:16px system-ui;max-width:920px;margin:2rem auto;padding:0 1rem}}
section{{border:1px solid #bbb;padding:1rem;margin:1rem 0}}
code{{background:#eee;padding:.1rem .3rem}}
</style>
</head><body><h1>Source-profile consolidation review</h1>
<p>Proposed profiles: <code>{profile_labels}</code>.</p>
<p>{proposal.comparison_count} exemplar comparisons across
{proposal.profile_pair_count} profile pairs are supported by the pinned policy
or exact qualified human judgments. Shared source was used only to retrieve the cohort. The weakest score
is {score}.</p>
<p>Approve the entire cohort only if these weakest-edge recordings contain the
same principal speaker.</p>
{''.join(cards)}</body></html>"""
    path = destination.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(document, encoding="utf-8")
    return path


def _comparison_score(result: Mapping[str, Any]) -> float | None:
    metrics = result.get("metrics")
    cross = metrics.get("cross", {}) if isinstance(metrics, Mapping) else {}
    if isinstance(cross, Mapping):
        for key in ("p10", "median"):
            value = cross.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value)
    for container in (result, result.get("metrics")):
        if not isinstance(container, Mapping):
            continue
        for key in ("cross_p10", "minimum_cross_similarity", "cross_median"):
            value = container.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value)
    return None


def _sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
