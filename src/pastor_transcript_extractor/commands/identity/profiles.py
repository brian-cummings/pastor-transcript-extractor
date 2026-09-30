from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, TaskProgressColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from pastor_transcript_extractor.commands.apps import identity_app
from pastor_transcript_extractor.commands.common import get_database
from pastor_transcript_extractor.config import build_paths
from pastor_transcript_extractor.exporting import export_profile_transcript_collection
from pastor_transcript_extractor.reviewed_speaker_evidence import (
    ReviewedEvidenceSyncResult,
    ReviewedSpeakerEvidence,
    load_reviewed_speaker_evidence,
    sync_reviewed_speaker_evidence,
)
from pastor_transcript_extractor.speaker_machine_assignment import (
    machine_assignment_report,
)
from pastor_transcript_extractor.speaker_negative_window_audit import (
    audit_speaker_negative_windows,
)
from pastor_transcript_extractor.speaker_pair_eligibility import (
    assess_automatic_speaker_observation,
)
from pastor_transcript_extractor.speaker_profile_discovery import (
    load_verified_shadow_profile_discovery,
)
from pastor_transcript_extractor.speaker_profile_promotion_typesafe import (
    DEFAULT_TYPESAFE_MODEL,
    PromotionProbabilityPolicy,
    TypeSafeSdkPromotionProvider,
    build_promotion_groupings,
    evaluate_profile_promotions,
)
from pastor_transcript_extractor.speaker_profile_status import (
    applicable_status_commands,
    build_profile_pipeline_status,
)
from pastor_transcript_extractor.storage import Database


console = Console()


