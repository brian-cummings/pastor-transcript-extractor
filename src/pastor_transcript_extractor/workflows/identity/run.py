from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class IdentityWorkflowRequest:
    """Validated command input for one guarded identity workflow run."""

    youtube_video_id: str | None
    all_extractions: bool
    plan_only: bool
    skip_discovery: bool
    apply_automatic: bool
    apply_confirmations: bool
    apply_promotions: bool
    apply_machine_canary: bool
    machine_assignment_policy_path: Path | None
    review_prewarm_limit: int
    base_dir: Path | None
    jobs: int


@dataclass(frozen=True, slots=True)
class IdentityWorkflowPolicy:
    """Derived mutation gates after request-level safety validation."""

    apply_confirmations: bool
    apply_promotions: bool
    apply_machine_assignments: bool


def validate_identity_workflow_request(
    request: IdentityWorkflowRequest,
) -> IdentityWorkflowPolicy:
    """Validate cross-option invariants before opening storage or running stages."""
    if (request.youtube_video_id is None) == (not request.all_extractions):
        raise ValueError("Pass exactly one YouTube video ID or --all.")
    if request.plan_only and (
        request.apply_automatic
        or request.apply_confirmations
        or request.apply_promotions
        or request.apply_machine_canary
    ):
        raise ValueError(
            "--plan-only cannot be combined with registry mutation flags"
        )

    apply_confirmations = request.apply_automatic or request.apply_confirmations
    apply_promotions = request.apply_automatic or request.apply_promotions
    apply_machine_assignments = (
        request.apply_automatic or request.apply_machine_canary
    )
    if not request.all_extractions and apply_promotions:
        raise ValueError("automatic profile promotion requires --all")
    if not request.all_extractions and request.apply_machine_canary:
        raise ValueError("machine canary activation requires --all")
    if request.review_prewarm_limit < 0:
        raise ValueError("review prewarm limit cannot be negative")
    if request.jobs < 1:
        raise ValueError("identity jobs must be at least one")

    return IdentityWorkflowPolicy(
        apply_confirmations=apply_confirmations,
        apply_promotions=apply_promotions,
        apply_machine_assignments=apply_machine_assignments,
    )
