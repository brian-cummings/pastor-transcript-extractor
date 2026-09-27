from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console

from pastor_transcript_extractor.commands.apps import identity_app
from pastor_transcript_extractor.commands.identity.common import (
    held_out_speaker_fixture_fingerprints,
)
from pastor_transcript_extractor.config import build_paths
from pastor_transcript_extractor.media_artifacts import MediaVerificationCache
from pastor_transcript_extractor.reviewed_speaker_evidence import (
    load_reviewed_speaker_evidence,
)
from pastor_transcript_extractor.speaker_machine_assignment import (
    active_machine_assignment_evidence,
    apply_machine_assignment_plan,
    load_machine_assignment_policy,
    machine_assignment_status,
    plan_machine_assignments,
    reconcile_machine_assignments,
    rollback_machine_assignments,
)
from pastor_transcript_extractor.speaker_shadow_association import (
    assess_profile_association_readiness,
)
from pastor_transcript_extractor.identity_automation import latest_association_reports
from pastor_transcript_extractor.storage import Database


console = Console()


@identity_app.command(
    "reconcile-current-proposals",
    help="Reconcile stale assignment evidence and plan every current proposal.",
)
def reconcile_current_proposals_command(
    dry_run: bool = typer.Option(False, "--dry-run"),
    activate_canary: bool = typer.Option(False, "--activate-canary"),
    machine_assignment_policy: Path = typer.Option(
        Path(
            "evaluation/speaker-associations/policies/"
            "machine-assignment-human-on-loop-v1.json"
        )
    ),
    association_root: Path = typer.Option(
        Path("evaluation/speaker-associations/shadow-runs")
    ),
    base_dir: Path | None = typer.Option(None),
) -> None:
    paths = build_paths(base_dir)
    database = Database(paths.database, readonly=dry_run)
    reports = latest_association_reports(association_root)
    current_results: dict[int, str] = {}
    for report_path in reports:
        try:
            payload = json.loads(report_path.read_text(encoding="utf-8"))
            candidate = payload.get("candidate", {})
            observation_id = candidate.get("observation_id")
            result_sha256 = payload.get("result_sha256")
            if isinstance(observation_id, int) and isinstance(result_sha256, str):
                current_results[observation_id] = result_sha256
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
    verification_cache = MediaVerificationCache(
        Path("evaluation/speaker-pairs/cache/media-verification").resolve()
    )
    evidence = load_reviewed_speaker_evidence(
        Path("evaluation/speaker-pairs").resolve()
    )
    readiness = assess_profile_association_readiness(database, evidence)
    policy = load_machine_assignment_policy(machine_assignment_policy)
    plan = plan_machine_assignments(
        database,
        latest_association_reports(association_root, outcomes=("proposed_match",)),
        readiness=readiness,
        policy=policy,
        verification_cache=verification_cache,
        excluded_observation_fingerprints=held_out_speaker_fixture_fingerprints(
            Path("evaluation/speaker-pairs/fixtures").resolve()
        ),
    )
    stale_evidence_count = sum(
        current_results.get(int(row["observation_id"])) is not None
        and current_results[int(row["observation_id"])]
        != row["association_result_sha256"]
        for row in database.list_speaker_machine_evidence()
    )
    if dry_run:
        console.print(
            "Proposal reconciliation dry run: "
            f"current_results={len(current_results)} "
            f"stale_evidence={stale_evidence_count} "
            f"assignment_ready={len(plan.candidates)} "
            f"blocked_or_skipped={sum(plan.skipped_counts.values())}."
        )
        if plan.skipped_counts:
            console.print(
                "Planning outcomes: "
                + ", ".join(
                    f"{reason}={count}"
                    for reason, count in plan.skipped_counts.items()
                )
            )
        return
    reconciliation = reconcile_machine_assignments(
        database,
        verification_cache=verification_cache,
        current_association_result_sha256_by_observation=current_results,
    )
    # Re-plan after stale active evidence has been revoked so its replacement
    # proposal can be admitted in this same reconciliation run.
    plan = plan_machine_assignments(
        database,
        latest_association_reports(
            association_root, outcomes=("proposed_match",)
        ),
        readiness=readiness,
        policy=policy,
        verification_cache=verification_cache,
        excluded_observation_fingerprints=(
            held_out_speaker_fixture_fingerprints(
                Path("evaluation/speaker-pairs/fixtures").resolve()
            )
        ),
    )
    applied = apply_machine_assignment_plan(
        database, plan, activate_canary=activate_canary
    )
    console.print(
        "Proposal reconciliation complete: "
        f"stale_or_reviewed_revoked={reconciliation.revoked} "
        f"confirmed={reconciliation.confirmed} "
        f"current_candidates={len(plan.candidates)} "
        f"evidence_recorded={applied.evidence_recorded} "
        f"evidence_reused={applied.evidence_reused} "
        f"activated={applied.assignments_activated} "
        f"activation_blocked={applied.activation_blocked}."
    )