@identity_app.command(
    "evaluate-profile-promotions",
    help="Evaluate discovery groupings with cached Jev promotion probabilities.",
)
def evaluate_profile_promotions_command(
    discovery_report: Path = typer.Option(
        ...,
        "--discovery-report",
        exists=True,
        dir_okay=False,
        readable=True,
        help="Completed shadow profile-discovery JSON artifact.",
    ),
    model: str = typer.Option(
        DEFAULT_TYPESAFE_MODEL,
        "--model",
        help="Pinned TypeSafe/Jev model.",
    ),
    output_root: Path = typer.Option(
        Path("evaluation/speaker-profile-discovery/promotion-judgments"),
        "--output-root",
        help="Content-addressed Jev judgment cache and artifact root.",
    ),
    successful_profile_value: float = typer.Option(
        1.0,
        min=0.0,
        help="Utility of a correct reversible provisional profile.",
    ),
    contaminated_profile_cost: float = typer.Option(
        3.0,
        min=0.0,
        help="Utility cost of a contaminated provisional profile.",
    ),
    details: bool = typer.Option(
        False,
        "--details",
        help="Show each grouping, probability, utility, cache state, and artifact.",
    ),
    plan_only: bool = typer.Option(
        False,
        "--plan-only",
        help="List candidate groupings without TypeSafe calls or artifact writes.",
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
    database = Database(paths.database, readonly=True)
    try:
        report = load_verified_shadow_profile_discovery(discovery_report)
        groupings = build_promotion_groupings(database, report)
        if plan_only:
            console.print(
                "Profile promotion probability plan: "
                f"groupings={len(groupings)}; no TypeSafe calls or artifact writes."
            )
            if details:
                for grouping in groupings:
                    console.print(
                        f"  group={grouping.group_id[:12]} "
                        f"members={','.join(str(value) for value in grouping.observation_ids)} "
                        f"retrieval={','.join(grouping.retrieval_reasons)}"
                    )
            return
        provider = TypeSafeSdkPromotionProvider(model=model)
        policy = PromotionProbabilityPolicy(
            successful_profile_value=successful_profile_value,
            contaminated_profile_cost=contaminated_profile_cost,
        )
        with Progress(
            TextColumn("{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task_id = progress.add_task(
                "Preparing Jev promotion evaluation",
                total=len(groupings),
            )

            def report_progress(completed, total, grouping, status) -> None:
                label = {
                    "checking_cache": "checking cache",
                    "cache_hit": "cache hit",
                    "cached_failure": "cached failure",
                    "calling_jev": "calling Jev",
                    "evaluated": "Jev result cached",
                    "live_failure": "Jev failure cached",
                }.get(status, status)
                progress.update(
                    task_id,
                    completed=completed,
                    total=total,
                    description=f"Profile group {grouping.group_id[:12]}: {label}",
                    refresh=True,
                )

            result = evaluate_profile_promotions(
                database,
                discovery_report,
                output_root,
                provider,
                policy=policy,
                progress_callback=report_progress,
            )
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        raise typer.BadParameter(str(error)) from error

    qualifying = sum(item.qualifies for item in result.assessments)
    failures = sum(item.error_type is not None for item in result.assessments)
    console.print(
        "Profile promotion probability evaluation: "
        f"groupings={len(result.assessments)} qualifying={qualifying} "
        f"deferred={len(result.assessments) - qualifying - failures} "
        f"failed={failures} cache_hits={result.cache_hits} "
        f"cache_misses={result.cache_misses} model_calls={result.model_calls} "
        f"cached_failures={result.cached_failures} "
        f"live_failures={result.live_failures}."
    )
    if details:
        for item in result.assessments:
            grouping = item.evidence.grouping
            if item.error_type is not None:
                outcome = f"failed:{item.error_type}:{item.error_message}"
            else:
                outcome = (
                    f"probability={item.probability:.4f} "
                    f"utility={item.expected_utility:.4f} "
                    f"action={'qualify' if item.qualifies else 'defer'}"
                )
            console.print(
                f"  group={grouping.group_id[:12]} "
                f"members={','.join(str(value) for value in grouping.observation_ids)} "
                f"cache={'hit' if item.cache_hit else 'miss'} {outcome} "
                f"artifact={item.artifact_path}",
                markup=False,
            )


def _print_reviewed_evidence_summary(
    evidence: ReviewedSpeakerEvidence,
    result: ReviewedEvidenceSyncResult | None,
) -> None:
    console.print(
        "Reviewed evidence: "
        f"events={evidence.review_event_count} "
        f"qualifications={len(evidence.qualifications)} "
        f"same_components={len(evidence.same_components())} "
        f"pair_relations={len(evidence.pair_relations)} "
        f"conflicts={len(evidence.qualification_conflicts) + len(evidence.pair_conflicts)}"
    )
    if result is None:
        return
    console.print(
        "Registry sync: "
        f"qualification_events={result.qualification_events_added} "
        f"profiles={result.profiles_added} "
        f"memberships={result.membership_events_added} "
        f"different_constraints={result.difference_events_added} "
        f"name_claims={result.name_claim_events_added} "
        f"profile_redirects={result.profile_redirect_events_added} "
        f"missing={len(result.missing_observations)} "
        f"merge_candidates={len(result.merge_candidates)} "
        f"conflicts={len(result.conflicts)}"
    )
    for candidate in result.merge_candidates:
        console.print(f"[cyan]Merge candidate:[/cyan] {candidate}")
    for conflict in result.conflicts:
        console.print(f"[yellow]Review conflict:[/yellow] {conflict}")



@identity_app.command(
    "sync-reviewed-speaker-evidence",
    help="Replay confirmed pair reviews into curated anonymous registry state.",
)
def sync_reviewed_speaker_evidence_command(
    evaluation_root: Path = typer.Option(
        Path("evaluation/speaker-pairs"),
        help="Speaker-pair drafts, reviews, and fixtures root.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Derive and report reviewed evidence without registry mutations.",
    ),
    base_dir: Path | None = typer.Option(
        None, help="Override app data directory."
    ),
) -> None:
    try:
        evidence = load_reviewed_speaker_evidence(
            evaluation_root.expanduser().resolve()
        )
        result = None
        if not dry_run:
            database = get_database(base_dir)
            result = sync_reviewed_speaker_evidence(database, evidence)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise typer.BadParameter(str(error)) from error
    _print_reviewed_evidence_summary(evidence, result)
    if dry_run:
        console.print("Dry run complete; no reviewed evidence was synchronized.")


@identity_app.command(
    "export-profile",
    help="Export the reviewed sermon transcript collection for a speaker profile.",
)
def export_profile_command(
    profile_id: int = typer.Option(
        ...,
        "--profile-id",
        help="Speaker profile id; redirects are resolved to the canonical profile.",
    ),
    base_dir: Path | None = typer.Option(
        None, help="Override app data directory."
    ),
) -> None:
    database = get_database(base_dir)
    paths = build_paths(base_dir, remember=True)
    try:
        result = export_profile_transcript_collection(
            database,
            paths,
            profile_id,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    if result.requested_profile_id != result.profile_id:
        console.print(
            f"Resolved speaker profile #{result.requested_profile_id} to canonical "
            f"profile #{result.profile_id}."
        )
    console.print(f"Wrote profile transcript collection to {result.export_path}")
    console.print(f"Wrote profile transcript manifest to {result.manifest_path}")
    console.print(
        f"Included {result.video_count} sermon(s); skipped {result.skipped_count}."
    )


@identity_app.command(
    "profile-status",
    help="Report the reviewed identity pipeline and what each profile needs next.",
)
def profile_status_command(
    evaluation_root: Path = typer.Option(
        Path("evaluation/speaker-pairs"),
        help="Speaker-pair drafts, reviews, and fixtures root.",
    ),
    discovery_root: Path = typer.Option(
        Path("evaluation/speaker-profile-discovery/shadow-runs"),
        help="Shadow profile-discovery reports to include in status.",
    ),
    base_dir: Path | None = typer.Option(
        None, help="Override app data directory."
    ),
) -> None:
    paths = build_paths(base_dir)
    if not paths.database.exists():
        raise typer.BadParameter(
            f"Application database does not exist: {paths.database}"
        )
    try:
        evidence = load_reviewed_speaker_evidence(
            evaluation_root.expanduser().resolve()
        )
        discovery_report = None
        discovery_report_path = None
        invalid_discovery_artifacts = 0
        discovery_paths = sorted(
            discovery_root.expanduser().resolve().glob("*/*.json"),
            key=lambda path: (path.stat().st_mtime_ns, str(path)),
            reverse=True,
        )
        for candidate_path in discovery_paths:
            try:
                discovery_report = load_verified_shadow_profile_discovery(
                    candidate_path
                )
            except (OSError, ValueError, json.JSONDecodeError):
                invalid_discovery_artifacts += 1
                continue
            discovery_report_path = candidate_path
            break
        database = Database(paths.database, readonly=True)
        review_actions = database.list_effective_observation_review_actions()

        def automatic_eligibility_resolver(
            observation_id: int,
            video_id: int,
        ) -> bool:
            eligibility = assess_automatic_speaker_observation(
                database,
                video_id,
                verify_media=False,
            )
            return (
                eligibility.eligible
                and eligibility.observation is not None
                and eligibility.observation.id == observation_id
            )

        status = build_profile_pipeline_status(
            database,
            evidence,
            discovery_report=discovery_report,
            discovery_report_path=discovery_report_path,
            automatic_eligibility_resolver=automatic_eligibility_resolver,
            review_actions=review_actions,
        )
        negative_window_audit = audit_speaker_negative_windows(
            database,
            evaluation_root.expanduser().resolve(),
            review_actions=review_actions,
        )
        assignment_report = machine_assignment_report(database)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise typer.BadParameter(str(error)) from error

    qualifications = status.qualification_counts
    console.print("[bold]Speaker identity status[/bold]")
    console.print(
        f"Observations: current={status.current_observation_count} "
        f"superseded={status.superseded_observation_count} "
        f"registry={status.registry_observation_count} | current "
        f"single={qualifications.get('qualified_single_speaker', 0)} "
        f"multiple={qualifications.get('multiple_speakers', 0)} "
        f"invalid={qualifications.get('invalid', 0)} "
        f"unresolved={qualifications.get('unresolved', 0)} "
        f"unreviewed={qualifications.get('unreviewed', 0)}"
    )
    pending_sync_count = (
        status.pending_qualification_count
        + status.pending_same_component_count
        + status.pending_difference_count
    )
    console.print(
        f"Evidence: reviews={status.review_event_count} "
        f"relations={status.pair_relation_count} "
        f"conflicts={status.evidence_conflict_count} | pending_sync="
        f"{pending_sync_count} "
        f"(qualifications={status.pending_qualification_count} "
        f"same_components={status.pending_same_component_count} "
        f"different_relations={status.pending_difference_count} "
        f"missing={status.missing_reviewed_observation_count})"
    )
    console.print(
        f"Profiles: canonical={status.canonical_profile_count} "
        f"shadow_ready={status.shadow_ready_profile_count} "
        f"human_on_loop={status.automatic_profile_ready_count} "
        f"linked={status.configured_identity_count}"
    )
    console.print(
        f"Backlog: "
        f"ungrouped={status.ungrouped_single_count} "
        f"unmatched_named={status.unmatched_named_ungrouped_single_count} "
        f"unnamed={status.unnamed_ungrouped_single_count} "
        f"stale_or_ineligible={status.stale_or_ineligible_ungrouped_single_count} "
        f"window_review={len(negative_window_audit.actionable)}"
    )
    if status.discovery_report_path is not None:
        console.print(
            "Shadow discovery: "
            f"candidates={status.shadow_discovery_candidate_count} "
            f"promoted={status.promoted_discovery_candidate_count} "
            f"stale={status.stale_discovery_candidate_count} "
            f"blocked={status.blocked_discovery_component_count} "
            f"review_frontiers={status.actionable_discovery_frontier_component_count} "
            f"report={status.discovery_result_sha256[:12]}"
        )
    else:
        console.print(
            "Shadow discovery: no valid report found "
            f"(invalid_artifacts_skipped={invalid_discovery_artifacts})"
        )

    table = Table(title="Canonical and promoted profiles")
    table.add_column("Profile", justify="right", no_wrap=True)
    table.add_column("State", no_wrap=True)
    table.add_column("Evidence", no_wrap=True)
    table.add_column("Automation", no_wrap=True)
    table.add_column("Identity evidence")
    blocker_labels = {
        "fewer_than_three_profile_members": "need 3 members",
        "fewer_than_three_distinct_recordings": "need 3 recordings",
        "fewer_than_three_reviewed_members": "need reinforced core",
        "reviewed_same_graph_disconnected": "no reinforced core",
        "reviewed_same_graph_contains_bridge": "no reinforced core",
        "discovery_candidate_unconfirmed": "needs confirmation",
        "discovery_promotion_provenance_missing": "missing promotion evidence",
        "conflicting_explicit_attribution": "conflicting names",
        "conflicting_name_claim_review": "conflicting name review",
        "internal_reviewed_difference": "speaker conflict",
        "attribution_spans_multiple_profiles": "duplicate attributed profile",
        "member_observation_missing": "missing observation",
    }
    for profile in status.profiles:
        identity = ", ".join(
            profile.configured_identities or profile.names
        ) or "unnamed"
        table.add_row(
            str(profile.profile_id),
            profile.state,
            (
                f"{profile.member_count} member rows / "
                f"{profile.recording_count} rec / "
                f"{profile.source_count} src"
                + (
                    f" ({profile.superseded_member_count} older rows)"
                    if profile.superseded_member_count
                    else ""
                )
            ),
            (
                "human-on-loop"
                if profile.automatic_profile_ready
                else "building"
                if profile.shadow_ready
                else "blocked"
            ),
            identity,
        )
    console.print(table)

    blocker_priority = (
        "internal_reviewed_difference",
        "conflicting_explicit_attribution",
        "conflicting_name_claim_review",
        "attribution_spans_multiple_profiles",
        "member_observation_missing",
        "discovery_promotion_provenance_missing",
        "discovery_candidate_unconfirmed",
        "fewer_than_three_distinct_recordings",
        "fewer_than_three_profile_members",
        "fewer_than_three_reviewed_members",
        "reviewed_same_graph_disconnected",
        "reviewed_same_graph_contains_bridge",
    )
    profiles_by_primary_blocker: dict[str, list[int]] = {}
    for profile in status.profiles:
        if profile.automatic_profile_ready or not profile.automatic_blockers:
            continue
        blocker = next(
            (
                candidate
                for candidate in blocker_priority
                if candidate in profile.automatic_blockers
            ),
            profile.automatic_blockers[0],
        )
        label = blocker_labels.get(blocker, blocker)
        profiles_by_primary_blocker.setdefault(label, []).append(
            profile.profile_id
        )
    if profiles_by_primary_blocker:
        console.print("[bold]Why profiles are not human-on-loop[/bold]")
        for label, profile_ids in sorted(profiles_by_primary_blocker.items()):
            console.print(
                f"  {label}: "
                + ", ".join(str(profile_id) for profile_id in profile_ids)
            )

    partial_cores = [
        profile
        for profile in status.profiles
        if (
            profile.automatic_profile_ready
            and profile.certified_exemplar_count < profile.member_count
        )
    ]
    if partial_cores:
        console.print(
            "[bold]Ready profiles with peripheral members excluded from "
            "automatic exemplars[/bold]"
        )
        console.print(
            "  "
            + ", ".join(
                f"{profile.profile_id} "
                f"({profile.certified_exemplar_count}/{profile.member_count})"
                for profile in partial_cores
            )
        )

    profile_assignment_counts = assignment_report["profile_counts"]
    if profile_assignment_counts:
        identity_by_profile = {
            profile.profile_id: ", ".join(
                profile.configured_identities or profile.names
            )
            or "unnamed"
            for profile in status.profiles
        }
        console.print("[bold]Automatic sermon associations by profile[/bold]")
        for profile_id, counts in profile_assignment_counts.items():
            nonzero = [
                f"{state}={count}"
                for state, count in counts.items()
                if count
            ]
            console.print(
                f"  {profile_id} "
                f"{identity_by_profile.get(profile_id, 'unnamed')}: "
                + " ".join(nonzero)
            )

    if status.discovered_profiles:
        discovery_table = Table(title="Auto-discovered profile candidates")
        discovery_table.add_column("Component", no_wrap=True)
        discovery_table.add_column("State", no_wrap=True)
        discovery_table.add_column("Evidence", no_wrap=True)
        discovery_table.add_column("Identity evidence")
        discovery_table.add_column("Next need")
        for profile in status.discovered_profiles:
            discovery_table.add_row(
                profile.component_id[:12],
                profile.state,
                (
                    f"{profile.member_count} obs / "
                    f"{profile.recording_count} rec / "
                    f"{profile.source_count} src"
                ),
                ", ".join(profile.names) or "unnamed",
                profile.next_need,
            )
        console.print(discovery_table)

    console.print("[bold]Guidance[/bold]")
    console.print(
        "- Building/blocked profiles: human review supplies identity evidence."
    )
    console.print(
        "- Human-on-loop profiles: the identity run associates eligible sermons; "
        "humans handle exceptions, conflicts, and attribution."
    )
    console.print("[bold]Next actions[/bold]")
    if negative_window_audit.actionable:
        console.print(
            f"- Review {len(negative_window_audit.actionable)} current sermon window(s) "
            "implicated by multiple-speaker or invalid-audio observations."
        )
    for action in status.actions:
        console.print(f"- {action.message}")
    all_needs = (
        *status.actions,
        *(need for profile in status.profiles for need in profile.needs),
    )
    commands = applicable_status_commands(all_needs)
    if commands:
        console.print("[bold]Applicable commands[/bold]")
        for command in commands:
            console.print(f"- {command}")
    if negative_window_audit.actionable:
        if not commands:
            console.print("[bold]Applicable commands[/bold]")
        console.print(
            "- pte identity review-next-speaker-negative-window "
            "--reviewer REVIEWER_ID --base-dir BASE_DIR"
        )
    console.print("Read-only status; use the commands above to make changes.")
