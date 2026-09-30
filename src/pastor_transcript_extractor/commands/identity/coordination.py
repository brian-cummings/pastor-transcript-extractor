from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import typer
from rich.console import Console

from pastor_transcript_extractor.commands.apps import identity_app
from pastor_transcript_extractor.commands.identity.review import review_speaker_pair
from pastor_transcript_extractor.config import build_paths, evaluation_root_for
from pastor_transcript_extractor.identity_coordination import (
    build_identity_coordination_report,
    load_discovery_observation_states,
    write_identity_coordination_report,
)
from pastor_transcript_extractor.identity import (
    backfill_shadow_identity_assessments,
)
from pastor_transcript_extractor.identity_automation import (
    build_identity_association_work_plan,
    select_superseded_profile_member_review,
    write_identity_work_event,
)
from pastor_transcript_extractor.media_artifacts import (
    MediaVerificationCache,
    backfill_existing_media_artifacts,
)
from pastor_transcript_extractor.speaker_association_audit import (
    audit_speaker_association_coverage,
)
from pastor_transcript_extractor.speaker_pair_eligibility import (
    assess_automatic_speaker_observation,
)
from pastor_transcript_extractor.speaker_profile_promotion import (
    plan_candidate_confirmations,
    plan_discovery_promotions,
)
from pastor_transcript_extractor.speaker_shadow_association import (
    load_shadow_policy,
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
    association_root: Path | None = typer.Option(None),
    base_dir: Path | None = typer.Option(None),
) -> None:
    paths = build_paths(base_dir)
    runtime_root = evaluation_root_for(paths, base_dir)
    association_root = association_root or runtime_root / "speaker-associations/shadow-runs"
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
    association_root: Path | None = typer.Option(None),
    base_dir: Path | None = typer.Option(None),
) -> None:
    paths = build_paths(base_dir)
    association_root = association_root or evaluation_root_for(paths, base_dir) / "speaker-associations/shadow-runs"
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
    cache_dir: Path | None = typer.Option(None),
    base_dir: Path | None = typer.Option(None),
) -> None:
    paths = build_paths(base_dir)
    cache_dir = cache_dir or evaluation_root_for(paths, base_dir) / "speaker-pairs/cache"
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
    association_root: Path | None = typer.Option(None),
    base_dir: Path | None = typer.Option(None),
) -> None:
    paths = build_paths(base_dir)
    association_root = association_root or evaluation_root_for(paths, base_dir) / "speaker-associations/shadow-runs"
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
                model_path=(
                    evaluation_root_for(paths, base_dir)
                    / "speaker-pairs/models/3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx"
                ),
                model_sha256=DEFAULT_SPEAKER_MODEL_SHA256,
                policy_path=Path(
                    "evaluation/speaker-pairs/policies/"
                    "campplus-development-candidate-v1.json"
                ),
                evaluation_root=Path("evaluation/speaker-pairs"),
                cache_dir=evaluation_root_for(paths, base_dir) / "speaker-pairs/cache",
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
    association_root: Path | None = typer.Option(None),
    base_dir: Path | None = typer.Option(None),
) -> None:
    paths = build_paths(base_dir, remember=not dry_run)
    association_root = association_root or evaluation_root_for(paths, base_dir) / "speaker-associations/shadow-runs"
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