@identity_app.command(
    "machine-assignment-status",
    help="Report reversible machine evidence and provisional assignment state.",
)
def machine_assignment_status_command(
    details: bool = typer.Option(
        False,
        "--details",
        help="List the current sermon-level associations and evidence paths.",
    ),
    profile_id: int | None = typer.Option(
        None,
        "--profile-id",
        help="Only show current associations for this canonical profile.",
    ),
    state: str | None = typer.Option(
        None,
        "--state",
        help=(
            "Only show active, awaiting_activation, blocked_policy, "
            "confirmed, or revoked associations."
        ),
    ),
    base_dir: Path | None = typer.Option(
        None,
        help="Override app data directory.",
    ),
) -> None:
    valid_states = {
        "active",
        "awaiting_activation",
        "blocked_policy",
        "confirmed",
        "revoked",
    }
    if state is not None and state not in valid_states:
        raise typer.BadParameter(
            "--state must be one of: " + ", ".join(sorted(valid_states))
        )
    paths = build_paths(base_dir)
    if not paths.database.exists():
        raise typer.BadParameter(
            f"Application database does not exist: {paths.database}"
        )
    database = Database(paths.database, readonly=True)
    status = machine_assignment_status(database)
    counts = status["counts"]
    console.print(
        "Machine assignments: "
        f"evidence={status['evidence_count']} "
        f"events={status['event_count']} "
        f"evidence_only={counts['evidence_only']} "
        f"active={counts['active']} "
        f"confirmed={counts['confirmed']} "
        f"revoked={counts['revoked']} "
        f"tripped_policies="
        f"{len(status['tripped_policy_fingerprints'])}."
    )
    console.print(
        "Machine assignments remain separate from reviewed profile membership."
    )
    current_counts = status["current_counts"]
    console.print(
        "Current sermon associations: "
        f"active={current_counts['active']} "
        f"awaiting_activation={current_counts['awaiting_activation']} "
        f"blocked_policy={current_counts['blocked_policy']} "
        f"confirmed={current_counts['confirmed']} "
        f"revoked={current_counts['revoked']}."
    )
    for policy_fingerprint, policy_counts in status["policies"].items():
        health = status["policy_health"].get(
            policy_fingerprint,
            {
                "reviewed_confirmed": 0,
                "reviewed_contradicted": 0,
                "pending_review": 0,
                "other_revoked": 0,
            },
        )
        console.print(
            f"  policy={policy_fingerprint} "
            f"evidence_only={policy_counts['evidence_only']} "
            f"active={policy_counts['active']} "
            f"confirmed={policy_counts['confirmed']} "
            f"revoked={policy_counts['revoked']} "
            f"current_reviewed_confirmed="
            f"{health['reviewed_confirmed']} "
            f"current_reviewed_contradicted="
            f"{health['reviewed_contradicted']} "
            f"current_pending_review={health['pending_review']}"
        )
    for trip in status["policy_trips"]:
        trigger = trip["youtube_video_id"] or (
            f"observation:{trip['observation_id']}"
        )
        console.print(
            "  circuit-breaker "
            f"policy={trip['policy_fingerprint']} trigger={trigger} "
            f"reason={trip['reason']} at={trip['created_at']}"
        )

    assignments = [
        assignment
        for assignment in status["assignments"]
        if (profile_id is None or assignment["profile_id"] == profile_id)
        and (state is None or assignment["state"] == state)
    ]
    if details or profile_id is not None or state is not None:
        labels: dict[int, str] = {}
        for profile in database.list_speaker_profiles():
            try:
                canonical_id = database.resolve_speaker_profile_id(profile.id)
            except ValueError:
                canonical_id = profile.id
            if profile.display_label:
                labels.setdefault(canonical_id, profile.display_label)
        console.print(
            f"[bold]Current sermon-level associations ({len(assignments)})[/bold]"
        )
        previous_profile_id = None
        for assignment in assignments:
            assignment_profile_id = int(assignment["profile_id"])
            if assignment_profile_id != previous_profile_id:
                console.print(
                    f"[bold]Profile {assignment_profile_id} — "
                    f"{labels.get(assignment_profile_id, 'unnamed')}[/bold]"
                )
                previous_profile_id = assignment_profile_id
            video = assignment["youtube_video_id"] or (
                f"observation:{assignment['observation_id']}"
            )
            title = assignment["video_title"] or "untitled"
            console.print(
                f"  {assignment['state']} {video} — {title}",
                markup=False,
            )
            console.print(
                f"    reason={assignment['reason']} "
                f"evidence={assignment['machine_evidence_id']} "
                f"created={assignment['evidence_created_at']}",
                markup=False,
            )
            console.print(
                f"    artifact={assignment['association_artifact_path']}",
                markup=False,
            )


@identity_app.command(
    "rollback-machine-assignments",
    help="Plan or append revocations for one machine policy fingerprint.",
)
def rollback_machine_assignments_command(
    policy_fingerprint: str = typer.Option(
        ...,
        "--policy-fingerprint",
        help="Exact machine evidence policy fingerprint to revoke.",
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Append rollback events; otherwise print the plan only.",
    ),
    base_dir: Path | None = typer.Option(
        None,
        help="Override app data directory.",
    ),
) -> None:
    paths = build_paths(base_dir)
    if not paths.database.exists():
        raise typer.BadParameter(
            f"Application database does not exist: {paths.database}"
        )
    readonly = Database(paths.database, readonly=True)
    eligible = sum(
        row["policy_fingerprint"] == policy_fingerprint
        for row in active_machine_assignment_evidence(readonly)
    )
    console.print(
        f"Machine rollback plan: policy={policy_fingerprint} active={eligible}."
    )
    if not apply:
        console.print("Plan only; pass --apply to append revocation events.")
        return
    database = Database(paths.database)
    database.initialize()
    revoked = rollback_machine_assignments(
        database,
        policy_fingerprint=policy_fingerprint,
    )
    console.print(f"Machine rollback complete: revoked={revoked}.")
