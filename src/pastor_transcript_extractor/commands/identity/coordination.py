from __future__ import annotations

from pathlib import Path
from typing import Callable

import typer
from rich.console import Console

from pastor_transcript_extractor.commands.apps import identity_app
from pastor_transcript_extractor.commands.identity.review import review_speaker_pair
from pastor_transcript_extractor.config import build_paths
from pastor_transcript_extractor.identity import (
    backfill_shadow_identity_assessments,
)
from pastor_transcript_extractor.identity_automation import (
    build_identity_association_work_plan,
    select_superseded_profile_member_review,
    write_identity_work_event,
)
from pastor_transcript_extractor.media_artifacts import (
    backfill_existing_media_artifacts,
)
from pastor_transcript_extractor.speaker_pair_eligibility import (
    assess_automatic_speaker_observation,
)
from pastor_transcript_extractor.storage import Database


DEFAULT_SPEAKER_MODEL_SHA256 = (
    "357a834f702b80161e5b981182c038e18553c1f2ca752ed6cec2052365d4129b"
)
console = Console()
_shadow_associator: Callable[..., object] | None = None


def configure_shadow_associator(associator: Callable[..., object]) -> None:
    """Bind shadow association after the large command is composed."""
    global _shadow_associator
    _shadow_associator = associator


def _print_identity_work_plan(plan, *, details: bool = False) -> None:
    console.print(
        "Identity association work: "
        + " ".join(f"{state}={count}" for state, count in plan.counts.items())
        + f" unique_videos={len(plan.items)} attempt_volume={plan.attempt_volume}."
    )
    blocker_counts: dict[tuple[str, str], int] = {}
    for item in plan.items:
        if item.state in {"associated", "dispatch_ready"}:
            continue
        key = (item.stage, item.reason_code)
        blocker_counts[key] = blocker_counts.get(key, 0) + 1
    if blocker_counts:
        console.print(
            "Durable blockers: "
            + ", ".join(
                f"{stage}:{reason}={count}"
                for (stage, reason), count in sorted(blocker_counts.items())
            )
        )
    if details:
        for item in plan.items:
            console.print(
                f"{item.youtube_video_id} state={item.state} "
                f"stage={item.stage} reason={item.reason_code} "
                f"next={item.next_operation}"
            )


@identity_app.command(
    "association-work-plan",
    help="Plan current accepted-sermon identity work without writing artifacts.",
)
def association_work_plan_command(
    details: bool = typer.Option(False, "--details"),
    association_root: Path = typer.Option(
        Path("evaluation/speaker-associations/shadow-runs")
    ),
    base_dir: Path | None = typer.Option(None),
) -> None:
    paths = build_paths(base_dir)
    if not paths.database.exists():
        raise typer.BadParameter(f"Application database does not exist: {paths.database}")
    plan = build_identity_association_work_plan(
        Database(paths.database, readonly=True), association_root
    )
    _print_identity_work_plan(plan, details=details)
    console.print("Dry run; durable identity state was not changed.")


@identity_app.command(
    "association-work-status",
    help="Summarize unique-video identity work and durable blocker reason codes.",
)
def association_work_status_command(
    details: bool = typer.Option(False, "--details"),
    association_root: Path = typer.Option(
        Path("evaluation/speaker-associations/shadow-runs")
    ),
    base_dir: Path | None = typer.Option(None),
) -> None:
    paths = build_paths(base_dir)
    if not paths.database.exists():
        raise typer.BadParameter(f"Application database does not exist: {paths.database}")
    _print_identity_work_plan(
        build_identity_association_work_plan(
            Database(paths.database, readonly=True), association_root
        ),
        details=details,
    )

@identity_app.command(
    "review-next-superseded-profile-member",
    help=(
        "Review one current replacement against a current profile exemplar "
        "to restore acoustic profile coverage."
    ),
)
def review_next_superseded_profile_member_command(
    reviewer: str | None = typer.Option(
        None, help="Stable human reviewer identifier."
    ),
    prepare_only: bool = typer.Option(False, "--prepare-only"),
    open_packet: bool = typer.Option(
        True, "--open-packet/--no-open-packet"
    ),
    evaluation_root: Path = typer.Option(
        Path("evaluation/speaker-pairs")
    ),
    cache_dir: Path = typer.Option(Path("evaluation/speaker-pairs/cache")),
    base_dir: Path | None = typer.Option(None),
) -> None:
    paths = build_paths(base_dir)
    if not paths.database.exists():
        raise typer.BadParameter(
            f"Application database does not exist: {paths.database}"
        )
    candidate = select_superseded_profile_member_review(
        Database(paths.database, readonly=True)
    )
    if candidate is None:
        console.print(
            "No safe one-review superseded-member candidate is available."
        )
        return
    console.print(
        "Selected current-exemplar restoration review: "
        f"profile={candidate.profile_id} "
        f"anchor={candidate.anchor_youtube_video_id} "
        f"replacement={candidate.replacement_youtube_video_id} "
        f"superseded_observation={candidate.superseded_observation_id}."
    )
    review_speaker_pair(
        video_a=candidate.anchor_youtube_video_id,
        video_b=candidate.replacement_youtube_video_id,
        reviewer=reviewer,
        evaluation_root=evaluation_root,
        cache_dir=cache_dir,
        open_packet=open_packet,
        prepare_only=prepare_only,
        base_dir=base_dir,
        selection_manifest_json=None,
        observation_fingerprint_a=None,
        observation_fingerprint_b=None,
    )