@identity_app.command(
    "coordinate",
    help="Plan or execute the non-mutating identity workflow for current extractions.",
)
def coordinate_identity_command(
    youtube_video_id: str | None = typer.Option(
        None,
        "--youtube-video-id",
        help="Coordinate one newly extracted YouTube video.",
    ),
    all_extractions: bool = typer.Option(
        False,
        "--all",
        help="Build a read-only coordination report for all latest extractions.",
    ),
    execute_shadow: bool = typer.Option(
        False,
        "--execute-shadow",
        help=(
            "Run missing shadow association for the requested video; never "
            "apply registry mutations."
        ),
    ),
    discovery_report: Path | None = typer.Option(
        None,
        "--discovery-report",
        exists=True,
        dir_okay=False,
        readable=True,
        help="Optional discovery artifact to include in promotion planning.",
    ),
    discovery_root: Path | None = typer.Option(
        None,
        help="Discovery artifacts used to avoid redundant batch work.",
    ),
    model_path: Path | None = typer.Option(
        None,
        help="Local ONNX speaker-embedding model.",
    ),
    model_sha256: str = typer.Option(
        DEFAULT_SPEAKER_MODEL_SHA256,
        help="Required checksum for the local model.",
    ),
    policy_path: Path = typer.Option(
        Path(
            "evaluation/speaker-pairs/policies/"
            "campplus-development-candidate-v1.json"
        ),
        help="Pinned shadow decision policy.",
    ),
    evaluation_root: Path = typer.Option(
        Path("evaluation/speaker-pairs"),
        help="Speaker-pair review and fixture root.",
    ),
    cache_dir: Path | None = typer.Option(
        None,
        help="Ignored acoustic and media-verification cache.",
    ),
    association_root: Path | None = typer.Option(
        None,
        help="Versioned shadow-association artifact root.",
    ),
    output_root: Path | None = typer.Option(
        None,
        help="Coordination report directory; defaults under application logs.",
    ),
    base_dir: Path | None = typer.Option(
        None,
        help="Override app data directory.",
    ),
) -> None:
    if (youtube_video_id is None) == (not all_extractions):
        raise typer.BadParameter(
            "Pass exactly one of --youtube-video-id or --all."
        )
    if execute_shadow and youtube_video_id is None:
        raise typer.BadParameter(
            "--execute-shadow currently requires --youtube-video-id; "
            "corpus discovery remains a separately scheduled batch."
        )
    paths = build_paths(base_dir)
    discovery_root = discovery_root or evaluation_root_for(paths, base_dir) / "speaker-profile-discovery/shadow-runs"
    model_path = model_path or (
        evaluation_root_for(paths, base_dir)
        / "speaker-pairs/models/3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx"
    )
    cache_dir = cache_dir or evaluation_root_for(paths, base_dir) / "speaker-pairs/cache"
    association_root = association_root or evaluation_root_for(paths, base_dir) / "speaker-associations/shadow-runs"
    if not paths.database.exists():
        raise typer.BadParameter(
            f"Application database does not exist: {paths.database}"
        )
    coordination_root = (
        output_root.expanduser().resolve()
        if output_root is not None
        else paths.logs / "identity-coordination"
    )
    audit_root = paths.logs / "association-audits"
    verification_cache = MediaVerificationCache(
        cache_dir.expanduser().resolve() / "media-verification"
    )
    try:
        policy_spec = load_shadow_policy(policy_path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise typer.BadParameter(str(error)) from error

    def audit() -> object:
        return audit_speaker_association_coverage(
            Database(paths.database, readonly=True),
            association_root=association_root,
            output_root=audit_root,
            verification_cache=verification_cache,
            required_policy_sha256=policy_spec.artifact_sha256,
        )

    effective_discovery_report = (
        discovery_report.expanduser().resolve()
        if discovery_report is not None
        else None
    )
    if effective_discovery_report is None:
        discovery_reports = list(
            discovery_root.expanduser().resolve().glob("*/*.json")
        )
        if discovery_reports:
            effective_discovery_report = max(
                discovery_reports,
                key=lambda path: (path.stat().st_mtime_ns, str(path)),
            )
    try:
        discovery_states = (
            load_discovery_observation_states(effective_discovery_report)
            if effective_discovery_report is not None
            else {}
        )
        audit_result = audit()
        preliminary = build_identity_coordination_report(
            audit_result.payload,
            youtube_video_id=youtube_video_id,
            discovery_observation_states=discovery_states,
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise typer.BadParameter(str(error)) from error

    executed_association = False
    association_execution_error: str | None = None
    if execute_shadow:
        case = preliminary["cases"][0]
        if case["next_action"] == "run_shadow_association":
            try:
                if _shadow_associator is None:
                    raise RuntimeError(
                        "Shadow association command was not configured."
                    )
                _shadow_associator(
                    youtube_video_id=youtube_video_id,
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
                    jobs=2,
                    model_path=model_path,
                    model_sha256=model_sha256,
                    policy_path=policy_path,
                    evaluation_root=evaluation_root,
                    cache_dir=cache_dir,
                    output_root=association_root,
                    base_dir=base_dir,
                )
                executed_association = True
                audit_result = audit()
            except (OSError, RuntimeError, ValueError, typer.BadParameter) as error:
                association_execution_error = str(error)
                console.print(
                    "Shadow association could not execute: "
                    f"{association_execution_error}"
                )
        else:
            console.print(
                "Shadow association not run: current next action is "
                f"{case['next_action']}."
            )

    association_paths = sorted(
        association_root.expanduser().resolve().glob("*/*.json")
    )
    confirmation_plan = plan_candidate_confirmations(
        Database(paths.database, readonly=True),
        association_paths,
    )
    promotion_summary = None
    if discovery_report is not None:
        try:
            promotion_plan = plan_discovery_promotions(
                Database(paths.database, readonly=True),
                discovery_report,
            )
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise typer.BadParameter(str(error)) from error
        promotion_summary = {
            "discovery_report": str(
                discovery_report.expanduser().resolve()
            ),
            "eligible_components": len(promotion_plan.candidates),
            "skipped_components": len(promotion_plan.skipped),
            "apply_allowed_by_coordinator": False,
        }
    report = build_identity_coordination_report(
        audit_result.payload,
        youtube_video_id=youtube_video_id,
        confirmation_observation_ids=(
            candidate.observation_id
            for candidate in confirmation_plan.candidates
        ),
        discovery_observation_states=discovery_states,
        promotion_summary=promotion_summary,
        execution_summary={
            "association_requested": execute_shadow,
            "association_executed": executed_association,
            "association_error": association_execution_error,
            "registry_mutations": 0,
        },
    )
    destination = write_identity_coordination_report(
        coordination_root,
        report,
    )
    counts = report["counts"]
    console.print(
        "Identity coordination: "
        f"extractions={counts['extractions']} "
        f"terminal={counts['terminal']} "
        f"waiting={counts['waiting_for_evidence']} "
        f"action_required={counts['action_required']} "
        f"association_executed={executed_association}"
    )
    console.print(
        "Workflow states: "
        + ", ".join(
            f"{state}={count}"
            for state, count in report["workflow_state_counts"].items()
        )
    )
    console.print(
        "Next actions: "
        + ", ".join(
            f"{action}={count}"
            for action, count in report["next_action_counts"].items()
        )
    )
    console.print(f"Wrote identity coordination report to {destination}")
    if effective_discovery_report is not None:
        console.print(
            "Discovery coverage source: "
            f"{effective_discovery_report}"
        )
    console.print(
        "Coordinator policy: shadow-only; registry mutations=0. "
        "Discovery remains a separately scheduled corpus batch."
    )
