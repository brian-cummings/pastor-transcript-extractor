from __future__ import annotations

from pathlib import Path
from typing import Callable

import typer

from pastor_transcript_extractor.commands.apps import identity_app
from pastor_transcript_extractor.workflows.identity.run import (
    IdentityWorkflowRequest,
)


IdentityWorkflowInvoker = Callable[[IdentityWorkflowRequest], object]
_identity_workflow_invoker: IdentityWorkflowInvoker | None = None


def configure_identity_workflow(invoker: IdentityWorkflowInvoker) -> None:
    """Bind the identity application workflow at composition time."""
    global _identity_workflow_invoker
    _identity_workflow_invoker = invoker


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
    )
    if _identity_workflow_invoker is None:
        raise RuntimeError("Identity workflow was not configured.")
    try:
        _identity_workflow_invoker(request)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
