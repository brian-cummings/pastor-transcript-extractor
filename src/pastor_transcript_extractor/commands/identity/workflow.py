from __future__ import annotations

from pathlib import Path
from typing import Callable

import typer
from rich.console import Console

from pastor_transcript_extractor import config, identity as identity_domain
from pastor_transcript_extractor.commands.apps import identity_app
from pastor_transcript_extractor.commands.common import get_database
from pastor_transcript_extractor.workflows.identity.run import (
    IdentityWorkflowRequest,
)


IdentityWorkflowInvoker = Callable[[IdentityWorkflowRequest], object]
_identity_workflow_invoker: IdentityWorkflowInvoker | None = None
console = Console()


def configure_identity_workflow(invoker: IdentityWorkflowInvoker) -> None:
    """Bind the identity application workflow at composition time."""
    global _identity_workflow_invoker
    _identity_workflow_invoker = invoker


@identity_app.command(
    "backfill",
    help=(
        "Create missing shadow identity and neutral speaker artifacts without "
        "reclassification."
    ),
)
def identity_backfill(
    video_id: int | None = typer.Option(
        None,
        "--video-id",
        help="Only backfill one database video id.",
    ),
    base_dir: Path | None = typer.Option(
        None,
        help="Override app data directory.",
    ),
) -> None:
    database = get_database(base_dir)
    paths = config.build_paths(base_dir, remember=True)
    result = identity_domain.backfill_shadow_identity_assessments(
        database,
        paths,
        video_id=video_id,
    )
    console.print(
        "Identity shadow backfill: "
        f"created {result.created}, reused {result.reused}, "
        f"skipped {result.skipped}, failed {result.failed}."
    )


@identity_app.command(
    "run",
    help=(
        "Sync reviewed evidence, then run backfill, shadow association, "
        "discovery, final coordination, and eligible normalized archival."
    ),
)
def identity_run_command(
    youtube_video_id: str | None = typer.Argument(
        None,
        help="One YouTube video ID; omit when using --all.",
    ),
    all_extractions: bool = typer.Option(
        False,
        "--all",
        help="Run across all current extractions and include corpus discovery.",
    ),
    plan_only: bool = typer.Option(
        False,
        "--plan-only",
        help="Show all stages without acoustic execution or registry mutation.",
    ),
    skip_discovery: bool = typer.Option(
        False,
        "--skip-discovery",
        help="Skip corpus profile discovery during an --all run.",
    ),
    apply_automatic: bool = typer.Option(
        False,
        "--apply-automatic",
        help=(
            "Apply validated confirmations, promotions, and policy-gated "
            "human-on-loop provisional assignments. Requires --all."
        ),
    ),
    apply_confirmations: bool = typer.Option(
        False,
        "--apply-confirmations",
        help="Apply validated independent provisional-profile confirmations.",
    ),
    apply_promotions: bool = typer.Option(
        False,
        "--apply-promotions",
        help="Promote verified discovery components into provisional profiles.",
    ),
    evaluate_profile_promotions: bool = typer.Option(
        True,
        "--evaluate-profile-promotions/--no-evaluate-profile-promotions",
        help=(
            "Evaluate bounded discovery groupings with Jev and include current "
            "cached positive-utility judgments in the promotion plan."
        ),
    ),
    promotion_model: str = typer.Option(
        "jev-1.13.0",
        "--promotion-model",
        help="Pinned TypeSafe/Jev model for profile-promotion judgments.",
    ),
    promotion_judgment_root: Path | None = typer.Option(
        None,
        "--promotion-judgment-root",
        help="Content-addressed Jev promotion-judgment cache root.",
    ),
    promotion_successful_profile_value: float = typer.Option(
        1.0,
        min=0.0,
        help="Utility of a correct reversible provisional profile.",
    ),
    promotion_contaminated_profile_cost: float = typer.Option(
        3.0,
        min=0.0,
        help="Utility cost of a contaminated provisional profile.",
    ),
    apply_machine_canary: bool = typer.Option(
        False,
        "--apply-machine-canary",
        help=(
            "Activate only eligible reversible machine assignments without "
            "also applying profile confirmations or promotions. Requires --all."
        ),
    ),
    machine_assignment_policy: Path | None = typer.Option(
        None,
        "--machine-assignment-policy",
        help=(
            "Use a versioned machine-assignment policy artifact. The default "
            "checked-in policy is shadow-only."
        ),
    ),
    review_prewarm_limit: int = typer.Option(
        24,
        "--review-prewarm-limit",
        min=0,
        help=(
            "Precompute exact clips for this many current actionable review "
            "observations during an --all run; use 0 to disable."
        ),
    ),
    jobs: int = typer.Option(
        2,
        "--jobs",
        min=1,
        help=(
            "Concurrent acoustic comparison jobs; registry mutations and "
            "artifact aggregation remain serialized."
        ),
    ),
    base_dir: Path | None = typer.Option(
        None,
        help="Override app data directory.",
    ),
) -> None:
    from pastor_transcript_extractor.config import build_paths

    paths = build_paths(base_dir)
    resolved_promotion_judgment_root = promotion_judgment_root or (
        paths.evaluation / "speaker-profile-discovery" / "promotion-judgments"
    )
    request = IdentityWorkflowRequest(
        youtube_video_id=youtube_video_id,
        all_extractions=all_extractions,
        plan_only=plan_only,
        skip_discovery=skip_discovery,
        apply_automatic=apply_automatic,
        apply_confirmations=apply_confirmations,
        apply_promotions=apply_promotions,
        apply_machine_canary=apply_machine_canary,
        machine_assignment_policy_path=machine_assignment_policy,
        review_prewarm_limit=review_prewarm_limit,
        base_dir=base_dir,
        jobs=jobs,
        evaluate_profile_promotions=evaluate_profile_promotions,
        promotion_model=promotion_model,
        promotion_judgment_root=resolved_promotion_judgment_root,
        promotion_successful_profile_value=promotion_successful_profile_value,
        promotion_contaminated_profile_cost=promotion_contaminated_profile_cost,
    )
    if _identity_workflow_invoker is None:
        raise RuntimeError("Identity workflow was not configured.")
    try:
        _identity_workflow_invoker(request)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
