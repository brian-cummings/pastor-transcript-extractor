from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from pastor_transcript_extractor.benchmark import (
    EligibilityPolicy,
    build_snapshot,
    compare_profile_to_panel,
    create_panel,
    effective_membership,
    record_membership,
    snapshot_document,
)
from pastor_transcript_extractor.commands.apps import benchmark_app
from pastor_transcript_extractor.config import build_paths, ensure_directories
from pastor_transcript_extractor.storage import Database


console = Console()


def _get_database(base_dir: Path | None = None) -> Database:
    paths = build_paths(base_dir, remember=True)
    ensure_directories(paths)
    database = Database(paths.database)
    database.initialize()
    return database


@benchmark_app.command("create", help="Create an idempotent named reference panel.")
def benchmark_create(
    key: str = typer.Option(..., "--key", help="Stable lowercase panel key."),
    name: str = typer.Option(..., "--name", help="Panel display name."),
    description: str = typer.Option(..., "--description", help="Panel purpose."),
    provenance: str = typer.Option(
        "manual-review", "--provenance", help="How this analytical selection originated."
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = _get_database(base_dir)
    try:
        panel, created = create_panel(
            database,
            key=key,
            name=name,
            description=description,
            provenance=provenance,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print(
        f"Reference panel {panel.key!r} {'created' if created else 'reused'} (#{panel.id})."
    )


def _benchmark_membership_command(
    *,
    panel_key: str,
    profile_id: int,
    reviewer: str,
    reason: str,
    action: str,
    base_dir: Path | None,
) -> None:
    database = _get_database(base_dir)
    try:
        outcome = record_membership(
            database,
            panel_key=panel_key,
            profile_id=profile_id,
            action=action,
            reviewer=reviewer,
            rationale=reason,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print(
        f"Membership event #{outcome.event.id} "
        f"{'created' if outcome.created else 'reused'}: "
        f"{action} profile #{profile_id}."
    )


@benchmark_app.command("add-profile", help="Append a reviewed profile attachment event.")
def benchmark_add_profile(
    panel_key: str = typer.Argument(..., help="Reference panel key."),
    profile_id: int = typer.Option(..., "--profile-id", help="Speaker profile id."),
    reviewer: str = typer.Option(..., "--reviewer", help="Reviewer name."),
    reason: str = typer.Option(..., "--reason", help="Selection rationale."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    _benchmark_membership_command(
        panel_key=panel_key,
        profile_id=profile_id,
        reviewer=reviewer,
        reason=reason,
        action="attach",
        base_dir=base_dir,
    )


@benchmark_app.command("remove-profile", help="Append a reviewed profile detachment event.")
def benchmark_remove_profile(
    panel_key: str = typer.Argument(..., help="Reference panel key."),
    profile_id: int = typer.Option(..., "--profile-id", help="Speaker profile id."),
    reviewer: str = typer.Option(..., "--reviewer", help="Reviewer name."),
    reason: str = typer.Option(..., "--reason", help="Removal rationale."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    _benchmark_membership_command(
        panel_key=panel_key,
        profile_id=profile_id,
        reviewer=reviewer,
        reason=reason,
        action="detach",
        base_dir=base_dir,
    )


@benchmark_app.command("list", help="List named reference panels.")
def benchmark_list(
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = _get_database(base_dir)
    table = Table(title="Reference Panels")
    table.add_column("Key")
    table.add_column("Name")
    table.add_column("Members", justify="right")
    table.add_column("Latest snapshot", justify="right")
    for panel in database.list_reference_panels():
        snapshot = database.get_latest_reference_panel_snapshot(panel.id)
        table.add_row(
            panel.key,
            panel.display_name,
            str(len(effective_membership(database, panel))),
            f"#{snapshot.id}" if snapshot is not None else "—",
        )
    console.print(table)


@benchmark_app.command("show", help="Inspect panel metadata and effective membership.")
def benchmark_show(
    panel_key: str = typer.Argument(..., help="Reference panel key."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = _get_database(base_dir)
    panel = database.get_reference_panel(panel_key)
    if panel is None:
        raise typer.BadParameter(f"Unknown reference panel: {panel_key}")
    console.print(f"{panel.display_name} ({panel.key})")
    console.print(f"Description: {panel.description}")
    console.print(f"Provenance: {panel.provenance}")
    table = Table(title="Effective Reviewed Membership")
    table.add_column("Reviewed profile id(s)")
    table.add_column("Redirect-resolved profile")
    table.add_column("Reviewer")
    table.add_column("Rationale")
    for membership in effective_membership(database, panel):
        reviews = membership["membership_reviews"]
        table.add_row(
            ", ".join(str(value) for value in membership["requested_profile_ids"]),
            str(membership["resolved_profile_id"]),
            "; ".join(str(review["reviewer"]) for review in reviews),
            "; ".join(str(review["rationale"]) for review in reviews),
        )
    console.print(table)


@benchmark_app.command("build", help="Build or reuse an immutable panel snapshot.")
def benchmark_build(
    panel_key: str = typer.Argument(..., help="Reference panel key."),
    minimum_analyzed_sermons: int = typer.Option(5, "--min-analyzed-sermons"),
    minimum_total_sermon_words: int = typer.Option(10_000, "--min-total-words"),
    minimum_analysis_coverage: float = typer.Option(0.8, "--min-coverage"),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    if minimum_analyzed_sermons < 0 or minimum_total_sermon_words < 0:
        raise typer.BadParameter("Eligibility minimums must not be negative")
    if not 0.0 <= minimum_analysis_coverage <= 1.0:
        raise typer.BadParameter("--min-coverage must be between 0 and 1")
    database = _get_database(base_dir)
    policy = EligibilityPolicy(
        minimum_analyzed_sermons=minimum_analyzed_sermons,
        minimum_total_sermon_words=minimum_total_sermon_words,
        minimum_analysis_coverage=minimum_analysis_coverage,
    )
    try:
        outcome = build_snapshot(database, panel_key, policy=policy)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    panel = database.get_reference_panel(panel_key)
    assert panel is not None
    document = snapshot_document(database, panel, outcome.snapshot)
    eligible = sum(
        member["eligibility_status"] == "eligible" for member in document["members"]
    )
    console.print(
        f"Snapshot #{outcome.snapshot.id} "
        f"{'created' if outcome.created else 'reused'}; "
        f"eligible={eligible}; excluded={len(document['members']) - eligible}."
    )
    console.print(
        f"Fingerprint: {outcome.snapshot.input_fingerprint}; "
        f"profile analyzer: {outcome.snapshot.profile_analyzer_key}@"
        f"{outcome.snapshot.profile_analyzer_version}; "
        f"features: {outcome.snapshot.feature_schema_version}; "
        f"eligibility: {outcome.snapshot.eligibility_policy_version}."
    )


@benchmark_app.command("show-snapshot", help="Inspect the latest immutable panel snapshot.")
def benchmark_show_snapshot(
    panel_key: str = typer.Argument(..., help="Reference panel key."),
    json_output: bool = typer.Option(False, "--json", help="Emit stable JSON and feature matrix."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = _get_database(base_dir)
    panel = database.get_reference_panel(panel_key)
    if panel is None:
        raise typer.BadParameter(f"Unknown reference panel: {panel_key}")
    snapshot = database.get_latest_reference_panel_snapshot(panel.id)
    if snapshot is None:
        raise typer.BadParameter(
            f"Reference panel {panel_key!r} has no snapshot. Run 'pte benchmark build' first."
        )
    document = snapshot_document(database, panel, snapshot)
    if json_output:
        console.print_json(json.dumps(document, sort_keys=True))
        return
    console.print(
        f"Snapshot #{snapshot.id}: {snapshot.input_fingerprint}\n"
        f"Profile analyzer: {snapshot.profile_analyzer_key}@{snapshot.profile_analyzer_version}\n"
        f"Feature schema: {snapshot.feature_schema_version}\n"
        f"Eligibility policy: {snapshot.eligibility_policy_version}"
    )
    table = Table(title=f"Snapshot Members — {panel.key}")
    table.add_column("Reviewed")
    table.add_column("Resolved")
    table.add_column("Display label")
    table.add_column("Profile analysis")
    table.add_column("Status")
    table.add_column("Reasons")
    for member in document["members"]:
        table.add_row(
            ", ".join(str(value) for value in member["requested_profile_ids"]),
            str(member["resolved_profile_id"]),
            str(member["resolved_display_label"]),
            (
                f"#{member['profile_analysis_run_id']}"
                if member["profile_analysis_run_id"] is not None
                else "—"
            ),
            str(member["eligibility_status"]),
            ", ".join(member["exclusion_reasons"]) or "—",
        )
    console.print(table)
    console.print(
        "Comparison features (ordered): "
        + ", ".join(document["snapshot"]["comparison_feature_names"])
    )
    console.print(
        "Coverage diagnostics (excluded from comparison): "
        + ", ".join(document["snapshot"]["coverage_feature_names"])
    )


@benchmark_app.command(
    "compare",
    help="Compare one profile with an immutable Scripture reference-panel snapshot.",
)
def benchmark_compare(
    profile_id: int = typer.Option(..., "--profile-id", help="Candidate speaker profile."),
    panel_key: str = typer.Option(..., "--panel", help="Reference panel key."),
    snapshot_id: int | None = typer.Option(
        None, "--snapshot-id", help="Use an exact panel snapshot instead of the latest."
    ),
    comparison_level: str = typer.Option("core", "--comparison-level", help="Fixed experimental scope: core or full."),
    historical_references: bool = typer.Option(False, "--historical-references", help="Explicitly pin historical reference inputs; requires --snapshot-id."),
    limit: int = typer.Option(5, "--limit", min=1, help="Nearest references to show."),
    json_output: bool = typer.Option(False, "--json", help="Emit the durable result JSON."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = _get_database(base_dir)
    try:
        outcome = compare_profile_to_panel(
            database,
            profile_id=profile_id,
            panel_key=panel_key,
            snapshot_id=snapshot_id,
            comparison_level=comparison_level,
            historical_references=historical_references,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    result = outcome.result
    if json_output:
        console.print_json(json.dumps(result, sort_keys=True))
        return
    console.print("Experimental comparison of collected sermon samples; no dimensions are certified.")
    candidate = result["candidate"]
    panel = result["panel"]
    diagnostics = candidate["coverage_diagnostics"]
    console.print(
        f"Comparison #{outcome.run.id} {'created' if outcome.created else 'reused'}: "
        f"profile #{candidate['resolved_profile_id']} {candidate['display_label']}\n"
        f"Panel: {panel['display_name']} ({panel['key']}), snapshot #{panel['snapshot_id']}\n"
        f"Scope: experimental collected-sermon sample differences; "
        f"level={result['comparison_level']}; "
        f"sermons={diagnostics.get('sermons_analyzed', '—')}; "
        f"analysis coverage={diagnostics.get('analysis_coverage_fraction', '—')}"
    )
    if result["status"] == "abstained":
        console.print(
            "Comparison abstained: " + ", ".join(result["abstention_reasons"])
        )
        if result["excluded_references"]:
            console.print(
                f"Excluded references: {len(result['excluded_references'])}. "
                "Use --json for exact reasons."
            )
        return
    table = Table(title="Nearest Scripture-use references")
    table.add_column("Rank", justify="right")
    table.add_column("Reference")
    table.add_column("Profile", justify="right")
    table.add_column("Distance", justify="right")
    table.add_column("Family distances")
    rankings = result["rankings"][:limit]
    for index, ranking in enumerate(rankings, start=1):
        tied_rank = 1 + sum(
            row["distance"] < ranking["distance"] for row in result["rankings"]
        )
        family_text = ", ".join(
            f"{item['family']}={item['distance']:.3f}"
            for item in ranking["family_distances"]
        )
        table.add_row(
            str(tied_rank),
            str(ranking["reference_display_label"]),
            f"#{ranking['reference_profile_id']}",
            f"{ranking['distance']:.3f}",
            family_text,
        )
    console.print(table)
    if len(result.get("tied_nearest_reference_ids", [])) > 1:
        console.print(
            "Tied nearest references (no unique winner): "
            + ", ".join(map(str, result["tied_nearest_reference_ids"]))
        )
    separation = result.get("ranking_separation")
    if separation is not None:
        console.print(
            f"Nearest/second-nearest distance margin: "
            f"{separation['absolute_margin']:.3f} "
            "(descriptive separation, not confidence)."
        )
    nearest = rankings[0]
    feature_rows = nearest["feature_differences"]
    closest = feature_rows[:3]
    different = list(reversed(feature_rows[-3:]))
    console.print(f"Closest measured features to {nearest['reference_display_label']}:")
    for item in closest:
        console.print(
            f"  {str(item['feature']).replace('_', ' ')}: "
            f"standardized difference={item['standardized_absolute_difference']:.3f}"
        )
    console.print("Largest measured differences:")
    for item in different:
        console.print(
            f"  {str(item['feature']).replace('_', ' ')}: "
            f"candidate={item['candidate_value']:.3f}, "
            f"reference={item['reference_value']:.3f}, "
            f"standardized difference={item['standardized_absolute_difference']:.3f}"
        )
    if result["excluded_references"]:
        console.print(
            f"Excluded references: {len(result['excluded_references'])}; "
            "use --json for exact reasons."
        )
    console.print(
        "Distances are descriptive, not probabilities. Nearest does not necessarily mean "
        "close, and this does not measure overall preaching similarity or church fit."
    )
