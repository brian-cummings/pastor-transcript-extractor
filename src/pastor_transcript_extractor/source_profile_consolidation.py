from __future__ import annotations

from dataclasses import dataclass
import hashlib
import html
import itertools
import json
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


SOURCE_PROFILE_CONSOLIDATION_VERSION = "source_profile_consolidation_v1"


@dataclass(frozen=True, slots=True)
class SourceProfileCandidate:
    profile_id: int
    member_observation_ids: tuple[int, ...]
    exemplar_observation_ids: tuple[int, ...]
    recording_count: int
    normalized_names: tuple[str, ...]


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
    anonymous_profile_ids: frozenset[int]


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
        for item in assess_profile_association_readiness(database, evidence)
    }
    linked_profile_ids = {
        database.resolve_speaker_profile_id(profile_id)
        for pastor in database.list_pastors()
        if (profile_id := database.get_pastor_speaker_profile_id(pastor.id))
        is not None
    }
    anonymous_profile_ids = frozenset(
        profile_id
        for profile_id in readiness_by_id
        if profile_id not in linked_profile_ids
        and not database.list_effective_name_claim_ids_for_profile(profile_id)
    )
    return _SourceProfileCandidateContext(
        videos_by_id=videos_by_id,
        observations_by_id=observations_by_id,
        readiness_by_id=readiness_by_id,
        anonymous_profile_ids=anonymous_profile_ids,
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
        if profile_id not in context.anonymous_profile_ids:
            continue
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
) -> SourceProfileConsolidationPlan:
    """Build non-overlapping complete-link profile cohorts.

    A profile edge is admitted only when every supplied cross-profile exemplar
    comparison says ``same_speaker``. A cohort is admitted only when every
    profile pair in it has such an edge. Missing and ambiguous results therefore
    fail closed.
    """
    if minimum_same_comparisons < 2:
        raise ValueError("at least two same-speaker comparisons are required")
    different_pairs = {
        tuple(sorted(pair))
        for pair in database.list_effective_observation_difference_pairs()
    }
    pair_evidence: list[SourceProfilePairEvidence] = []
    eligible_profile_pairs: set[tuple[int, int]] = set()
    pair_by_profiles: dict[tuple[int, int], SourceProfilePairEvidence] = {}
    ordered_candidates = sorted(candidates, key=lambda item: item.profile_id)
    for left, right in itertools.combinations(ordered_candidates, 2):
        blockers: list[str] = []
        names = set(left.normalized_names) | set(right.normalized_names)
        if len(names) > 1:
            blockers.append("conflicting_explicit_attribution")
        cross_pairs = [
            tuple(sorted((left_id, right_id)))
            for left_id in left.exemplar_observation_ids
            for right_id in right.exemplar_observation_ids
        ]
        if any(pair in different_pairs for pair in cross_pairs):
            blockers.append("reviewed_different_speaker_constraint")
        results = [comparisons.get(pair) for pair in cross_pairs]
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
) -> int | None:
    return merge_reviewed_source_profile_cohort(
        database,
        source_id=plan.source_id,
        profile_ids=set(proposal.profile_ids),
        reviewer=reviewer,
        evidence_sha256=artifact_sha256,
        conflicts=conflicts,
    )


def source_profile_consolidation_payload(
    plan: SourceProfileConsolidationPlan,
    *,
    comparisons: Mapping[tuple[int, int], Mapping[str, Any]],
    model_fingerprint: str,
    policy_fingerprint: str,
    preparation_failures: Sequence[tuple[int, str]] = (),
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
    }
    payload["result_sha256"] = _sha256(payload)
    return payload


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
<p>{proposal.comparison_count} independent exemplar comparisons across
{proposal.profile_pair_count} profile pairs all passed the pinned same-speaker
policy. Shared source was used only to retrieve the cohort. The weakest score
is {score}.</p>
<p>Approve the entire cohort only if these weakest-edge recordings contain the
same principal speaker.</p>
{''.join(cards)}</body></html>"""
    path = destination.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(document, encoding="utf-8")
    return path


def _comparison_score(result: Mapping[str, Any]) -> float | None:
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