@identity_app.command(
    "dispatch-associations",
    help="Run a bounded, restart-safe batch of current unattempted associations.",
)
def dispatch_associations_command(
    limit: int = typer.Option(25, "--limit", min=1),
    dry_run: bool = typer.Option(False, "--dry-run"),
    jobs: int = typer.Option(2, "--jobs", min=1),
    retry_failed_only: bool = typer.Option(
        False,
        "--retry-failed-only",
        help=(
            "Retry persisted technical failures without retrying "
            "policy-terminal outcomes."
        ),
    ),
    association_root: Path = typer.Option(
        Path("evaluation/speaker-associations/shadow-runs")
    ),
    base_dir: Path | None = typer.Option(None),
) -> None:
    paths = build_paths(base_dir)
    plan = build_identity_association_work_plan(
        Database(paths.database, readonly=True), association_root
    )
    selected = plan.select(
        *("technical_failure",)
        if retry_failed_only
        else ("dispatch_ready", "technical_failure"),
        limit=limit,
    )
    console.print(
        f"Association dispatch selected={len(selected)} limit={limit} "
        f"mode={'dry-run' if dry_run else 'execute'}."
    )
    if dry_run or not selected:
        for item in selected:
            console.print(f"{item.youtube_video_id} {item.reason_code}")
        return
    # Limit by explicit deterministic video IDs. This gives observation-level
    # failure isolation and makes restart semantics independent of scan order.
    succeeded = failed = 0
    for item in selected:
        try:
            if _shadow_associator is None:
                raise RuntimeError("Shadow association command was not configured.")
            _shadow_associator(
                youtube_video_id=item.youtube_video_id,
                all_eligible=False,
                unattempted_only=False,
                neighborhood_profile_id=[],
                include_profiled=False,
                limit=None,
                plan_only=False,
                minimum_profile_members=3,
                maximum_exemplars=3,
                minimum_same_exemplars=2,
                maximum_global_profiles=1,
                jobs=jobs,
                model_path=Path(
                    "evaluation/speaker-pairs/models/"
                    "3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx"
                ),
                model_sha256=DEFAULT_SPEAKER_MODEL_SHA256,
                policy_path=Path(
                    "evaluation/speaker-pairs/policies/"
                    "campplus-development-candidate-v1.json"
                ),
                evaluation_root=Path("evaluation/speaker-pairs"),
                cache_dir=Path("evaluation/speaker-pairs/cache"),
                output_root=association_root,
                base_dir=base_dir,
            )
            succeeded += 1
        except Exception as error:
            failed += 1
            write_identity_work_event(
                association_root,
                item,
                operation="association_dispatch",
                outcome="technical_failure",
                detail=f"{type(error).__name__}: {error}",
            )
            console.print(
                f"Association failed in isolation: {item.youtube_video_id} "
                f"{type(error).__name__}: {error}"
            )
    console.print(
        f"Association dispatch complete: selected={len(selected)} "
        f"succeeded={succeeded} failed={failed}."
    )


@identity_app.command(
    "repair-association-prerequisites",
    help="Repair current technical prerequisites from existing local artifacts only.",
)
def repair_association_prerequisites_command(
    limit: int = typer.Option(25, "--limit", min=1),
    dry_run: bool = typer.Option(False, "--dry-run"),
    association_root: Path = typer.Option(
        Path("evaluation/speaker-associations/shadow-runs")
    ),
    base_dir: Path | None = typer.Option(None),
) -> None:
    paths = build_paths(base_dir, remember=not dry_run)
    readonly = Database(paths.database, readonly=True)
    plan = build_identity_association_work_plan(readonly, association_root)
    selected = plan.select("prerequisite_blocked", limit=limit)
    console.print(
        f"Prerequisite repair selected={len(selected)} limit={limit} "
        f"mode={'dry-run' if dry_run else 'execute'}."
    )
    if dry_run:
        for item in selected:
            console.print(
                f"{item.youtube_video_id} reason={item.reason_code} "
                f"operation={item.next_operation}"
            )
        return
    database = Database(paths.database)
    repaired = still_blocked = failed = 0
    for item in selected:
        outcome = "still_blocked"
        detail = "prerequisite unchanged"
        try:
            if item.next_operation == "backfill_existing_normalized_media":
                result = backfill_existing_media_artifacts(
                    database, paths, video_id=item.video_id
                )
                detail = (
                    f"registered={result.artifacts_registered}; "
                    f"attempts={result.attempts_registered}"
                )
            elif item.next_operation == "rebuild_observation_from_current_extraction":
                result = backfill_shadow_identity_assessments(
                    database, paths, video_id=item.video_id
                )
                detail = (
                    f"created={result.created}; reused={result.reused}; "
                    f"skipped={result.skipped}; failed={result.failed}"
                )
            eligibility = assess_automatic_speaker_observation(
                database, item.video_id, verify_media=False
            )
            if eligibility.eligible:
                outcome = "repaired_and_requeued"
                repaired += 1
            else:
                detail += f"; current_reason={eligibility.reason_code}"
                still_blocked += 1
        except (OSError, RuntimeError, ValueError) as error:
            outcome = "technical_failure"
            detail = f"{type(error).__name__}: {error}"
            failed += 1
        write_identity_work_event(
            association_root,
            item,
            operation=item.next_operation,
            outcome=outcome,
            detail=detail,
        )
    console.print(
        f"Prerequisite repair complete: repaired_and_requeued={repaired} "
        f"still_blocked={still_blocked} failed={failed}."
    )
