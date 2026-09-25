from __future__ import annotations

from datetime import date
from pathlib import Path
import re

import typer
from rich.console import Console
from rich.table import Table

from pastor_transcript_extractor.commands.apps import (
    organization_app,
    pastor_app,
    root_app,
    source_ownership_app,
)
from pastor_transcript_extractor.commands.common import get_database, unknown_pastor_error
from pastor_transcript_extractor.config import build_paths, ensure_directories
from pastor_transcript_extractor.exporting import export_organization_review_markdown
from pastor_transcript_extractor.source_ownership import (
    apply_source_ownership_schema,
    audit_source_ownership,
    backfill_source_ownership,
)
from pastor_transcript_extractor.storage import Database


console = Console()


@root_app.command(help="Initialize the app data directory and SQLite database.")
def init(
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    paths = build_paths(base_dir, remember=True)
    ensure_directories(paths)
    database = Database(paths.database)
    database.initialize()
    console.print(f"Initialized app data at [bold]{paths.root}[/bold]")


@source_ownership_app.command(
    "migrate",
    help="Apply or preview the replayable source-ownership migration.",
)
def source_ownership_migrate(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Run the migration and audit inside a rolled-back savepoint.",
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    paths = build_paths(base_dir, remember=True)
    if not paths.database.exists():
        raise typer.BadParameter(
            f"Database does not exist: {paths.database}. Run 'pte init' first."
        )
    database = Database(paths.database)
    with database.connect() as connection:
        if connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'sources'"
        ).fetchone() is None:
            raise typer.BadParameter(
                "Database is not initialized; run 'pte init' first."
            )
        if dry_run:
            connection.execute("SAVEPOINT source_ownership_preview")
        try:
            apply_source_ownership_schema(connection)
            result = backfill_source_ownership(connection)
            report = audit_source_ownership(connection, app_root=paths.root)
        finally:
            if dry_run:
                connection.execute("ROLLBACK TO source_ownership_preview")
                connection.execute("RELEASE source_ownership_preview")
    mode = "preview" if dry_run else "applied"
    console.print(
        f"Source ownership migration {mode}: "
        f"organizations={result.organizations_created}, "
        f"snapshots={result.snapshots_created}, "
        f"claims={result.affiliation_claims_created}, "
        f"source_targets={result.source_target_policies_created}, "
        f"video_targets={result.video_target_contexts_created}, "
        f"artifact_namespaces={result.artifact_namespaces_created}."
    )
    console.print(
        "Projected audit passed." if report.ok else "Projected audit failed."
    )
    if not report.ok:
        raise typer.Exit(code=1)

@source_ownership_app.command(
    "audit",
    help="Validate organization, target-context, and artifact-namespace projections.",
)
def source_ownership_audit(
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Exit unsuccessfully when any ownership invariant fails.",
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    paths = build_paths(base_dir)
    with database.connect() as connection:
        report = audit_source_ownership(connection, app_root=paths.root)
    values = {
        "Foreign-key violations": report.foreign_key_violations,
        "Legacy imports without external refs": report.imported_refs_without_external_ref,
        "Imported links without organization": report.imported_links_without_organization,
        "Legacy sources without target policy": report.legacy_sources_without_target_policy,
        "Legacy videos without target context": report.legacy_videos_without_target_context,
        "Videos without artifact namespace": report.videos_without_artifact_namespace,
        "Artifact namespace path mismatches": report.artifact_namespace_path_mismatches,
    }
    table = Table(title="Source ownership audit")
    table.add_column("Invariant")
    table.add_column("Failures", justify="right")
    for label, value in values.items():
        table.add_row(label, str(value))
    console.print(table)
    console.print("Source ownership audit passed." if report.ok else "Source ownership audit failed.")
    if strict and not report.ok:
        raise typer.Exit(code=1)


@organization_app.command("add", help="Create a publishing organization.")
def organization_add(
    slug: str = typer.Argument(..., help="Stable organization slug."),
    display_name: str = typer.Argument(..., help="Human-readable organization name."),
    organization_type: str = typer.Option(
        "church",
        "--type",
        help="Organization type, such as church, conference, ministry, school, or network.",
    ),
    notes: str | None = typer.Option(None, help="Optional organization notes."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    organization = database.add_organization(
        slug=slug,
        display_name=display_name,
        organization_type=organization_type,
        notes=notes,
    )
    console.print(
        f"Added organization #{organization.id}: {organization.slug} -> "
        f"{organization.display_name} ({organization.organization_type})"
    )


@organization_app.command("list", help="List publishing organizations.")
def organization_list(
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    organizations = database.list_organizations()
    if not organizations:
        console.print("No organizations configured.")
        return
    table = Table(title="Organizations")
    table.add_column("ID", justify="right")
    table.add_column("Slug")
    table.add_column("Type")
    table.add_column("Display Name")
    for organization in organizations:
        table.add_row(
            str(organization.id),
            organization.slug,
            organization.organization_type,
            organization.display_name,
        )
    console.print(table)


@organization_app.command(
    "review",
    help="Build a publisher-scoped review without asserting speaker identity.",
)
def organization_review(
    organization: str = typer.Argument(..., help="Organization slug."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    paths = build_paths(base_dir, remember=True)
    try:
        result = export_organization_review_markdown(
            database,
            paths,
            organization,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print(f"Wrote organization review markdown to {result.export_path}")
    console.print(f"Wrote organization review manifest to {result.manifest_path}")
    console.print(
        f"Included {result.video_count} video(s); skipped {result.skipped_count}."
    )


@organization_app.command(
    "claims",
    help="List imported affiliation claims without linking people by name.",
)
def organization_claims(
    organization: str | None = typer.Option(
        None,
        help="Only show claims for one organization slug.",
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    organization_id = None
    if organization is not None:
        organization_record = database.get_organization_by_slug(organization)
        if organization_record is None:
            raise typer.BadParameter(f"Unknown organization slug: {organization}")
        organization_id = organization_record.id
    claims = database.list_organization_affiliation_claims(organization_id)
    if not claims:
        console.print("No affiliation claims matched.")
        return
    table = Table(title="Organization Affiliation Claims")
    table.add_column("ID", justify="right")
    table.add_column("Organization")
    table.add_column("Claimed Name")
    table.add_column("Role")
    table.add_column("Review")
    for claim in claims:
        table.add_row(
            str(claim["id"]),
            str(claim["organization_slug"]),
            str(claim["claimed_person_name"]),
            str(claim["claimed_role"]),
            str(claim["review_status"] or "unreviewed"),
        )
    console.print(table)


@organization_app.command(
    "reject-affiliation-claim",
    help="Append a reviewed rejection without creating or linking a person.",
)
def organization_reject_affiliation_claim(
    claim_id: int = typer.Argument(..., help="Affiliation claim id."),
    reviewer: str = typer.Option(..., help="Reviewer name."),
    reason: str = typer.Option(..., help="Reason for rejection."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    try:
        event_id = database.review_organization_affiliation_claim(
            claim_id=claim_id,
            pastor_id=None,
            attach=False,
            reviewer=reviewer,
            reason=reason,
            review_event_key=f"reject:{claim_id}:{reviewer}:{reason}",
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print(f"Recorded affiliation claim rejection event #{event_id}.")


@pastor_app.command("add", help="Create a pastor profile and folder namespace.")
def pastor_add(
    slug: str = typer.Argument(..., help="Slug for this pastor, used in folder paths."),
    display_name: str = typer.Argument(..., help="Human-readable pastor name."),
    notes: str | None = typer.Option(None, help="Optional notes for this pastor."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    pastor = database.add_pastor(slug=slug, display_name=display_name, notes=notes)
    console.print(f"Added pastor #{pastor.id}: {pastor.slug} -> {pastor.display_name}")


@pastor_app.command("list", help="List configured pastors.")
def pastor_list(
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    pastors = database.list_pastors()

    if not pastors:
        console.print("No pastors configured.")
        return

    table = Table(title="Pastors")
    table.add_column("ID", justify="right")
    table.add_column("Slug")
    table.add_column("Display Name")
    for pastor in pastors:
        table.add_row(str(pastor.id), pastor.slug, pastor.display_name)
    console.print(table)


@pastor_app.command(
    "affiliate",
    help="Record a reviewed or manually grounded organization affiliation.",
)
def pastor_affiliate(
    pastor: str = typer.Argument(..., help="Pastor slug."),
    organization: str = typer.Argument(..., help="Organization slug."),
    role: str = typer.Option("pastor", help="Role held at the organization."),
    started_on: str | None = typer.Option(
        None,
        "--from",
        help="Inclusive start date in YYYY-MM-DD format.",
    ),
    ended_on: str | None = typer.Option(
        None,
        "--to",
        help="Exclusive end date in YYYY-MM-DD format.",
    ),
    temporal_status: str | None = typer.Option(
        None,
        "--status",
        help="Temporal status: current, former, bounded, or unknown.",
    ),
    notes: str | None = typer.Option(None, help="Optional affiliation notes."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    pastor_record = database.get_pastor_by_slug(pastor)
    if pastor_record is None:
        raise unknown_pastor_error(pastor, base_dir)
    organization_record = database.get_organization_by_slug(organization)
    if organization_record is None:
        raise typer.BadParameter(f"Unknown organization slug: {organization}")
    try:
        start_date = date.fromisoformat(started_on) if started_on is not None else None
        end_date = date.fromisoformat(ended_on) if ended_on is not None else None
    except ValueError as error:
        raise typer.BadParameter("Affiliation dates must use YYYY-MM-DD.") from error
    if start_date is not None and end_date is not None and end_date <= start_date:
        raise typer.BadParameter("--to must be later than --from.")
    inferred_status = (
        "bounded"
        if end_date is not None and start_date is not None
        else "former"
        if end_date is not None
        else "current"
        if start_date is not None
        else "unknown"
    )
    resolved_status = temporal_status or inferred_status
    if resolved_status not in {"current", "former", "bounded", "unknown"}:
        raise typer.BadParameter(
            "--status must be current, former, bounded, or unknown."
        )
    role_label = role.strip()
    if not role_label:
        raise typer.BadParameter("--role cannot be empty.")
    role_key = re.sub(r"[^a-z0-9]+", "_", role_label.lower()).strip("_")
    affiliation = database.add_pastor_organization_affiliation(
        pastor_id=pastor_record.id,
        organization_id=organization_record.id,
        role_key=role_key,
        role_label=role_label,
        started_on=started_on,
        ended_on=ended_on,
        temporal_status=resolved_status,
        provenance_kind="manual",
        notes=notes,
    )
    console.print(
        f"Recorded affiliation #{affiliation.id}: {pastor_record.slug} -> "
        f"{organization_record.slug} ({role_label}, {resolved_status})."
    )


@pastor_app.command(
    "affiliate-claim",
    help="Explicitly attach an imported affiliation claim to a selected pastor.",
)
def pastor_affiliate_claim(
    pastor: str = typer.Argument(..., help="Existing curated pastor slug."),
    claim_id: int = typer.Argument(..., help="Imported affiliation claim id."),
    reviewer: str = typer.Option(..., help="Reviewer name."),
    reason: str = typer.Option(..., help="Grounded reason for the attachment."),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    pastor_record = database.get_pastor_by_slug(pastor)
    if pastor_record is None:
        raise unknown_pastor_error(pastor, base_dir)
    try:
        event_id = database.review_organization_affiliation_claim(
            claim_id=claim_id,
            pastor_id=pastor_record.id,
            attach=True,
            reviewer=reviewer,
            reason=reason,
            review_event_key=(
                f"attach:{claim_id}:{pastor_record.id}:{reviewer}:{reason}"
            ),
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print(
        f"Attached affiliation claim #{claim_id} to pastor "
        f"{pastor_record.slug} with review event #{event_id}."
    )
