from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Sequence

from pastor_transcript_extractor.reviewed_speaker_evidence import (
    ReviewedEvidenceSyncResult,
    ReviewedSpeakerEvidence,
    sync_reviewed_speaker_evidence,
)
from pastor_transcript_extractor.speaker_profile_promotion import (
    CandidateConfirmationPlan,
    DiscoveryPromotionPlan,
    PromotionCandidate,
    apply_candidate_confirmations,
    apply_discovery_promotions,
    plan_candidate_confirmations,
    plan_discovery_promotions,
)
from pastor_transcript_extractor.speaker_profile_status import (
    build_profile_pipeline_status,
)
from pastor_transcript_extractor.storage import Database


@dataclass(frozen=True, slots=True)
class AutomaticProfileActionPlan:
    pending_qualification_count: int
    pending_same_component_count: int
    pending_difference_count: int
    confirmation_plan: CandidateConfirmationPlan
    promotion_plan: DiscoveryPromotionPlan | None

    @property
    def pending_sync_count(self) -> int:
        return (
            self.pending_qualification_count
            + self.pending_same_component_count
            + self.pending_difference_count
        )


@dataclass(frozen=True, slots=True)
class AutomaticProfileActionResult:
    sync_result: ReviewedEvidenceSyncResult
    confirmation_event_ids: tuple[int, ...]
    promoted_profile_ids: tuple[int, ...]


def plan_profile_automatic_actions(
    database: Database,
    evidence: ReviewedSpeakerEvidence,
    *,
    association_report_paths: Sequence[Path],
    discovery_report_path: Path | None,
) -> AutomaticProfileActionPlan:
    status = build_profile_pipeline_status(database, evidence)
    confirmation_plan = plan_candidate_confirmations(
        database,
        association_report_paths,
    )
    promotion_plan = (
        _plan_pending_discovery_promotions(database, discovery_report_path)
        if discovery_report_path is not None
        else None
    )
    return AutomaticProfileActionPlan(
        pending_qualification_count=status.pending_qualification_count,
        pending_same_component_count=status.pending_same_component_count,
        pending_difference_count=status.pending_difference_count,
        confirmation_plan=confirmation_plan,
        promotion_plan=promotion_plan,
    )


def apply_profile_automatic_actions(
    database: Database,
    evidence: ReviewedSpeakerEvidence,
    *,
    association_report_paths: Sequence[Path],
    discovery_report_path: Path | None,
) -> AutomaticProfileActionResult:
    sync_result = sync_reviewed_speaker_evidence(database, evidence)

    # Replan after every preceding registry mutation so stale artifacts fail
    # closed against current membership and constraints.
    confirmation_plan = plan_candidate_confirmations(
        database,
        association_report_paths,
    )
    confirmation_event_ids = apply_candidate_confirmations(
        database,
        confirmation_plan,
    )
    promotion_plan = (
        _plan_pending_discovery_promotions(database, discovery_report_path)
        if discovery_report_path is not None
        else None
    )
    promoted_profile_ids = (
        apply_discovery_promotions(database, promotion_plan)
        if promotion_plan is not None
        else ()
    )
    return AutomaticProfileActionResult(
        sync_result=sync_result,
        confirmation_event_ids=confirmation_event_ids,
        promoted_profile_ids=promoted_profile_ids,
    )


def _plan_pending_discovery_promotions(
    database: Database,
    discovery_report_path: Path,
) -> DiscoveryPromotionPlan:
    plan = plan_discovery_promotions(database, discovery_report_path)
    pending_candidates = tuple(
        candidate
        for candidate in plan.candidates
        if not _promotion_is_complete(database, candidate)
    )
    return replace(plan, candidates=pending_candidates)


def _promotion_is_complete(
    database: Database,
    candidate: PromotionCandidate,
) -> bool:
    profile_id = candidate.existing_profile_id
    if (
        not isinstance(profile_id, int)
        or database.get_speaker_profile_discovery_promotion(profile_id) is None
    ):
        return False
    canonical_id = database.resolve_speaker_profile_id(profile_id)
    return all(
        canonical_id
        in {
            database.resolve_speaker_profile_id(member_profile_id)
            for member_profile_id in database.list_effective_profile_ids_for_observation(
                observation_id
            )
        }
        for observation_id in candidate.observation_ids
    )
